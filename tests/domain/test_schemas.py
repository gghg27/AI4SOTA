from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai4sota.domain.decisions import DecisionRecord
from ai4sota.domain.experiments import (
    ExperimentSpec,
    ResearchCommitManifest,
    RunManifest,
    SplitManifest,
    SplitMember,
)
from ai4sota.domain.modules import (
    DataModuleSpec,
    DatasetSourceSpec,
    EvaluationSpec,
    MethodSpec,
    ModuleKind,
    PreprocessingSpec,
    SplitProtocolSpec,
)
from ai4sota.domain.projects import ProjectSpec
from ai4sota.domain.task import TaskContract

CONTENT_HASH = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

DATA_MODULE_FIXTURE = {
    "id": "data/seed",
    "version": "1.0.0",
    "content_hash": CONTENT_HASH,
    "origin": {
        "type": "project",
        "based_on": "data/seed@0.4.0",
        "remote_source": None,
    },
    "source": "sources/seed.yaml",
    "preprocessing": "preprocessing/seed.yaml",
    "entrypoint": "adapter:load",
    "canonical_outputs": ["signal", "label", "subject_id"],
    "task_contract": "tasks/emotion.yaml",
    "task_contract_hash": CONTENT_HASH,
    "validation_commands": ["pytest tests/data -q"],
}


@pytest.mark.parametrize(
    "content_hash",
    [
        "sha256:",
        "sha256:not-a-hex-digest",
        "sha256:" + "a" * 63,
    ],
)
def test_content_hash_rejects_noncanonical_sha256_digests(content_hash: str) -> None:
    """Catches malformed content addresses being persisted as scientific provenance."""
    with pytest.raises(ValidationError):
        TaskContract(
            id="task/emotion",
            content_hash=content_hash,
            prediction_unit="trial",
            target_type="multiclass",
            classes={"negative": 0, "neutral": 1},
            required_metadata=["subject_id"],
        )


def test_decision_record_rejects_a_selection_absent_from_options() -> None:
    """Catches a confirmed decision whose stored answer was never an offered choice."""
    with pytest.raises(ValidationError):
        DecisionRecord(
            id="decision/subject-split",
            content_hash=CONTENT_HASH,
            scope="evaluation",
            question="Which subject-safe split should be used?",
            options=["group holdout", "group k-fold"],
            selected_option="random holdout",
            confirmed_by="researcher",
            confirmed_content_hashes=[CONTENT_HASH],
        )


def test_task_contract_rejects_duplicate_class_codes() -> None:
    """Catches a task ontology that maps distinct classes to one model output."""
    with pytest.raises(ValidationError):
        TaskContract(
            id="task/emotion",
            content_hash=CONTENT_HASH,
            prediction_unit="trial",
            target_type="multiclass",
            classes={"negative": 0, "neutral": 0},
            required_metadata=["subject_id"],
        )


def test_data_module_round_trips_with_remote_source_reserved() -> None:
    """Catches lossy module serialization or a remote source being required in v1."""
    spec = DataModuleSpec.model_validate(DATA_MODULE_FIXTURE)
    assert spec.kind is ModuleKind.DATA
    assert spec.origin.remote_source is None
    assert DataModuleSpec.model_validate(spec.model_dump()).id == "data/seed"


def test_project_contract_rejects_unknown_persisted_fields() -> None:
    """Catches silent acceptance of unversioned or misspelled project fields."""
    with pytest.raises(ValidationError):
        ProjectSpec(
            id="project/seed-emotion",
            content_hash=CONTENT_HASH,
            name="Seed emotion",
            active_modules={
                "data": "modules/data/current",
                "method": "modules/method/current",
                "evaluation": "modules/evaluation/current",
            },
            unsupported_field="must fail",
        )


def test_source_rejects_a_non_positive_sampling_rate() -> None:
    """Catches invalid acquisition metadata before it reaches compatibility checks."""
    with pytest.raises(ValidationError):
        DatasetSourceSpec(
            id="source/seed",
            content_hash=CONTENT_HASH,
            name="Seed EEG",
            locations=["data/seed.edf"],
            sampling_rate_hz=0,
            metadata_fields=["subject_id"],
            fingerprint_hash=CONTENT_HASH,
        )


def test_module_entrypoints_and_metric_ownership_are_enforced() -> None:
    """Catches empty runnable modules and ambiguous evaluation-primary metrics."""
    with pytest.raises(ValidationError):
        MethodSpec(
            id="method/baseline",
            version="1.0.0",
            content_hash=CONTENT_HASH,
            origin={"type": "project", "remote_source": None},
            framework="numpy",
            entrypoint="",
            input_requirements={"layout": "batch,time,channel"},
            output_capabilities=["logits"],
        )
    with pytest.raises(ValidationError):
        EvaluationSpec(
            id="evaluation/subject-holdout",
            version="1.0.0",
            content_hash=CONTENT_HASH,
            origin={"type": "project", "remote_source": None},
            entrypoint="evaluate:run",
            task_contract="tasks/emotion.yaml",
            task_contract_hash=CONTENT_HASH,
            required_predictions=["logits"],
            protocol={"kind": "group_holdout", "group_by": "subject_id"},
            metrics=[
                {"name": "accuracy", "primary": True, "implementation": "builtin/v1"},
                {"name": "macro_f1", "primary": True, "implementation": "builtin/v1"},
            ],
        )


