"""Deterministic, group-safe split manifest materialization."""

from __future__ import annotations

import math
import random
from collections.abc import Sequence

import numpy as np

from ai4sota.contracts import CanonicalDataset
from ai4sota.domain.experiments import SplitManifest, SplitMember
from ai4sota.domain.modules import EvaluationSpec, SplitProtocolSpec
from ai4sota.storage import canonical_manifest_hash

ZERO_HASH = "sha256:" + "0" * 64


def materialize_split(
    dataset: CanonicalDataset, evaluation: EvaluationSpec, seed: int
) -> SplitManifest:
    """Freeze the evaluation-owned split policy into exact sample membership."""
    sample_ids = _required_identifiers(dataset.sample_ids, "sample_ids", unique=True)
    group_field = evaluation.protocol.group_by
    if group_field not in dataset.metadata:
        raise ValueError(f"metadata.{group_field} is required for split materialization")
    groups = _required_identifiers(
        dataset.metadata[group_field], f"metadata.{group_field}", unique=False
    )
    if len(sample_ids) != len(groups):
        raise ValueError(
            f"metadata.{group_field} must contain {len(sample_ids)} samples; "
            f"got {len(groups)}"
        )

    assignments = assign_groups(groups, evaluation.protocol, seed)
    members = tuple(
        SplitMember(sample_id=sample_id, partition=assignments[group])
        for sample_id, group in zip(sample_ids, groups, strict=True)
    )
    identity_hash = canonical_manifest_hash(
        {
            "evaluation_hash": evaluation.content_hash,
            "seed": seed,
            "group_by": group_field,
            "members": [member.model_dump(mode="json") for member in members],
        }
    )
    draft = SplitManifest(
        id=f"split/{identity_hash.removeprefix('sha256:')[:16]}",
        content_hash=ZERO_HASH,
        evaluation_hash=evaluation.content_hash,
        seed=seed,
        group_by=group_field,
        members=members,
    )
    manifest = draft.model_copy(
        update={"content_hash": canonical_manifest_hash(draft)}
    )
    validate_no_group_leakage(manifest, groups)
    return manifest


def assign_groups(
    groups: Sequence[str], protocol: SplitProtocolSpec, seed: int
) -> dict[str, str]:
    """Assign each group to one partition according to its declared protocol."""
    if protocol.folds is not None:
        raise ValueError("protocol.folds is not supported by SplitManifest")
    if protocol.repeats != 1:
        raise ValueError("protocol.repeats must be 1 for SplitManifest")

    unique_groups = sorted(set(groups))
    if protocol.kind == "declared_split":
        if protocol.evaluate_split is None:
            raise ValueError(
                f"protocol.evaluate_split is required for metadata.{protocol.group_by}"
            )
        if protocol.evaluate_split not in unique_groups:
            raise ValueError(
                f"protocol.evaluate_split must exist in metadata.{protocol.group_by}"
            )
        return {group: group for group in unique_groups}
    if protocol.kind != "group_holdout":
        raise ValueError(f"protocol.kind {protocol.kind!r} is not supported")
    if protocol.test_fraction is None:
        raise ValueError("protocol.test_fraction is required for group_holdout")
    if len(unique_groups) < 2:
        raise ValueError("metadata groups must contain at least two distinct values")

    shuffled_groups = unique_groups.copy()
    random.Random(seed).shuffle(shuffled_groups)
    test_count = math.ceil(len(shuffled_groups) * protocol.test_fraction)
    test_count = min(max(test_count, 1), len(shuffled_groups) - 1)
    test_groups = set(shuffled_groups[:test_count])
    return {
        group: "test" if group in test_groups else "train" for group in unique_groups
    }


def validate_no_group_leakage(manifest: SplitManifest, group_by: Sequence[str]) -> None:
    """Reject manifests that place one declared group in multiple partitions."""
    if len(manifest.members) != len(group_by):
        raise ValueError("group_by must align with manifest.members")
    partition_by_group: dict[str, str] = {}
    for member, group in zip(manifest.members, group_by, strict=True):
        previous = partition_by_group.setdefault(group, member.partition)
        if previous != member.partition:
            raise ValueError(
                f"group {group!r} appears in both {previous!r} and {member.partition!r}"
            )


def _required_identifiers(
    values: object, field_name: str, *, unique: bool
) -> tuple[str, ...]:
    array = np.asarray(values, dtype=object)
    if array.ndim != 1:
        raise ValueError(f"{field_name} must be a one-dimensional array")

    normalized: list[str] = []
    for value in array:
        if _is_missing_identifier(value):
            raise ValueError(f"{field_name} must not contain null values")
        identifier = str(value).strip()
        if not identifier:
            raise ValueError(f"{field_name} must not contain absent values")
        normalized.append(identifier)

    if unique and len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} must contain unique values")
    return tuple(normalized)


def _is_missing_identifier(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, (float, np.floating, np.complexfloating)):
        return bool(np.isnan(value))
    if isinstance(value, (np.datetime64, np.timedelta64)):
        return bool(np.isnat(value))
    return False
