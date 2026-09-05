"""Deterministic statistics over explicitly declared Run repetitions."""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from collections.abc import Set as AbstractSet

from pydantic import Field

from ai4sota.domain import RunManifest
from ai4sota.domain.common import NonEmptyStr, StrictModel

from .comparison import field_differences

REPETITION_DIMENSIONS = frozenset({"seed", "fold", "repeat"})
_IDENTITY_OR_RESULT_FIELDS = frozenset({"id", "content_hash", "metrics"})


class AggregationError(ValueError):
    """Raised when Runs differ outside their explicit repetition coordinates."""


class AggregatedMetric(StrictModel):
    count: int = Field(ge=2)
    mean: float
    standard_deviation: float = Field(ge=0)


class AggregatedResult(StrictModel):
    count: int = Field(ge=2)
    dimensions: tuple[NonEmptyStr, ...]
    metrics: dict[NonEmptyStr, AggregatedMetric]


def aggregate_runs(
    runs: Sequence[RunManifest], dimensions: AbstractSet[str]
) -> AggregatedResult:
    """Aggregate completed Runs only when their declared dimensions explain all variance."""
    if len(runs) < 2:
        raise AggregationError("at least two Runs are required for aggregation")
    declared = frozenset(dimensions)
    if not declared:
        raise AggregationError("at least one repetition dimension must be declared")
    unknown = declared - REPETITION_DIMENSIONS
    if unknown:
        raise AggregationError(f"unknown repetition dimensions: {sorted(unknown)}")
    for dimension in declared:
        if any(getattr(run, dimension) is None for run in runs):
            raise AggregationError(
                f"all aggregated Runs must declare {dimension!r} coordinates"
            )
    run_ids = tuple(run.id for run in runs)
    if len(set(run_ids)) != len(run_ids):
        raise AggregationError("duplicate Run id in aggregation")
    coordinate_names = tuple(sorted(declared))
    coordinates = tuple(
        tuple(getattr(run, dimension) for dimension in coordinate_names)
        for run in runs
    )
    if len(set(coordinates)) != len(coordinates):
        raise AggregationError("duplicate repetition coordinates in aggregation")
    if any(run.status != "succeeded" for run in runs):
        raise AggregationError("all aggregated Runs must have succeeded")
    _validate_metric_sets(runs)
    differences = set(field_differences(runs))
    disallowed = differences - declared - _IDENTITY_OR_RESULT_FIELDS
    if disallowed:
        raise AggregationError(
            "Runs differ outside declared repetition dimensions: "
            f"{sorted(disallowed)}"
        )
    return AggregatedResult(
        count=len(runs),
        dimensions=tuple(sorted(declared)),
        metrics={
            name: _aggregate_metric([run.metrics[name] for run in runs])
            for name in sorted(runs[0].metrics)
        },
    )


def _validate_metric_sets(runs: Sequence[RunManifest]) -> None:
    names = set(runs[0].metrics)
    if not names:
        raise AggregationError("aggregated Runs must contain metrics")
    for run in runs[1:]:
        if set(run.metrics) != names:
            raise AggregationError("aggregated Runs must have identical metric names")
    if any(
        not math.isfinite(value)
        for run in runs
        for value in run.metrics.values()
    ):
        raise AggregationError("aggregated metrics must be finite")


def _aggregate_metric(values: Sequence[float]) -> AggregatedMetric:
    return AggregatedMetric(
        count=len(values),
        mean=statistics.fmean(values),
        standard_deviation=statistics.stdev(values),
    )


__all__ = [
    "REPETITION_DIMENSIONS",
    "AggregatedMetric",
    "AggregatedResult",
    "AggregationError",
    "aggregate_runs",
]
