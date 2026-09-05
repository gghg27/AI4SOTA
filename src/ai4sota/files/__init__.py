"""Hash-checked project file operations."""

from .hashing import sha256_file
from .patches import AppliedPatch, PatchConflict, PatchSet, PatchTarget, apply_patch_set

__all__ = [
    "AppliedPatch",
    "PatchConflict",
    "PatchSet",
    "PatchTarget",
    "apply_patch_set",
    "sha256_file",
]
