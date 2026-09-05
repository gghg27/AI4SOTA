from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .contracts import CanonicalDataset
from .io_utils import file_fingerprint, read_yaml
from .loading import load_project_module, require_callable
from .project import resolve_project


def validate_project(project_path: Path) -> tuple[CanonicalDataset, dict[str, Any]]:
    project_dir = resolve_project(project_path)
    data_config = read_yaml(project_dir / "data" / "dataset.yaml")
    method_config = read_yaml(project_dir / "method" / "method.yaml")
    evaluation_config = read_yaml(project_dir / "evaluation" / "evaluation.yaml")
    run_config = read_yaml(project_dir / "configs" / "default.yaml")

    data_module = load_project_module(project_dir, "data/adapter.py", "data")
    load_dataset = require_callable(data_module, "load_dataset", "data")
    dataset = load_dataset(project_dir=project_dir, config=data_config)
    if not isinstance(dataset, CanonicalDataset):
        raise TypeError("data.load_dataset must return CanonicalDataset")
    report = dataset.validate()

    data_path = _resolve_data_path(project_dir, data_config)
    labels = np.asarray(dataset.targets.get("label", []))
    split = np.asarray(dataset.metadata.get("split", []))
    report.update(
        {
            "status": "valid",
            "data_path": str(data_path),
            "data_fingerprint": file_fingerprint(data_path),
            "labels": {
                str(label): int(np.sum(labels == label)) for label in np.unique(labels)
            },
            "splits": {
                str(name): int(np.sum(split == name)) for name in np.unique(split)
            },
            "configs": {
                "method": method_config,
                "evaluation": evaluation_config,
                "run": run_config,
            },
        }
    )
    return dataset, report


def _resolve_data_path(project_dir: Path, config: dict[str, Any]) -> Path:
    raw = config.get("source", {}).get("path")
    if not raw:
        raise ValueError("data/dataset.yaml must define source.path")
    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        path = project_dir / path
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"configured data file does not exist: {path}")
    return path

