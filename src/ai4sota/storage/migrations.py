"""Explicit, previewable migrations from checked Phase 1 manifests."""

from __future__ import annotations

import difflib
import hashlib
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel

from ai4sota.domain import DataModuleSpec, EvaluationSpec, MethodSpec, ProjectSpec

from .atomic import atomic_write_bytes
from .manifests import canonical_manifest_hash

Migration = Callable[[dict[str, Any], str], dict[str, Any]]
PHASE1_TASK_CONTRACT_HASH = (
    "sha256:bdc75a386dfae7886c01e32d6bb88a04"
    "e165901ca15ff570375db1b36d84a324"
)


@dataclass(frozen=True)
class MigrationPlan:
    path: Path
    source_version: str
    target_version: str
    kind: str
    original_hash: str
    original_bytes: bytes
    migrated_bytes: bytes
    diff: str


def plan_schema_migration(path: Path, target: str) -> MigrationPlan:
    original = path.read_bytes()
    value = yaml.safe_load(original)
    if not isinstance(value, dict):
        raise TypeError(f"expected a mapping in {path}")
    kind = _phase1_kind(path, value)
    source_version = str(value.get("schema_version", "0.1"))
    key = (source_version, target, kind)
    try:
        migration, model = MIGRATIONS[key]
    except KeyError as error:
        raise ValueError(f"no registered schema migration for {key}") from error
    original_hash = _sha256(original)
    migrated = migration(value, original_hash)
    migrated["content_hash"] = "sha256:" + "0" * 64
    migrated = model.model_validate(migrated).model_dump(mode="json")
    migrated["content_hash"] = canonical_manifest_hash(migrated)
    migrated_bytes = yaml.safe_dump(
        migrated, allow_unicode=True, sort_keys=False
    ).encode("utf-8")
    diff = "".join(
        difflib.unified_diff(
            original.decode("utf-8").splitlines(keepends=True),
            migrated_bytes.decode("utf-8").splitlines(keepends=True),
            fromfile=str(path),
            tofile=f"{path} ({target})",
        )
    )
    return MigrationPlan(
        path=path,
        source_version=source_version,
        target_version=target,
        kind=kind,
        original_hash=original_hash,
        original_bytes=original,
        migrated_bytes=migrated_bytes,
        diff=diff,
    )


def apply_schema_migration(plan: MigrationPlan, expected_hash: str) -> Path:
    if expected_hash != plan.original_hash:
        raise ValueError("migration expected hash does not match the preview")
    current = plan.path.read_bytes()
    if _sha256(current) != plan.original_hash:
        raise ValueError("manifest hash changed after migration preview")
    digest = plan.original_hash.removeprefix("sha256:")
    backup = plan.path.with_name(f"{plan.path.name}.{digest}.bak")
    _create_or_verify_backup(backup, plan.original_bytes)
    atomic_write_bytes(plan.path, plan.migrated_bytes)
    return backup


def _create_or_verify_backup(path: Path, data: bytes) -> None:
    try:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        if path.read_bytes() != data:
            raise FileExistsError(
                f"migration backup has unexpected content: {path}"
            ) from None


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _phase1_kind(path: Path, value: dict[str, Any]) -> str:
    parent = path.parent.name.lower()
    if path.name.lower() == "project.yaml" and "schema_version" in value:
        return "project"
    if parent == "data" and path.name.lower() == "dataset.yaml":
        return "data"
    if parent == "method" and path.name.lower() == "method.yaml":
        return "method"
    if parent == "evaluation" and path.name.lower() == "evaluation.yaml":
        return "evaluation"
    raise ValueError(f"unrecognized Phase 1 schema: {path}")


def _slug(value: object, fallback: str) -> str:
    text = str(value or fallback).strip().lower().replace("_", "-").replace(" ", "-")
    return text or fallback


