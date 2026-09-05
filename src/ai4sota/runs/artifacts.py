"""Manifest-guarded artifact reclamation with append-only tombstones."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import Field

from ai4sota.domain import RunManifest
from ai4sota.domain.common import ContentHash, NonEmptyStr, StrictModel
from ai4sota.files.hashing import sha256_file

from .lifecycle import TERMINAL_STATES, _append_json_line
from .repository import _is_link_or_reparse, load_run_manifest


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
    manifest = _verified_expected_manifest(directory, expected_manifest_hash)
    if manifest.status not in TERMINAL_STATES:
        raise ArtifactCleanupValidationError(
            f"artifacts may be cleaned only for a terminal Run, found {manifest.status!r}"
        )
    selected = _preflight_artifacts(directory, tuple(paths))
    _verified_expected_manifest(directory, expected_manifest_hash)

    removed: list[ArtifactCleanupItem] = []
    for item in selected:
        try:
            _verified_expected_manifest(directory, expected_manifest_hash)
            _recheck_artifact(item)
            item.path.unlink()
        except (OSError, ArtifactCleanupValidationError) as error:
            record = _cleanup_record(manifest.id, expected_manifest_hash, removed)
            if removed:
                _append_tombstone(directory, record)
            raise ArtifactCleanupPartialFailure(record, item.relative_path) from error
        removed.append(
            ArtifactCleanupItem(
                path=item.relative_path,
                sha256=item.sha256,
                size_bytes=item.size_bytes,
                reason=reason,
                removed_at=datetime.now(UTC),
            )
        )

    record = _cleanup_record(manifest.id, expected_manifest_hash, removed)
    _append_tombstone(directory, record)
    return record


def _verified_expected_manifest(
    run_dir: Path, expected_hash: str
) -> RunManifest:
    try:
        manifest = load_run_manifest(run_dir)
    except (OSError, ValueError) as error:
        raise ArtifactCleanupValidationError("Run manifest hash cannot be verified") from error
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
        raise ArtifactCleanupValidationError("artifacts root is a link or reparse point")
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
    run_id: str, manifest_hash: str, items: list[ArtifactCleanupItem]
) -> ArtifactCleanupRecord:
    return ArtifactCleanupRecord(
        id=f"artifact-cleanup-{uuid4().hex}",
        run_id=run_id,
        run_manifest_hash=manifest_hash,
        recorded_at=datetime.now(UTC),
        items=tuple(items),
    )


def _append_tombstone(run_dir: Path, record: ArtifactCleanupRecord) -> None:
    path = run_dir / "artifact-tombstones.jsonl"
    if _is_link_or_reparse(path):
        raise ArtifactCleanupValidationError(
            "artifact tombstone ledger must not be a link or reparse point"
        )
    _append_json_line(path, record.model_dump_json())
