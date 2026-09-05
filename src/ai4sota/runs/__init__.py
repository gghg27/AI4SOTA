"""Immutable Run snapshots, lifecycle state, and artifact provenance."""

from .artifacts import (
    ArtifactCleanupItem,
    ArtifactCleanupPartialFailure,
    ArtifactCleanupRecord,
    ArtifactCleanupValidationError,
    cleanup_artifacts,
)
from .lifecycle import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATES,
    RunEvent,
    append_run_event,
)
from .repository import (
    InvalidRunTransition,
    RunManifestIntegrityError,
    RunPersistenceError,
    RunRepository,
    RunStateConflict,
    load_run_manifest,
    manifest_hash,
    transition_run,
    verify_run_integrity,
)
from .snapshots import SnapshotValidationError, hash_tree, prepare_run

__all__ = [
    "ALLOWED_TRANSITIONS",
    "TERMINAL_STATES",
    "ArtifactCleanupItem",
    "ArtifactCleanupPartialFailure",
    "ArtifactCleanupRecord",
    "ArtifactCleanupValidationError",
    "InvalidRunTransition",
    "RunEvent",
    "RunManifestIntegrityError",
    "RunPersistenceError",
    "RunRepository",
    "RunStateConflict",
    "SnapshotValidationError",
    "append_run_event",
    "cleanup_artifacts",
    "hash_tree",
    "load_run_manifest",
    "manifest_hash",
    "prepare_run",
    "transition_run",
    "verify_run_integrity",
]
