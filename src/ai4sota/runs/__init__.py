"""Immutable Run snapshots, lifecycle state, and artifact provenance."""

from .aggregation import (
    REPETITION_DIMENSIONS,
    AggregatedMetric,
    AggregatedResult,
    AggregationError,
    aggregate_runs,
)
from .artifacts import (
    ArtifactCleanupItem,
    ArtifactCleanupPartialFailure,
    ArtifactCleanupRecord,
    ArtifactCleanupValidationError,
    cleanup_artifacts,
)
from .comparison import BLOCKING_FIELDS, ComparabilityReport, compare_runs
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
    record_run_metrics,
    transition_run,
    verify_run_integrity,
)
from .snapshots import (
    SnapshotValidationError,
    hash_tree,
    prepare_run,
    snapshot_input_hashes,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "BLOCKING_FIELDS",
    "REPETITION_DIMENSIONS",
    "TERMINAL_STATES",
    "AggregatedMetric",
    "AggregatedResult",
    "AggregationError",
    "ArtifactCleanupItem",
    "ArtifactCleanupPartialFailure",
    "ArtifactCleanupRecord",
    "ArtifactCleanupValidationError",
    "ComparabilityReport",
    "InvalidRunTransition",
    "RunEvent",
    "RunManifestIntegrityError",
    "RunPersistenceError",
    "RunRepository",
    "RunStateConflict",
    "SnapshotValidationError",
    "aggregate_runs",
    "append_run_event",
    "cleanup_artifacts",
    "compare_runs",
    "hash_tree",
    "load_run_manifest",
    "manifest_hash",
    "prepare_run",
    "record_run_metrics",
    "snapshot_input_hashes",
    "transition_run",
    "verify_run_integrity",
]
