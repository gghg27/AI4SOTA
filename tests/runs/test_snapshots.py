from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

import pytest
from pydantic import BaseModel

import ai4sota.runs.snapshots as snapshots_module
from ai4sota.domain import (
    DataModuleSpec,
    DatasetSourceSpec,
    EvaluationSpec,
    ExperimentSpec,
    MethodSpec,
    ModuleKind,
    ProjectSpec,
    RunManifest,
    SplitManifest,
)
from ai4sota.files.hashing import sha256_file
from ai4sota.projects import ProjectLayout
from ai4sota.runs import (
    SnapshotValidationError,
    aggregate_runs,
    hash_tree,
    prepare_run,
)
from ai4sota.storage import ManifestStore, canonical_manifest_hash

ModelT = TypeVar("ModelT", bound=BaseModel)
ZERO_HASH = "sha256:" + "0" * 64


def _rewrite_manifest(path: Path, model: type[ModelT], **updates: object) -> ModelT:
    current = ManifestStore().read(path, model)
    draft = current.model_copy(update={**updates, "content_hash": ZERO_HASH})
    updated = draft.model_copy(update={"content_hash": canonical_manifest_hash(draft)})
    ManifestStore().write(path, updated)
    return updated


def _rebind_experiment(
    project: ProjectLayout,
    experiment: ExperimentSpec,
    changed_path: Path,
    **updates: object,
) -> ExperimentSpec:
    input_hashes = dict(experiment.input_hashes)
    input_hashes[changed_path.relative_to(project.root).as_posix()] = sha256_file(
        changed_path
    )
    draft = experiment.model_copy(
        update={
            **updates,
            "input_hashes": input_hashes,
            "content_hash": ZERO_HASH,
        }
    )
    return draft.model_copy(update={"content_hash": canonical_manifest_hash(draft)})


def test_workspace_edit_after_prepare_does_not_change_snapshot(
    runnable_project: tuple[ProjectLayout, ExperimentSpec, Path],
) -> None:
    """Catches a prepared Run retaining references to mutable workspace code."""
    project, experiment, _ = runnable_project

    manifest = prepare_run(project, experiment)
    live = project.module_dir(ModuleKind.METHOD) / "model.py"
    snapshot_root = project.runs_dir / manifest.id / "snapshot"
    snapshot = snapshot_root / "modules" / "method" / "current" / "model.py"
    before = sha256_file(snapshot)

    live.write_text("changed after approval", encoding="utf-8")

    assert sha256_file(snapshot) == before
    assert manifest.snapshot_hash == hash_tree(snapshot_root)


def test_prepare_run_copies_only_the_selected_scientific_inputs(
    runnable_project: tuple[ProjectLayout, ExperimentSpec, Path],
) -> None:
    """Catches snapshots omitting bound inputs or copying an external raw dataset."""
    project, experiment, external_data = runnable_project

    manifest = prepare_run(project, experiment)
    snapshot = project.runs_dir / manifest.id / "snapshot"

    assert (snapshot / "ai4sota.project.yaml").is_file()
    assert (snapshot / "experiment.yaml").is_file()
    assert (snapshot / "tasks" / "active.yaml").is_file()
    assert (snapshot / "modules" / "data" / "current" / "adapter.py").is_file()
    assert (snapshot / "modules" / "method" / "current" / "model.py").is_file()
    assert (snapshot / "modules" / "evaluation" / "current" / "evaluator.py").is_file()
    assert (snapshot / "adapters" / "logits_adapter.py").is_file()
    assert (snapshot / "configs" / "train.yaml").is_file()
    assert (snapshot / "schemas" / "prediction.json").is_file()
    assert (snapshot / "pipeline.py").is_file()
    assert (snapshot / "data" / "fingerprints" / "seed.yaml").is_file()
    assert not (snapshot / "data" / "fingerprints" / "unselected.yaml").exists()
    assert (snapshot / "data" / "splits" / "approved.yaml").is_file()
    assert not (snapshot / "data" / "splits" / "unselected.yaml").exists()
    assert all(path.name != external_data.name for path in snapshot.rglob("*"))


def test_prepare_run_rechecks_approved_module_hashes_before_copying(
    runnable_project: tuple[ProjectLayout, ExperimentSpec, Path],
) -> None:
    """Catches stale approval hashes being accepted after a manifest edit."""
    project, experiment, _ = runnable_project
    method_manifest = project.module_dir(ModuleKind.METHOD) / "module.yaml"
    method_manifest.write_text(
        method_manifest.read_text(encoding="utf-8").replace("numpy", "pytorch"),
        encoding="utf-8",
    )

    with pytest.raises(SnapshotValidationError, match="method module"):
        prepare_run(project, experiment)

    assert list(project.runs_dir.iterdir()) == []


