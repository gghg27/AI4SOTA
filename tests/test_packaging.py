from __future__ import annotations

import tomllib
from pathlib import Path

from setuptools import Distribution, find_namespace_packages
from setuptools.command.build_py import build_py


def test_built_package_includes_hidden_project_template_attributes(
    tmp_path: Path,
) -> None:
    """Catches package-data globs dropping the byte-preservation policy."""
    project_root = Path(__file__).resolve().parents[1]
    source_root = project_root / "src"
    with (project_root / "pyproject.toml").open("rb") as stream:
        package_data = tomllib.load(stream)["tool"]["setuptools"]["package-data"]
    distribution = Distribution(
        {
            "packages": find_namespace_packages(where=str(source_root)),
            "package_dir": {"": str(source_root)},
            "package_data": package_data,
        }
    )
    distribution.script_name = str(project_root / "pyproject.toml")
    command = build_py(distribution)
    command.build_lib = str(tmp_path / "package")
    command.ensure_finalized()

    command.run()

    source = source_root / "ai4sota" / "templates" / "v1" / ".gitattributes"
    packaged = tmp_path / "package" / "ai4sota" / "templates" / "v1" / ".gitattributes"
    assert packaged.read_bytes() == source.read_bytes()
