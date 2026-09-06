from __future__ import annotations

import importlib
import importlib.util
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from uuid import uuid4


@contextmanager
def snapshot_module_context(
    bundle_root: Path, relative_path: str
) -> Iterator[ModuleType]:
    """Scope synchronous bundle imports, including lazy imports, to one invocation."""
    root = bundle_root.resolve()
    entrypoint = root / relative_path
    search_paths = list(dict.fromkeys((str(entrypoint.parent), str(root))))
    local_names = {
        child.stem if child.is_file() else child.name
        for directory in search_paths
        for child in Path(directory).iterdir()
        if child.is_dir() or child.suffix == ".py"
    }
    namespace = f"_ai4sota_snapshot_{uuid4().hex}"
    saved_path = list(sys.path)
    saved_bytecode = sys.dont_write_bytecode
    displaced = {
        name: module
        for name, module in tuple(sys.modules.items())
        if name.split(".")[0] in local_names
    }
    try:
        for name in displaced:
            del sys.modules[name]
        sys.path[:0] = search_paths
        sys.dont_write_bytecode = True
        package = ModuleType(namespace)
        package.__path__ = [str(root)]
        package.__package__ = namespace
        sys.modules[namespace] = package
        importlib.invalidate_caches()
        initializer = root / "__init__.py"
        if initializer.is_file():
            spec = importlib.util.spec_from_file_location(
                namespace, initializer, submodule_search_locations=[str(root)]
            )
            if spec is None or spec.loader is None:
                raise ImportError(f"could not load bundle package from {initializer}")
            package = importlib.util.module_from_spec(spec)
            sys.modules[namespace] = package
            spec.loader.exec_module(package)
        module_name = ".".join(Path(relative_path).with_suffix("").parts)
        yield importlib.import_module(f"{namespace}.{module_name}")
    finally:
        for name, module in tuple(sys.modules.items()):
            filename = getattr(module, "__file__", None)
            if (
                name == namespace
                or name.startswith(namespace + ".")
                or name.split(".")[0] in local_names
                or (filename and Path(filename).is_relative_to(root))
            ):
                sys.modules.pop(name, None)
        sys.modules.update(displaced)
        sys.path[:] = saved_path
        sys.dont_write_bytecode = saved_bytecode
        importlib.invalidate_caches()


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
