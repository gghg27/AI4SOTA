from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

import pytest

import ai4sota.runs.lifecycle as lifecycle_module
from ai4sota.domain import RunManifest
from ai4sota.runs import (
    InvalidRunTransition,
    RunEvent,
    RunManifestIntegrityError,
    RunPersistenceError,
    RunStateConflict,
    append_run_event,
    hash_tree,
    load_run_manifest,
    transition_run,
    verify_run_integrity,
)
from ai4sota.storage import ManifestStore, canonical_manifest_hash

CONTENT_HASH = "sha256:" + "a" * 64


def make_run(run_dir: Path, status: str = "draft") -> RunManifest:
    snapshot = run_dir / "snapshot"
    snapshot.mkdir(parents=True)
    (snapshot / "model.py").write_text("MODEL = 1\n", encoding="utf-8")
    draft = RunManifest(
        id="run-001",
        content_hash=CONTENT_HASH,
        project_id="project/seed-emotion",
        experiment_hash=CONTENT_HASH,
        snapshot_hash=hash_tree(snapshot),
        data_fingerprint_hash=CONTENT_HASH,
        task_contract_hash=CONTENT_HASH,
        split_manifest_hash=CONTENT_HASH,
        evaluation_protocol_hash=CONTENT_HASH,
        metric_implementation_hash=CONTENT_HASH,
        integrity_state="verified",
        status=status,
    )
    manifest = draft.model_copy(update={"content_hash": canonical_manifest_hash(draft)})
    ManifestStore().write(run_dir / "manifest.yaml", manifest)
    return manifest


def test_append_run_event_is_append_only_and_fsyncs_each_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches event replacement or a successful append left only in buffers."""
    run_dir = tmp_path / "run-001"
    make_run(run_dir)
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
    assert len(calls) >= 3


def test_append_run_event_rejects_an_event_for_a_different_run(
    tmp_path: Path,
) -> None:
    """Catches one Run's event being appended to another Run's ledger."""
    run_dir = tmp_path / "run-001"
    make_run(run_dir)
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


def test_transition_run_rejects_a_different_stale_expected_state_without_an_event(
    tmp_path: Path,
) -> None:
    """Catches a stale caller overwriting a state transition it did not observe."""
    run_dir = tmp_path / "run-001"
    make_run(run_dir)
    transition_run(run_dir, expected="draft", target="awaiting_approval")
    events_before = (run_dir / "events.jsonl").read_bytes()

    with pytest.raises(RunStateConflict, match="expected 'queued'"):
        transition_run(run_dir, expected="queued", target="preparing")

    assert (run_dir / "events.jsonl").read_bytes() == events_before
    assert load_run_manifest(run_dir).status == "awaiting_approval"


def test_transition_retry_returns_the_committed_projection(tmp_path: Path) -> None:
    """Catches an acknowledged transition becoming unsafe to retry."""
    run_dir = tmp_path / "run-001"
    make_run(run_dir)
    committed = transition_run(run_dir, expected="draft", target="awaiting_approval")
    events_before = (run_dir / "events.jsonl").read_bytes()

    retried = transition_run(run_dir, expected="draft", target="awaiting_approval")

    assert retried == committed
    assert (run_dir / "events.jsonl").read_bytes() == events_before


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


def test_verify_run_integrity_recomputes_the_snapshot_hash(tmp_path: Path) -> None:
    """Catches workers trusting a Run whose immutable snapshot was altered."""
    run_dir = tmp_path / "run-001"
    manifest = make_run(run_dir, status="queued")

    assert verify_run_integrity(run_dir) == manifest

    (run_dir / "snapshot" / "model.py").write_text("MODEL = 2\n", encoding="utf-8")
    with pytest.raises(RunManifestIntegrityError, match="snapshot hash"):
        verify_run_integrity(run_dir)


@pytest.mark.parametrize(
    ("status", "target"),
    [
        ("queued", "preparing"),
        ("preparing", "running"),
        ("running", "succeeded"),
    ],
)
def test_execution_transitions_require_an_intact_snapshot(
    tmp_path: Path, status: str, target: str
) -> None:
    """Catches execution proceeding after the frozen code boundary is corrupted."""
    run_dir = tmp_path / "run-001"
    original = make_run(run_dir, status=status)
    (run_dir / "snapshot" / "model.py").write_text("tampered\n", encoding="utf-8")

    with pytest.raises(RunManifestIntegrityError, match="snapshot hash"):
        transition_run(run_dir, expected=status, target=target)

    assert load_run_manifest(run_dir) == original
    assert not (run_dir / "events.jsonl").exists()


def test_transition_recovers_a_durable_event_after_projection_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches a crash between the transition fact and manifest projection."""
    run_dir = tmp_path / "run-001"
    original = make_run(run_dir, status="queued")
    real_write = ManifestStore.write

    def fail_target_projection(store: ManifestStore, path: Path, value: object) -> None:
        if (
            path == run_dir / "manifest.yaml"
            and getattr(value, "status", None) == "preparing"
        ):
            raise OSError("injected manifest projection failure")
        real_write(store, path, value)  # type: ignore[arg-type]

    monkeypatch.setattr(ManifestStore, "write", fail_target_projection)
    with pytest.raises(RunPersistenceError, match="manifest projection"):
        transition_run(run_dir, expected="queued", target="preparing")

    assert load_run_manifest(run_dir) == original
    event = json.loads((run_dir / "events.jsonl").read_text(encoding="utf-8"))
    assert event["details"]["source_manifest_hash"] == original.content_hash
    assert event["details"]["target_manifest"]["status"] == "preparing"

    monkeypatch.setattr(ManifestStore, "write", real_write)
    recovered = transition_run(run_dir, expected="queued", target="preparing")

    assert recovered.status == "preparing"
    assert load_run_manifest(run_dir) == recovered
    assert (run_dir / "events.jsonl").read_bytes().count(b"\n") == 1


