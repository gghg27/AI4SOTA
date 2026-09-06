from __future__ import annotations

import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import TypeVar

import numpy as np
import pytest
import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel

import ai4sota.runner as runner_module
from ai4sota.domain import (
    ComparabilityState,
    CompatibilityState,
    DataModuleSpec,
    DatasetSourceSpec,
    EvaluationSpec,
    MethodSpec,
    ModuleKind,
    PreprocessingSpec,
    RunManifest,
    TaskContract,
)
from ai4sota.files import sha256_file
from ai4sota.history import GitAdapter, create_research_commit
from ai4sota.library import ModuleDraft, ModuleLibrary, hash_tree
from ai4sota.projects import ProjectLayout
from ai4sota.runner import execute_run
from ai4sota.runs import (
    RunRepository,
    SnapshotValidationError,
    compare_runs,
    prepare_run,
)
from ai4sota.storage import ManifestStore, canonical_manifest_hash
from ai4sota.workflows import (
    ApprovalValidationError,
    ExperimentBlocked,
    bind_experiment_approval,
    compile_project,
    execute_approved_run,
    prepare_experiment,
)

ModelT = TypeVar("ModelT", bound=BaseModel)
ZERO_HASH = "sha256:" + "0" * 64


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def _write_hashed_manifest(
    path: Path, model: type[ModelT], payload: dict[str, object]
) -> ModelT:
    draft = model.model_validate({**payload, "content_hash": ZERO_HASH})
    value = draft.model_copy(update={"content_hash": canonical_manifest_hash(draft)})
    ManifestStore().write(path, value)
    return value


def _publish_and_import(
    library: ModuleLibrary,
    project: ProjectLayout,
    module_id: str,
    version: str,
    files: dict[str, str],
) -> None:
    draft_root = library.root.parent / "drafts" / module_id.replace("/", "-")
    draft_root.mkdir(parents=True)
    for relative, content in files.items():
        path = draft_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    draft = ModuleDraft(path=draft_root, module_id=module_id, version=version)
    published = library.publish(draft, expected_hash=hash_tree(draft_root))
    library.import_version(published.ref, project)


