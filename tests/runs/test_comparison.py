from __future__ import annotations

from typing import Literal

import pytest

from ai4sota.domain import ComparabilityState, RunManifest
from ai4sota.runs.comparison import compare_runs

CONTENT_HASH = "sha256:" + "a" * 64


def make_run(
    run_id: str,
    *,
    split_manifest_hash: str = CONTENT_HASH,
    seed: int | None = None,
    status: str = "succeeded",
    macro_f1: float = 0.8,
    metric_environment_state: Literal["reproducible", "unresolved"] = "reproducible",
) -> RunManifest:
    return RunManifest(
        id=run_id,
        content_hash=CONTENT_HASH,
        project_id="project/seed-emotion",
        experiment_hash=CONTENT_HASH,
        snapshot_hash=CONTENT_HASH,
        data_fingerprint_hash=CONTENT_HASH,
        task_contract_hash=CONTENT_HASH,
        split_manifest_hash=split_manifest_hash,
        evaluation_protocol_hash=CONTENT_HASH,
        metric_implementation_hash=CONTENT_HASH,
        metric_environment_state=metric_environment_state,
        integrity_state="verified",
        status=status,
        seed=seed,
        metrics={"macro_f1": macro_f1},
    )


def test_different_test_members_suppress_delta_language() -> None:
    """Catches result deltas being reported across different test memberships."""
    report = compare_runs(
        [
            make_run("run-a", macro_f1=0.8),
            make_run(
                "run-other-split",
                split_manifest_hash="sha256:" + "b" * 64,
                macro_f1=0.85,
            ),
        ]
    )

    assert report.state is ComparabilityState.NONE
    assert report.metric_deltas is None
    assert "split_manifest_hash" in report.blocking_fields


def test_repetition_coordinate_difference_is_reported_as_a_caveat() -> None:
    """Catches seed variation being mislabeled as a fully direct comparison."""
    report = compare_runs(
        [make_run("run-seed-7", seed=7), make_run("run-seed-17", seed=17)]
    )

    assert report.state is ComparabilityState.CAVEATS
    assert report.caveat_fields == ("seed",)
    assert report.metric_deltas == {"macro_f1": (0.0,)}


def test_completed_runs_report_metric_deltas_relative_to_the_first_run() -> None:
    """Catches a direct comparison reversing or dropping a measured difference."""
    report = compare_runs(
        [
            make_run("run-baseline", macro_f1=0.8),
            make_run("run-candidate", macro_f1=0.83),
        ]
    )

    assert report.state is ComparabilityState.DIRECT
    assert report.metric_deltas == {"macro_f1": pytest.approx((0.03,))}


def test_unresolved_metric_environment_suppresses_delta_language() -> None:
    """Catches equal unknown dependency states authorizing a direct comparison."""
    report = compare_runs(
        [
            make_run("run-a", metric_environment_state="unresolved"),
            make_run("run-b", metric_environment_state="unresolved"),
        ]
    )

    assert report.state is ComparabilityState.NONE
    assert report.blocking_fields == ("metric_environment_state",)
    assert report.metric_deltas is None


def test_incomplete_run_suppresses_delta_language() -> None:
    """Catches an unfinished Run being used to make an improvement claim."""
    report = compare_runs(
        [make_run("run-complete"), make_run("run-running", status="running")]
    )

    assert report.state is ComparabilityState.NONE
    assert report.metric_deltas is None
    assert report.blocking_fields == ("status",)


def test_nonfinite_metrics_suppress_delta_language() -> None:
    """Catches an invalid numeric metric being emitted as a comparison result."""
    report = compare_runs(
        [make_run("run-valid"), make_run("run-nan", macro_f1=float("nan"))]
    )

    assert report.state is ComparabilityState.NONE
    assert report.metric_deltas is None
    assert report.blocking_fields == ("metrics",)