def test_transition_wraps_event_persistence_failure_without_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches an event fsync error being mistaken for a committed transition."""
    run_dir = tmp_path / "run-001"
    original = make_run(run_dir, status="queued")

    def fail_append(path: Path, serialized: str) -> None:
        raise OSError("injected event persistence failure")

    monkeypatch.setattr(lifecycle_module, "_append_json_line", fail_append)

    with pytest.raises(RunPersistenceError, match="transition event"):
        transition_run(run_dir, expected="queued", target="preparing")

    assert load_run_manifest(run_dir) == original


def test_append_run_event_requires_a_matching_manifest(tmp_path: Path) -> None:
    """Catches an orphan directory becoming an authoritative Run ledger."""
    run_dir = tmp_path / "run-001"
    run_dir.mkdir()
    event = RunEvent(id="event-001", run_id="run-001", event_type="note")

    with pytest.raises((FileNotFoundError, RunManifestIntegrityError)):
        append_run_event(run_dir, event)

    assert not (run_dir / "events.jsonl").exists()


def test_append_run_event_rejects_a_non_file_ledger(tmp_path: Path) -> None:
    """Catches append logic treating a directory as a ledger path."""
    run_dir = tmp_path / "run-001"
    make_run(run_dir)
    (run_dir / "events.jsonl").mkdir()
    event = RunEvent(id="event-001", run_id="run-001", event_type="note")

    with pytest.raises(ValueError, match="ledger"):
        append_run_event(run_dir, event)


def test_direct_event_appends_are_serialized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches direct writers interleaving validation and append operations."""
    run_dir = tmp_path / "run-001"
    make_run(run_dir)
    real_append = lifecycle_module._append_json_line
    state_lock = Lock()
    active = 0
    maximum_active = 0

    def observed_append(path: Path, serialized: str) -> None:
        nonlocal active, maximum_active
        with state_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.01)
        try:
            real_append(path, serialized)
        finally:
            with state_lock:
                active -= 1

    monkeypatch.setattr(lifecycle_module, "_append_json_line", observed_append)
    events = [
        RunEvent(id=f"event-{index}", run_id="run-001", event_type="note")
        for index in range(8)
    ]
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda event: append_run_event(run_dir, event), events))

    assert maximum_active == 1
    assert (run_dir / "events.jsonl").read_bytes().count(b"\n") == len(events)
