"""Atomic project file patches guarded by their proposed base hashes."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ai4sota.storage.atomic import atomic_write_bytes

from .hashing import sha256_file


@dataclass(frozen=True)
class PatchTarget:
    """One text file replacement paired with its expected current hash."""

    path: str
    expected_sha256: str
    content: str


@dataclass(frozen=True)
class PatchSet:
    """A group of replacements that must apply together."""

    targets: Sequence[PatchTarget]


@dataclass(frozen=True)
class AppliedPatch:
    """The project-relative files replaced by a successful patch."""

    paths: tuple[str, ...]


class PatchConflict(Exception):
    """Raised when one or more patch targets no longer have their base hash."""

    def __init__(self, paths: tuple[str, ...]) -> None:
        self.paths = paths
        super().__init__(f"patch conflicts: {', '.join(paths)}")


def apply_patch_set(project_root: Path, patch_set: PatchSet) -> AppliedPatch:
    """Replace all patch targets only when every expected hash still matches."""
    resolved = [
        _resolve_inside(project_root, target.path) for target in patch_set.targets
    ]
    conflicts = tuple(
        target.path
        for target, path in zip(patch_set.targets, resolved, strict=True)
        if _is_conflicted(path, target.expected_sha256)
    )
    if conflicts:
        raise PatchConflict(conflicts)

    for target, path in zip(patch_set.targets, resolved, strict=True):
        atomic_write_bytes(path, target.content.encode("utf-8"))
    return AppliedPatch(paths=tuple(target.path for target in patch_set.targets))


def _is_conflicted(path: Path, expected_sha256: str) -> bool:
    try:
        return sha256_file(path) != expected_sha256
    except FileNotFoundError:
        return True


def _resolve_inside(project_root: Path, relative_path: str) -> Path:
    root = project_root.resolve(strict=True)
    target = Path(relative_path)
    if target.is_absolute() or target.drive:
        raise ValueError(f"patch path must be relative: {relative_path}")

    candidate = root / target
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"patch path escapes project root: {relative_path}") from error
    return candidate
