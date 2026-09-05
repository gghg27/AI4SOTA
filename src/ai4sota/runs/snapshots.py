"""Immutable, content-addressed Run snapshot creation."""

from __future__ import annotations

import json
import os
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
from ai4sota.files.hashing import sha256_file
from ai4sota.projects import ProjectLayout
from ai4sota.storage import ManifestStore, atomic_write_bytes, canonical_manifest_hash

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
    if not directory.is_dir() or _is_link_or_reparse(directory):
        raise SnapshotValidationError(f"snapshot root must be a real directory: {root}")
    files: list[dict[str, str]] = []
    for path in sorted(directory.rglob("*"), key=lambda item: item.as_posix()):
        if _is_link_or_reparse(path):
            raise SnapshotValidationError(f"snapshot cannot contain links: {path}")
        if path.is_file():
            files.append(
                {
                    "path": path.relative_to(directory).as_posix(),
                    "sha256": sha256_file(path),
                }
            )
    return canonical_manifest_hash({"files": files})


def prepare_run(project: ProjectLayout, experiment: ExperimentSpec) -> RunManifest:
    """Verify approved inputs and atomically publish an executable Run snapshot."""
    if experiment.approval_id is None:
        raise SnapshotValidationError("experiment must have an approval identifier")
    _verify_model_hash(experiment, "experiment")
    project_spec = _read_verified_manifest(
        project.project_file, ProjectSpec, "project manifest"
    )
    if experiment.project_id != project_spec.id:
        raise SnapshotValidationError(
            f"experiment project {experiment.project_id!r} does not match "
            f"{project_spec.id!r}"
        )

    task = _read_verified_manifest(project.task_file, TaskContract, "task contract")
    if task.content_hash != experiment.task_contract_hash:
        raise SnapshotValidationError("task contract hash does not match approval")

    module_bindings: tuple[tuple[ModuleKind, type[BaseModel], str, str], ...] = (
        (
            ModuleKind.DATA,
            DataModuleSpec,
            experiment.data_module_hash,
            "data module",
        ),
        (
            ModuleKind.METHOD,
            MethodSpec,
            experiment.method_module_hash,
            "method module",
        ),
        (
            ModuleKind.EVALUATION,
            EvaluationSpec,
            experiment.evaluation_module_hash,
            "evaluation module",
        ),
    )
    verified_modules: dict[ModuleKind, BaseModel] = {}
    for kind, model, expected_hash, label in module_bindings:
        _, value = _find_verified_manifest(
            project.module_dir(kind), model, expected_hash, label
        )
        verified_modules[kind] = value

    _, split = _find_verified_manifest(
        project.splits_dir,
        SplitManifest,
        experiment.split_manifest_hash,
        "split manifest",
    )
    evaluation = verified_modules[ModuleKind.EVALUATION]
    assert isinstance(evaluation, EvaluationSpec)
    if split.evaluation_hash != evaluation.content_hash:
        raise SnapshotValidationError(
            "split manifest evaluation hash does not match the approved evaluation"
        )

    data = verified_modules[ModuleKind.DATA]
    assert isinstance(data, DataModuleSpec)
    fingerprint_files = _resolve_data_fingerprint_files(
        project, data, experiment.data_fingerprint_hash
    )
    adapter_files = _resolve_bound_adapter_files(
        project.adapters_dir, experiment.generated_adapter_hashes
    )

    run_id = f"run-{uuid4().hex}"
    run_dir = project.runs_dir / run_id
    staging = project.index_file.parent / f".{run_id}.{uuid4().hex}.tmp"
    if run_dir.exists():
        raise FileExistsError(f"Run directory already exists: {run_dir}")
    staging.mkdir(parents=True)
    try:
        snapshot = staging / "snapshot"
        _copy_file(project.project_file, snapshot / project.project_file.name)
        _copy_file(project.task_file, snapshot / "tasks" / project.task_file.name)
        ManifestStore().write(snapshot / "experiment.yaml", experiment)
        for kind in ModuleKind:
            _copy_tree(
                project.module_dir(kind),
                snapshot / "modules" / kind.value / "current",
            )
        for source in adapter_files:
            _copy_file(
                source,
                snapshot / "adapters" / source.relative_to(project.adapters_dir),
            )
        _copy_optional_small_tree(
            project.root / "configs", snapshot / "configs", "small config"
        )
        _copy_optional_small_tree(
            project.root / "schemas", snapshot / "schemas", "schema"
        )
        for source in fingerprint_files:
            _copy_file(
                source,
                snapshot
                / "data"
                / "fingerprints"
                / source.relative_to(project.fingerprints_dir),
            )
        split_path, _ = _find_verified_manifest(
            project.splits_dir,
            SplitManifest,
            experiment.split_manifest_hash,
            "split manifest",
        )
        _copy_file(
            split_path,
            snapshot / "data" / "splits" / split_path.relative_to(project.splits_dir),
        )
        for name in _ROOT_SNAPSHOT_FILES:
            source = project.root / name
            if source.is_file():
                _copy_file(source, snapshot / name)

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
        )
        manifest = draft.model_copy(
            update={"content_hash": canonical_manifest_hash(draft)}
        )
        ManifestStore().write(staging / "manifest.yaml", manifest)
        for name in ("logs", "metrics", "artifacts"):
            (staging / name).mkdir()
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
        os.replace(staging, run_dir)
        return manifest
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _resolve_data_fingerprint_files(
    project: ProjectLayout, data: DataModuleSpec, expected_hash: str
) -> tuple[Path, ...]:
    module_dir = project.module_dir(ModuleKind.DATA)
    _, source = _find_verified_manifest_by_id(
        module_dir, DatasetSourceSpec, data.source, "dataset source"
    )
    _find_verified_manifest_by_id(
        module_dir,
        PreprocessingSpec,
        data.preprocessing,
        "preprocessing manifest",
    )
    if source.fingerprint_hash != expected_hash:
        raise SnapshotValidationError(
            "data module source does not contain the approved fingerprint hash"
        )

    matches: list[Path] = []
    for path in _manifest_files(project.fingerprints_dir):
        document = _load_mapping(path)
        if document is None or document.get("fingerprint_hash") != expected_hash:
            continue
        try:
            record = DatasetSourceSpec.model_validate(document)
        except ValidationError as error:
            raise SnapshotValidationError(f"invalid data fingerprint record: {path}") from error
        _verify_model_hash(record, "data fingerprint record")
        matches.append(path)
    if len(matches) != 1:
        raise SnapshotValidationError(
            f"approved data fingerprint hash matched {len(matches)} records"
        )
    return tuple(matches)