def _project_migration(value: dict[str, Any], legacy_hash: str) -> dict[str, Any]:
    del legacy_hash
    name = str(value.get("name") or "project")
    return {
        "api_version": "ai4sota/v1",
        "id": f"project/{_slug(name, 'project')}",
        "version": "1.0.0",
        "name": name,
        "active_task": "tasks/active.yaml",
        "active_modules": {
            "data": "modules/data/current",
            "method": "modules/method/current",
            "evaluation": "modules/evaluation/current",
        },
    }


def _data_migration(value: dict[str, Any], legacy_hash: str) -> dict[str, Any]:
    source = value.get("source")
    source = source if isinstance(source, dict) else {}
    fields = value.get("fields")
    fields = fields if isinstance(fields, dict) else {}
    outputs: list[str] = []
    for group in ("inputs", "targets", "metadata"):
        mapping = fields.get(group)
        if isinstance(mapping, dict):
            outputs.extend(str(item) for item in mapping)
    source_path = str(source.get("path") or "dataset")
    return {
        "api_version": "ai4sota/v1",
        "id": f"data/{_slug(Path(source_path).stem, 'dataset')}",
        "version": "1.0.0",
        "kind": "data",
        "origin": {"type": "project", "based_on": legacy_hash},
        "source": "source.yaml",
        "preprocessing": "preprocessing.yaml",
        "entrypoint": "adapter:load",
        "canonical_outputs": list(dict.fromkeys(outputs)) or ["features", "label"],
        "task_contract": "tasks/active.yaml",
        "task_contract_hash": PHASE1_TASK_CONTRACT_HASH,
        "validation_commands": [],
    }


def _method_migration(value: dict[str, Any], legacy_hash: str) -> dict[str, Any]:
    name = str(value.get("name") or "method")
    recipe_keys = ("learning_rate", "epochs", "l2")
    return {
        "api_version": "ai4sota/v1",
        "id": f"method/{_slug(name, 'method')}",
        "version": "1.0.0",
        "kind": "method",
        "origin": {"type": "project", "based_on": legacy_hash},
        "framework": "numpy",
        "entrypoint": "model:fit_predict",
        "input_requirements": {
            key: value[key]
            for key in ("input_key", "target_key", "split_key")
            if key in value
        },
        "output_capabilities": ["label"],
        "training_recipe": {key: value[key] for key in recipe_keys if key in value},
    }


def _evaluation_migration(
    value: dict[str, Any], legacy_hash: str
) -> dict[str, Any]:
    prediction_key = str(value.get("prediction_key") or "label")
    split_key = str(value.get("split_key") or "split")
    return {
        "api_version": "ai4sota/v1",
        "id": "evaluation/phase1",
        "version": "1.0.0",
        "kind": "evaluation",
        "origin": {"type": "project", "based_on": legacy_hash},
        "entrypoint": "evaluator:evaluate",
        "task_contract": "tasks/active.yaml",
        "task_contract_hash": PHASE1_TASK_CONTRACT_HASH,
        "required_predictions": [prediction_key],
        "required_metadata": [split_key],
        "protocol": {
            "kind": "declared_split",
            "group_by": split_key,
            "evaluate_split": str(value.get("evaluate_split") or "test"),
        },
        "metrics": [
            {
                "name": "accuracy",
                "primary": True,
                "implementation": "ai4sota/phase1",
                "required_prediction_fields": [prediction_key],
            }
        ],
    }


MIGRATIONS: dict[tuple[str, str, str], tuple[Migration, type[BaseModel]]] = {
    ("0.1", "ai4sota/v1", "project"): (_project_migration, ProjectSpec),
    ("0.1", "ai4sota/v1", "data"): (_data_migration, DataModuleSpec),
    ("0.1", "ai4sota/v1", "method"): (_method_migration, MethodSpec),
    ("0.1", "ai4sota/v1", "evaluation"): (_evaluation_migration, EvaluationSpec),
}
