"""Headless orchestration for one approved scientific experiment."""

from __future__ import annotations

import json
import platform
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar
from uuid import uuid4

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError, model_validator

from ai4sota.compatibility import CompatibilityReport, compile_compatibility
from ai4sota.domain import (
    CompatibilityState,
    DataModuleSpec,
    DatasetSourceSpec,
    EvaluationSpec,
    ExperimentSpec,
    MethodSpec,
    ModuleKind,
    PreprocessingSpec,
    ProjectSpec,
    RunManifest,
    SplitManifest,
    TaskContract,
)
from ai4sota.domain.common import ContentHash, NonEmptyStr, StrictModel
from ai4sota.evaluation import materialize_split
from ai4sota.files import (
    PathValidationError,
    StableReadError,
    resolve_bundle_file,
    stable_read_file,
)
from ai4sota.library import hash_tree as module_tree_hash
from ai4sota.projects import ProjectLayout
from ai4sota.runner import execute_run, load_snapshot_dataset
from ai4sota.runs import prepare_run, snapshot_input_hashes
from ai4sota.storage import (
    ManifestStore,
    canonical_manifest_hash,
)

ZERO_HASH = "sha256:" + "0" * 64
ManifestT = TypeVar("ManifestT", DatasetSourceSpec, PreprocessingSpec)


class ExperimentBlocked(RuntimeError):
    """Raised when deterministic compatibility policy forbids preparation."""

    def __init__(self, report: CompatibilityReport) -> None:
        self.report = report
        super().__init__(f"experiment is blocked: {report.state.value}")


class ApprovalValidationError(ValueError):
    """Raised when an approval does not bind one exact ExperimentSpec."""


class PreparedExperiment(StrictModel):
    """Reviewable, unapproved experiment and its exact preparation hash."""

    spec: ExperimentSpec
    split: SplitManifest
    compatibility: CompatibilityReport
    approval_hash: ContentHash

    @model_validator(mode="after")
    def validates_preparation_boundary(self) -> PreparedExperiment:
        if self.spec.approval_id is not None:
            raise ValueError("prepared experiment must not claim approval")
        if self.spec.content_hash != canonical_manifest_hash(self.spec):
            raise ValueError("prepared experiment hash is not canonical")
        if self.approval_hash != self.spec.content_hash:
            raise ValueError("approval_hash must bind the prepared ExperimentSpec")
        if self.split.content_hash != self.spec.split_manifest_hash:
            raise ValueError("prepared split does not match the ExperimentSpec")
        return self


class ExperimentApproval(StrictModel):
    """Caller-supplied approval of one exact, content-addressed ExperimentSpec."""

    approval_id: NonEmptyStr
    approval_hash: ContentHash
    experiment: ExperimentSpec

    @model_validator(mode="after")
    def validates_exact_approval(self) -> ExperimentApproval:
        _validate_approval(self)
        return self


@dataclass(frozen=True)
class _ActiveSpecs:
    project: ProjectSpec
    task: TaskContract
    data: DataModuleSpec
    source: DatasetSourceSpec
    preprocessing: PreprocessingSpec
    method: MethodSpec
    evaluation: EvaluationSpec


def compile_project(project: ProjectLayout) -> CompatibilityReport:
    """Compile the active Data, Method, Evaluation, and Task manifests."""
    specs = _load_active_specs(project)
    return compile_compatibility(
        data=specs.data,
        method=specs.method,
        evaluation=specs.evaluation,
        task=specs.task,
    )


