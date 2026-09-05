"""Deterministic comparability policy for immutable Run manifests."""

from __future__ import annotations

import math
from collections.abc import Sequence

from pydantic import Field

from ai4sota.domain import ComparabilityState, RunManifest
from ai4sota.domain.common import NonEmptyStr, StrictModel

BLOCKING_FIELDS = (
    "data_fingerprint_hash",
    "task_contract_hash",
    "split_manifest_hash",
    "evaluation_protocol_hash",
    "metric_implementation_hash",
    "integrity_state",
)
_CAVEAT_FIELDS = frozenset({"project_id", "seed", "fold", "repeat"})
_IGNORED_FIELDS = frozenset(
    {
        "id",
        "content_hash",
        "experiment_hash",
        "snapshot_hash",
        "status",
        "metrics",
        "parent_research_commit",
    }
)


class ComparabilityReport(StrictModel):
    """A field-level verdict that governs whether metric deltas are permissible."""

    state: ComparabilityState
    blocking_fields: tuple[NonEmptyStr, ...] = ()
    caveat_fields: tuple[NonEmptyStr, ...] = ()
    metric_deltas: dict[NonEmptyStr, tuple[float, ...]] | None = Field(
        default=None
    )


def field_differences(runs: Sequence[RunManifest]) -> tuple[str, ...]:
    """Return every manifest field whose value is not shared by all supplied Runs."""
    if not runs:
        raise ValueError("at least one Run is required")
    first = runs[0].model_dump(mode="json")
    return tuple(
        name
        for name, value in first.items()
        if any(run.model_dump(mode="json")[name] != value for run in runs[1:])
    )


def compare_runs(runs: Sequence[RunManifest]) -> ComparabilityReport:
    """Classify completed Runs without letting callers override scientific policy."""
    if len(runs) < 2:
        raise ValueError("at least two Runs are required for comparison")
    differences = field_differences(runs)
    blocking = tuple(name for name in BLOCKING_FIELDS if name in differences)
    if any(run.status != "succeeded" for run in runs):
        blocking = tuple(dict.fromkeys((*blocking, "status")))
    if any(
        not math.isfinite(value)
        for run in runs
        for value in run.metrics.values()
    ):
        blocking = tuple(dict.fromkeys((*blocking, "metrics")))
    if blocking:
        return ComparabilityReport(
            state=ComparabilityState.NONE,
            blocking_fields=blocking,
            metric_deltas=None,
        )
    return classify_non_blocking_differences(runs, differences)


def classify_non_blocking_differences(
    runs: Sequence[RunManifest], differences: Sequence[str]
) -> ComparabilityReport:
    """Classify permitted differences and calculate baseline-relative deltas."""
    caveats = tuple(name for name in differences if name in _CAVEAT_FIELDS)
    unknown = tuple(
        name
        for name in differences
        if name not in _CAVEAT_FIELDS and name not in _IGNORED_FIELDS
    )
    if unknown:
        return ComparabilityReport(
            state=ComparabilityState.CAVEATS,
            caveat_fields=(*caveats, *unknown),
            metric_deltas=_metric_deltas(runs),
        )
    state = ComparabilityState.CAVEATS if caveats else ComparabilityState.DIRECT
    return ComparabilityReport(
        state=state,
        caveat_fields=caveats,
        metric_deltas=_metric_deltas(runs),
    )


def _metric_deltas(runs: Sequence[RunManifest]) -> dict[str, tuple[float, ...]]:
    shared_names = set(runs[0].metrics)
    for run in runs[1:]:
        shared_names.intersection_update(run.metrics)
    return {
        name: tuple(run.metrics[name] - runs[0].metrics[name] for run in runs[1:])
        for name in sorted(shared_names)
    }


__all__ = [
    "BLOCKING_FIELDS",
    "ComparabilityReport",
    "classify_non_blocking_differences",
    "compare_runs",
    "field_differences",
]
