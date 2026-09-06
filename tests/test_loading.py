from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest

from ai4sota.loading import snapshot_module_context


def test_nested_bundle_imports_execute_package_initializers(tmp_path: Path) -> None:
    """Catches relative imports losing root and nested package initialization."""
    (tmp_path / "__init__.py").write_text("OFFSET = 0.1\n", encoding="utf-8")
    package = tmp_path / "evaluation"
    package.mkdir()
    (package / "__init__.py").write_text("from .. import OFFSET\n", encoding="utf-8")
    (package / "metrics.py").write_text("VALUE = 0.7\n", encoding="utf-8")
    (package / "evaluator.py").write_text(
        "from . import OFFSET\nfrom .metrics import VALUE\n"
        "def evaluate():\n    from metrics import VALUE as sibling\n"
        "    return VALUE + OFFSET, sibling\n", encoding="utf-8"
    )
    with snapshot_module_context(tmp_path, "evaluation/evaluator.py") as module:
        assert module.evaluate() == pytest.approx((0.8, 0.7))


@pytest.mark.parametrize("failure", ["RuntimeError", "KeyboardInterrupt", "SystemExit"])
def test_failed_bundle_import_restores_shadowed_modules_and_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """Catches an import failure retaining local helpers or displacing host modules."""
    sentinel = ModuleType("metrics")
    sentinel.VALUE = "host"
    monkeypatch.setitem(sys.modules, "metrics", sentinel)
    (tmp_path / "metrics.py").write_text("VALUE = 'snapshot'\n", encoding="utf-8")
    (tmp_path / "evaluator.py").write_text(
        "from metrics import VALUE\nassert VALUE == 'snapshot'\n"
        f"raise {failure}('stop import')\n", encoding="utf-8"
    )
    previous_path = list(sys.path)
    previous_bytecode = sys.dont_write_bytecode
    with (
        pytest.raises((RuntimeError, KeyboardInterrupt, SystemExit), match="stop import"),
        snapshot_module_context(tmp_path, "evaluator.py"),
    ):
        pytest.fail("the failing import must propagate")
    assert sys.path == previous_path
    assert sys.dont_write_bytecode == previous_bytecode
    assert sys.modules["metrics"] is sentinel
    assert not any(name.startswith("_ai4sota_snapshot_") for name in sys.modules)
    assert not list(tmp_path.rglob("__pycache__"))
