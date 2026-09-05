from __future__ import annotations

from pathlib import Path

import pytest

from ai4sota.domain import ModuleKind, ProjectSpec
from ai4sota.projects import ProjectLayout
from ai4sota.storage import ManifestStore, canonical_manifest_hash


def test_project_layout_creates_authoritative_directories(tmp_path: Path) -> None:
    """Catches project creation omitting a documented authoritative path."""
    layout = ProjectLayout.create(tmp_path, "seed-emotion")

    assert layout.root == tmp_path / "seed-emotion"
    assert layout.project_file.is_file()
    assert layout.task_file == layout.root / "tasks" / "active.yaml"
    assert layout.module_dir(ModuleKind.DATA).is_dir()
    assert layout.module_dir(ModuleKind.METHOD).is_dir()
    assert layout.module_dir(ModuleKind.EVALUATION).is_dir()
    assert layout.adapters_dir.is_dir()
    assert layout.fingerprints_dir.is_dir()
    assert layout.splits_dir.is_dir()
    assert layout.events_file.parent.is_dir()
    assert layout.decisions_dir.is_dir()
    assert layout.references_dir.is_dir()
    assert layout.runs_dir.is_dir()
    assert layout.research_commits_dir.is_dir()
    assert layout.index_file.parent.name == ".ai4sota"


def test_project_layout_writes_a_valid_project_manifest(tmp_path: Path) -> None:
    """Catches layout creation producing a placeholder that domain code rejects."""
    layout = ProjectLayout.create(tmp_path, "seed-emotion")

    project = ManifestStore().read(layout.project_file, ProjectSpec)

    assert project.id == "project/seed-emotion"
    assert project.name == "seed-emotion"
    assert project.active_modules == {
        ModuleKind.DATA: "modules/data/current",
        ModuleKind.METHOD: "modules/method/current",
        ModuleKind.EVALUATION: "modules/evaluation/current",
    }
    assert project.content_hash == canonical_manifest_hash(project)


def test_project_layout_refuses_to_overwrite_an_existing_project(tmp_path: Path) -> None:
    """Catches project creation destroying an existing directory."""
    existing = tmp_path / "seed-emotion"
    existing.mkdir()
    sentinel = existing / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError):
        ProjectLayout.create(tmp_path, "seed-emotion")

    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_project_layout_does_not_delete_a_directory_created_during_a_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches cleanup deleting a target another process won the race to create."""
    target = tmp_path / "seed-emotion"
    sentinel = target / "other-process.txt"
    original_mkdir = Path.mkdir

    def competing_mkdir(
        path: Path,
        mode: int = 0o777,
        parents: bool = False,
        exist_ok: bool = False,
    ) -> None:
        if path == target:
            original_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)
            sentinel.write_text("keep", encoding="utf-8")
            raise FileExistsError(target)
        original_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

    monkeypatch.setattr(Path, "mkdir", competing_mkdir)

    with pytest.raises(FileExistsError):
        ProjectLayout.create(tmp_path, "seed-emotion")

    assert sentinel.read_text(encoding="utf-8") == "keep"
