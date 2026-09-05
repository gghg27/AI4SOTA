"""Authoritative Run manifest repository and state transitions."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from ai4sota.domain import RunManifest
from ai4sota.files import StableReadError, stable_read_file
from ai4sota.projects import ProjectLayout
from ai4sota.storage import ManifestStore, canonical_manifest_hash

from .lifecycle import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATES,
    RunEvent,
    _append_run_event_locked,
)


class RunManifestIntegrityError(ValueError):
    """Raised when a persisted Run manifest no longer matches its hash."""


class RunStateConflict(RuntimeError):
    """Raised when a compare-and-set caller observed a stale state."""


class InvalidRunTransition(ValueError):
    """Raised when the lifecycle does not permit a requested target state."""


class RunPersistenceError(RuntimeError):
    """Raised when a lifecycle fact or its manifest projection cannot persist."""


@dataclass(frozen=True)
class RunRepository:
    """Resolve Run identifiers within one project and apply guarded updates."""

    project: ProjectLayout

    def run_dir(self, run_id: str) -> Path:
        candidate = Path(run_id)
        if (
            not run_id.strip()
            or candidate.is_absolute()
            or candidate.drive
            or len(candidate.parts) != 1
            or candidate.parts[0] in {".", ".."}
        ):
            raise ValueError(f"invalid run id: {run_id!r}")
        return self.project.runs_dir / candidate

    def load(self, run_id: str) -> RunManifest:
        return load_run_manifest(self.run_dir(run_id))

    def transition_run(self, run_id: str, expected: str, target: str) -> RunManifest:
        return transition_run(self.run_dir(run_id), expected, target)


def load_run_manifest(run_dir: Path) -> RunManifest:
    """Read a strict Run manifest and verify its canonical content address."""
    directory = Path(run_dir)
    if _is_link_or_reparse(directory) or not directory.is_dir():
        raise RunManifestIntegrityError("Run directory must be a real directory")
    manifest_path = directory / "manifest.yaml"
    try:
        manifest_bytes = stable_read_file(manifest_path).data
        document = yaml.safe_load(manifest_bytes.decode("utf-8"))
        manifest = RunManifest.model_validate(document)
    except FileNotFoundError:
        raise
    except (
        OSError,
        StableReadError,
        UnicodeError,
        yaml.YAMLError,
        ValidationError,
    ) as error:
        raise RunManifestIntegrityError("Run manifest cannot be read safely") from error
    actual_hash = canonical_manifest_hash(manifest)
    if manifest.content_hash != actual_hash:
        raise RunManifestIntegrityError(
            f"Run manifest hash mismatch: expected {manifest.content_hash}, "
            f"computed {actual_hash}"
        )
    if directory.name != manifest.id:
        raise RunManifestIntegrityError(
            f"Run manifest id {manifest.id!r} does not match directory {directory.name!r}"
        )
    return manifest


def manifest_hash(run_dir: Path) -> str:
    """Return the verified canonical hash bound into a Run manifest."""
    return load_run_manifest(run_dir).content_hash


def verify_run_integrity(run_dir: Path) -> RunManifest:
    """Verify the Run identity, manifest hash, and immutable snapshot tree."""
    directory = Path(run_dir)
    manifest = load_run_manifest(directory)
    from .snapshots import SnapshotValidationError, hash_tree

    try:
        actual_snapshot_hash = hash_tree(directory / "snapshot")
    except (OSError, SnapshotValidationError) as error:
        raise RunManifestIntegrityError("Run snapshot cannot be verified") from error
    if manifest.snapshot_hash != actual_snapshot_hash:
        raise RunManifestIntegrityError(
            f"Run snapshot hash mismatch: expected {manifest.snapshot_hash}, "
            f"computed {actual_snapshot_hash}"
        )
    return manifest


def transition_run(run_dir: Path, expected: str, target: str) -> RunManifest:
    """Compare-and-set one legal lifecycle transition under a per-Run lock."""
    directory = Path(run_dir)
    if not directory.is_dir():
        raise FileNotFoundError(f"run directory does not exist: {directory}")
    with _exclusive_run_lock(directory):
        current = load_run_manifest(directory)
        recovered = _recover_pending_transition(directory, current)
        if recovered is not None:
            event, current = recovered
            if event.previous_status == expected and event.status == target:
                return current
        if current.status != expected:
            if _has_committed_transition(directory, current, expected, target):
                return current
            raise RunStateConflict(
                f"Run state conflict: expected {expected!r}, found {current.status!r}"
            )
        allowed = ALLOWED_TRANSITIONS.get(current.status, frozenset())
        if target not in allowed:
            raise InvalidRunTransition(
                f"cannot transition Run from {current.status!r} to {target!r}"
            )
        if _requires_integrity_check(current.status, target):
            verify_run_integrity(directory)

        draft = current.model_copy(update={"status": target})
        updated = draft.model_copy(
            update={"content_hash": canonical_manifest_hash(draft)}
        )
        event = RunEvent(
            id=f"event-{uuid4().hex}",
            run_id=current.id,
            event_type="run_state_transition",
            occurred_at=datetime.now(UTC),
            previous_status=current.status,
            status=target,
            details={
                "source_manifest_hash": current.content_hash,
                "target_manifest_hash": updated.content_hash,
                "target_manifest": updated.model_dump(mode="json"),
            },
        )
        try:
            _append_run_event_locked(directory, event, current.id)
        except Exception as error:
            raise RunPersistenceError("could not persist transition event") from error
        try:
            ManifestStore().write(directory / "manifest.yaml", updated)
        except Exception as error:
            raise RunPersistenceError(
                "could not persist manifest projection"
            ) from error
        return updated


def _recover_pending_transition(
    run_dir: Path, current: RunManifest
) -> tuple[RunEvent, RunManifest] | None:
    for event in reversed(_read_run_events(run_dir, current.id)):
        target = _event_target_manifest(event, run_dir.name)
        if target is None:
            continue
        source_hash = event.details.get("source_manifest_hash")
        if current.content_hash == target.content_hash:
            return None
        if current.content_hash != source_hash:
            continue
        if _requires_integrity_check(current.status, target.status):
            verify_run_integrity(run_dir)
        try:
            ManifestStore().write(run_dir / "manifest.yaml", target)
        except Exception as error:
            raise RunPersistenceError(
                "could not recover manifest projection"
            ) from error
        return event, target
    return None


def _has_committed_transition(
    run_dir: Path, current: RunManifest, expected: str, target: str
) -> bool:
    if current.status != target:
        return False
    for event in reversed(_read_run_events(run_dir, current.id)):
        projected = _event_target_manifest(event, run_dir.name)
        if projected is None:
            continue
        return (
            event.previous_status == expected
            and event.status == target
            and projected.content_hash == current.content_hash
        )
    return False


def _event_target_manifest(event: RunEvent, directory_name: str) -> RunManifest | None:
    if event.event_type != "run_state_transition":
        return None
    document = event.details.get("target_manifest")
    target_hash = event.details.get("target_manifest_hash")
    if not isinstance(document, dict) or not isinstance(target_hash, str):
        return None
    try:
        target = RunManifest.model_validate(document)
    except ValidationError as error:
        raise RunManifestIntegrityError(
            "transition event has an invalid projection"
        ) from error
    if (
        target.id != directory_name
        or target.content_hash != target_hash
        or canonical_manifest_hash(target) != target_hash
        or target.status != event.status
    ):
        raise RunManifestIntegrityError("transition event projection is inconsistent")
    return target


def _read_run_events(run_dir: Path, run_id: str) -> tuple[RunEvent, ...]:
    path = run_dir / "events.jsonl"
    if not path.exists() and not _is_link_or_reparse(path):
        return ()
    try:
        data = stable_read_file(path).data
        events = tuple(
            RunEvent.model_validate(json.loads(line))
            for line in data.splitlines()
            if line.strip()
        )
    except (OSError, StableReadError, ValueError, ValidationError) as error:
        raise RunManifestIntegrityError(
            "Run event ledger cannot be verified"
        ) from error
    if any(event.run_id != run_id for event in events):
        raise RunManifestIntegrityError("Run event ledger contains a foreign Run id")
    return events


def _requires_integrity_check(source: str, target: str) -> bool:
    return (source, target) in {
        ("queued", "preparing"),
        ("preparing", "running"),
    } or (source == "running" and target in TERMINAL_STATES)


@contextmanager
def _exclusive_run_lock(run_dir: Path) -> Iterator[None]:
    if _is_link_or_reparse(run_dir) or not run_dir.is_dir():
        raise RunManifestIntegrityError("Run directory must be a real directory")
    _reject_link_components(run_dir)
    lock_path = run_dir / ".transition.lock"
    if _is_link_or_reparse(lock_path):
        raise RunManifestIntegrityError("Run transition lock must not be a link")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(lock_path, flags, 0o600)
        opened = os.fstat(descriptor)
        current = lock_path.lstat()
        if (
            not stat.S_ISREG(opened.st_mode)
            or _is_link_or_reparse(lock_path)
            or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
        ):
            raise RunManifestIntegrityError(
                "Run transition lock must be a stable regular file"
            )
    except RunManifestIntegrityError:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    except OSError as error:
        if descriptor >= 0:
            os.close(descriptor)
        raise RunManifestIntegrityError(
            "Run transition lock cannot be opened"
        ) from error
    with os.fdopen(descriptor, "r+b") as stream:
        stream.seek(0)
        _lock_file(stream.fileno())
        try:
            if lock_path.stat().st_size == 0:
                stream.write(b"\0")
                stream.flush()
            yield
        finally:
            stream.seek(0)
            _unlock_file(stream.fileno())


def _reject_link_components(path: Path) -> None:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if _is_link_or_reparse(current):
            raise RunManifestIntegrityError(
                f"Run path contains a link or reparse point: {current}"
            )


def _lock_file(file_descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(file_descriptor, msvcrt.LK_LOCK, 1)
        return
    import fcntl

    fcntl.flock(file_descriptor, fcntl.LOCK_EX)  # type: ignore[attr-defined]


def _unlock_file(file_descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(file_descriptor, msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(file_descriptor, fcntl.LOCK_UN)  # type: ignore[attr-defined]


def _is_link_or_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(attributes & reparse_flag)
