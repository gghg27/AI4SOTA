from __future__ import annotations

import numpy as np
import pytest

from ai4sota import CanonicalDataset
from ai4sota.domain import EvaluationSpec, SplitManifest
from ai4sota.domain.modules import SplitProtocolSpec
from ai4sota.evaluation.splits import materialize_split

CONTENT_HASH = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

DATASET = CanonicalDataset(
    sample_ids=np.array(["sample-1", "sample-2", "sample-3", "sample-4"]),
    inputs={"features": np.zeros((4, 1))},
    targets={"label": np.array([0, 1, 0, 1])},
    metadata={"subject_id": np.array(["subject-a", "subject-a", "subject-b", "subject-b"])},
)

EVALUATION = EvaluationSpec(
    id="evaluation/subject-holdout",
    content_hash=CONTENT_HASH,
    origin={"type": "project", "remote_source": None},
    entrypoint="evaluate:run",
    task_contract="tasks/emotion.yaml",
    task_contract_hash=CONTENT_HASH,
    required_predictions=["logits"],
    protocol={
        "kind": "group_holdout",
        "group_by": "subject_id",
        "test_fraction": 0.5,
    },
    metrics=[{"name": "accuracy", "primary": True, "implementation": "builtin/v1"}],
)


def subjects_in(manifest: SplitManifest, partition: str) -> set[str]:
    members = manifest.members
    sample_subjects = dict(zip(DATASET.sample_ids.astype(str), DATASET.metadata["subject_id"]))
    return {
        str(sample_subjects[member.sample_id])
        for member in members
        if member.partition == partition
    }


def test_group_split_is_subject_safe_and_repeatable() -> None:
    """Catches per-sample assignment that leaks a subject across partitions."""
    first = materialize_split(DATASET, EVALUATION, seed=17)
    second = materialize_split(DATASET, EVALUATION, seed=17)

    assert first == second
    assert tuple(member.sample_id for member in first.members) == (
        "sample-1",
        "sample-2",
        "sample-3",
        "sample-4",
    )
    assert subjects_in(first, "train").isdisjoint(subjects_in(first, "test"))


@pytest.mark.parametrize(
    ("sample_ids", "message"),
    [
        (np.array(["sample-1", "", "sample-3"], dtype=object), "sample_ids"),
        (np.array(["sample-1", None, "sample-3"], dtype=object), "sample_ids"),
        (np.array(["sample-1", "sample-1", "sample-3"]), "sample_ids"),
    ],
)
def test_materialize_split_rejects_invalid_sample_ids(
    sample_ids: np.ndarray, message: str
) -> None:
    """Catches ambiguous manifest membership caused by bad canonical identifiers."""
    dataset = CanonicalDataset(
        sample_ids=sample_ids,
        inputs={"features": np.zeros((3, 1))},
        targets={"label": np.array([0, 1, 0])},
        metadata={"subject_id": np.array(["a", "b", "c"])},
    )

    with pytest.raises(ValueError, match=message):
        materialize_split(dataset, EVALUATION, seed=17)


def test_materialize_split_requires_the_evaluation_group_metadata() -> None:
    """Catches a split manifest built without the required leakage boundary."""
    dataset = CanonicalDataset(
        sample_ids=np.array(["sample-1", "sample-2"]),
        inputs={"features": np.zeros((2, 1))},
        targets={"label": np.array([0, 1])},
        metadata={},
    )

    with pytest.raises(ValueError, match="metadata.subject_id"):
        materialize_split(dataset, EVALUATION, seed=17)


def test_materialize_split_rejects_null_group_metadata() -> None:
    """Catches null subject identifiers being coerced into a synthetic group."""
    dataset = CanonicalDataset(
        sample_ids=np.array(["sample-1", "sample-2"]),
        inputs={"features": np.zeros((2, 1))},
        targets={"label": np.array([0, 1])},
        metadata={"subject_id": np.array(["subject-a", None], dtype=object)},
    )

    with pytest.raises(ValueError, match="metadata.subject_id"):
        materialize_split(dataset, EVALUATION, seed=17)


def test_declared_split_preserves_declared_partition_labels() -> None:
    """Catches legacy declared partitions being reinterpreted as a generated holdout."""
    evaluation = EVALUATION.model_copy(
        update={
            "protocol": SplitProtocolSpec(
                kind="declared_split", group_by="split", evaluate_split="test"
            )
        }
    )
    dataset = CanonicalDataset(
        sample_ids=np.array(["sample-1", "sample-2", "sample-3"]),
        inputs={"features": np.zeros((3, 1))},
        targets={"label": np.array([0, 1, 0])},
        metadata={"split": np.array(["train", "train", "test"])},
    )

    manifest = materialize_split(dataset, evaluation, seed=17)

    assert [member.partition for member in manifest.members] == ["train", "train", "test"]
