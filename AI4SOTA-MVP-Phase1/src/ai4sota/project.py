from __future__ import annotations

import shutil
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

import numpy as np

from .io_utils import file_fingerprint, read_yaml, utc_now, write_json, write_yaml


REQUIRED_PROJECT_FILES = (
    "project.yaml",
    "data/dataset.yaml",
    "data/adapter.py",
    "method/method.yaml",
    "method/model.py",
    "evaluation/evaluation.yaml",
    "evaluation/evaluator.py",
    "configs/default.yaml",
    "pipeline.py",
)


@dataclass
class CreatedProject:
    project_dir: Path
    data_path: Path


def create_project(
    name: str,
    output_dir: Path,
    *,
    data_path: Path | None = None,
    demo: bool = False,
) -> CreatedProject:
    safe_name = _validate_project_name(name)
    output_dir = output_dir.expanduser().resolve()
    project_dir = output_dir / safe_name
    if project_dir.exists():
        raise FileExistsError(f"project directory already exists: {project_dir}")
    if not demo and data_path is None:
        raise ValueError("provide --data PATH or use --demo")
    if demo and data_path is not None:
        raise ValueError("--demo and --data cannot be used together")

    try:
        project_dir.mkdir(parents=True)
        _copy_template(project_dir)
        (project_dir / "runs").mkdir()

        if demo:
            resolved_data = project_dir / "demo_data" / "demo.npz"
            _create_demo_dataset(resolved_data)
            source_value = "demo_data/demo.npz"
        else:
            assert data_path is not None
            resolved_data = data_path.expanduser().resolve()
            if not resolved_data.is_file():
                raise FileNotFoundError(f"data file does not exist: {resolved_data}")
            if resolved_data.suffix.lower() != ".npz":
                raise ValueError("phase 1 default adapter accepts only .npz data")
            source_value = str(resolved_data)

        project_config = read_yaml(project_dir / "project.yaml")
        project_config.update(
            {
                "name": safe_name,
                "created_at": utc_now(),
                "schema_version": "0.1",
            }
        )
        write_yaml(project_dir / "project.yaml", project_config)

        data_config = read_yaml(project_dir / "data" / "dataset.yaml")
        data_config["source"]["path"] = source_value
        write_yaml(project_dir / "data" / "dataset.yaml", data_config)

        source_record: dict[str, Any] = {
            "path": source_value,
            "resolved_path_at_creation": str(resolved_data.resolve()),
            "size_bytes": resolved_data.stat().st_size,
            "fingerprint": file_fingerprint(resolved_data),
        }
        write_json(project_dir / "data" / "source.json", source_record)
        return CreatedProject(project_dir=project_dir, data_path=resolved_data)
    except Exception:
        if project_dir.exists():
            shutil.rmtree(project_dir)
        raise


def resolve_project(path: Path) -> Path:
    project_dir = path.expanduser().resolve()
    if not project_dir.is_dir():
        raise FileNotFoundError(f"project directory does not exist: {project_dir}")
    missing = [item for item in REQUIRED_PROJECT_FILES if not (project_dir / item).is_file()]
    if missing:
        raise ValueError("not a valid AI4SOTA project; missing: " + ", ".join(missing))
    return project_dir


def _copy_template(project_dir: Path) -> None:
    template = files("ai4sota").joinpath("templates", "project")
    _copy_template_tree(template, project_dir)


def _copy_template_tree(source, target: Path) -> None:
    """Copy importlib resources without assuming they are real filesystem Paths."""
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        destination = target / item.name
        if item.is_dir():
            _copy_template_tree(item, destination)
        else:
            destination.write_bytes(item.read_bytes())


def _create_demo_dataset(path: Path) -> None:
    rng = np.random.default_rng(20260822)
    sample_count = 240
    feature_count = 8
    X = rng.normal(size=(sample_count, feature_count))
    weights = np.array([1.8, -1.4, 1.1, 0.7, -0.5, 0.4, 0.0, -0.2])
    score = X @ weights + rng.normal(scale=0.8, size=sample_count)
    y = (score > np.median(score)).astype(np.int64)
    order = rng.permutation(sample_count)
    split = np.full(sample_count, "train", dtype="U5")
    split[order[int(sample_count * 0.75) :]] = "test"
    sample_ids = np.asarray([f"sample_{index:04d}" for index in range(sample_count)])
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, X=X, y=y, split=split, sample_ids=sample_ids)


def _validate_project_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise ValueError("project name must not be empty")
    if normalized in {".", ".."} or any(char in normalized for char in '<>:"/\\|?*'):
        raise ValueError("project name contains characters that are invalid on common platforms")
    return normalized