def prepare_experiment(project: ProjectLayout) -> PreparedExperiment:
    """Materialize a split and bind the exact prospective Run input closure."""
    specs = _load_active_specs(project)
    compatibility = compile_compatibility(
        data=specs.data,
        method=specs.method,
        evaluation=specs.evaluation,
        task=specs.task,
    )
    if compatibility.state is not CompatibilityState.COMPATIBLE:
        raise ExperimentBlocked(compatibility)

    _ensure_fingerprint_record(project, specs.source)
    runtime_config = _load_runtime_config(project)
    dataset = _load_dataset_from_preparation_snapshot(project)
    seed = _load_seed(project)
    split = materialize_split(dataset, specs.evaluation, seed)
    split_path = project.splits_dir / (
        f"{split.id.replace('/', '-')}-{split.content_hash[7:19]}.yaml"
    )
    ManifestStore().write(split_path, split)
    selection = ExperimentSpec(
        id=f"experiment-{uuid4().hex}",
        content_hash=ZERO_HASH,
        project_id=specs.project.id,
        data_module_hash=specs.data.content_hash,
        method_module_hash=specs.method.content_hash,
        evaluation_module_hash=specs.evaluation.content_hash,
        task_contract_hash=specs.task.content_hash,
        data_fingerprint_hash=specs.source.fingerprint_hash,
        split_manifest_hash=split.content_hash,
        seed=seed,
        input_hashes={"pending": ZERO_HASH},
        generated_adapter_hashes=(),
        runtime_config=runtime_config,
        environment={"python": platform.python_version()},
    )
    input_hashes = snapshot_input_hashes(project, selection)
    draft = selection.model_copy(update={"input_hashes": input_hashes})
    spec = draft.model_copy(
        update={"content_hash": canonical_manifest_hash(draft)}
    )
    return PreparedExperiment(
        spec=spec,
        split=split,
        compatibility=compatibility,
        approval_hash=spec.content_hash,
    )


def bind_experiment_approval(
    prepared: PreparedExperiment, approval_id: str
) -> ExperimentApproval:
    """Create the exact approval candidate a caller must review and confirm."""
    PreparedExperiment.model_validate(prepared.model_dump(mode="python"))
    draft = prepared.spec.model_copy(
        update={"approval_id": approval_id, "content_hash": ZERO_HASH}
    )
    approved = draft.model_copy(
        update={"content_hash": canonical_manifest_hash(draft)}
    )
    return ExperimentApproval(
        approval_id=approval_id,
        approval_hash=approved.content_hash,
        experiment=approved,
    )


def execute_approved_run(
    project: ProjectLayout, approval: ExperimentApproval
) -> RunManifest:
    """Recheck an exact approval, freeze its inputs, and execute the snapshot."""
    _validate_approval(approval)
    queued = prepare_run(project, approval.experiment)
    return execute_run(project, queued.id)


def _validate_approval(approval: ExperimentApproval) -> None:
    experiment = approval.experiment
    if not approval.approval_id.strip():
        raise ApprovalValidationError("approval id must not be empty")
    if experiment.approval_id != approval.approval_id:
        raise ApprovalValidationError(
            "approval id does not match the approved ExperimentSpec"
        )
    computed = canonical_manifest_hash(experiment)
    if experiment.content_hash != computed or approval.approval_hash != computed:
        raise ApprovalValidationError(
            "approval hash does not match the exact approved ExperimentSpec"
        )


def _load_active_specs(project: ProjectLayout) -> _ActiveSpecs:
    store = ManifestStore()
    project_spec = store.read(project.project_file, ProjectSpec)
    _verify_canonical(project_spec, "project manifest")
    expected_task = project.task_file.relative_to(project.root).as_posix()
    if project_spec.active_task != expected_task:
        raise ValueError(f"active task must be {expected_task!r}")
    for kind in ModuleKind:
        expected = project.module_dir(kind).relative_to(project.root).as_posix()
        if project_spec.active_modules[kind] != expected:
            raise ValueError(f"active {kind.value} module must be {expected!r}")

    task = store.read(project.task_file, TaskContract)
    data_root = project.module_dir(ModuleKind.DATA)
    data = store.read(data_root / "module.yaml", DataModuleSpec)
    method = store.read(
        project.module_dir(ModuleKind.METHOD) / "module.yaml", MethodSpec
    )
    evaluation = store.read(
        project.module_dir(ModuleKind.EVALUATION) / "module.yaml",
        EvaluationSpec,
    )
    source = _load_manifest_reference(
        data_root, DatasetSourceSpec, data.source, "dataset source"
    )
    preprocessing = _load_manifest_reference(
        data_root,
        PreprocessingSpec,
        data.preprocessing,
        "preprocessing manifest",
    )
    for value, label in (
        (task, "task contract"),
        (data, "data module"),
        (source, "dataset source"),
        (preprocessing, "preprocessing manifest"),
        (method, "method module"),
        (evaluation, "evaluation module"),
    ):
        _verify_canonical(value, label)
    return _ActiveSpecs(
        project=project_spec,
        task=task,
        data=data,
        source=source,
        preprocessing=preprocessing,
        method=method,
        evaluation=evaluation,
    )


