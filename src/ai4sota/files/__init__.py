"""Hash-checked project file operations."""

from .hashing import sha256_file
from .patches import (
    AppliedPatch,
    PatchConflict,
    PatchSet,
    PatchTarget,
    PatchValidationError,
    apply_patch_set,
)
from .stable import StableFile, StableReadError, stable_read_file

__all__ = [
    "AppliedPatch",
    "PatchConflict",
    "PatchSet",
    "PatchTarget",
    "PatchValidationError",
    "StableFile",
    "StableReadError",
    "apply_patch_set",
    "sha256_file",
    "stable_read_file",
]