def test_split_protocol_preserves_the_declared_evaluation_partition() -> None:
    """Catches Phase 1's evaluate_split being dropped from typed persistence."""
    protocol = SplitProtocolSpec(
        kind="declared_split",
        group_by="split",
        evaluate_split="test",
    )

    assert protocol.evaluate_split == "test"


def test_ledger_manifests_round_trip_exact_content_addresses() -> None:
    """Catches snapshots that lose their hash-bound scientific provenance."""
    preprocessing = PreprocessingSpec(
        id="preprocessing/seed",
        content_hash=CONTENT_HASH,
        transforms=[{"name": "bandpass", "parameters": {"low_hz": 1, "high_hz": 40}}],
        graph_hash=CONTENT_HASH,
    )
    split = SplitManifest(
        id="split/run-001",
        content_hash=CONTENT_HASH,
        evaluation_hash=CONTENT_HASH,
        seed=17,
        group_by="subject_id",
        members=[
            SplitMember(sample_id="sample-001", partition="train"),
            SplitMember(sample_id="sample-002", partition="test"),
        ],
    )
    experiment = ExperimentSpec(
        id="experiment/run-001",
        content_hash=CONTENT_HASH,
        project_id="project/seed-emotion",
        data_module_hash=CONTENT_HASH,
        method_module_hash=CONTENT_HASH,
        evaluation_module_hash=CONTENT_HASH,
        task_contract_hash=CONTENT_HASH,
        data_fingerprint_hash=CONTENT_HASH,
        split_manifest_hash=split.content_hash,
        seed=17,
        input_hashes={"modules/method/current/model.py": CONTENT_HASH},
    )
    run = RunManifest(
        id="run/001",
        content_hash=CONTENT_HASH,
        project_id="project/seed-emotion",
        experiment_hash=experiment.content_hash,
        snapshot_hash=CONTENT_HASH,
        data_fingerprint_hash=CONTENT_HASH,
        task_contract_hash=CONTENT_HASH,
        split_manifest_hash=split.content_hash,
        evaluation_protocol_hash=CONTENT_HASH,
        metric_implementation_hash=CONTENT_HASH,
        integrity_state="verified",
    )
    commit = ResearchCommitManifest(
        id="research-commit/001",
        content_hash=CONTENT_HASH,
        project_id="project/seed-emotion",
        run_ids=[run.id],
        run_manifest_hashes=[run.content_hash],
        git_sha="0123456789abcdef",
        snapshot_hash=run.snapshot_hash,
    )
    decision = DecisionRecord(
        id="decision/subject-split",
        content_hash=CONTENT_HASH,
        scope="evaluation",
        question="Which subject-safe split should be used?",
        options=["group holdout", "group k-fold"],
        selected_option="group holdout",
        confirmed_by="researcher",
        confirmed_content_hashes=[experiment.content_hash],
    )

    assert preprocessing.api_version == "ai4sota/v1"
    assert (
        SplitManifest.model_validate(split.model_dump()).members[1].partition == "test"
    )
    assert experiment.input_hashes == {"modules/method/current/model.py": CONTENT_HASH}
    assert RunManifest.model_validate(run.model_dump()).snapshot_hash == CONTENT_HASH
    assert ResearchCommitManifest.model_validate(commit.model_dump()).run_ids == (
        "run/001",
    )
    assert (
        DecisionRecord.model_validate(decision.model_dump()).scope.value == "evaluation"
    )


@pytest.mark.parametrize(
    "input_hashes",
    [
        {},
        {"/modules/method/current/model.py": CONTENT_HASH},
        {"modules/method/current/../model.py": CONTENT_HASH},
        {"modules\\method\\current\\model.py": CONTENT_HASH},
        {"./modules/method/current/model.py": CONTENT_HASH},
        {".": CONTENT_HASH},
        {" modules/method/current/model.py ": CONTENT_HASH},
    ],
)
def test_experiment_rejects_empty_or_noncanonical_input_paths(
    input_hashes: dict[str, str],
) -> None:
    """Catches ambiguous or incomplete project input closures."""
    with pytest.raises(ValidationError):
        ExperimentSpec(
            id="experiment/run-001",
            content_hash=CONTENT_HASH,
            project_id="project/seed-emotion",
            data_module_hash=CONTENT_HASH,
            method_module_hash=CONTENT_HASH,
            evaluation_module_hash=CONTENT_HASH,
            task_contract_hash=CONTENT_HASH,
            data_fingerprint_hash=CONTENT_HASH,
            split_manifest_hash=CONTENT_HASH,
            seed=17,
            input_hashes=input_hashes,
        )
