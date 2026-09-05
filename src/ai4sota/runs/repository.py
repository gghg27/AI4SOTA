"""Authoritative Run manifest repository and state transitions."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from ai4sota.domain import RunManifest
from ai4sota.projects import ProjectLayout
from ai4sota.storage import ManifestStore, canonical_manifest_hash

from .lifecycle import ALLOWED_TRANSITIONS, RunEvent, append_run_event


class RunManifestIntegrityError(ValueError):
    """Raised when a persisted Run manifest no longer matches its hash."""


class RunStateConflict(RuntimeError):
    """Raised when a compare-and-set caller observed a stale state."""


class InvalidRunTransition(ValueError):
    """Raised when the lifecycle does not permit a requested target state."""


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

    def transition_run(
        self, run_id: str, expected: str, target: str
    ) -> RunManifest:
        return transition_run(self.run_dir(run_id), expected, target)


def load_run_manifest(run_dir: Path) -> RunManifest:
    """Read a strict Run manifest and verify its canonical content address."""
    directory = Path(run_dir)
    manifest_path = directory / "manifest.yaml"
    if _is_link_or_reparse(manifest_path):
        raise RunManifestIntegrityError("Run manifest must not be a link or reparse point")
    manifest = ManifestStore().read(manifest_path, RunManifest)
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


def transition_run(run_dir: Path, expected: str, target: str) -> RunManifest:
    """Compare-and-set one legal lifecycle transition under a per-Run lock."""
    directory = Path(run_dir)
    if not directory.is_dir():
        raise FileNotFoundError(f"run directory does not exist: {directory}")
    with _exclusive_run_lock(directory):
        current = load_run_manifest(directory)
        if current.status != expected:
            raise RunStateConflict(
                f"Run state conflict: expected {expected!r}, found {current.status!r}"
            )
        allowed = ALLOWED_TRANSITIONS.get(current.status, frozenset())
        if target not in allowed:
            raise InvalidRunTransition(
                f"cannot transition Run from {current.status!r} to {target!r}"
            )

        draft = current.model_copy(update={"status": target})
        updated = draft.model_copy(
            update={"content_hash": canonical_manifest_hash(draft)}
        )
        ManifestStore().write(directory / "manifest.yaml", updated)
        append_run_event(
            directory,
            RunEvent(
                id=f"event-{uuid4().hex}",
                run_id=current.id,
                event_type="run_state_transition",
                occurred_at=datetime.now(UTC),
                previous_status=current.status,
                status=target,
            ),
        )
        return updated


@contextmanager
def _exclusive_run_lock(run_dir: Path) -> Iterator[None]:
    lock_path = run_dir / ".transition.lock"
    if _is_link_or_reparse(lock_path):
        raise RunManifestIntegrityError("Run transition lock must not be a link")
    with lock_path.open("a+b") as stream:
        if lock_path.stat().st_size == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        _lock_file(stream.fileno())
        try:
            yield
        finally:
            stream.seek(0)
            _unlock_file(stream.fileno())


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
