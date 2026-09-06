"""Human-readable authoritative manifest persistence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TypeVar

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel

from ai4sota.domain import RunManifest

from .atomic import atomic_write_bytes

ModelT = TypeVar("ModelT", bound=BaseModel)
_OPTIONAL_RUN_FIELDS = frozenset(
    {"seed", "fold", "repeat", "metric_environment_state"}
)
_RUN_MANIFEST_FIELDS = frozenset(RunManifest.model_fields) - _OPTIONAL_RUN_FIELDS


def canonical_manifest_hash(value: BaseModel | Mapping[str, Any]) -> str:
    """Hash canonical JSON after excluding the top-level content_hash field."""
    if isinstance(value, BaseModel):
        document = value.model_dump(mode="json")
    else:
        document = dict(value)
    if isinstance(value, RunManifest) or _is_run_manifest_document(document):
        for field in _OPTIONAL_RUN_FIELDS:
            if document.get(field) is None:
                document.pop(field, None)
    document.pop("content_hash", None)
    encoded = json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _is_run_manifest_document(document: Mapping[str, Any]) -> bool:
    return _RUN_MANIFEST_FIELDS.issubset(document)


class ManifestStore:
    """Read and atomically write YAML or JSON Pydantic manifests."""

    def read(self, path: Path, model: type[ModelT]) -> ModelT:
        value = self._load(path)
        return model.model_validate(value)

    def write(self, path: Path, value: BaseModel | Mapping[str, Any]) -> None:
        if isinstance(value, BaseModel):
            document = value.model_dump(mode="json")
        else:
            document = dict(value)
        atomic_write_bytes(path, self._dump(path, document))

    @staticmethod
    def _load(path: Path) -> Any:
        suffix = path.suffix.lower()
        with path.open("r", encoding="utf-8") as stream:
            if suffix in {".yaml", ".yml"}:
                return yaml.safe_load(stream)
            if suffix == ".json":
                return json.load(stream)
        raise ValueError(f"unsupported manifest format: {path.suffix}")

    @staticmethod
    def _dump(path: Path, value: Mapping[str, Any]) -> bytes:
        suffix = path.suffix.lower()
        if suffix in {".yaml", ".yml"}:
            text = yaml.safe_dump(
                dict(value), allow_unicode=True, sort_keys=False
            )
        elif suffix == ".json":
            text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        else:
            raise ValueError(f"unsupported manifest format: {path.suffix}")
        return text.encode("utf-8")