def create_v1_demo_project(root: Path) -> ProjectLayout:
    project = ProjectLayout.create(root.parent, root.name)
    (project.root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    dataset_path = root.parent / "demo-dataset.npz"
    np.savez(
        dataset_path,
        sample_ids=np.array(["sample-1", "sample-2", "sample-3", "sample-4"]),
        features=np.array([[-2.0], [-1.0], [1.0], [2.0]]),
        labels=np.array([0, 0, 1, 1]),
        subject_ids=np.array(["subject-a", "subject-a", "subject-b", "subject-b"]),
    )
    fingerprint = sha256_file(dataset_path)
    task = _write_hashed_manifest(
        project.task_file,
        TaskContract,
        {
            "id": "task/demo-classification",
            "prediction_unit": "sample",
            "target_type": "binary_classification",
            "classes": {"negative": 0, "positive": 1},
            "required_metadata": ["sample_id", "subject_id"],
        },
    )

    library = ModuleLibrary(root.parent / "module-library")
    data_draft = root.parent / "data-manifests"
    data_draft.mkdir()
    source = _write_hashed_manifest(
        data_draft / "dataset.yaml",
        DatasetSourceSpec,
        {
            "id": "dataset/demo-source",
            "name": "Local demo data",
            "locations": ["../demo-dataset.npz"],
            "sampling_rate_hz": 1.0,
            "metadata_fields": ["sample_id", "subject_id"],
            "fingerprint_hash": fingerprint,
            "source_format": "npz",
        },
    )
    _write_hashed_manifest(
        data_draft / "preprocessing.yaml",
        PreprocessingSpec,
        {
            "id": "preprocessing/demo-v1",
            "transforms": [],
            "graph_hash": "sha256:" + "1" * 64,
        },
    )
    data = _write_hashed_manifest(
        data_draft / "module.yaml",
        DataModuleSpec,
        {
            "id": "data/demo",
            "origin": {"type": "project"},
            "source": "dataset.yaml",
            "preprocessing": "preprocessing.yaml",
            "entrypoint": "adapter:load_dataset",
            "canonical_outputs": [
                "features",
                "label",
                "sample_id",
                "subject_id",
            ],
            "task_contract": task.id,
            "task_contract_hash": task.content_hash,
        },
    )
    _publish_and_import(
        library,
        project,
        data.id,
        data.version,
        {
            "module.yaml": (data_draft / "module.yaml").read_text(encoding="utf-8"),
            "dataset.yaml": (data_draft / "dataset.yaml").read_text(encoding="utf-8"),
            "preprocessing.yaml": (
                data_draft / "preprocessing.yaml"
            ).read_text(encoding="utf-8"),
            "config.yaml": yaml.safe_dump({"source": str(dataset_path)}),
            "adapter.py": (
                "from pathlib import Path\n"
                "import numpy as np\n"
                "from ai4sota import CanonicalDataset\n\n"
                "def load_dataset(project_dir: Path, config: dict) -> CanonicalDataset:\n"
                "    del project_dir\n"
                "    with np.load(config['source'], allow_pickle=False) as values:\n"
                "        return CanonicalDataset(\n"
                "            sample_ids=values['sample_ids'],\n"
                "            inputs={'features': values['features']},\n"
                "            targets={'label': values['labels']},\n"
                "            metadata={'subject_id': values['subject_ids']},\n"
                "        )\n"
            ),
        },
    )

    method_draft = root.parent / "method-manifests"
    method_draft.mkdir()
    method = _write_hashed_manifest(
        method_draft / "module.yaml",
        MethodSpec,
        {
            "id": "method/demo",
            "origin": {"type": "project"},
            "framework": "numpy",
            "entrypoint": "model:fit_predict",
            "input_requirements": {"features": "features"},
            "output_capabilities": ["label"],
            "task_contracts": [task.id],
        },
    )
    _publish_and_import(
        library,
        project,
        method.id,
        method.version,
        {
            "module.yaml": (method_draft / "module.yaml").read_text(encoding="utf-8"),
            "config.yaml": yaml.safe_dump({"learning_rate": 0.01}),
            "model.py": (
                "import numpy as np\n"
                "from ai4sota import PredictionBundle\n\n"
                "def fit_predict(dataset, config):\n"
                "    threshold = float(config['learning_rate'])\n"
                "    labels = (np.asarray(dataset.inputs['features'])[:, 0] > threshold).astype(int)\n"
                "    return PredictionBundle(\n"
                "        sample_ids=dataset.sample_ids, outputs={'label': labels},\n"
                "        metadata={'decision_threshold': threshold},\n"
                "    )\n"
            ),
        },
    )

    evaluation_draft = root.parent / "evaluation-manifests"
    evaluation_draft.mkdir()
    evaluation = _write_hashed_manifest(
        evaluation_draft / "module.yaml",
        EvaluationSpec,
        {
            "id": "evaluation/demo",
            "origin": {"type": "project"},
            "entrypoint": "evaluator:evaluate",
            "task_contract": task.id,
            "task_contract_hash": task.content_hash,
            "required_predictions": ["label"],
            "required_metadata": ["subject_id"],
            "protocol": {
                "kind": "group_holdout",
                "group_by": "subject_id",
                "test_fraction": 0.5,
            },
            "metrics": [
                {
                    "name": "accuracy",
                    "primary": True,
                    "implementation": "metrics:accuracy",
                    "required_prediction_fields": ["label"],
                }
            ],
        },
    )
    _publish_and_import(
        library,
        project,
        evaluation.id,
        evaluation.version,
        {
            "module.yaml": (
                evaluation_draft / "module.yaml"
            ).read_text(encoding="utf-8"),
            "config.yaml": yaml.safe_dump(
                {"target_key": "label", "prediction_key": "label"}
            ),
            "metrics.py": "def accuracy(truth, predicted):\n    return 0.0\n",
            "evaluator.py": (
                "import numpy as np\n"
                "from ai4sota import EvaluationResult\n\n"
                "def evaluate(dataset, predictions, config):\n"
                "    truth = np.asarray(dataset.targets[config['target_key']])\n"
                "    predicted = np.asarray(predictions.outputs[config['prediction_key']])\n"
                "    mask = np.asarray(dataset.metadata['split']) == 'test'\n"
                "    return EvaluationResult(\n"
                "        metrics={\n"
                "            'accuracy': float(np.mean(truth[mask] == predicted[mask])),\n"
                "            'decision_threshold': float(predictions.metadata['decision_threshold']),\n"
                "        }\n"
                "    )\n"
            ),
        },
    )
    configs = project.root / "configs"
    configs.mkdir()
    (configs / "default.yaml").write_text("random_seed: 17\n", encoding="utf-8")
    ManifestStore().write(project.fingerprints_dir / "demo.yaml", source)

    _git(project.root, "init", "-b", "main")
    _git(project.root, "config", "user.name", "AI4SOTA Tests")
    _git(project.root, "config", "user.email", "tests@ai4sota.invalid")
    GitAdapter().ensure_repository(project.root, "Initial demo project")
    return project


def _edit_learning_rate(project: ProjectLayout, value: float) -> None:
    path = project.module_dir(ModuleKind.METHOD) / "config.yaml"
    path.write_text(yaml.safe_dump({"learning_rate": value}), encoding="utf-8")


def test_data_manifest_references_resolve_bundle_paths_not_internal_ids(
    tmp_path: Path,
) -> None:
    """Catches Data manifest file references being interpreted as schema IDs."""
    project = create_v1_demo_project(tmp_path / "demo")
    data_root = project.module_dir(ModuleKind.DATA)
    data = ManifestStore().read(data_root / "module.yaml", DataModuleSpec)
    source = ManifestStore().read(data_root / data.source, DatasetSourceSpec)
    preprocessing = ManifestStore().read(
        data_root / data.preprocessing, PreprocessingSpec
    )

    prepared = prepare_experiment(project)

    assert data.source == "dataset.yaml"
    assert source.id == "dataset/demo-source"
    assert data.preprocessing == "preprocessing.yaml"
    assert preprocessing.id == "preprocessing/demo-v1"
    assert prepared.spec.data_fingerprint_hash == source.fingerprint_hash


def test_relative_dataset_location_uses_project_root_for_prepare_and_execute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches external data identity depending on the worker process CWD."""
    project = create_v1_demo_project(tmp_path / "demo")
    unrelated_cwd = tmp_path / "unrelated" / "nested-cwd"
    unrelated_cwd.mkdir(parents=True)
    monkeypatch.chdir(unrelated_cwd)

    prepared = prepare_experiment(project)
    completed = execute_approved_run(
        project,
        bind_experiment_approval(prepared, "approval/relative-dataset"),
    )

    assert completed.status == "succeeded"
    assert completed.data_fingerprint_hash == prepared.spec.data_fingerprint_hash


def test_two_runs_compare_and_promote_to_research_commit(tmp_path: Path) -> None:
    """Catches a headless flow bypassing snapshots, comparison, or exact promotion."""
    project = create_v1_demo_project(tmp_path / "demo")
    report = compile_project(project)
    assert report.state is CompatibilityState.COMPATIBLE

    first_prepared = prepare_experiment(project)
    first = execute_approved_run(
        project,
        bind_experiment_approval(first_prepared, "approval/demo-001"),
    )
    _edit_learning_rate(project, 0.02)
    second_prepared = prepare_experiment(project)
    second = execute_approved_run(
        project,
        bind_experiment_approval(second_prepared, "approval/demo-002"),
    )

    comparison = compare_runs([first, second])
    assert comparison.state is ComparabilityState.DIRECT
    assert first.status == second.status == "succeeded"
    assert first.metrics == {"accuracy": 1.0, "decision_threshold": 0.01}
    assert second.metrics == {"accuracy": 1.0, "decision_threshold": 0.02}
    assert comparison.metric_deltas == {
        "accuracy": (0.0,),
        "decision_threshold": (0.01,),
    }
    assert first.snapshot_hash != second.snapshot_hash

    _edit_learning_rate(project, 0.03)
    commit = create_research_commit(
        project,
        {
            "id": "research-commit-demo-002",
            "project_id": second.project_id,
        },
        [second.id],
    )

    assert commit.git_sha
    assert yaml.safe_load(
        _git(
            project.root,
            "show",
            f"{commit.git_sha}:modules/method/current/config.yaml",
        )
    ) == {"learning_rate": 0.02}
    assert yaml.safe_load(
        (project.module_dir(ModuleKind.METHOD) / "config.yaml").read_text(
            encoding="utf-8"
        )
    ) == {"learning_rate": 0.03}
    assert not tuple(project.root.parent.glob(".ai4sota-research-*"))


def test_changed_evaluation_code_blocks_metric_comparison(tmp_path: Path) -> None:
    """Catches changed metric code retaining a directly-comparable identity."""
    project = create_v1_demo_project(tmp_path / "demo")
    first = execute_approved_run(
        project,
        bind_experiment_approval(
            prepare_experiment(project), "approval/evaluation-code-001"
        ),
    )
    evaluator = project.module_dir(ModuleKind.EVALUATION) / "evaluator.py"
    source = evaluator.read_text(encoding="utf-8")
    evaluator.write_text(
        source.replace(
            "'accuracy': float(np.mean(truth[mask] == predicted[mask]))",
            "'accuracy': 0.5",
        ),
        encoding="utf-8",
    )
    second = execute_approved_run(
        project,
        bind_experiment_approval(
            prepare_experiment(project), "approval/evaluation-code-002"
        ),
    )

    comparison = compare_runs([first, second])

    assert first.metrics["accuracy"] == 1.0
    assert second.metrics["accuracy"] == 0.5
    assert comparison.state is ComparabilityState.NONE
    assert comparison.blocking_fields == ("metric_implementation_hash",)
    assert comparison.metric_deltas is None


def test_changed_dependency_lock_blocks_metric_comparison(tmp_path: Path) -> None:
    """Catches runtime dependency drift retaining a comparable metric identity."""
    project = create_v1_demo_project(tmp_path / "demo")
    lockfile = project.root / "uv.lock"
    lockfile.write_text("version = 1\n", encoding="utf-8")
    first = execute_approved_run(
        project,
        bind_experiment_approval(
            prepare_experiment(project), "approval/dependency-lock-001"
        ),
    )
    lockfile.write_text("version = 2\n", encoding="utf-8")
    second = execute_approved_run(
        project,
        bind_experiment_approval(
            prepare_experiment(project), "approval/dependency-lock-002"
        ),
    )

    comparison = compare_runs([first, second])

    assert first.metric_implementation_hash != second.metric_implementation_hash
    assert comparison.state is ComparabilityState.NONE
    assert comparison.blocking_fields == ("metric_implementation_hash",)
    assert comparison.metric_deltas is None


def test_missing_dependency_lock_blocks_metric_comparison(tmp_path: Path) -> None:
    """Catches an unknown evaluator environment being treated as reproducible."""
    project = create_v1_demo_project(tmp_path / "demo")
    (project.root / "uv.lock").unlink()
    first = execute_approved_run(
        project,
        bind_experiment_approval(
            prepare_experiment(project), "approval/missing-dependency-lock-001"
        ),
    )
    _edit_learning_rate(project, 0.02)
    second = execute_approved_run(
        project,
        bind_experiment_approval(
            prepare_experiment(project), "approval/missing-dependency-lock-002"
        ),
    )

    comparison = compare_runs([first, second])

    assert comparison.state is ComparabilityState.NONE
    assert comparison.blocking_fields == ("metric_environment_state",)
    assert comparison.metric_deltas is None


def test_changed_runtime_inventory_blocks_comparison_with_same_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches installed evaluator dependency drift hidden by an unchanged lock."""
    project = create_v1_demo_project(tmp_path / "demo")
    installed_version = "1.0.0"

    def distributions() -> tuple[SimpleNamespace, ...]:
        return (
            SimpleNamespace(
                metadata={"Name": "Evaluator_Runtime"},
                version=installed_version,
            ),
        )

    monkeypatch.setattr(importlib.metadata, "distributions", distributions)
    first_prepared = prepare_experiment(project)
    first = execute_approved_run(
        project,
        bind_experiment_approval(first_prepared, "approval/runtime-inventory-001"),
    )
    installed_version = "2.0.0"
    second_prepared = prepare_experiment(project)
    second = execute_approved_run(
        project,
        bind_experiment_approval(second_prepared, "approval/runtime-inventory-002"),
    )

    comparison = compare_runs([first, second])

    assert first_prepared.spec.environment["distributions"] == [
        {"name": "evaluator-runtime", "version": "1.0.0"}
    ]
    assert second_prepared.spec.environment["distributions"] == [
        {"name": "evaluator-runtime", "version": "2.0.0"}
    ]
    assert first.metric_environment_state == "reproducible"
    assert second.metric_environment_state == "reproducible"
    assert first.metric_implementation_hash != second.metric_implementation_hash
    assert comparison.state is ComparabilityState.NONE
    assert comparison.blocking_fields == ("metric_implementation_hash",)
    assert comparison.metric_deltas is None


def test_unreadable_runtime_inventory_marks_run_unresolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches a failed inventory capture retaining a reproducibility claim."""
    project = create_v1_demo_project(tmp_path / "demo")

    def unreadable_inventory() -> tuple[SimpleNamespace, ...]:
        raise OSError("injected distribution metadata failure")

    monkeypatch.setattr(
        importlib.metadata, "distributions", unreadable_inventory
    )

    completed = execute_approved_run(
        project,
        bind_experiment_approval(
            prepare_experiment(project), "approval/unreadable-runtime-inventory"
        ),
    )

    assert completed.metric_environment_state == "unresolved"


def test_approval_hash_mismatch_is_rejected_before_run_creation(
    tmp_path: Path,
) -> None:
    """Catches a caller changing the exact approved ExperimentSpec hash."""
    project = create_v1_demo_project(tmp_path / "demo")
    approval = bind_experiment_approval(
        prepare_experiment(project), "approval/mismatch"
    )
    tampered = approval.model_copy(update={"approval_hash": ZERO_HASH})

    with pytest.raises(ApprovalValidationError, match="hash"):
        execute_approved_run(project, tampered)

    assert tuple(project.runs_dir.iterdir()) == ()


def test_live_edit_makes_an_approved_input_closure_stale(tmp_path: Path) -> None:
    """Catches execution silently rebuilding approval after workspace drift."""
    project = create_v1_demo_project(tmp_path / "demo")
    approval = bind_experiment_approval(
        prepare_experiment(project), "approval/stale"
    )
    _edit_learning_rate(project, 0.02)

    with pytest.raises(SnapshotValidationError, match="input hash"):
        execute_approved_run(project, approval)

    assert tuple(project.runs_dir.iterdir()) == ()


def test_blocked_compatibility_prevents_split_and_experiment(
    tmp_path: Path,
) -> None:
    """Catches the workflow overriding the deterministic compatibility verdict."""
    project = create_v1_demo_project(tmp_path / "demo")
    path = project.module_dir(ModuleKind.METHOD) / "module.yaml"
    current = ManifestStore().read(path, MethodSpec)
    draft = current.model_copy(
        update={"task_contracts": ("task/unsupported",), "content_hash": ZERO_HASH}
    )
    blocked = draft.model_copy(
        update={"content_hash": canonical_manifest_hash(draft)}
    )
    ManifestStore().write(path, blocked)

    report = compile_project(project)

    assert report.state is CompatibilityState.INCOMPATIBLE
    with pytest.raises(ExperimentBlocked):
        prepare_experiment(project)
    assert tuple(project.splits_dir.iterdir()) == ()


@pytest.mark.parametrize(
    "input_requirements",
    [
        {
            "features": {
                "field": "features",
                "adaptation": "axis_transpose",
                "parameters": {
                    "source_axes": ["sample", "feature"],
                    "target_axes": ["feature", "sample"],
                },
            }
        },
        {
            "prediction": {
                "field": "features",
                "adaptation": "field_rename",
                "parameters": {
                    "source_field": "features",
                    "target_field": "prediction",
                },
            }
        },
    ],
    ids=["data-axis-adapter", "prediction-field-adapter"],
)
def test_inert_mechanical_adapters_are_blocked_before_run_preparation(
    tmp_path: Path,
    input_requirements: dict[str, object],
) -> None:
    """Catches reviewable but unapplied adapters silently authorizing execution."""
    project = create_v1_demo_project(tmp_path / "demo")
    path = project.module_dir(ModuleKind.METHOD) / "module.yaml"
    current = ManifestStore().read(path, MethodSpec)
    draft = current.model_copy(
        update={"input_requirements": input_requirements, "content_hash": ZERO_HASH}
    )
    adaptable = draft.model_copy(
        update={"content_hash": canonical_manifest_hash(draft)}
    )
    ManifestStore().write(path, adaptable)

    report = compile_project(project)

    assert report.state is CompatibilityState.ADAPTABLE
    assert any(finding.adapters for finding in report.findings)
    with pytest.raises(ExperimentBlocked) as captured:
        prepare_experiment(project)
    assert captured.value.report == report
    assert tuple(project.splits_dir.iterdir()) == ()
    assert tuple(project.adapters_dir.iterdir()) == ()


def test_prepare_experiment_persists_the_canonical_subject_safe_split(
    tmp_path: Path,
) -> None:
    """Catches a generated split that cannot enter the immutable Run boundary."""
    project = create_v1_demo_project(tmp_path / "demo")

    prepared = prepare_experiment(project)

    paths = tuple(project.splits_dir.glob("*.yaml"))
    assert len(paths) == 1
    stored = ManifestStore().read(paths[0], type(prepared.split))
    assert stored == prepared.split
    assert stored.content_hash == canonical_manifest_hash(stored)
    subjects = {
        "sample-1": "subject-a",
        "sample-2": "subject-a",
        "sample-3": "subject-b",
        "sample-4": "subject-b",
    }
    train = {
        subjects[item.sample_id]
        for item in stored.members
        if item.partition == "train"
    }
    test = {
        subjects[item.sample_id]
        for item in stored.members
        if item.partition == "test"
    }
    assert train.isdisjoint(test)


def test_runner_uses_the_immutable_snapshot_and_persists_lifecycle_metrics(
    tmp_path: Path,
) -> None:
    """Catches a worker loading live code/config or losing objective Run results."""
    project = create_v1_demo_project(tmp_path / "demo")
    approval = bind_experiment_approval(
        prepare_experiment(project), "approval/snapshot-worker"
    )
    queued = prepare_run(project, approval.experiment)
    _edit_learning_rate(project, 0.99)

    completed = execute_run(project, queued.id)

    stored = ManifestStore().read(
        project.runs_dir / queued.id / "manifest.yaml", RunManifest
    )
    assert completed == stored
    assert stored.status == "succeeded"
    assert stored.seed == 17
    assert stored.metrics == {"accuracy": 1.0, "decision_threshold": 0.01}
    assert json.loads(
        (project.runs_dir / queued.id / "metrics" / "metrics.json").read_text(
            encoding="utf-8"
        )
    ) == stored.metrics
    assert yaml.safe_load(
        (
            project.runs_dir
            / queued.id
            / "snapshot"
            / "modules"
            / "method"
            / "current"
            / "config.yaml"
        ).read_text(encoding="utf-8")
    ) == {"learning_rate": 0.01}
    events = [
        json.loads(line)
        for line in (project.runs_dir / queued.id / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [event["status"] for event in events if event.get("status")] == [
        "queued",
        "preparing",
        "running",
        "running",
        "succeeded",
    ]


@pytest.mark.parametrize("change", ["replace", "delete"])
def test_external_data_change_during_execution_records_integrity_anomaly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    """Catches changed external data being published as a verified success."""
    project = create_v1_demo_project(tmp_path / "demo")
    approval = bind_experiment_approval(prepare_experiment(project), "approval/data")
    queued = prepare_run(project, approval.experiment)
    real_load = runner_module.load_snapshot_dataset

    def load_then_change(snapshot: Path):
        dataset = real_load(snapshot)
        raw = tmp_path / "demo-dataset.npz"
        if change == "replace":
            raw.write_bytes(b"changed after loading")
        else:
            raw.unlink()
        return dataset

    monkeypatch.setattr(runner_module, "load_snapshot_dataset", load_then_change)
    with pytest.raises(RuntimeError, match="run failed"):
        execute_run(project, queued.id)

    stored = RunRepository(project).load(queued.id)
    assert stored.status == "failed"
    assert stored.integrity_state == "anomalous"
    run_dir = project.runs_dir / queued.id
    events = [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events[-1]["details"]["integrity_anomaly"]
    assert "external dataset" in (run_dir / "logs" / "worker.log").read_text(
        encoding="utf-8"
    )
    report = compare_runs([stored, stored.model_copy(update={"id": "another-run"})])
    assert report.state is ComparabilityState.NONE
    assert "integrity_state" in report.blocking_fields
    with pytest.raises(ValueError, match="succeeded and verified"):
        create_research_commit(project, {"id": "rejected"}, [stored.id])


@pytest.mark.parametrize("relative", [False, True], ids=["sibling", "relative"])
@pytest.mark.parametrize("lazy", [False, True], ids=["module-level", "lazy"])
def test_snapshot_helper_imports_are_isolated_across_successive_runs(
    tmp_path: Path, relative: bool, lazy: bool
) -> None:
    """Catches missing sibling imports and cached helpers leaking between Runs."""
    project = create_v1_demo_project(tmp_path / "demo")
    evaluation = project.module_dir(ModuleKind.EVALUATION)
    evaluator = evaluation / "evaluator.py"
    source = evaluator.read_text(encoding="utf-8")
    statement = f"from {'.' if relative else ''}metrics import accuracy\n"
    if lazy:
        source = source.replace(
            "def evaluate(dataset, predictions, config):\n",
            "def evaluate(dataset, predictions, config):\n    " + statement,
        )
    else:
        source = statement + source
    source = source.replace(
        "float(np.mean(truth[mask] == predicted[mask]))",
        "accuracy(truth[mask], predicted[mask])",
    )
    evaluator.write_text(source, encoding="utf-8")
    previous_path = list(sys.path)
    previous_metrics = sys.modules.get("metrics")
    measured = []
    for value in (0.25, 0.75):
        (evaluation / "metrics.py").write_text(
            f"def accuracy(truth, predicted):\n    return {value}\n", encoding="utf-8"
        )
        approval = bind_experiment_approval(
            prepare_experiment(project), "approval/import"
        )
        completed = execute_approved_run(project, approval)
        measured.append(completed.metrics["accuracy"])
        assert sys.path == previous_path
        assert sys.modules.get("metrics") is previous_metrics
        assert not any(
            str(project.runs_dir) in str(getattr(module, "__file__", ""))
            for module in tuple(sys.modules.values())
        )
        assert not list(project.runs_dir.rglob("__pycache__"))
    assert measured == [0.25, 0.75]


@pytest.mark.parametrize(
    "stage", ["load_snapshot_dataset", "_verify_snapshot_runtime_environment"]
)
def test_keyboard_interrupt_preserves_logs_and_terminal_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    """Catches Ctrl+C orphaning a running record and discarding captured output."""
    project = create_v1_demo_project(tmp_path / "demo")
    approval = bind_experiment_approval(
        prepare_experiment(project), "approval/interrupt"
    )
    queued = prepare_run(project, approval.experiment)
    interruption = KeyboardInterrupt("stop this Run")

    def interrupted_load(*args: object):
        print("loading interrupted by user")
        raise interruption

    monkeypatch.setattr(runner_module, stage, interrupted_load)
    with pytest.raises(KeyboardInterrupt) as raised:
        execute_run(project, queued.id)
    assert raised.value is interruption
    assert RunRepository(project).load(queued.id).status == "interrupted"
    run_dir = project.runs_dir / queued.id
    log = (run_dir / "logs" / "worker.log").read_text(encoding="utf-8")
    if stage == "load_snapshot_dataset":
        assert "loading interrupted by user" in log
    assert "KeyboardInterrupt: stop this Run" in log
    events = [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events[-1]["status"] == "interrupted"


def test_runner_rejects_runtime_inventory_change_after_run_preparation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches execution under a runtime other than the recorded inventory."""
    project = create_v1_demo_project(tmp_path / "demo")
    installed_version = "1.0.0"

    def distributions() -> tuple[SimpleNamespace, ...]:
        return (
            SimpleNamespace(
                metadata={"Name": "Evaluator Runtime"},
                version=installed_version,
            ),
        )

    monkeypatch.setattr(importlib.metadata, "distributions", distributions)
    approval = bind_experiment_approval(
        prepare_experiment(project), "approval/runtime-changed-before-execution"
    )
    queued = prepare_run(project, approval.experiment)
    installed_version = "2.0.0"

    with pytest.raises(RuntimeError, match="run failed") as captured:
        execute_run(project, queued.id)

    assert captured.value.__cause__ is not None
    assert "runtime environment does not match" in str(captured.value.__cause__)
    assert RunRepository(project).load(queued.id).status == "failed"


def test_runner_recovers_a_durable_success_after_projection_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches a committed success being reported as a failed execution."""
    project = create_v1_demo_project(tmp_path / "demo")
    approval = bind_experiment_approval(
        prepare_experiment(project), "approval/success-recovery"
    )
    queued = prepare_run(project, approval.experiment)
    real_write = ManifestStore.write
    failed_once = False

    def fail_success_projection(
        store: ManifestStore, path: Path, value: object
    ) -> None:
        nonlocal failed_once
        if not failed_once and getattr(value, "status", None) == "succeeded":
            failed_once = True
            raise OSError("injected success projection failure")
        real_write(store, path, value)  # type: ignore[arg-type]

    monkeypatch.setattr(ManifestStore, "write", fail_success_projection)

    completed = execute_run(project, queued.id)

    assert completed.status == "succeeded"
    assert completed.metrics == {"accuracy": 1.0, "decision_threshold": 0.01}
    assert RunRepository(project).load(queued.id) == completed


def test_runner_records_a_worker_start_failure_as_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches a failed worker-start transition leaving a Run in preparation."""
    project = create_v1_demo_project(tmp_path / "demo")
    approval = bind_experiment_approval(
        prepare_experiment(project), "approval/worker-start-failure"
    )
    queued = prepare_run(project, approval.experiment)
    real_transition = RunRepository.transition_run

    def fail_worker_start(
        repository: RunRepository, run_id: str, expected: str, target: str
    ) -> RunManifest:
        if (expected, target) == ("preparing", "running"):
            raise RuntimeError("injected worker start failure")
        return real_transition(repository, run_id, expected, target)

    monkeypatch.setattr(RunRepository, "transition_run", fail_worker_start)

    with pytest.raises(RuntimeError, match="run failed"):
        execute_run(project, queued.id)

    stored = RunRepository(project).load(queued.id)
    worker_log = (
        project.runs_dir / queued.id / "logs" / "worker.log"
    ).read_text(encoding="utf-8")
    assert stored.status == "failed"
    assert "injected worker start failure" in worker_log


def test_runner_failure_recovers_a_pending_running_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches failure handling racing a durable worker-start transition fact."""
    project = create_v1_demo_project(tmp_path / "demo")
    approval = bind_experiment_approval(
        prepare_experiment(project), "approval/pending-worker-start"
    )
    queued = prepare_run(project, approval.experiment)
    real_write = ManifestStore.write
    failed_once = False

    def fail_running_projection(
        store: ManifestStore, path: Path, value: object
    ) -> None:
        nonlocal failed_once
        if not failed_once and getattr(value, "status", None) == "running":
            failed_once = True
            raise OSError("injected running projection failure")
        real_write(store, path, value)  # type: ignore[arg-type]

    monkeypatch.setattr(ManifestStore, "write", fail_running_projection)

    with pytest.raises(RuntimeError, match="run failed"):
        execute_run(project, queued.id)

    stored = RunRepository(project).load(queued.id)
    assert stored.status == "failed"
    events = [
        json.loads(line)
        for line in (project.runs_dir / queued.id / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [event["status"] for event in events if event.get("status")] == [
        "queued",
        "preparing",
        "running",
        "failed",
    ]


def test_runner_failure_bookkeeping_does_not_mask_the_execution_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches failed terminal bookkeeping replacing the worker-start cause."""
    project = create_v1_demo_project(tmp_path / "demo")
    approval = bind_experiment_approval(
        prepare_experiment(project), "approval/failure-bookkeeping"
    )
    queued = prepare_run(project, approval.experiment)
    real_transition = RunRepository.transition_run

    def fail_start(
        repository: RunRepository, run_id: str, expected: str, target: str
    ) -> RunManifest:
        if (expected, target) == ("preparing", "running"):
            raise RuntimeError("original worker start failure")
        return real_transition(repository, run_id, expected, target)

    def fail_terminal_record(repository: RunRepository, run_id: str) -> RunManifest:
        raise OSError("injected failure-state persistence error")

    monkeypatch.setattr(RunRepository, "transition_run", fail_start)
    monkeypatch.setattr(RunRepository, "fail_run", fail_terminal_record)

    with pytest.raises(RuntimeError, match="run failed") as captured:
        execute_run(project, queued.id)

    assert captured.value.__cause__ is not None
    assert str(captured.value.__cause__) == "original worker start failure"
    assert RunRepository(project).load(queued.id).status == "preparing"


def test_runner_does_not_publish_success_before_the_worker_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches required log persistence failing after terminal success."""
    project = create_v1_demo_project(tmp_path / "demo")
    approval = bind_experiment_approval(
        prepare_experiment(project), "approval/log-failure"
    )
    queued = prepare_run(project, approval.experiment)
    real_write = runner_module.atomic_write_bytes
    failed_once = False

    def fail_first_worker_log(path: Path, data: bytes) -> None:
        nonlocal failed_once
        if not failed_once and path.name == "worker.log":
            failed_once = True
            raise OSError("injected worker log failure")
        real_write(path, data)

    monkeypatch.setattr(runner_module, "atomic_write_bytes", fail_first_worker_log)

    with pytest.raises(RuntimeError, match="run failed"):
        execute_run(project, queued.id)

    stored = RunRepository(project).load(queued.id)
    assert stored.status == "failed"
    assert "injected worker log failure" in (
        project.runs_dir / queued.id / "logs" / "worker.log"
    ).read_text(encoding="utf-8")


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ai4sota", *args],
        check=False,
        text=True,
        capture_output=True,
    )


def test_json_cli_runs_compares_and_promotes_exact_snapshot(tmp_path: Path) -> None:
    """Catches headless commands emitting prose or bypassing workflow services."""
    project = create_v1_demo_project(tmp_path / "demo")
    first_approval = tmp_path / "approval-1.json"
    second_approval = tmp_path / "approval-2.json"

    compiled = _cli("compile", str(project.root), "--json")
    assert compiled.returncode == 0, compiled.stderr
    assert json.loads(compiled.stdout)["state"] == "compatible"

    first_prepared = _cli(
        "prepare-run",
        str(project.root),
        "--approval-id",
        "approval/cli-001",
        "--output",
        str(first_approval),
        "--json",
    )
    assert first_prepared.returncode == 0, first_prepared.stderr
    first_document = json.loads(first_prepared.stdout)
    first_run = _cli(
        "run-approved",
        str(project.root),
        str(first_approval),
        "--approval-hash",
        first_document["approval_hash"],
        "--json",
    )
    assert first_run.returncode == 0, first_run.stderr
    first = json.loads(first_run.stdout)

    _edit_learning_rate(project, 0.02)
    second_prepared = _cli(
        "prepare-run",
        str(project.root),
        "--approval-id",
        "approval/cli-002",
        "--output",
        str(second_approval),
        "--json",
    )
    assert second_prepared.returncode == 0, second_prepared.stderr
    second_document = json.loads(second_prepared.stdout)
    second_run = _cli(
        "run-approved",
        str(project.root),
        str(second_approval),
        "--approval-hash",
        second_document["approval_hash"],
        "--json",
    )
    assert second_run.returncode == 0, second_run.stderr
    second = json.loads(second_run.stdout)

    compared = _cli(
        "compare",
        str(project.root),
        first["id"],
        second["id"],
        "--json",
    )
    assert compared.returncode == 0, compared.stderr
    comparison = json.loads(compared.stdout)
    assert comparison["state"] == "directly_comparable"
    assert comparison["metric_deltas"]["decision_threshold"] == [0.01]

    _edit_learning_rate(project, 0.03)
    draft = tmp_path / "research-draft.json"
    draft.write_text(
        json.dumps(
            {
                "id": "research-commit-cli-002",
                "project_id": second["project_id"],
            }
        ),
        encoding="utf-8",
    )
    promoted = _cli(
        "research-commit",
        str(project.root),
        str(draft),
        second["id"],
        "--json",
    )
    assert promoted.returncode == 0, promoted.stderr
    commit = json.loads(promoted.stdout)
    assert yaml.safe_load(
        _git(
            project.root,
            "show",
            f"{commit['git_sha']}:modules/method/current/config.yaml",
        )
    ) == {"learning_rate": 0.02}


def test_cli_compare_rejects_a_tampered_run_snapshot(tmp_path: Path) -> None:
    """Catches CLI comparison trusting a stale stored integrity label."""
    project = create_v1_demo_project(tmp_path / "demo")
    first = execute_approved_run(
        project,
        bind_experiment_approval(
            prepare_experiment(project), "approval/tamper-001"
        ),
    )
    _edit_learning_rate(project, 0.02)
    second = execute_approved_run(
        project,
        bind_experiment_approval(
            prepare_experiment(project), "approval/tamper-002"
        ),
    )
    frozen_method = (
        project.runs_dir
        / first.id
        / "snapshot"
        / "modules"
        / "method"
        / "current"
        / "model.py"
    )
    frozen_method.write_text("tampered\n", encoding="utf-8")

    compared = _cli(
        "compare", str(project.root), first.id, second.id, "--json"
    )

    assert compared.returncode == 1
    assert compared.stdout == ""
    assert "snapshot hash mismatch" in compared.stderr


def test_cli_rejects_single_run_comparison_and_wrong_approval_hash(
    tmp_path: Path,
) -> None:
    """Catches invalid CLI inputs reaching comparison or Run preparation."""
    project = create_v1_demo_project(tmp_path / "demo")
    approval_path = tmp_path / "approval.json"
    prepared = _cli(
        "prepare-run",
        str(project.root),
        "--approval-id",
        "approval/cli-invalid",
        "--output",
        str(approval_path),
        "--json",
    )
    assert prepared.returncode == 0, prepared.stderr

    invalid_compare = _cli(
        "compare", str(project.root), "run-only", "--json"
    )
    assert invalid_compare.returncode == 1
    assert "at least two" in invalid_compare.stderr

    invalid_approval = _cli(
        "run-approved",
        str(project.root),
        str(approval_path),
        "--approval-hash",
        ZERO_HASH,
        "--json",
    )
    assert invalid_approval.returncode == 1
    assert "approval hash" in invalid_approval.stderr
    assert tuple(project.runs_dir.iterdir()) == ()
