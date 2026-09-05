from __future__ import annotations

import pytest

from ai4sota.domain import RunManifest
from ai4sota.runs.aggregation import AggregationError, aggregate_runs

CONTENT_HASH = "sha256:" + "a" * 64


def make_run(
    run_id: str,
    *,
    seed: int | None = None,
    snapshot_hash: str = CONTENT_HASH,
    status: str = "succeeded",
    macro_f1: float = 0.8,
) -> RunManifest:
    return RunManifest(
        id=run_id,
        content_hash=CONTENT_HASH,
        project_id="project/seed-emotion",
        experiment_hash=CONTENT_HASH,
        snapshot_hash=snapshot_hash,
        data_fingerprint_hash=CONTENT_HASH,
        task_contract_hash=CONTENT_HASH,
        split_manifest_hash=CONTENT_HASH,
        evaluation_protocol_hash=CONTENT_HASH,
        metric_implementation_hash=CONTENT_HASH,
        integrity_state="verified",
        status=status,
        seed=seed,
        metrics={"macro_f1": macro_f1},
    )


def test_only_declared_seed_may_be_aggregated() -> None:
    """Catches seed repetitions being rejected despite being explicitly declared."""
    result = aggregate_runs(
        [make_run("run-seed-7", seed=7, macro_f1=0.8), make_run("run-seed-17", seed=17, macro_f1=0.82)],
        dimensions={"seed"},
    )

    assert result.count == 2
    assert result.dimensions == ("seed",)
    assert result.metrics["macro_f1"].mean == pytest.approx(0.81)
    assert result.metrics["macro_f1"].standard_deviation == pytest.approx(
        0.0141421356
    )


def test_aggregation_rejects_an_undeclared_repetition_coordinate() -> None:
    """Catches combining distinct seeds when callers omitted the seed dimension."""
    with pytest.raises(AggregationError, match="dimension"):
        aggregate_runs(
            [make_run("run-seed-7", seed=7), make_run("run-seed-17", seed=17)],
            dimensions=set(),
        )


def test_aggregation_rejects_a_non_coordinate_manifest_difference() -> None:
    """Catches snapshot provenance changes being hidden behind a seed aggregation."""
    with pytest.raises(AggregationError, match="snapshot_hash"):
        aggregate_runs(
            [
                make_run("run-seed-7", seed=7),
                make_run(
                    "run-seed-17",
                    seed=17,
                    snapshot_hash="sha256:" + "b" * 64,
                ),
            ],
            dimensions={"seed"},
        )


def test_aggregation_rejects_unknown_dimensions() -> None:
    """Catches callers treating arbitrary manifest fields as repetition coordinates."""
    with pytest.raises(AggregationError, match="unknown"):
        aggregate_runs(
            [make_run("run-a"), make_run("run-b")], dimensions={"experiment_hash"}
        )


def test_aggregation_rejects_an_undeclared_coordinate_value() -> None:
    """Catches a caller declaring seed repetition when a Run records no seed."""
    with pytest.raises(AggregationError, match="seed"):
        aggregate_runs(
            [make_run("run-seed-7", seed=7), make_run("run-no-seed")],
            dimensions={"seed"},
        )


def test_aggregation_rejects_incomplete_runs() -> None:
    """Catches a partial metric vector being included in aggregate statistics."""
    with pytest.raises(AggregationError, match="succeeded"):
        aggregate_runs(
            [make_run("run-seed-7", seed=7), make_run("run-running", seed=17, status="running")],
            dimensions={"seed"},
        )