def test_prepare_run_rejects_a_different_active_task_reference(
    runnable_project: tuple[ProjectLayout, ExperimentSpec, Path],
) -> None:
    """Catches a valid project manifest selecting a task outside the snapshot."""
    project, experiment, _ = runnable_project
    updated = _rewrite_manifest(
        project.project_file, ProjectSpec, active_task="tasks/other.yaml"
    )
    rebound = _rebind_experiment(project, experiment, project.project_file)

    with pytest.raises(SnapshotValidationError, match="active task"):
        prepare_run(project, rebound)

    assert updated.active_task == "tasks/other.yaml"
    assert list(project.runs_dir.iterdir()) == []


@pytest.mark.parametrize("kind", list(ModuleKind))
def test_prepare_run_rejects_a_different_active_module_reference(
    runnable_project: tuple[ProjectLayout, ExperimentSpec, Path],
    kind: ModuleKind,
) -> None:
    """Catches project-selected modules differing from the snapshotted trees."""
    project, experiment, _ = runnable_project
    current = ManifestStore().read(project.project_file, ProjectSpec)
    active_modules = dict(current.active_modules)
    active_modules[kind] = f"modules/{kind.value}/alternate"
    _rewrite_manifest(
        project.project_file, ProjectSpec, active_modules=active_modules
    )
    rebound = _rebind_experiment(project, experiment, project.project_file)

    with pytest.raises(SnapshotValidationError, match=f"active {kind.value} module"):
        prepare_run(project, rebound)

    assert list(project.runs_dir.iterdir()) == []


def test_prepare_run_requires_an_approval_identifier(
    runnable_project: tuple[ProjectLayout, ExperimentSpec, Path],
) -> None:
    """Catches unapproved experiment state being frozen as an executable Run."""
    project, experiment, _ = runnable_project

    with pytest.raises(SnapshotValidationError, match="approval"):
        prepare_run(project, experiment.model_copy(update={"approval_id": None}))

    assert list(project.runs_dir.iterdir()) == []


def test_prepare_run_rejects_a_tampered_referenced_source_manifest(
    runnable_project: tuple[ProjectLayout, ExperimentSpec, Path],
) -> None:
    """Catches an altered dataset schema entering a hash-bound snapshot."""
    project, experiment, _ = runnable_project
    source = project.module_dir(ModuleKind.DATA) / "dataset.yaml"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "sampling_rate_hz: 200.0", "sampling_rate_hz: 201.0"
        ),
        encoding="utf-8",
    )

    with pytest.raises(SnapshotValidationError, match="dataset source"):
        prepare_run(project, experiment)

    assert list(project.runs_dir.iterdir()) == []


def test_prepare_run_rejects_a_large_file_misplaced_as_config(
    runnable_project: tuple[ProjectLayout, ExperimentSpec, Path],
) -> None:
    """Catches raw or generated payloads being copied through the config boundary."""
    project, experiment, _ = runnable_project
    (project.root / "configs" / "weights.bin").write_bytes(b"x" * (1024 * 1024 + 1))

    with pytest.raises(SnapshotValidationError, match="small config"):
        prepare_run(project, experiment)

    assert list(project.runs_dir.iterdir()) == []


def test_prepare_run_rejects_code_changed_after_experiment_approval(
    runnable_project: tuple[ProjectLayout, ExperimentSpec, Path],
) -> None:
    """Catches executable child bytes omitted from the Experiment hash boundary."""
    project, experiment, _ = runnable_project
    model = project.module_dir(ModuleKind.METHOD) / "model.py"
    model.write_text("LEARNING_RATE = 0.02\n", encoding="utf-8")

    with pytest.raises(SnapshotValidationError, match="input hash"):
        prepare_run(project, experiment)

    assert list(project.runs_dir.iterdir()) == []


def test_prepare_run_rejects_an_unapproved_new_module_file(
    runnable_project: tuple[ProjectLayout, ExperimentSpec, Path],
) -> None:
    """Catches an executable entering a selected module tree after approval."""
    project, experiment, _ = runnable_project
    (project.module_dir(ModuleKind.METHOD) / "unapproved.py").write_text(
        "BACKDOOR = True\n", encoding="utf-8"
    )

    with pytest.raises(SnapshotValidationError, match="input set"):
        prepare_run(project, experiment)

    assert list(project.runs_dir.iterdir()) == []


