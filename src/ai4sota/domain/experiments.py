"""Immutable composition, split, run, and research-history manifest schemas."""

from __future__ import annotations

from pathlib import PurePosixPath

from pydantic import Field, field_validator, model_validator

from .common import (
    ContentHash,
    NonEmptyStr,
    SchemaHeader,
    StrictModel,
    require_non_empty_items,
)


class SplitMember(StrictModel):
    sample_id: NonEmptyStr
    partition: NonEmptyStr
    fold: int | None = None


class SplitManifest(SchemaHeader):
    evaluation_hash: ContentHash
    seed: int
    group_by: NonEmptyStr
    members: tuple[SplitMember, ...]

    @field_validator("members")
    @classmethod
    def members_are_unique_and_not_empty(
        cls, value: tuple[SplitMember, ...]
    ) -> tuple[SplitMember, ...]:
        if not value:
            raise ValueError("members must contain at least one member")
        sample_ids = [member.sample_id for member in value]
        if len(set(sample_ids)) != len(sample_ids):
            raise ValueError("members must use unique sample_id values")
        return value


class ExperimentSpec(SchemaHeader):
    project_id: NonEmptyStr
    data_module_hash: ContentHash
    method_module_hash: ContentHash
    evaluation_module_hash: ContentHash
    task_contract_hash: ContentHash
    data_fingerprint_hash: ContentHash
    split_manifest_hash: ContentHash
    seed: int
    input_hashes: dict[NonEmptyStr, ContentHash]
    generated_adapter_hashes: tuple[ContentHash, ...] = ()
    runtime_config: dict[str, object] = Field(default_factory=dict)
    environment: dict[str, object] = Field(default_factory=dict)
    approval_id: NonEmptyStr | None = None

    @field_validator("input_hashes", mode="before")
    @classmethod
    def input_paths_are_canonical_and_not_empty(cls, value: object) -> object:
        if not isinstance(value, dict) or not value:
            raise ValueError("input_hashes must contain at least one input")
        for raw_path in value:
            if not isinstance(raw_path, str):
                raise TypeError("input_hashes keys must be paths")
            path = PurePosixPath(raw_path)
            if (
                not path.parts
                or raw_path != raw_path.strip()
                or "\\" in raw_path
                or path.is_absolute()
                or path.as_posix() != raw_path
                or ".." in path.parts
                or (path.parts and ":" in path.parts[0])
            ):
                raise ValueError(
                    "input_hashes keys must be canonical project-relative POSIX paths"
                )
        return value


class RunManifest(SchemaHeader):
    project_id: NonEmptyStr
    experiment_hash: ContentHash
    snapshot_hash: ContentHash
    data_fingerprint_hash: ContentHash
    task_contract_hash: ContentHash
    split_manifest_hash: ContentHash
    evaluation_protocol_hash: ContentHash
    metric_implementation_hash: ContentHash
    integrity_state: NonEmptyStr
    status: NonEmptyStr = "draft"
    metrics: dict[NonEmptyStr, float] = Field(default_factory=dict)
    parent_research_commit: NonEmptyStr | None = None
    seed: int | None = None
    fold: int | None = None
    repeat: int | None = None


class ResearchCommitManifest(SchemaHeader):
    project_id: NonEmptyStr
    run_ids: tuple[NonEmptyStr, ...]
    run_manifest_hashes: tuple[ContentHash, ...]
    git_sha: NonEmptyStr
    snapshot_hash: ContentHash
    parent_research_commit_ids: tuple[NonEmptyStr, ...] = ()
    comparison_state: NonEmptyStr | None = None

    @field_validator("run_ids", "run_manifest_hashes")
    @classmethod
    def run_references_are_not_empty(
        cls, value: tuple[str, ...], info: object
    ) -> tuple[str, ...]:
        field_name = getattr(info, "field_name", "run references")
        return require_non_empty_items(value, field_name)

    @model_validator(mode="after")
    def run_ids_match_manifest_hashes(self) -> ResearchCommitManifest:
        if len(self.run_ids) != len(self.run_manifest_hashes):
            raise ValueError("run_ids and run_manifest_hashes must have equal lengths")
        return self
