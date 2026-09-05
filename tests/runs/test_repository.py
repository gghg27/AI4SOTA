from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import ai4sota.runs.lifecycle as lifecycle_module
from ai4sota.domain import RunManifest
from ai4sota.runs import (
    InvalidRunTransition,
    RunEvent,
    RunStateConflict,
    append_run_event,
    load_run_manifest,
    transition_run,
)
from ai4sota.storage import ManifestStore, canonical_manifest_hash

CONTENT_HASH = "sha256:" + "a" * 64


def make_run(run_dir: Path, status: str = "draft") -> RunManifest:
    draft = RunManifest(
        id="run-001",
        content_hash=CONTENT_HASH,
        project_id="project/seed-emotion",
        experiment_hash=CONTENT_HASH,
        snapshot_hash=CONTENT_HASH,
        data_fingerprint_hash=CONTENT_HASH,
        task_contract_hash=CONTENT_HASH,
        split_manifest_hash=CONTENT_HASH,
        evaluation_protocol_hash=CONTENT_HASH,
        metric_implementation_hash=CONTENT_HASH,
        integrity_state="verified",
        status=status,
    )
    manifest = draft.model_copy(
        update={"content_hash": canonical_manifest_hash(draft)}
    )
    ManifestStore().write(run_dir / "manifest.yaml", manifest)
    return manifest


def test_append_run_event_is_append_only_and_fsyncs_each_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches event replacement or a successful append left only in buffers."""
    run_dir = tmp_path / "run-001"
    run_dir.mkdir()
    calls: list[int] = []
    real_fsync = lifecycle_module.os.fsync

    def observed_fsync(file_descriptor: int) -> None:
        calls.append(file_descriptor)
        real_fsync(file_descriptor)

    monkeypatch.setattr(lifecycle_module.os, "fsync", observed_fsync)
    first = RunEvent(
        id="event-001",
        run_id="run-001",
        event_type="note",
        occurred_at=datetime(2026, 9, 6, tzinfo=UTC),
        details={"message": "prepared"},
    )
    second = first.model_copy(update={"id": "event-002"})

    append_run_event(run_dir, first)
    prefix = (run_dir / "events.jsonl").read_bytes()
    append_run_event(run_dir, second)

    payload = (run_dir / "events.jsonl").read_bytes()
    assert payload.startswith(prefix)
    assert [json.loads(line)["id"] for line in payload.splitlines()] == [
        "event-001",
        "event-002",
    ]
    assert len(calls) == 2


def test_append_run_event_rejects_an_event_for_a_different_run(
    tmp_path: Path,
) -> None:
    """Catches one Run's event being appended to another Run's ledger."""
    run_dir = tmp_path / "run-001"
    run_dir.mkdir()
    event = RunEvent(
        id="event-foreign",
        run_id="run-002",
        event_type="note",
        details={"message": "wrong ledger"},
    )

    with pytest.raises(ValueError, match="run id"):
        append_run_event(run_dir, event)

    assert not (run_dir / "events.jsonl").exists()


def test_transition_run_updates_manifest_and_records_the_transition(
    tmp_path: Path,
) -> None:
    """Catches a legal state change updating only one side of the Run record."""
    run_dir = tmp_path / "run-001"
    make_run(run_dir)

    updated = transition_run(run_dir, expected="draft", target="awaiting_approval")

    assert updated.status == "awaiting_approval"
    assert load_run_manifest(run_dir) == updated
    event = json.loads((run_dir / "events.jsonl").read_text(encoding="utf-8"))
    assert event["previous_status"] == "draft"
    assert event["status"] == "awaiting_approval"


def test_transition_run_rejects_a_stale_expected_state_without_an_event(
    tmp_path: Path,
) -> None:
    """Catches a stale caller overwriting a state transition it did not observe."""
    run_dir = tmp_path / "run-001"
    make_run(run_dir)
    transition_run(run_dir, expected="draft", target="awaiting_approval")
    events_before = (run_dir / "events.jsonl").read_bytes()

    with pytest.raises(RunStateConflict, match="expected 'draft'"):
        transition_run(run_dir, expected="draft", target="awaiting_approval")

    assert (run_dir / "events.jsonl").read_bytes() == events_before
    assert load_run_manifest(run_dir).status == "awaiting_approval"


@pytest.mark.parametrize(
    ("status", "target"),
    [("draft", "running"), ("succeeded", "running"), ("failed", "running")],
)
def test_transition_run_rejects_invalid_and_terminal_transitions(
    tmp_path: Path, status: str, target: str
) -> None:
    """Catches lifecycle rules being bypassed by direct status replacement."""
    run_dir = tmp_path / "run-001"
    original = make_run(run_dir, status=status)

    with pytest.raises(InvalidRunTransition):
        transition_run(run_dir, expected=status, target=target)

    assert load_run_manifest(run_dir) == original
    assert not (run_dir / "events.jsonl").exists()


def test_running_run_can_be_recorded_as_interrupted(tmp_path: Path) -> None:
    """Catches crash recovery being forced into a false success or failure state."""
    run_dir = tmp_path / "run-001"
    make_run(run_dir)

    for expected, target in (
        ("draft", "awaiting_approval"),
        ("awaiting_approval", "queued"),
        ("queued", "preparing"),
        ("preparing", "running"),
        ("running", "interrupted"),
    ):
        transition_run(run_dir, expected=expected, target=target)

    assert load_run_manifest(run_dir).status == "interrupted"
    assert (run_dir / "events.jsonl").read_bytes().count(b"\n") == 5


def test_preparation_failure_is_a_terminal_transition(tmp_path: Path) -> None:
    """Catches setup failures being left in a nonterminal preparing state."""
    run_dir = tmp_path / "run-001"
    make_run(run_dir, status="preparing")

    transition_run(run_dir, expected="preparing", target="failed")

    assert load_run_manifest(run_dir).status == "failed"
    with pytest.raises(InvalidRunTransition):
        transition_run(run_dir, expected="failed", target="running")
