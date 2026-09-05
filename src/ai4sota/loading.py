from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def load_project_module(project_dir: Path, relative_path: str, role: str) -> ModuleType:
    path = project_dir / relative_path
    module_name = f"ai4sota_user_{role}_{abs(hash(str(path)))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load {role} module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def require_callable(module: ModuleType, name: str, role: str):
    value = getattr(module, name, None)
    if not callable(value):
        raise TypeError(f"{role} module must define callable {name}(...)")
    return value
