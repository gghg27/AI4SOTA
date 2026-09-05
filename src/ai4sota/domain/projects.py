"""Project-level configuration and conversation routing contracts."""

from __future__ import annotations

from pydantic import Field, field_validator, model_validator

from .common import (
    ConversationScope,
    ModuleKind,
    NonEmptyStr,
    SchemaHeader,
    require_non_empty,
)


class ProjectSpec(SchemaHeader):
    name: NonEmptyStr
    active_task: NonEmptyStr = "tasks/active.yaml"
    active_modules: dict[ModuleKind, NonEmptyStr]
    default_provider_profile: NonEmptyStr | None = None
    conversation_overrides: dict[ConversationScope, NonEmptyStr] = Field(
        default_factory=dict
    )

    @field_validator("active_task")
    @classmethod
    def active_task_is_not_empty(cls, value: str) -> str:
        return require_non_empty(value)

    @model_validator(mode="after")
    def has_one_active_module_of_each_kind(self) -> ProjectSpec:
        if set(self.active_modules) != set(ModuleKind):
            raise ValueError("active_modules must declare data, method, and evaluation")
        return self
