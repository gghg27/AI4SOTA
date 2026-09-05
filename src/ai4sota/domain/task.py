"""Shared task ontology contracts referenced by all three module kinds."""

from __future__ import annotations

from pydantic import field_validator

from .common import NonEmptyStr, SchemaHeader, require_non_empty_items


class TaskContract(SchemaHeader):
    prediction_unit: NonEmptyStr
    target_type: NonEmptyStr
    classes: dict[NonEmptyStr, int]
    required_metadata: tuple[NonEmptyStr, ...]
    unknown_label_policy: NonEmptyStr = "reject"
    output_semantics: NonEmptyStr = "class_logits"
    aggregation_unit: NonEmptyStr | None = None

    @field_validator("classes")
    @classmethod
    def classes_have_unique_codes(cls, value: dict[str, int]) -> dict[str, int]:
        if not value:
            raise ValueError("classes must contain at least one class")
        if len(set(value.values())) != len(value):
            raise ValueError("classes must use unique class codes")
        return value

    @field_validator("required_metadata")
    @classmethod
    def required_metadata_is_not_empty(
        cls, value: tuple[str, ...]
    ) -> tuple[str, ...]:
        return require_non_empty_items(value, "required_metadata")
