from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


def test_wheel_includes_hidden_project_template_attributes(
    tmp_path: Path,
) -> None:
    """Catches wheel builds dropping the hidden byte-preservation policy."""
    project_root = Path(__file__).resolve().parents[1]
    build_root = tmp_path / "source"
    build_root.mkdir()
    shutil.copy2(project_root / "pyproject.toml", build_root / "pyproject.toml")
    shutil.copytree(
        project_root / "src",
        build_root / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.py[co]", "*.egg-info"),
    )
    wheel_dir = tmp_path / "wheel"
    wheel_dir.mkdir()

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--disable-pip-version-check",
            "--no-cache-dir",
            "--no-deps",
            "--no-build-isolation",
            "--no-index",
            "--wheel-dir",
            str(wheel_dir),
            ".",
        ],
        cwd=build_root,
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    wheels = list(wheel_dir.glob("*.whl"))
    assert len(wheels) == 1, wheels
    member = "ai4sota/templates/v1/.gitattributes"
    with zipfile.ZipFile(wheels[0]) as wheel:
        assert member in wheel.namelist()
        assert wheel.read(member) == b"* -text\n"
