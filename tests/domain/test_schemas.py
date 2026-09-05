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
)
from ai4sota.domain.projects import ProjectSpec
from ai4sota.domain.task import TaskContract

DATA_MODULE_FIXTURE = {
    "id": "data/seed",
    "version": "1.0.0",
    "content_hash": "sha256:data-module",
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
    "task_contract_hash": "sha256:task",
    "validation_commands": ["pytest tests/data -q"],
}


def test_task_contract_rejects_duplicate_class_codes() -> None:
    """Catches a task ontology that maps distinct classes to one model output."""
    with pytest.raises(ValidationError):
        TaskContract(
            id="task/emotion",
            content_hash="sha256:task",
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
            content_hash="sha256:project",
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
            content_hash="sha256:source",
            name="Seed EEG",
            locations=["data/seed.edf"],
            sampling_rate_hz=0,
            metadata_fields=["subject_id"],
            fingerprint_hash="sha256:fingerprint",
        )


def test_module_entrypoints_and_metric_ownership_are_enforced() -> None:
    """Catches empty runnable modules and ambiguous evaluation-primary metrics."""
    with pytest.raises(ValidationError):
        MethodSpec(
            id="method/baseline",
            version="1.0.0",
            content_hash="sha256:method",
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
            content_hash="sha256:evaluation",
            origin={"type": "project", "remote_source": None},
            entrypoint="evaluate:run",
            task_contract="tasks/emotion.yaml",
            task_contract_hash="sha256:task",
            required_predictions=["logits"],
            protocol={"kind": "group_holdout", "group_by": "subject_id"},
            metrics=[
                {"name": "accuracy", "primary": True, "implementation": "builtin/v1"},
                {"name": "macro_f1", "primary": True, "implementation": "builtin/v1"},
            ],
        )


def test_ledger_manifests_round_trip_exact_content_addresses() -> None:
    """Catches snapshots that lose their hash-bound scientific provenance."""
    preprocessing = PreprocessingSpec(
        id="preprocessing/seed",
        content_hash="sha256:preprocessing",
        transforms=[{"name": "bandpass", "parameters": {"low_hz": 1, "high_hz": 40}}],
        graph_hash="sha256:graph",
    )
    split = SplitManifest(
        id="split/run-001",
        content_hash="sha256:split",
        evaluation_hash="sha256:evaluation",
        seed=17,
        group_by="subject_id",
        members=[
            SplitMember(sample_id="sample-001", partition="train"),
            SplitMember(sample_id="sample-002", partition="test"),
        ],
    )
    experiment = ExperimentSpec(
        id="experiment/run-001",
        content_hash="sha256:experiment",
        project_id="project/seed-emotion",
        data_module_hash="sha256:data-module",
        method_module_hash="sha256:method",
        evaluation_module_hash="sha256:evaluation",
        task_contract_hash="sha256:task",
        data_fingerprint_hash="sha256:fingerprint",
        split_manifest_hash=split.content_hash,
        seed=17,
    )
    run = RunManifest(
        id="run/001",
        content_hash="sha256:run",
        project_id="project/seed-emotion",
        experiment_hash=experiment.content_hash,
        snapshot_hash="sha256:snapshot",
        data_fingerprint_hash="sha256:fingerprint",
        task_contract_hash="sha256:task",
        split_manifest_hash=split.content_hash,
        evaluation_protocol_hash="sha256:protocol",
        metric_implementation_hash="sha256:metrics",
        integrity_state="verified",
    )
    commit = ResearchCommitManifest(
        id="research-commit/001",
        content_hash="sha256:commit",
        project_id="project/seed-emotion",
        run_ids=[run.id],
        run_manifest_hashes=[run.content_hash],
        git_sha="0123456789abcdef",
        snapshot_hash=run.snapshot_hash,
    )
    decision = DecisionRecord(
        id="decision/subject-split",
        content_hash="sha256:decision",
        scope="evaluation",
        question="Which subject-safe split should be used?",
        options=["group holdout", "group k-fold"],
        selected_option="group holdout",
        confirmed_by="researcher",
        confirmed_content_hashes=[experiment.content_hash],
    )

    assert preprocessing.api_version == "ai4sota/v1"
    assert SplitManifest.model_validate(split.model_dump()).members[1].partition == "test"
    assert RunManifest.model_validate(run.model_dump()).snapshot_hash == "sha256:snapshot"
    assert ResearchCommitManifest.model_validate(commit.model_dump()).run_ids == ("run/001",)
    assert DecisionRecord.model_validate(decision.model_dump()).scope.value == "evaluation"
