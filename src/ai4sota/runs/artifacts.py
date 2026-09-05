"""Manifest-guarded artifact reclamation with append-only tombstones."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, Literal
from uuid import uuid4

from pydantic import Field

from ai4sota.domain import RunManifest
from ai4sota.domain.common import ContentHash, NonEmptyStr, StrictModel
from ai4sota.files.hashing import sha256_file
from ai4sota.storage import atomic_write_bytes

from .lifecycle import TERMINAL_STATES
from .repository import (
    _exclusive_run_lock,
    _is_link_or_reparse,
    _lock_file,
    _unlock_file,
    load_run_manifest,
)


class ArtifactCleanupItem(StrictModel):
    path: NonEmptyStr
    sha256: ContentHash
    size_bytes: int = Field(ge=0)
    reason: NonEmptyStr
    removed_at: datetime


class ArtifactCleanupRecord(StrictModel):
    id: NonEmptyStr
    run_id: NonEmptyStr
    run_manifest_hash: ContentHash
    recorded_at: datetime
    items: tuple[ArtifactCleanupItem, ...]


class _ArtifactCleanupEntry(StrictModel):
    cleanup_id: NonEmptyStr
    run_id: NonEmptyStr
    run_manifest_hash: ContentHash
    phase: Literal["intent", "completed"]
    recorded_at: datetime
    item: ArtifactCleanupItem


class ArtifactCleanupValidationError(ValueError):
    """Raised before deletion when a cleanup request is not provably safe."""


class ArtifactCleanupPartialFailure(RuntimeError):
    """Raised after recording payloads removed before an unlink failure."""

    def __init__(self, record: ArtifactCleanupRecord, failed_path: str) -> None:
        self.record = record
        self.failed_path = failed_path
        super().__init__(
            f"artifact cleanup stopped at {failed_path!r} after "
            f"{len(record.items)} successful removals"
        )


class _SelectedArtifact(StrictModel):
    relative_path: NonEmptyStr
    path: Path
    identity: Path
    sha256: ContentHash
    size_bytes: int = Field(ge=0)


def cleanup_artifacts(
    run_dir: Path,
    paths: Sequence[str],
    expected_manifest_hash: str,
    *,
    reason: str = "user requested cleanup",
) -> ArtifactCleanupRecord:
    """Delete selected files only below artifacts/ and durably record successes.

    Every request is fully validated before the first unlink. If an unlink then fails,
    prior successes are tombstoned and exposed on ArtifactCleanupPartialFailure; the
    failed and remaining payloads are left in place.
    """
    if not reason.strip():
        raise ArtifactCleanupValidationError("cleanup reason must not be empty")
    directory = Path(run_dir)
    if _is_link_or_reparse(directory) or not directory.is_dir():
        raise ArtifactCleanupValidationError("Run directory must be a real directory")
    with _exclusive_run_lock(directory):
        manifest = _verified_expected_manifest(directory, expected_manifest_hash)
        if manifest.status not in TERMINAL_STATES:
            raise ArtifactCleanupValidationError(
                "artifacts may be cleaned only for a terminal Run, "
                f"found {manifest.status!r}"
            )
        selected = _preflight_artifacts(directory, tuple(paths))
        _verified_expected_manifest(directory, expected_manifest_hash)
        cleanup_id = f"artifact-cleanup-{uuid4().hex}"
        removed: list[ArtifactCleanupItem] = []

        try:
            ledger_context = _open_cleanup_ledger(directory)
            with ledger_context as ledger:
                for selected_item in selected:
                    item = ArtifactCleanupItem(
                        path=selected_item.relative_path,
                        sha256=selected_item.sha256,
                        size_bytes=selected_item.size_bytes,
                        reason=reason,
                        removed_at=datetime.now(UTC),
                    )
                    try:
                        _verified_expected_manifest(directory, expected_manifest_hash)
                        _recheck_artifact(selected_item)
                        _append_cleanup_entry(
                            ledger,
                            _journal_entry(
                                cleanup_id,
                                manifest.id,
                                expected_manifest_hash,
                                "intent",
                                item,
                            ),
                        )
                    except (OSError, ValueError) as error:
                        raise ArtifactCleanupPartialFailure(
                            _cleanup_record(
                                cleanup_id,
                                manifest.id,
                                expected_manifest_hash,
                                removed,
                            ),
                            selected_item.relative_path,
                        ) from error

                    try:
                        selected_item.path.unlink()
                    except OSError as error:
                        if not selected_item.path.exists():
                            removed.append(item)
                        raise ArtifactCleanupPartialFailure(
                            _cleanup_record(
                                cleanup_id,
                                manifest.id,
                                expected_manifest_hash,
                                removed,
                            ),
                            selected_item.relative_path,
                        ) from error

                    removed.append(item)
                    try:
                        _append_cleanup_entry(
                            ledger,
                            _journal_entry(
                                cleanup_id,
                                manifest.id,
                                expected_manifest_hash,
                                "completed",
                                item,
                            ),
                        )
                    except (OSError, ValueError) as error:
                        raise ArtifactCleanupPartialFailure(
                            _cleanup_record(
                                cleanup_id,
                                manifest.id,
                                expected_manifest_hash,
                                removed,
                            ),
                            selected_item.relative_path,
                        ) from error
        except ArtifactCleanupValidationError:
            raise
        except ArtifactCleanupPartialFailure:
            raise
        except OSError as error:
            failed_path = selected[0].relative_path
            raise ArtifactCleanupPartialFailure(
                _cleanup_record(
                    cleanup_id,
                    manifest.id,
                    expected_manifest_hash,
                    removed,
                ),
                failed_path,
            ) from error

        return _cleanup_record(cleanup_id, manifest.id, expected_manifest_hash, removed)


def _verified_expected_manifest(run_dir: Path, expected_hash: str) -> RunManifest:
    try:
        manifest = load_run_manifest(run_dir)
    except (OSError, ValueError) as error:
        raise ArtifactCleanupValidationError(
            "Run manifest hash cannot be verified"
        ) from error
    if manifest.content_hash != expected_hash:
        raise ArtifactCleanupValidationError(
            f"Run manifest hash mismatch: expected {expected_hash}, "
            f"found {manifest.content_hash}"
        )
    return manifest


def _preflight_artifacts(
    run_dir: Path, relative_paths: tuple[str, ...]
) -> tuple[_SelectedArtifact, ...]:
    if not relative_paths:
        raise ArtifactCleanupValidationError("at least one artifact path is required")
    artifact_root = run_dir / "artifacts"
    if _is_link_or_reparse(artifact_root) or not artifact_root.is_dir():
        raise ArtifactCleanupValidationError("artifacts root must be a real directory")
    resolved_root = artifact_root.resolve(strict=True)
    selected: list[_SelectedArtifact] = []
    identities: set[Path] = set()
    for value in relative_paths:
        relative = Path(value)
        if (
            not value.strip()
            or relative.is_absolute()
            or relative.drive
            or relative.parts in {(), (".",)}
            or ".." in relative.parts
        ):
            raise ArtifactCleanupValidationError(
                f"artifact path must be relative below artifacts/: {value!r}"
            )
        candidate = artifact_root / relative
        _reject_link_components(artifact_root, relative)
        try:
            identity = candidate.resolve(strict=True)
            identity.relative_to(resolved_root)
        except (FileNotFoundError, OSError, ValueError) as error:
            raise ArtifactCleanupValidationError(
                f"artifact path escapes or does not exist: {value!r}"
            ) from error
        if identity == resolved_root or not candidate.is_file():
            raise ArtifactCleanupValidationError(
                f"artifact selection must name a regular file: {value!r}"
            )
        if identity in identities:
            raise ArtifactCleanupValidationError(
                f"duplicate artifact selection: {value!r}"
            )
        identities.add(identity)
        selected.append(
            _SelectedArtifact(
                relative_path=relative.as_posix(),
                path=candidate,
                identity=identity,
                sha256=sha256_file(candidate),
                size_bytes=candidate.stat().st_size,
            )
        )
    return tuple(selected)


def _reject_link_components(root: Path, relative: Path) -> None:
    current = root
    if _is_link_or_reparse(current):
        raise ArtifactCleanupValidationError(
            "artifacts root is a link or reparse point"
        )
    for part in relative.parts:
        current = current / part
        if current.exists() and _is_link_or_reparse(current):
            raise ArtifactCleanupValidationError(
                f"artifact path contains a link or reparse point: {relative}"
            )


def _recheck_artifact(item: _SelectedArtifact) -> None:
    if _is_link_or_reparse(item.path):
        raise ArtifactCleanupValidationError(
            f"artifact changed to a link before deletion: {item.relative_path}"
        )
    try:
        identity = item.path.resolve(strict=True)
    except OSError as error:
        raise ArtifactCleanupValidationError(
            f"artifact disappeared before deletion: {item.relative_path}"
        ) from error
    if (
        identity != item.identity
        or not item.path.is_file()
        or item.path.stat().st_size != item.size_bytes
        or sha256_file(item.path) != item.sha256
    ):
        raise ArtifactCleanupValidationError(
            f"artifact changed after cleanup preflight: {item.relative_path}"
        )


def _cleanup_record(
    cleanup_id: str,
    run_id: str,
    manifest_hash: str,
    items: list[ArtifactCleanupItem],
) -> ArtifactCleanupRecord:
    return ArtifactCleanupRecord(
        id=cleanup_id,
        run_id=run_id,
        run_manifest_hash=manifest_hash,
        recorded_at=datetime.now(UTC),
        items=tuple(items),
    )


def _journal_entry(
    cleanup_id: str,
    run_id: str,
    manifest_hash: str,
    phase: Literal["intent", "completed"],
    item: ArtifactCleanupItem,
) -> _ArtifactCleanupEntry:
    return _ArtifactCleanupEntry(
        cleanup_id=cleanup_id,
        run_id=run_id,
        run_manifest_hash=manifest_hash,
        phase=phase,
        recorded_at=datetime.now(UTC),
        item=item,
    )


@contextmanager
def _open_cleanup_ledger(run_dir: Path) -> Iterator[BinaryIO]:
    path = run_dir / "artifact-tombstones.jsonl"
    if _is_link_or_reparse(path):
        raise ArtifactCleanupValidationError(
            "artifact tombstone ledger must not be a link or reparse point"
        )
    if path.exists() and not path.is_file():
        raise ArtifactCleanupValidationError(
            "artifact tombstone ledger must be a regular file"
        )
    if not path.exists():
        atomic_write_bytes(path, b"")

    flags = os.O_RDWR | os.O_APPEND | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        current = path.lstat()
        if (
            not stat.S_ISREG(opened.st_mode)
            or _is_link_or_reparse(path)
            or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
        ):
            raise ArtifactCleanupValidationError(
                "artifact tombstone ledger must be a stable regular file"
            )
        os.lseek(descriptor, 0, os.SEEK_SET)
        _lock_file(descriptor)
        with os.fdopen(descriptor, "a+b", closefd=False) as stream:
            try:
                yield stream
            finally:
                os.lseek(descriptor, 0, os.SEEK_SET)
                _unlock_file(descriptor)
    finally:
        os.close(descriptor)


def _append_cleanup_entry(stream: BinaryIO, entry: _ArtifactCleanupEntry) -> None:
    encoded = (entry.model_dump_json() + "\n").encode("utf-8")
    written = stream.write(encoded)
    if written != len(encoded):
        raise OSError("short append to artifact tombstone ledger")
    stream.flush()
    os.fsync(stream.fileno())
