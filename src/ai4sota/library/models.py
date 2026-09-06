"""Immutable local-library value objects and errors."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ai4sota.domain import ModuleKind


class LibraryValidationError(ValueError):
    """Raised when a module reference, schema, or source tree is invalid."""


class ModuleNotFound(FileNotFoundError):
    """Raised when a requested published module version is absent."""


class VersionExists(FileExistsError):
    """Raised when publishing would overwrite an immutable version."""


class PublishConflict(ValueError):
    """Raised when a draft changed after its publish confirmation."""

    def __init__(self, expected_hash: str, actual_hash: str) -> None:
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash
        super().__init__(
            f"publish confirmation is stale: expected {expected_hash}, got {actual_hash}"
        )


@dataclass(frozen=True)
class ModuleDraft:
    """An editable tree proposed for publication as one module version."""

    path: Path
    module_id: str
    version: str

    @property
    def ref(self) -> str:
        return f"{self.module_id}@{self.version}"

    @property
    def kind(self) -> ModuleKind:
        return ModuleKind(self.module_id.split("/", maxsplit=1)[0])


@dataclass(frozen=True)
class PublishedModule:
    """A validated, immutable library version and its complete tree hash."""

    ref: str
    content_hash: str
    path: Path


__all__ = [
    "LibraryValidationError",
    "ModuleDraft",
    "ModuleNotFound",
    "PublishConflict",
    "PublishedModule",
    "VersionExists",
]
