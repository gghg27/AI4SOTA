"""Shared versioned primitives for persisted AI4SOTA scientific records."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ContentHash = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, pattern=r"^sha256:")
]


class StrictModel(BaseModel):
    """Reject undeclared fields and prevent accidental record mutation."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SchemaHeader(StrictModel):
    """Fields shared by every persisted, content-addressed schema file."""

    api_version: Literal["ai4sota/v1"] = "ai4sota/v1"
    id: NonEmptyStr
    version: NonEmptyStr = "1.0.0"
    content_hash: ContentHash


class ModuleKind(StrEnum):
    DATA = "data"
    METHOD = "method"
    EVALUATION = "evaluation"


class ConversationScope(StrEnum):
    PROJECT = "project"
    DATA = "data"
    METHOD = "method"
    EVALUATION = "evaluation"


class CompatibilityState(StrEnum):
    COMPATIBLE = "compatible"
    ADAPTABLE = "adaptable"
    REQUIRES_DECISION = "requires_decision"
    INCOMPATIBLE = "incompatible"


class ComparabilityState(StrEnum):
    DIRECT = "directly_comparable"
    CAVEATS = "comparable_with_caveats"
    NONE = "not_comparable"


class OriginType(StrEnum):
    PROJECT = "project"
    LIBRARY = "library"
    IMPORTED = "imported"


class RemoteSourceSpec(StrictModel):
    """Reserved provenance for future remote libraries; v1 never synchronizes it."""

    provider: NonEmptyStr
    reference: NonEmptyStr
    url: NonEmptyStr | None = None
    revision: NonEmptyStr | None = None


class OriginSpec(StrictModel):
    type: OriginType
    based_on: NonEmptyStr | None = None
    remote_source: RemoteSourceSpec | None = None


def require_non_empty(value: str) -> str:
    """Validate executable entry points without imposing a module-layout syntax."""
    if not value.strip():
        raise ValueError("must not be empty")
    return value


def require_non_empty_items(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    if not values:
        raise ValueError(f"{field_name} must contain at least one item")
    if any(not item.strip() for item in values):
        raise ValueError(f"{field_name} must not contain empty items")
    return values
