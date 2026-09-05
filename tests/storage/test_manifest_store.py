from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest
from pydantic import ValidationError

import ai4sota.storage.atomic as atomic_module
from ai4sota.domain import TaskContract
from ai4sota.storage import (
    ManifestStore,
    atomic_write_bytes,
    canonical_manifest_hash,
    durable_replace,
)

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


def test_canonical_manifest_hash_is_ordered_and_excludes_its_own_field() -> None:
    """Catches unstable hashing or a self-referential content hash."""
    first = {
        "id": "x",
        "content_hash": "sha256:" + "f" * 64,
        "api_version": "ai4sota/v1",
    }
    second = {
        "api_version": "ai4sota/v1",
        "id": "x",
        "content_hash": "sha256:" + "0" * 64,
    }

    assert canonical_manifest_hash(first) == (
        "sha256:b1b69890623096f383947d46632cf21b723d41b44cc86d766956c40fa492f0d0"
    )
    assert canonical_manifest_hash(second) == canonical_manifest_hash(first)


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


def test_atomic_write_replaces_existing_bytes_without_temp_files(
    tmp_path: Path,
) -> None:
    """Catches in-place replacement or successful writes leaving scratch files."""
    path = tmp_path / "nested" / "manifest.bin"
    path.parent.mkdir()
    path.write_bytes(b"old")

    atomic_write_bytes(path, b"new")

    assert path.read_bytes() == b"new"
    assert list(path.parent.glob("*.tmp")) == []


def test_durable_replace_publishes_a_complete_directory(tmp_path: Path) -> None:
    """Catches Run publication bypassing durable replacement metadata."""
    source = tmp_path / "staged-run"
    destination = tmp_path / "runs" / "run-001"
    source.mkdir()
    (source / "manifest.yaml").write_text("status: queued\n", encoding="utf-8")
    destination.parent.mkdir()

    durable_replace(source, destination)

    assert not source.exists()
    assert (destination / "manifest.yaml").read_text(encoding="utf-8") == (
        "status: queued\n"
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows durability dispatch")
def test_atomic_write_uses_windows_write_through_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches Windows replacement returning before metadata is durable."""
    path = tmp_path / "manifest.bin"
    calls: list[tuple[Path, Path]] = []
    real_replace = atomic_module._replace_windows_write_through

    def observed_replace(source: Path, destination: Path) -> None:
        calls.append((source, destination))
        real_replace(source, destination)

    monkeypatch.setattr(
        atomic_module, "_replace_windows_write_through", observed_replace
    )

    atomic_write_bytes(path, b"durable")

    assert path.read_bytes() == b"durable"
    assert len(calls) == 1
    assert calls[0][1] == path


@pytest.mark.skipif(os.name != "nt", reason="Windows symlink replacement semantics")
def test_atomic_write_replaces_destination_symlink_without_touching_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches Windows replacement resolving the destination symlink first."""
    external = tmp_path / "external.bin"
    external.write_bytes(b"sentinel")
    destination = tmp_path / "manifest.bin"
    try:
        destination.symlink_to(external)
    except OSError as error:
        if getattr(error, "winerror", None) != 1314:
            raise
        destination.write_bytes(b"old")
        original_resolve = Path.resolve

        def resolve_as_destination_symlink(path: Path, strict: bool = False) -> Path:
            if path == destination:
                return external
            return original_resolve(path, strict=strict)

        monkeypatch.setattr(Path, "resolve", resolve_as_destination_symlink)

    atomic_write_bytes(destination, b"replacement")

    assert external.read_bytes() == b"sentinel"
    assert destination.read_bytes() == b"replacement"
    assert not destination.is_symlink()


@pytest.mark.skipif(os.name != "posix", reason="POSIX durability dispatch")
def test_atomic_write_fsyncs_parent_directory_after_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches POSIX rename metadata remaining only in the directory cache."""
    path = tmp_path / "manifest.bin"
    synced_modes: list[int] = []
    real_fsync = os.fsync

    def observed_fsync(file_descriptor: int) -> None:
        synced_modes.append(os.fstat(file_descriptor).st_mode)
        real_fsync(file_descriptor)

    monkeypatch.setattr(atomic_module.os, "fsync", observed_fsync)

    atomic_write_bytes(path, b"durable")

    assert path.read_bytes() == b"durable"
    assert len(synced_modes) == 2
    assert stat.S_ISREG(synced_modes[0])
    assert stat.S_ISDIR(synced_modes[1])
