"""Immutable, content-addressed Run snapshot creation."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ValidationError

from ai4sota.domain import (
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
from ai4sota.files import StableFile, StableReadError, stable_read_file
from ai4sota.projects import ProjectLayout
from ai4sota.storage import (
    ManifestStore,
    atomic_write_bytes,
    canonical_manifest_hash,
    durable_make_directory,
    durable_replace,
)

from .lifecycle import RunEvent, append_run_event
from .repository import _is_link_or_reparse

ModelT = TypeVar("ModelT", bound=BaseModel)
_MANIFEST_SUFFIXES = frozenset({".json", ".yaml", ".yml"})
_ROOT_SNAPSHOT_FILES = (
    "pipeline.py",
    "pyproject.toml",
    "uv.lock",
    "requirements.txt",
)
_MAX_CONFIG_FILE_BYTES = 1024 * 1024


class SnapshotValidationError(ValueError):
    """Raised when approved inputs cannot be verified and frozen exactly."""


def hash_tree(root: Path) -> str:
    """Hash a directory from sorted relative paths and exact file hashes."""
    directory = Path(root)
    files = _read_tree(directory, "snapshot")
    document = [
        {
            "path": path.relative_to(directory).as_posix(),
            "sha256": value.sha256,
        }
        for path, value in sorted(files.items(), key=lambda item: item[0].as_posix())
    ]
    return canonical_manifest_hash({"files": document})


def prepare_run(project: ProjectLayout, experiment: ExperimentSpec) -> RunManifest:
    """Verify approved inputs and atomically publish an executable Run snapshot."""
    if experiment.approval_id is None:
        raise SnapshotValidationError("experiment must have an approval identifier")
    _verify_model_hash(experiment, "experiment")

    project_file = _read_file(project.project_file, "project manifest")
    project_spec = _verified_manifest(
        project.project_file, project_file, ProjectSpec, "project manifest"
    )
    if experiment.project_id != project_spec.id:
        raise SnapshotValidationError(
            f"experiment project {experiment.project_id!r} does not match "
            f"{project_spec.id!r}"
        )
    _verify_active_project_references(project, project_spec)

    task_file = _read_file(project.task_file, "task contract")
    task = _verified_manifest(
        project.task_file, task_file, TaskContract, "task contract"
    )
    if task.content_hash != experiment.task_contract_hash:
        raise SnapshotValidationError("task contract hash does not match approval")

    module_files = {
        kind: _read_tree(project.module_dir(kind), f"{kind.value} module tree")
        for kind in ModuleKind
    }
    data_path, data = _find_verified_manifest(
        module_files[ModuleKind.DATA],
        DataModuleSpec,
        experiment.data_module_hash,
        "data module",
    )
    method_path, method = _find_verified_manifest(
        module_files[ModuleKind.METHOD],
        MethodSpec,
        experiment.method_module_hash,
        "method module",
    )
    evaluation_path, evaluation = _find_verified_manifest(
        module_files[ModuleKind.EVALUATION],
        EvaluationSpec,
        experiment.evaluation_module_hash,
        "evaluation module",
    )

    _, source = _find_verified_manifest_by_id(
        module_files[ModuleKind.DATA],
        DatasetSourceSpec,
        data.source,
        "dataset source",
    )
    _find_verified_manifest_by_id(
        module_files[ModuleKind.DATA],
        PreprocessingSpec,
        data.preprocessing,
        "preprocessing manifest",
    )

    split_candidates = _read_tree(project.splits_dir, "split manifests")
    split_path, split = _find_verified_manifest(
        split_candidates,
        SplitManifest,
        experiment.split_manifest_hash,
        "split manifest",
    )
    fingerprint_candidates = _read_tree(
        project.fingerprints_dir, "data fingerprint records"
    )
    fingerprint_path, fingerprint_record = _find_fingerprint_record(
        fingerprint_candidates, experiment.data_fingerprint_hash
    )
    adapter_candidates = _read_tree(project.adapters_dir, "generated adapters")
    adapter_files = _resolve_bound_adapter_files(
        adapter_candidates, experiment.generated_adapter_hashes
    )
    config_files = _read_optional_small_tree(project.root / "configs", "small config")
    schema_files = _read_optional_small_tree(project.root / "schemas", "schema")
    root_files = _read_root_snapshot_files(project.root)

    inputs: dict[Path, StableFile] = {
        project.project_file: project_file,
        project.task_file: task_file,
        data_path: module_files[ModuleKind.DATA][data_path],
        method_path: module_files[ModuleKind.METHOD][method_path],
        evaluation_path: module_files[ModuleKind.EVALUATION][evaluation_path],
        fingerprint_path: fingerprint_candidates[fingerprint_path],
        split_path: split_candidates[split_path],
    }
    for files in module_files.values():
        inputs.update(files)
    for path in adapter_files:
        inputs[path] = adapter_candidates[path]
    inputs.update(config_files)
    inputs.update(schema_files)
    inputs.update(root_files)
    relative_inputs = _verify_exact_input_map(project, experiment, inputs)

    _verify_semantic_closure(
        experiment,
        task,
        data,
        method,
        evaluation,
        split,
        source,
        fingerprint_record,
    )

    run_id = f"run-{uuid4().hex}"
    run_dir = project.runs_dir / run_id
    staging = project.index_file.parent / run_id
    if run_dir.exists():
        raise FileExistsError(f"Run directory already exists: {run_dir}")
    durable_make_directory(staging)
    try:
        snapshot = staging / "snapshot"
        for relative_path, value in sorted(relative_inputs.items()):
            atomic_write_bytes(snapshot / relative_path, value.data)
        ManifestStore().write(snapshot / "experiment.yaml", experiment)

        snapshot_hash = hash_tree(snapshot)
        protocol_hash = canonical_manifest_hash(
            {"protocol": evaluation.protocol.model_dump(mode="json")}
        )
        metric_hash = canonical_manifest_hash(
            {
                "metrics": [
                    metric.model_dump(mode="json") for metric in evaluation.metrics
                ]
            }
        )
        draft = RunManifest(
            id=run_id,
            content_hash="sha256:" + "0" * 64,
            project_id=experiment.project_id,
            experiment_hash=experiment.content_hash,
            snapshot_hash=snapshot_hash,
            data_fingerprint_hash=experiment.data_fingerprint_hash,
            task_contract_hash=experiment.task_contract_hash,
            split_manifest_hash=experiment.split_manifest_hash,
            evaluation_protocol_hash=protocol_hash,
            metric_implementation_hash=metric_hash,
            integrity_state="verified",
            status="queued",
            seed=experiment.seed,
        )
        manifest = draft.model_copy(
            update={"content_hash": canonical_manifest_hash(draft)}
        )
        ManifestStore().write(staging / "manifest.yaml", manifest)
        for name in ("logs", "metrics", "artifacts"):
            durable_make_directory(staging / name)
        append_run_event(
            staging,
            RunEvent(
                id=f"event-{uuid4().hex}",
                run_id=run_id,
                event_type="run_prepared",
                status="queued",
                details={"approval_id": experiment.approval_id},
            ),
        )
        _verify_external_fingerprint(source, experiment.data_fingerprint_hash)
        if hash_tree(snapshot) != snapshot_hash:
            raise SnapshotValidationError(
                "staged snapshot changed before durable publication"
            )
        durable_replace(staging, run_dir)
        return manifest
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _verify_active_project_references(
    project: ProjectLayout, project_spec: ProjectSpec
) -> None:
    active_task = project.task_file.relative_to(project.root).as_posix()
    if project_spec.active_task != active_task:
        raise SnapshotValidationError(
            f"project active task must be {active_task!r}, "
            f"found {project_spec.active_task!r}"
        )
    for kind in ModuleKind:
        active_module = project.module_dir(kind).relative_to(project.root).as_posix()
        if project_spec.active_modules[kind] != active_module:
            raise SnapshotValidationError(
                f"project active {kind.value} module must be {active_module!r}, "
                f"found {project_spec.active_modules[kind]!r}"
            )


def _verify_exact_input_map(
    project: ProjectLayout,
    experiment: ExperimentSpec,
    inputs: Mapping[Path, StableFile],
) -> dict[str, StableFile]:
    relative: dict[str, StableFile] = {}
    for path, value in inputs.items():
        try:
            key = path.relative_to(project.root).as_posix()
        except ValueError as error:
            raise SnapshotValidationError(
                f"snapshot input is outside the project: {path}"
            ) from error
        relative[key] = value

    actual_hashes = {path: value.sha256 for path, value in relative.items()}
    expected_paths = set(experiment.input_hashes)
    actual_paths = set(actual_hashes)
    if expected_paths != actual_paths:
        missing = sorted(expected_paths - actual_paths)
        unexpected = sorted(actual_paths - expected_paths)
        raise SnapshotValidationError(
            f"approved input set mismatch: missing={missing}, unexpected={unexpected}"
        )
    changed = sorted(
        path
        for path, actual_hash in actual_hashes.items()
        if experiment.input_hashes[path] != actual_hash
    )
    if changed:
        raise SnapshotValidationError(f"approved input hash mismatch: {changed}")
    return relative


def _verify_semantic_closure(
    experiment: ExperimentSpec,
    task: TaskContract,
    data: DataModuleSpec,
    method: MethodSpec,
    evaluation: EvaluationSpec,
    split: SplitManifest,
    source: DatasetSourceSpec,
    fingerprint_record: DatasetSourceSpec,
) -> None:
    if data.task_contract != task.id or data.task_contract_hash != task.content_hash:
        raise SnapshotValidationError(
            "data module task contract does not match approval"
        )
    if task.id not in method.task_contracts:
        raise SnapshotValidationError(
            "method does not support the approved task contract"
        )
    if (
        evaluation.task_contract != task.id
        or evaluation.task_contract_hash != task.content_hash
    ):
        raise SnapshotValidationError(
            "evaluation module task contract does not match approval"
        )
    if split.evaluation_hash != evaluation.content_hash:
        raise SnapshotValidationError(
            "split manifest evaluation hash does not match the approved evaluation"
        )
    if split.seed != experiment.seed:
        raise SnapshotValidationError("split seed does not match the experiment seed")
    if split.group_by != evaluation.protocol.group_by:
        raise SnapshotValidationError(
            "split group boundary does not match the evaluation protocol"
        )
    if source.fingerprint_hash != experiment.data_fingerprint_hash:
        raise SnapshotValidationError(
            "data module source does not contain the approved fingerprint hash"
        )
    if fingerprint_record != source:
        raise SnapshotValidationError(
            "selected fingerprint record does not match the dataset source revision"
        )


def _verify_external_fingerprint(source: DatasetSourceSpec, expected_hash: str) -> None:
    if len(source.locations) != 1:
        raise SnapshotValidationError(
            "strong fingerprint verification currently requires one dataset location"
        )
    location = Path(source.locations[0])
    actual = _read_file(location, "external dataset fingerprint").sha256
    if actual != expected_hash:
        raise SnapshotValidationError(
            f"external data fingerprint mismatch: expected {expected_hash}, found {actual}"
        )


def _find_fingerprint_record(
    files: Mapping[Path, StableFile], expected_hash: str
) -> tuple[Path, DatasetSourceSpec]:
    matches: list[tuple[Path, DatasetSourceSpec]] = []
    for path, value in _manifest_files(files).items():
        document = _load_mapping(path, value.data)
        if document is None or document.get("fingerprint_hash") != expected_hash:
            continue
        record = _validate_model(
            path, document, DatasetSourceSpec, "data fingerprint record"
        )
        _verify_model_hash(record, "data fingerprint record")
        matches.append((path, record))
    if len(matches) != 1:
        raise SnapshotValidationError(
            f"approved data fingerprint hash matched {len(matches)} records"
        )
    return matches[0]


def _resolve_bound_adapter_files(
    files: Mapping[Path, StableFile], expected_hashes: Iterable[str]
) -> tuple[Path, ...]:
    selected: list[Path] = []
    for expected_hash in expected_hashes:
        matches = [
            path for path, value in files.items() if value.sha256 == expected_hash
        ]
        if len(matches) != 1:
            raise SnapshotValidationError(
                f"generated adapter hash {expected_hash} matched {len(matches)} files"
            )
        if matches[0] not in selected:
            selected.append(matches[0])
    return tuple(selected)


def _find_verified_manifest_by_id(
    files: Mapping[Path, StableFile],
    model: type[ModelT],
    expected_id: str,
    label: str,
) -> tuple[Path, ModelT]:
    matches: list[tuple[Path, ModelT]] = []
    for path, value in _manifest_files(files).items():
        document = _load_mapping(path, value.data)
        if document is None or document.get("id") != expected_id:
            continue
        parsed = _validate_model(path, document, model, label)
        _verify_model_hash(parsed, label)
        matches.append((path, parsed))
    if len(matches) != 1:
        raise SnapshotValidationError(
            f"referenced {label} id matched {len(matches)} manifests"
        )
    return matches[0]


def _find_verified_manifest(
    files: Mapping[Path, StableFile],
    model: type[ModelT],
    expected_hash: str,
    label: str,
) -> tuple[Path, ModelT]:
    matches: list[tuple[Path, ModelT]] = []
    for path, value in _manifest_files(files).items():
        document = _load_mapping(path, value.data)
        if document is None or document.get("content_hash") != expected_hash:
            continue
        parsed = _validate_model(path, document, model, label)
        _verify_model_hash(parsed, label)
        matches.append((path, parsed))
    if len(matches) != 1:
        raise SnapshotValidationError(
            f"approved {label} hash matched {len(matches)} manifests"
        )
    return matches[0]


def _verified_manifest(
    path: Path, value: StableFile, model: type[ModelT], label: str
) -> ModelT:
    document = _load_mapping(path, value.data)
    if document is None:
        raise SnapshotValidationError(f"invalid {label}: {path}")
    parsed = _validate_model(path, document, model, label)
    _verify_model_hash(parsed, label)
    return parsed


def _validate_model(
    path: Path,
    document: Mapping[str, Any],
    model: type[ModelT],
    label: str,
) -> ModelT:
    try:
        return model.model_validate(document)
    except ValidationError as error:
        raise SnapshotValidationError(f"invalid {label}: {path}") from error


def _verify_model_hash(value: BaseModel, label: str) -> None:
    declared = getattr(value, "content_hash", None)
    computed = canonical_manifest_hash(value)
    if declared != computed:
        raise SnapshotValidationError(
            f"{label} hash mismatch: expected {declared}, computed {computed}"
        )


def _manifest_files(files: Mapping[Path, StableFile]) -> dict[Path, StableFile]:
    return {
        path: value
        for path, value in files.items()
        if path.suffix.lower() in _MANIFEST_SUFFIXES
    }


def _read_root_snapshot_files(root: Path) -> dict[Path, StableFile]:
    files: dict[Path, StableFile] = {}
    for name in _ROOT_SNAPSHOT_FILES:
        path = root / name
        if _is_link_or_reparse(path):
            raise SnapshotValidationError(
                f"snapshot source cannot contain links: {path}"
            )
        if path.is_file():
            files[path] = _read_file(path, "root snapshot file")
    return files


def _read_optional_small_tree(root: Path, label: str) -> dict[Path, StableFile]:
    if _is_link_or_reparse(root):
        raise SnapshotValidationError(f"snapshot source cannot contain links: {root}")
    if not root.exists():
        return {}
    files = _read_tree(root, label)
    for path, value in files.items():
        if len(value.data) > _MAX_CONFIG_FILE_BYTES:
            raise SnapshotValidationError(
                f"{label} exceeds {_MAX_CONFIG_FILE_BYTES} bytes: {path}"
            )
    return files


def _read_tree(root: Path, label: str) -> dict[Path, StableFile]:
    directory = Path(root)
    if _is_link_or_reparse(directory) or not directory.is_dir():
        raise SnapshotValidationError(f"{label} root must be a real directory: {root}")
    files: dict[Path, StableFile] = {}
    try:
        paths = sorted(directory.rglob("*"), key=lambda item: item.as_posix())
    except OSError as error:
        raise SnapshotValidationError(f"cannot enumerate {label}: {root}") from error
    for path in paths:
        if _is_link_or_reparse(path):
            raise SnapshotValidationError(
                f"snapshot source cannot contain links: {path}"
            )
        if path.is_file():
            files[path] = _read_file(path, label)
    return files


def _read_file(path: Path, label: str) -> StableFile:
    try:
        return stable_read_file(path)
    except (OSError, StableReadError) as error:
        raise SnapshotValidationError(f"cannot stably read {label}: {path}") from error


def _load_mapping(path: Path, data: bytes) -> Mapping[str, Any] | None:
    try:
        text = data.decode("utf-8")
        if path.suffix.lower() in {".yaml", ".yml"}:
            value = yaml.safe_load(text)
        else:
            value = json.loads(text)
    except (UnicodeError, ValueError, yaml.YAMLError) as error:
        raise SnapshotValidationError(f"cannot read manifest: {path}") from error
    return value if isinstance(value, Mapping) else None