def _load_manifest_reference(
    root: Path,
    model: type[ManifestT],
    reference: str,
    label: str,
) -> ManifestT:
    try:
        path = resolve_bundle_file(root, reference)
        document = yaml.safe_load(stable_read_file(path).data.decode("utf-8"))
        value = model.model_validate(document)
    except (
        OSError,
        PathValidationError,
        StableReadError,
        UnicodeError,
        ValidationError,
        yaml.YAMLError,
    ) as error:
        raise ValueError(f"invalid referenced {label}: {reference!r}") from error
    _verify_canonical(value, label)
    return value


def _verify_canonical(value: object, label: str) -> None:
    content_hash = getattr(value, "content_hash", None)
    if content_hash != canonical_manifest_hash(value):  # type: ignore[arg-type]
        raise ValueError(f"{label} content hash is not canonical")


def _load_dataset_from_preparation_snapshot(project: ProjectLayout):
    data_root = project.module_dir(ModuleKind.DATA)
    before = module_tree_hash(data_root)
    with tempfile.TemporaryDirectory(prefix="ai4sota-prepare-") as temporary:
        snapshot = Path(temporary) / "snapshot"
        destination = snapshot / "modules" / "data" / "current"
        destination.parent.mkdir(parents=True)
        shutil.copytree(data_root, destination)
        if module_tree_hash(destination) != before:
            raise ValueError("Data preparation snapshot does not match the workspace")
        dataset = load_snapshot_dataset(snapshot)
    if module_tree_hash(data_root) != before:
        raise ValueError("Data module changed during experiment preparation")
    return dataset


def _ensure_fingerprint_record(
    project: ProjectLayout, source: DatasetSourceSpec
) -> None:
    matches: list[DatasetSourceSpec] = []
    for path in sorted(project.fingerprints_dir.glob("*.yaml")):
        try:
            candidate = ManifestStore().read(path, DatasetSourceSpec)
        except ValidationError:
            continue
        if candidate.fingerprint_hash == source.fingerprint_hash:
            matches.append(candidate)
    if len(matches) > 1:
        raise ValueError("dataset fingerprint matched multiple records")
    if matches:
        if matches[0] != source:
            raise ValueError("dataset fingerprint record does not match active source")
        return
    path = project.fingerprints_dir / f"{source.fingerprint_hash[7:23]}.yaml"
    ManifestStore().write(path, source)


def _load_runtime_config(project: ProjectLayout) -> dict[str, object]:
    return {
        kind.value: _read_yaml_mapping(
            project.module_dir(kind) / "config.yaml", required=False
        )
        for kind in ModuleKind
    }


def _load_seed(project: ProjectLayout) -> int:
    config = _read_yaml_mapping(
        project.root / "configs" / "default.yaml", required=False
    )
    raw = config.get("random_seed", 17)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise TypeError("configs/default.yaml random_seed must be an integer")
    return raw


def _read_yaml_mapping(path: Path, *, required: bool) -> dict[str, object]:
    if not path.exists():
        if required:
            raise FileNotFoundError(path)
        return {}
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"expected a string-keyed mapping in {path}")
    json.dumps(value, allow_nan=False)
    return value


__all__ = [
    "ApprovalValidationError",
    "ExperimentApproval",
    "ExperimentBlocked",
    "PreparedExperiment",
    "bind_experiment_approval",
    "compile_project",
    "execute_approved_run",
    "prepare_experiment",
]
