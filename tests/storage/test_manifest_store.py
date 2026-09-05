from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai4sota.domain import TaskContract
from ai4sota.storage import ManifestStore, atomic_write_bytes

CONTENT_HASH = "sha256:" + "a" * 64
TASK_FIXTURE = {
    "api_version": "ai4sota/v1",
    "id": "task/emotion",
    "version": "1.0.0",
    "content_hash": CONTENT_HASH,
    "prediction_unit": "trial",
    "target_type": "multiclass",
    "classes": {"negative": 0, "neutral": 1},
    "required_metadata": ["subject_id"],
}


def test_manifest_write_is_readable_and_leaves_no_temp_file(tmp_path: Path) -> None:
    """Catches non-atomic YAML writes or output that strict models cannot read."""
    store = ManifestStore()
    path = tmp_path / "tasks" / "active.yaml"

    store.write(path, TASK_FIXTURE)

    assert store.read(path, TaskContract).id == "task/emotion"
    assert list(path.parent.glob("*.tmp")) == []


def test_json_manifest_round_trip_preserves_model_data(tmp_path: Path) -> None:
    """Catches suffix handling that silently changes JSON manifest values."""
    store = ManifestStore()
    path = tmp_path / "tasks" / "active.json"
    task = TaskContract.model_validate(TASK_FIXTURE)

    store.write(path, task)

    assert json.loads(path.read_text(encoding="utf-8"))["classes"] == {
        "negative": 0,
        "neutral": 1,
    }
    assert store.read(path, TaskContract) == task


def test_manifest_read_rejects_unknown_persisted_fields(tmp_path: Path) -> None:
    """Catches storage reads bypassing the strict Pydantic contract."""
    path = tmp_path / "task.yaml"
    value = {**TASK_FIXTURE, "misspelled_field": True}
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ValidationError):
        ManifestStore().read(path, TaskContract)


def test_atomic_write_replaces_existing_bytes_without_temp_files(tmp_path: Path) -> None:
    """Catches in-place replacement or successful writes leaving scratch files."""
    path = tmp_path / "nested" / "manifest.bin"
    path.parent.mkdir()
    path.write_bytes(b"old")

    atomic_write_bytes(path, b"new")

    assert path.read_bytes() == b"new"
    assert list(path.parent.glob("*.tmp")) == []
