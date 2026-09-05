"""Strict Data, Method, and Evaluation module schema contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, PositiveFloat, field_validator, model_validator

from .common import (
    ContentHash,
    ModuleKind,
    NonEmptyStr,
    OriginSpec,
    SchemaHeader,
    StrictModel,
    require_non_empty,
    require_non_empty_items,
)


class DatasetSourceSpec(SchemaHeader):
    name: NonEmptyStr
    locations: tuple[NonEmptyStr, ...]
    sampling_rate_hz: PositiveFloat
    metadata_fields: tuple[NonEmptyStr, ...]
    fingerprint_hash: ContentHash
    license: NonEmptyStr | None = None
    source_format: NonEmptyStr | None = None
    axes: tuple[NonEmptyStr, ...] = ()
    units: dict[NonEmptyStr, NonEmptyStr] = Field(default_factory=dict)
    channel_names: tuple[NonEmptyStr, ...] = ()

    @field_validator("locations", "metadata_fields")
    @classmethod
    def required_lists_are_not_empty(
        cls, value: tuple[str, ...], info: Any
    ) -> tuple[str, ...]:
        return require_non_empty_items(value, info.field_name)


class TransformSpec(StrictModel):
    name: NonEmptyStr
    parameters: dict[str, Any] = Field(default_factory=dict)
    fitted_state_scope: NonEmptyStr | None = None


class PreprocessingSpec(SchemaHeader):
    transforms: tuple[TransformSpec, ...]
    graph_hash: ContentHash
    channel_policy: NonEmptyStr | None = None
    cache_policy: NonEmptyStr | None = None
    semantic_decision_ids: tuple[NonEmptyStr, ...] = ()


class DataModuleSpec(SchemaHeader):
    kind: Literal[ModuleKind.DATA] = ModuleKind.DATA
    origin: OriginSpec
    source: NonEmptyStr
    preprocessing: NonEmptyStr
    entrypoint: NonEmptyStr
    canonical_outputs: tuple[NonEmptyStr, ...]
    task_contract: NonEmptyStr
    task_contract_hash: ContentHash
    validation_commands: tuple[NonEmptyStr, ...] = ()

    @field_validator("entrypoint")
    @classmethod
    def entrypoint_is_not_empty(cls, value: str) -> str:
        return require_non_empty(value)

    @field_validator("canonical_outputs")
    @classmethod
    def canonical_outputs_are_not_empty(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return require_non_empty_items(value, "canonical_outputs")


class MethodSpec(SchemaHeader):
    kind: Literal[ModuleKind.METHOD] = ModuleKind.METHOD
    origin: OriginSpec
    framework: NonEmptyStr
    entrypoint: NonEmptyStr
    input_requirements: dict[str, Any]
    output_capabilities: tuple[NonEmptyStr, ...]
    task_contracts: tuple[NonEmptyStr, ...] = ()
    training_recipe: dict[str, Any] = Field(default_factory=dict)
    checkpoint_policy: dict[str, Any] = Field(default_factory=dict)
    validation_commands: tuple[NonEmptyStr, ...] = ()

    @field_validator("entrypoint")
    @classmethod
    def entrypoint_is_not_empty(cls, value: str) -> str:
        return require_non_empty(value)

    @field_validator("output_capabilities")
    @classmethod
    def output_capabilities_are_not_empty(
        cls, value: tuple[str, ...]
    ) -> tuple[str, ...]:
        return require_non_empty_items(value, "output_capabilities")


class MetricSpec(StrictModel):
    name: NonEmptyStr
    primary: bool = False
    implementation: NonEmptyStr
    required_prediction_fields: tuple[NonEmptyStr, ...] = ()
    averaging: NonEmptyStr | None = None
    positive_class: NonEmptyStr | None = None


class SplitProtocolSpec(StrictModel):
    kind: NonEmptyStr
    group_by: NonEmptyStr
    test_fraction: PositiveFloat | None = None
    folds: int | None = None
    repeats: int = 1

    @model_validator(mode="after")
    def validates_protocol_numbers(self) -> SplitProtocolSpec:
        if self.test_fraction is not None and self.test_fraction >= 1:
            raise ValueError("test_fraction must be less than one")
        if self.folds is not None and self.folds < 2:
            raise ValueError("folds must be at least two")
        if self.repeats < 1:
            raise ValueError("repeats must be at least one")
        return self


class EvaluationSpec(SchemaHeader):
    kind: Literal[ModuleKind.EVALUATION] = ModuleKind.EVALUATION
    origin: OriginSpec
    entrypoint: NonEmptyStr
    task_contract: NonEmptyStr
    task_contract_hash: ContentHash
    required_predictions: tuple[NonEmptyStr, ...]
    required_metadata: tuple[NonEmptyStr, ...] = ()
    protocol: SplitProtocolSpec
    metrics: tuple[MetricSpec, ...]
    output_artifacts: tuple[NonEmptyStr, ...] = ()

    @field_validator("entrypoint")
    @classmethod
    def entrypoint_is_not_empty(cls, value: str) -> str:
        return require_non_empty(value)

    @field_validator("required_predictions")
    @classmethod
    def required_predictions_are_not_empty(
        cls, value: tuple[str, ...]
    ) -> tuple[str, ...]:
        return require_non_empty_items(value, "required_predictions")

    @model_validator(mode="after")
    def has_exactly_one_primary_metric(self) -> EvaluationSpec:
        if sum(metric.primary for metric in self.metrics) != 1:
            raise ValueError("metrics must declare exactly one primary metric")
        return self


__all__ = [
    "DataModuleSpec",
    "DatasetSourceSpec",
    "EvaluationSpec",
    "MethodSpec",
    "MetricSpec",
    "ModuleKind",
    "PreprocessingSpec",
    "SplitProtocolSpec",
    "TransformSpec",
]