def _find_verified_manifest_by_id(
    root: Path,
    model: type[ModelT],
    expected_id: str,
    label: str,
) -> tuple[Path, ModelT]:
    matches: list[tuple[Path, ModelT]] = []
    for path in _manifest_files(root):
        document = _load_mapping(path)
        if document is None or document.get("id") != expected_id:
            continue
        try:
            value = model.model_validate(document)
        except ValidationError as error:
            raise SnapshotValidationError(f"invalid {label}: {path}") from error
        _verify_model_hash(value, label)
        matches.append((path, value))
    if len(matches) != 1:
        raise SnapshotValidationError(
            f"referenced {label} id matched {len(matches)} manifests"
        )
    return matches[0]


def _resolve_bound_adapter_files(
    adapters_dir: Path, expected_hashes: Iterable[str]
) -> tuple[Path, ...]:
    files = tuple(path for path in _regular_files(adapters_dir))
    selected: list[Path] = []
    for expected_hash in expected_hashes:
        matches = [path for path in files if sha256_file(path) == expected_hash]
        if len(matches) != 1:
            raise SnapshotValidationError(
                f"generated adapter hash {expected_hash} matched {len(matches)} files"
            )
        if matches[0] not in selected:
            selected.append(matches[0])
    return tuple(selected)


def _find_verified_manifest(
    root: Path,
    model: type[ModelT],
    expected_hash: str,
    label: str,
) -> tuple[Path, ModelT]:
    matches: list[tuple[Path, ModelT]] = []
    for path in _manifest_files(root):
        document = _load_mapping(path)
        if document is None or document.get("content_hash") != expected_hash:
            continue
        try:
            value = model.model_validate(document)
        except ValidationError as error:
            raise SnapshotValidationError(f"invalid {label}: {path}") from error
        _verify_model_hash(value, label)
        matches.append((path, value))
    if len(matches) != 1:
        raise SnapshotValidationError(
            f"approved {label} hash matched {len(matches)} manifests"
        )
    return matches[0]


def _read_verified_manifest(
    path: Path, model: type[ModelT], label: str
) -> ModelT:
    try:
        value = ManifestStore().read(path, model)
    except (OSError, TypeError, ValueError, ValidationError) as error:
        raise SnapshotValidationError(f"invalid {label}: {path}") from error
    _verify_model_hash(value, label)
    return value


def _verify_model_hash(value: BaseModel, label: str) -> None:
    declared = getattr(value, "content_hash", None)
    computed = canonical_manifest_hash(value)
    if declared != computed:
        raise SnapshotValidationError(
            f"{label} hash mismatch: expected {declared}, computed {computed}"
        )


def _manifest_files(root: Path) -> tuple[Path, ...]:
    return tuple(
        path
        for path in _regular_files(root)
        if path.suffix.lower() in _MANIFEST_SUFFIXES
    )


def _regular_files(root: Path) -> tuple[Path, ...]:
    if not root.exists():
        return ()
    if not root.is_dir() or _is_link_or_reparse(root):
        raise SnapshotValidationError(f"snapshot source must be a real directory: {root}")
    files: list[Path] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if _is_link_or_reparse(path):
            raise SnapshotValidationError(f"snapshot source cannot contain links: {path}")
        if path.is_file():
            files.append(path)
    return tuple(files)


def _load_mapping(path: Path) -> Mapping[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as stream:
            if path.suffix.lower() in {".yaml", ".yml"}:
                value = yaml.safe_load(stream)
            else:
                value = json.load(stream)
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as error:
        raise SnapshotValidationError(f"cannot read manifest: {path}") from error
    return value if isinstance(value, Mapping) else None


def _copy_optional_small_tree(source: Path, destination: Path, label: str) -> None:
    if not source.exists():
        return
    files = _regular_files(source)
    for path in files:
        size = path.stat().st_size
        if size > _MAX_CONFIG_FILE_BYTES:
            raise SnapshotValidationError(
                f"{label} exceeds {_MAX_CONFIG_FILE_BYTES} bytes: {path}"
            )
    for path in files:
        _copy_file(path, destination / path.relative_to(source))


def _copy_tree(source: Path, destination: Path) -> None:
    for path in _regular_files(source):
        _copy_file(path, destination / path.relative_to(source))


def _copy_file(source: Path, destination: Path) -> None:
    if _is_link_or_reparse(source) or not source.is_file():
        raise SnapshotValidationError(f"snapshot source must be a regular file: {source}")
    atomic_write_bytes(destination, source.read_bytes())
