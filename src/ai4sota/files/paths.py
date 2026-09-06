"""Canonical lexical resolution for project-owned relative file references."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath


class PathValidationError(ValueError):
    """Raised when a persisted relative path cannot identify one bundle file."""


def resolve_bundle_file(bundle_root: Path, reference: str) -> Path:
    """Resolve one canonical POSIX file reference below an existing bundle root."""
    root = Path(os.path.abspath(bundle_root))
    if not root.is_dir():
        raise PathValidationError(f"bundle root must be an existing directory: {root}")
    relative = PurePosixPath(reference)
    if (
        reference != reference.strip()
        or not relative.parts
        or relative.parts == (".",)
        or "\\" in reference
        or relative.is_absolute()
        or relative.as_posix() != reference
        or ".." in relative.parts
        or ":" in relative.parts[0]
    ):
        raise PathValidationError(
            f"bundle file reference must be a canonical relative POSIX path: {reference!r}"
        )
    return root.joinpath(*relative.parts)


def resolve_file_location(base: Path, location: str) -> Path:
    """Resolve an absolute or base-relative external file location lexically."""
    candidate = Path(location).expanduser()
    if candidate.drive and not candidate.is_absolute():
        raise PathValidationError(
            f"drive-relative file locations are ambiguous: {location!r}"
        )
    if candidate.is_absolute():
        return candidate
    return Path(os.path.abspath(base)) / candidate


__all__ = [
    "PathValidationError",
    "resolve_bundle_file",
    "resolve_file_location",
]
