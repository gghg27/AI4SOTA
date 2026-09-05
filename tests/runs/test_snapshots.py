from __future__ import annotations

from pathlib import Path

import pytest

from ai4sota.domain import ExperimentSpec, ModuleKind
from ai4sota.files.hashing import sha256_file
from ai4sota.projects import ProjectLayout
from ai4sota.runs import SnapshotValidationError, hash_tree, prepare_run


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
    assert (
        snapshot / "modules" / "evaluation" / "current" / "evaluator.py"
    ).is_file()
    assert (snapshot / "adapters" / "logits_adapter.py").is_file()
    assert (snapshot / "configs" / "train.yaml").is_file()
    assert (snapshot / "schemas" / "prediction.json").is_file()
    assert (snapshot / "pipeline.py").is_file()
    assert (snapshot / "data" / "fingerprints" / "seed.yaml").is_file()
    assert not (
        snapshot / "data" / "fingerprints" / "unselected.yaml"
    ).exists()
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
