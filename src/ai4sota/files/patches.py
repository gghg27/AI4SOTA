"""Atomic project file patches guarded by their proposed base hashes."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ai4sota.storage.atomic import atomic_write_bytes

from .hashing import sha256_file

_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


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


class PatchValidationError(ValueError):
    """Raised when a patch request is invalid before file access is safe."""


@dataclass(frozen=True)
class _ResolvedTarget:
    """A safe lexical replacement path paired with its canonical identity."""

    path: Path
    identity: Path


def apply_patch_set(project_root: Path, patch_set: PatchSet) -> AppliedPatch:
    """Replace all patch targets only when every expected hash still matches."""
    targets = tuple(patch_set.targets)
    _validate_expected_hashes(targets)
    root = _resolve_project_root(project_root)
    resolved = [_resolve_inside(root, target.path) for target in targets]
    _reject_duplicate_paths(resolved)
    conflicts = tuple(
        target.path
        for target, resolved_target in zip(targets, resolved, strict=True)
        if _is_conflicted(resolved_target.path, target.expected_sha256)
    )
    if conflicts:
        raise PatchConflict(conflicts)

    for target, resolved_target in zip(targets, resolved, strict=True):
        atomic_write_bytes(resolved_target.path, target.content.encode("utf-8"))
    return AppliedPatch(paths=tuple(target.path for target in targets))


def _validate_expected_hashes(targets: Sequence[PatchTarget]) -> None:
    invalid_paths = tuple(
        target.path
        for target in targets
        if _SHA256_PATTERN.fullmatch(target.expected_sha256) is None
    )
    if invalid_paths:
        raise PatchValidationError(
            f"invalid expected SHA-256 for patch targets: {', '.join(invalid_paths)}"
        )


def _resolve_project_root(project_root: Path) -> Path:
    root = project_root.resolve(strict=False)
    if not root.is_dir():
        raise PatchValidationError("project root must be an existing directory")
    return root


def _is_conflicted(path: Path, expected_sha256: str) -> bool:
    try:
        return sha256_file(path) != expected_sha256
    except FileNotFoundError:
        return True


def _resolve_inside(root: Path, relative_path: str) -> _ResolvedTarget:
    target = Path(relative_path)
    if target.is_absolute() or target.drive:
        raise PatchValidationError(f"patch path must be relative: {relative_path}")
    if ".." in target.parts:
        raise PatchValidationError(
            f"patch path escapes project root through traversal: {relative_path}"
        )

    candidate = root / target
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise PatchValidationError(
            f"patch path escapes project root: {relative_path}"
        ) from error
    if resolved == root:
        raise PatchValidationError(f"patch path cannot be the project root: {relative_path}")
    return _ResolvedTarget(path=candidate, identity=resolved)


def _reject_duplicate_paths(paths: Sequence[_ResolvedTarget]) -> None:
    seen: set[Path] = set()
    for path in paths:
        if path.identity in seen:
            raise PatchValidationError(f"duplicate patch target: {path.identity}")
        seen.add(path.identity)