def test_prepare_run_recomputes_the_external_data_fingerprint(
    runnable_project: tuple[ProjectLayout, ExperimentSpec, Path],
) -> None:
    """Catches mutable raw data being accepted under an obsolete fingerprint."""
    project, experiment, external_data = runnable_project
    external_data.write_bytes(b"changed external dataset bytes")

    with pytest.raises(SnapshotValidationError, match="fingerprint"):
        prepare_run(project, experiment)

    assert list(project.runs_dir.iterdir()) == []


def test_prepare_run_binds_exact_selected_fingerprint_record_bytes(
    runnable_project: tuple[ProjectLayout, ExperimentSpec, Path],
) -> None:
    """Catches byte-level edits that preserve a fingerprint record's meaning."""
    project, experiment, _ = runnable_project
    record = project.fingerprints_dir / "seed.yaml"
    record.write_text(
        record.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8"
    )

    with pytest.raises(SnapshotValidationError, match="input hash"):
        prepare_run(project, experiment)

    assert list(project.runs_dir.iterdir()) == []


@pytest.mark.parametrize(
    ("kind", "model", "updates", "experiment_field"),
    [
        (
            ModuleKind.DATA,
            DataModuleSpec,
            {"task_contract": "task/other"},
            "data_module_hash",
        ),
        (
            ModuleKind.DATA,
            DataModuleSpec,
            {"task_contract_hash": "sha256:" + "9" * 64},
            "data_module_hash",
        ),
        (
            ModuleKind.METHOD,
            MethodSpec,
            {"task_contracts": ("task/other",)},
            "method_module_hash",
        ),
        (
            ModuleKind.EVALUATION,
            EvaluationSpec,
            {"task_contract": "task/other"},
            "evaluation_module_hash",
        ),
        (
            ModuleKind.EVALUATION,
            EvaluationSpec,
            {"task_contract_hash": "sha256:" + "9" * 64},
            "evaluation_module_hash",
        ),
    ],
)
def test_prepare_run_rejects_module_task_reference_mismatches(
    runnable_project: tuple[ProjectLayout, ExperimentSpec, Path],
    kind: ModuleKind,
    model: type[BaseModel],
    updates: dict[str, object],
    experiment_field: str,
) -> None:
    """Catches individually valid manifests that do not form one task closure."""
    project, experiment, _ = runnable_project
    path = project.module_dir(kind) / "module.yaml"
    updated = _rewrite_manifest(path, model, **updates)
    rebound = _rebind_experiment(
        project,
        experiment,
        path,
        **{experiment_field: updated.content_hash},
    )
    if kind is ModuleKind.EVALUATION:
        split_path = project.splits_dir / "approved.yaml"
        split = _rewrite_manifest(
            split_path, SplitManifest, evaluation_hash=updated.content_hash
        )
        rebound = _rebind_experiment(
            project,
            rebound,
            split_path,
            split_manifest_hash=split.content_hash,
        )

    with pytest.raises(SnapshotValidationError, match="task contract"):
        prepare_run(project, rebound)


def test_prepare_run_rejects_a_fingerprint_record_for_another_source_revision(
    runnable_project: tuple[ProjectLayout, ExperimentSpec, Path],
) -> None:
    """Catches a selected fingerprint record that only shares the raw digest."""
    project, experiment, _ = runnable_project
    path = project.fingerprints_dir / "seed.yaml"
    _rewrite_manifest(path, DatasetSourceSpec, name="Different source revision")
    rebound = _rebind_experiment(project, experiment, path)

    with pytest.raises(SnapshotValidationError, match="fingerprint record"):
        prepare_run(project, rebound)


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"seed": 23}, "seed"),
        ({"group_by": "session_id"}, "group"),
    ],
)
def test_prepare_run_rejects_split_boundary_mismatches(
    runnable_project: tuple[ProjectLayout, ExperimentSpec, Path],
    updates: dict[str, object],
    message: str,
) -> None:
    """Catches an approved split that belongs to another execution boundary."""
    project, experiment, _ = runnable_project
    path = project.splits_dir / "approved.yaml"
    split = _rewrite_manifest(path, SplitManifest, **updates)
    rebound = _rebind_experiment(
        project,
        experiment,
        path,
        split_manifest_hash=split.content_hash,
    )

    with pytest.raises(SnapshotValidationError, match=message):
        prepare_run(project, rebound)


