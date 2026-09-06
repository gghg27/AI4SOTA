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
from .paths import PathValidationError, resolve_bundle_file, resolve_file_location
from .stable import StableFile, StableReadError, stable_read_file

__all__ = [
    "AppliedPatch",
    "PatchConflict",
    "PatchSet",
    "PatchTarget",
    "PatchValidationError",
    "PathValidationError",
    "StableFile",
    "StableReadError",
    "apply_patch_set",
    "resolve_bundle_file",
    "resolve_file_location",
    "sha256_file",
    "stable_read_file",
]
