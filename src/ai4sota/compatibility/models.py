"""Strict output contracts for deterministic compatibility compilation."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Literal

from pydantic import JsonValue, TypeAdapter, ValidationError, field_validator

from ai4sota.domain.common import (
    CompatibilityState,
    ContentHash,
    NonEmptyStr,
    StrictModel,
)

_JSON_PARAMETERS = TypeAdapter(dict[str, JsonValue])


class AdapterKind(StrEnum):
    AXIS_TRANSPOSE = "axis_transpose"
    ADD_BATCH_DIMENSION = "add_batch_dimension"
    SAFE_DTYPE_CONVERSION = "safe_dtype_conversion"
    VARIABLE_LENGTH_PADDING_MASK = "variable_length_padding_mask"
    FIELD_RENAME = "field_rename"
    STRUCTURAL_WRAP = "structural_wrap"


class MechanicalAdapterSpec(StrictModel):
    """A reviewable transformation proven to be in the v1 mechanical whitelist."""

    api_version: Literal["ai4sota/v1"] = "ai4sota/v1"
    kind: AdapterKind
    field: NonEmptyStr
    parameters: dict[str, JsonValue]


class CompatibilityFinding(StrictModel):
    rule: NonEmptyStr
    field: NonEmptyStr
    state: CompatibilityState
    message: NonEmptyStr
    adapters: tuple[MechanicalAdapterSpec, ...] = ()


class CompatibilityReport(StrictModel):
    ruleset_version: Literal["ai4sota/compatibility/v1"] = (
        "ai4sota/compatibility/v1"
    )
    state: CompatibilityState
    findings: tuple[CompatibilityFinding, ...]
    contract_hash: ContentHash

    @field_validator("findings")
    @classmethod
    def findings_are_not_empty(
        cls, value: tuple[CompatibilityFinding, ...]
    ) -> tuple[CompatibilityFinding, ...]:
        if not value:
            raise ValueError("findings must contain at least one finding")
        return value


def json_parameters(value: object) -> dict[str, JsonValue] | None:
    """Return JSON-compatible adapter parameters, rejecting opaque Python values."""
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value
    ):
        return None
    try:
        parameters = _JSON_PARAMETERS.validate_python(value)
        json.dumps(parameters, allow_nan=False)
        return parameters
    except (TypeError, ValueError, ValidationError):
        return None


__all__ = [
    "AdapterKind",
    "CompatibilityFinding",
    "CompatibilityReport",
    "MechanicalAdapterSpec",
]