def test_prepare_run_stages_the_same_bytes_that_were_verified(
    runnable_project: tuple[ProjectLayout, ExperimentSpec, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches a second source read replacing already approved bytes."""
    project, experiment, _ = runnable_project
    live_model = project.module_dir(ModuleKind.METHOD) / "model.py"
    relative = live_model.relative_to(project.root).as_posix()
    real_atomic_write = snapshots_module.atomic_write_bytes
    mutated = False

    def mutate_during_staging(path: Path, data: bytes) -> None:
        nonlocal mutated
        if not mutated and "snapshot" in path.parts:
            mutated = True
            live_model.write_text("LEARNING_RATE = 9.99\n", encoding="utf-8")
        real_atomic_write(path, data)

    monkeypatch.setattr(snapshots_module, "atomic_write_bytes", mutate_during_staging)

    manifest = prepare_run(project, experiment)
    staged_model = (
        project.runs_dir
        / manifest.id
        / "snapshot"
        / "modules"
        / "method"
        / "current"
        / "model.py"
    )
    assert sha256_file(staged_model) == experiment.input_hashes[relative]


def test_prepare_run_rejects_staged_snapshot_corruption_before_publication(
    runnable_project: tuple[ProjectLayout, ExperimentSpec, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches staged bytes changing after the snapshot hash was computed."""
    project, experiment, _ = runnable_project
    real_append = snapshots_module.append_run_event

    def corrupt_after_event(run_dir: Path, event: object) -> None:
        real_append(run_dir, event)  # type: ignore[arg-type]
        (run_dir / "snapshot" / "pipeline.py").write_text(
            "CORRUPTED = True\n", encoding="utf-8"
        )

    monkeypatch.setattr(snapshots_module, "append_run_event", corrupt_after_event)

    with pytest.raises(SnapshotValidationError, match="staged snapshot"):
        prepare_run(project, experiment)

    assert list(project.runs_dir.iterdir()) == []


def test_prepare_run_uses_durable_directory_publication(
    runnable_project: tuple[ProjectLayout, ExperimentSpec, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches a Run rename returning before publication metadata is durable."""
    project, experiment, _ = runnable_project
    real_replace = snapshots_module.durable_replace
    calls: list[tuple[Path, Path]] = []

    def observed_replace(source: Path, destination: Path) -> None:
        calls.append((source, destination))
        real_replace(source, destination)

    monkeypatch.setattr(snapshots_module, "durable_replace", observed_replace)

    manifest = prepare_run(project, experiment)

    assert calls == [
        (project.index_file.parent / manifest.id, project.runs_dir / manifest.id)
    ]


def test_prepare_run_persists_the_approved_repetition_seed(
    runnable_project: tuple[ProjectLayout, ExperimentSpec, Path],
) -> None:
    """Catches aggregation coordinates being lost when an approved Run is frozen."""
    project, experiment, _ = runnable_project

    manifest = prepare_run(project, experiment)

    assert manifest.seed == 17
    assert ManifestStore().read(
        project.runs_dir / manifest.id / "manifest.yaml", RunManifest
    ).seed == 17


def test_prepared_run_repetition_seeds_aggregate_without_changing_the_snapshot(
    runnable_project: tuple[ProjectLayout, ExperimentSpec, Path],
) -> None:
    """Catches seed repetitions altering the immutable approved input snapshot."""
    project, experiment, _ = runnable_project

    first = prepare_run(project, experiment, repetition_seed=7)
    second = prepare_run(project, experiment, repetition_seed=17)
    completed = [
        _completed_run(first, macro_f1=0.8),
        _completed_run(second, macro_f1=0.82),
    ]

    result = aggregate_runs(completed, dimensions={"seed"})

    assert first.snapshot_hash == second.snapshot_hash
    assert first.experiment_hash == second.experiment_hash == experiment.content_hash
    assert (first.seed, second.seed) == (7, 17)
    assert ManifestStore().read(
        project.runs_dir / first.id / "manifest.yaml", RunManifest
    ).seed == 7
    first_event = json.loads(
        (project.runs_dir / first.id / "events.jsonl").read_text(encoding="utf-8")
    )
    assert first_event["details"]["approval_id"] == experiment.approval_id
    assert first_event["details"]["repetition_coordinates"] == {"seed": 7}
    assert result.metrics["macro_f1"].mean == pytest.approx(0.81)


def _completed_run(manifest: RunManifest, *, macro_f1: float) -> RunManifest:
    draft = manifest.model_copy(
        update={
            "content_hash": ZERO_HASH,
            "status": "succeeded",
            "metrics": {"macro_f1": macro_f1},
        }
    )
    return draft.model_copy(update={"content_hash": canonical_manifest_hash(draft)})
