"""Exact filesystem contract for an AI4SOTA v1 project."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

from ai4sota.domain import ModuleKind, ProjectSpec
from ai4sota.storage import (
    ManifestStore,
    atomic_write_bytes,
    canonical_manifest_hash,
)


@dataclass(frozen=True)
class ProjectLayout:
    root: Path

    @classmethod
    def create(cls, root: Path, name: str) -> ProjectLayout:
        project_name = _validate_project_name(name)
        project_root = root.expanduser().resolve() / project_name
        if project_root.exists():
            raise FileExistsError(f"project directory already exists: {project_root}")
        layout = cls(project_root)
        created = False
        try:
            project_root.mkdir(parents=True)
            created = True
            _copy_template_tree(
                files("ai4sota").joinpath("templates", "v1"), project_root
            )
            for directory in layout.authoritative_directories:
                directory.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(layout.events_file, b"")
            project_value: dict[str, Any] = {
                "api_version": "ai4sota/v1",
                "id": f"project/{project_name}",
                "version": "1.0.0",
                "name": project_name,
                "active_task": "tasks/active.yaml",
                "active_modules": {
                    kind.value: f"modules/{kind.value}/current" for kind in ModuleKind
                },
                "content_hash": "sha256:" + "0" * 64,
            }
            project = ProjectSpec.model_validate(project_value)
            project_value["content_hash"] = canonical_manifest_hash(project)
            ManifestStore().write(
                layout.project_file, ProjectSpec.model_validate(project_value)
            )
            return layout
        except Exception:
            if created and project_root.exists():
                shutil.rmtree(project_root)
            raise

    @property
    def project_file(self) -> Path:
        return self.root / "ai4sota.project.yaml"

    @property
    def task_file(self) -> Path:
        return self.root / "tasks" / "active.yaml"

    def module_dir(self, kind: ModuleKind | str) -> Path:
        module_kind = ModuleKind(kind)
        return self.root / "modules" / module_kind.value / "current"

    @property
    def adapters_dir(self) -> Path:
        return self.root / "adapters"

    @property
    def fingerprints_dir(self) -> Path:
        return self.root / "data" / "fingerprints"

    @property
    def splits_dir(self) -> Path:
        return self.root / "data" / "splits"

    @property
    def events_file(self) -> Path:
        return self.root / "conversations" / "events.jsonl"

    @property
    def decisions_dir(self) -> Path:
        return self.root / "decisions"

    @property
    def references_dir(self) -> Path:
        return self.root / "references"

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    @property
    def research_commits_dir(self) -> Path:
        return self.root / "research-commits"

    @property
    def index_file(self) -> Path:
        return self.root / ".ai4sota" / "index.sqlite"

    @property
    def authoritative_directories(self) -> tuple[Path, ...]:
        return (
            *(self.module_dir(kind) for kind in ModuleKind),
            self.adapters_dir,
            self.fingerprints_dir,
            self.splits_dir,
            self.events_file.parent,
            self.decisions_dir,
            self.references_dir,
            self.runs_dir,
            self.research_commits_dir,
            self.index_file.parent,
        )


def _validate_project_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise ValueError("project name must not be empty")
    if normalized in {".", ".."} or any(char in normalized for char in '<>:"/\\|?*'):
        raise ValueError("project name contains characters that are invalid on common platforms")
    return normalized


def _copy_template_tree(source: Any, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        destination = target / item.name
        if item.is_dir():
            _copy_template_tree(item, destination)
        else:
            atomic_write_bytes(destination, item.read_bytes())
