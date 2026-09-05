"""User-confirmed scientific decisions that cannot be inferred from chat history."""

from __future__ import annotations

from pydantic import field_validator

from .common import (
    ContentHash,
    ConversationScope,
    NonEmptyStr,
    SchemaHeader,
    require_non_empty_items,
)


class DecisionRecord(SchemaHeader):
    scope: ConversationScope
    question: NonEmptyStr
    options: tuple[NonEmptyStr, ...]
    selected_option: NonEmptyStr
    confirmed_by: NonEmptyStr
    confirmed_content_hashes: tuple[ContentHash, ...]
    evidence_ids: tuple[NonEmptyStr, ...] = ()
    affected_schema_ids: tuple[NonEmptyStr, ...] = ()
    affected_files: tuple[NonEmptyStr, ...] = ()
    affected_tests: tuple[NonEmptyStr, ...] = ()
    supersedes: NonEmptyStr | None = None

    @field_validator("options", "confirmed_content_hashes")
    @classmethod
    def required_decision_values_are_not_empty(
        cls, value: tuple[str, ...], info: object
    ) -> tuple[str, ...]:
        field_name = getattr(info, "field_name", "decision values")
        return require_non_empty_items(value, field_name)
