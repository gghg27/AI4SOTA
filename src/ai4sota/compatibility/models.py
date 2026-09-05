"""Strict output contracts for deterministic compatibility compilation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Literal, cast

from pydantic import (
    JsonValue,
    TypeAdapter,
    ValidationError,
    field_serializer,
    field_validator,
    model_validator,
)

from ai4sota.domain.common import (
    CompatibilityState,
    ContentHash,
    NonEmptyStr,
    StrictModel,
)
from ai4sota.storage import canonical_manifest_hash

_JSON_PARAMETERS = TypeAdapter(dict[str, JsonValue])
RULESET_VERSION: Literal["ai4sota/compatibility/v1"] = (
    "ai4sota/compatibility/v1"
)

STATE_RANK = {
    CompatibilityState.COMPATIBLE: 0,
    CompatibilityState.ADAPTABLE: 1,
    CompatibilityState.REQUIRES_DECISION: 2,
    CompatibilityState.INCOMPATIBLE: 3,
}


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
    parameters: Mapping[str, object]

    @field_validator("parameters")
    @classmethod
    def parameters_are_immutable_json(
        cls, value: Mapping[str, object]
    ) -> Mapping[str, object]:
        parameters = json_parameters(value)
        if parameters is None:
            raise ValueError("parameters must contain finite JSON-compatible values")
        return cast(Mapping[str, object], _freeze_json(parameters))

    @field_serializer("parameters")
    def serialize_parameters(self, value: Mapping[str, object]) -> JsonValue:
        return _thaw_json(value)


class CompatibilityFinding(StrictModel):
    rule: NonEmptyStr
    field: NonEmptyStr
    state: CompatibilityState
    message: NonEmptyStr
    adapters: tuple[MechanicalAdapterSpec, ...] = ()


def compatibility_contract_hash(
    findings: tuple[CompatibilityFinding, ...],
    ruleset_version: str = RULESET_VERSION,
) -> str:
    """Hash the complete ordered rule output and its version."""
    return canonical_manifest_hash(
        {
            "findings": [finding.model_dump(mode="json") for finding in findings],
            "ruleset": ruleset_version,
        }
    )


class CompatibilityReport(StrictModel):
    ruleset_version: Literal["ai4sota/compatibility/v1"] = RULESET_VERSION
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

    @model_validator(mode="after")
    def state_and_hash_match_findings(self) -> CompatibilityReport:
        expected_state = max(
            (finding.state for finding in self.findings),
            key=STATE_RANK.__getitem__,
        )
        if self.state is not expected_state:
            raise ValueError("state does not match the maximum finding state")
        expected_hash = compatibility_contract_hash(
            self.findings, self.ruleset_version
        )
        if self.contract_hash != expected_hash:
            raise ValueError("contract_hash does not match findings and ruleset")
        return self


def json_parameters(value: object) -> dict[str, JsonValue] | None:
    """Return JSON-compatible adapter parameters, rejecting opaque Python values."""
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        return None
    try:
        parameters = _JSON_PARAMETERS.validate_python(dict(value))
        json.dumps(parameters, allow_nan=False)
        return parameters
    except (TypeError, ValueError, ValidationError):
        return None


def _freeze_json(value: JsonValue) -> object:
    if isinstance(value, dict):
        return MappingProxyType(
            {key: _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: object) -> JsonValue:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported immutable JSON value: {type(value).__name__}")


__all__ = [
    "RULESET_VERSION",
    "STATE_RANK",
    "AdapterKind",
    "CompatibilityFinding",
    "CompatibilityReport",
    "MechanicalAdapterSpec",
    "compatibility_contract_hash",
]
