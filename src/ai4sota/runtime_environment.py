"""Deterministic identity for the Python runtime executing evaluator code."""

from __future__ import annotations

import importlib.metadata
import platform
import re
import sys
from collections.abc import Mapping

_ENVIRONMENT_SCHEMA = "ai4sota/runtime-environment/v1"
_NORMALIZED_NAME_SEPARATOR = re.compile(r"[-_.]+")


def capture_runtime_environment() -> dict[str, object] | None:
    """Return a normalized installed runtime inventory, or None if unreliable."""
    try:
        distributions: dict[str, str] = {}
        for distribution in importlib.metadata.distributions():
            raw_name = distribution.metadata["Name"]
            raw_version = distribution.version
            if not isinstance(raw_name, str) or not isinstance(raw_version, str):
                return None
            name = _NORMALIZED_NAME_SEPARATOR.sub("-", raw_name.strip()).lower()
            version = raw_version.strip().lower()
            if not name or not version:
                return None
            previous = distributions.get(name)
            if previous is not None and previous != version:
                return None
            distributions[name] = version

        implementation = sys.implementation.name.strip().lower()
        version = platform.python_version().strip().lower()
        cache_tag = sys.implementation.cache_tag
        if not implementation or not version or not isinstance(cache_tag, str):
            return None
        return {
            "schema": _ENVIRONMENT_SCHEMA,
            "python": {
                "implementation": implementation,
                "version": version,
                "cache_tag": cache_tag,
            },
            "distributions": [
                {"name": name, "version": distributions[name]}
                for name in sorted(distributions)
            ],
        }
    except Exception:  # noqa: BLE001
        return None


def is_runtime_environment_identity(value: Mapping[str, object]) -> bool:
    """Return whether a mapping carries the supported runtime identity schema."""
    return value.get("schema") == _ENVIRONMENT_SCHEMA


__all__ = ["capture_runtime_environment", "is_runtime_environment_identity"]
