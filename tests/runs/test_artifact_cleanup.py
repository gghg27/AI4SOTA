from __future__ import annotations

import json
from pathlib import Path

import pytest

import ai4sota.runs.artifacts as artifacts_module
from ai4sota.domain import RunManifest
from ai4sota.files.hashing import sha256_file
from ai4sota.runs import (
    ArtifactCleanupPartialFailure,
    ArtifactCleanupValidationError,
    cleanup_artifacts,
    manifest_hash,
)
from ai4sota.storage import ManifestStore, canonical_manifest_hash

CONTENT_HASH = "sha256:" + "b" * 64


@pytest.fixture
def completed_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run-001"
    for name in ("metrics", "logs", "snapshot", "artifacts"):
        (run_dir / name).mkdir(parents=True, exist_ok=True)
    (run_dir / "metrics" / "metrics.json").write_text(
        '{"accuracy": 0.75}\n', encoding="utf-8"
    )
    (run_dir / "logs" / "worker.log").write_text("complete\n", encoding="utf-8")
    (run_dir / "snapshot" / "model.py").write_text("MODEL = 1\n", encoding="utf-8")
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
        status="succeeded",
        metrics={"accuracy": 0.75},
    )
    manifest = draft.model_copy(update={"content_hash": canonical_manifest_hash(draft)})
    ManifestStore().write(run_dir / "manifest.yaml", manifest)
    return run_dir


def test_artifact_cleanup_keeps_scientific_record_and_writes_tombstone(
    completed_run: Path,
) -> None:
    """Catches artifact reclamation deleting the immutable scientific record."""
    payload = completed_run / "artifacts" / "checkpoint.pt"
    payload.write_bytes(b"checkpoint payload")
    checkpoint_hash = sha256_file(payload)

    record = cleanup_artifacts(
        completed_run,
        ["checkpoint.pt"],
        expected_manifest_hash=manifest_hash(completed_run),
        reason="storage pressure",
    )

    assert not payload.exists()
    assert (completed_run / "manifest.yaml").exists()
    assert (completed_run / "metrics").is_dir()
    assert (completed_run / "logs").is_dir()
    assert (completed_run / "snapshot").is_dir()
    assert record.items[0].sha256 == checkpoint_hash
    assert record.items[0].size_bytes == len(b"checkpoint payload")
    assert record.items[0].reason == "storage pressure"
    assert "checkpoint.pt" in (completed_run / "artifact-tombstones.jsonl").read_text(
        encoding="utf-8"
    )


def test_cleanup_rechecks_manifest_hash_before_deleting_any_payload(
    completed_run: Path,
) -> None:
    """Catches cleanup proceeding against a Run record the caller did not approve."""
    payload = completed_run / "artifacts" / "checkpoint.pt"
    payload.write_bytes(b"keep")

    with pytest.raises(ArtifactCleanupValidationError, match="manifest hash"):
        cleanup_artifacts(
            completed_run,
            ["checkpoint.pt"],
            expected_manifest_hash="sha256:" + "f" * 64,
        )

    assert payload.read_bytes() == b"keep"
    assert not (completed_run / "artifact-tombstones.jsonl").exists()


@pytest.mark.parametrize(
    "selected",
    ["../manifest.yaml", "..\\manifest.yaml", "", ".", "C:\\outside.bin"],
)
def test_cleanup_rejects_paths_outside_the_artifact_payload_root(
    completed_run: Path, selected: str
) -> None:
    """Catches traversal, absolute, and root selections reaching scientific files."""
    payload = completed_run / "artifacts" / "checkpoint.pt"
    payload.write_bytes(b"keep")

    with pytest.raises(ArtifactCleanupValidationError):
        cleanup_artifacts(
            completed_run,
            [selected],
            expected_manifest_hash=manifest_hash(completed_run),
        )

    assert payload.read_bytes() == b"keep"
    assert (completed_run / "manifest.yaml").is_file()


def test_cleanup_preflights_every_path_before_deleting_the_first(
    completed_run: Path,
) -> None:
    """Catches an invalid later selection causing avoidable partial deletion."""
    payload = completed_run / "artifacts" / "checkpoint.pt"
    payload.write_bytes(b"keep")

    with pytest.raises(ArtifactCleanupValidationError):
        cleanup_artifacts(
            completed_run,
            ["checkpoint.pt", "../manifest.yaml"],
            expected_manifest_hash=manifest_hash(completed_run),
        )

    assert payload.read_bytes() == b"keep"
    assert not (completed_run / "artifact-tombstones.jsonl").exists()


def test_cleanup_rejects_a_symlink_that_escapes_artifacts(
    completed_run: Path, tmp_path: Path
) -> None:
    """Catches a selected payload resolving through a link to external data."""
    external = tmp_path / "external.pt"
    external.write_bytes(b"outside")
    link = completed_run / "artifacts" / "checkpoint.pt"
    try:
        link.symlink_to(external)
    except OSError as error:
        if getattr(error, "winerror", None) == 1314:
            pytest.skip("symlink creation requires Windows developer mode")
        raise

    with pytest.raises(ArtifactCleanupValidationError, match="link|reparse|escape"):
        cleanup_artifacts(
            completed_run,
            ["checkpoint.pt"],
            expected_manifest_hash=manifest_hash(completed_run),
        )

    assert external.read_bytes() == b"outside"


def test_cleanup_appends_tombstones_across_requests(completed_run: Path) -> None:
    """Catches a later cleanup replacing prior artifact provenance."""
    first = completed_run / "artifacts" / "first.pt"
    second = completed_run / "artifacts" / "second.pt"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    cleanup_artifacts(
        completed_run,
        ["first.pt"],
        expected_manifest_hash=manifest_hash(completed_run),
    )
    prefix = (completed_run / "artifact-tombstones.jsonl").read_bytes()
    cleanup_artifacts(
        completed_run,
        ["second.pt"],
        expected_manifest_hash=manifest_hash(completed_run),
    )

    tombstones = (completed_run / "artifact-tombstones.jsonl").read_bytes()
    assert tombstones.startswith(prefix)
    assert tombstones.count(b"\n") == 4


def test_cleanup_records_successes_before_reporting_a_partial_failure(
    completed_run: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches a mid-cleanup failure erasing evidence of payloads already removed."""
    first = completed_run / "artifacts" / "first.pt"
    second = completed_run / "artifacts" / "second.pt"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    real_unlink = Path.unlink

    def fail_second(path: Path, *args: object, **kwargs: object) -> None:
        if path == second:
            raise PermissionError("locked payload")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_second)

    with pytest.raises(ArtifactCleanupPartialFailure) as captured:
        cleanup_artifacts(
            completed_run,
            ["first.pt", "second.pt"],
            expected_manifest_hash=manifest_hash(completed_run),
        )

    assert not first.exists()
    assert second.exists()
    assert [item.path for item in captured.value.record.items] == ["first.pt"]
    tombstone = (completed_run / "artifact-tombstones.jsonl").read_text(
        encoding="utf-8"
    )
    assert "first.pt" in tombstone
    second_entries = [
        json.loads(line)
        for line in tombstone.splitlines()
        if json.loads(line)["item"]["path"] == "second.pt"
    ]
    assert [entry["phase"] for entry in second_entries] == ["intent"]


def test_cleanup_records_prior_success_when_a_later_payload_changes(
    completed_run: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches a post-preflight race hiding an artifact already removed."""
    first = completed_run / "artifacts" / "first.pt"
    second = completed_run / "artifacts" / "second.pt"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    real_unlink = Path.unlink

    def mutate_after_first(path: Path, *args: object, **kwargs: object) -> None:
        real_unlink(path, *args, **kwargs)
        if path == first:
            second.write_bytes(b"changed during cleanup")

    monkeypatch.setattr(Path, "unlink", mutate_after_first)

    with pytest.raises(ArtifactCleanupPartialFailure) as captured:
        cleanup_artifacts(
            completed_run,
            ["first.pt", "second.pt"],
            expected_manifest_hash=manifest_hash(completed_run),
        )

    assert not first.exists()
    assert second.read_bytes() == b"changed during cleanup"
    assert [item.path for item in captured.value.record.items] == ["first.pt"]
    tombstone = (completed_run / "artifact-tombstones.jsonl").read_text(
        encoding="utf-8"
    )
    assert "first.pt" in tombstone
    assert "second.pt" not in tombstone


def test_cleanup_rechecks_the_manifest_before_each_delete(
    completed_run: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches a changed Run record being ignored midway through cleanup."""
    first = completed_run / "artifacts" / "first.pt"
    second = completed_run / "artifacts" / "second.pt"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    run_manifest = completed_run / "manifest.yaml"
    real_unlink = Path.unlink

    def mutate_manifest_after_first(
        path: Path, *args: object, **kwargs: object
    ) -> None:
        real_unlink(path, *args, **kwargs)
        if path == first:
            run_manifest.write_text(
                run_manifest.read_text(encoding="utf-8").replace(
                    "status: succeeded", "status: failed"
                ),
                encoding="utf-8",
            )

    monkeypatch.setattr(Path, "unlink", mutate_manifest_after_first)

    with pytest.raises(ArtifactCleanupPartialFailure) as captured:
        cleanup_artifacts(
            completed_run,
            ["first.pt", "second.pt"],
            expected_manifest_hash=manifest_hash(completed_run),
        )

    assert not first.exists()
    assert second.exists()
    assert [item.path for item in captured.value.record.items] == ["first.pt"]


def test_cleanup_rejects_a_non_file_tombstone_ledger_before_deletion(
    completed_run: Path,
) -> None:
    """Catches ledger validation happening only after an irreversible unlink."""
    payload = completed_run / "artifacts" / "checkpoint.pt"
    payload.write_bytes(b"keep")
    (completed_run / "artifact-tombstones.jsonl").mkdir()

    with pytest.raises(ArtifactCleanupValidationError, match="ledger"):
        cleanup_artifacts(
            completed_run,
            ["checkpoint.pt"],
            expected_manifest_hash=manifest_hash(completed_run),
        )

    assert payload.read_bytes() == b"keep"


def test_cleanup_intent_failure_reports_no_deleted_items(
    completed_run: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches an unlink proceeding without a durable deletion intent."""
    payload = completed_run / "artifacts" / "checkpoint.pt"
    payload.write_bytes(b"keep")

    def fail_intent(stream: object, entry: object) -> None:
        raise OSError("injected intent fsync failure")

    monkeypatch.setattr(artifacts_module, "_append_cleanup_entry", fail_intent)

    with pytest.raises(ArtifactCleanupPartialFailure) as captured:
        cleanup_artifacts(
            completed_run,
            ["checkpoint.pt"],
            expected_manifest_hash=manifest_hash(completed_run),
        )

    assert captured.value.record.items == ()
    assert payload.read_bytes() == b"keep"


def test_cleanup_completion_failure_reports_the_deleted_item(
    completed_run: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches a post-unlink fsync failure hiding an actual deletion."""
    payload = completed_run / "artifacts" / "checkpoint.pt"
    payload.write_bytes(b"delete me")
    real_append = artifacts_module._append_cleanup_entry

    def fail_completion(stream: object, entry: object) -> None:
        if getattr(entry, "phase", None) == "completed":
            raise OSError("injected completion fsync failure")
        real_append(stream, entry)  # type: ignore[arg-type]

    monkeypatch.setattr(artifacts_module, "_append_cleanup_entry", fail_completion)

    with pytest.raises(ArtifactCleanupPartialFailure) as captured:
        cleanup_artifacts(
            completed_run,
            ["checkpoint.pt"],
            expected_manifest_hash=manifest_hash(completed_run),
        )

    assert not payload.exists()
    assert [item.path for item in captured.value.record.items] == ["checkpoint.pt"]
    entries = [
        json.loads(line)
        for line in (completed_run / "artifact-tombstones.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [entry["phase"] for entry in entries] == ["intent"]


def test_cleanup_journals_each_item_before_and_after_unlink(
    completed_run: Path,
) -> None:
    """Catches batch-only tombstones that cannot recover the unlink boundary."""
    first = completed_run / "artifacts" / "first.pt"
    second = completed_run / "artifacts" / "second.pt"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    cleanup_artifacts(
        completed_run,
        ["first.pt", "second.pt"],
        expected_manifest_hash=manifest_hash(completed_run),
    )

    entries = [
        json.loads(line)
        for line in (completed_run / "artifact-tombstones.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [(entry["item"]["path"], entry["phase"]) for entry in entries] == [
        ("first.pt", "intent"),
        ("first.pt", "completed"),
        ("second.pt", "intent"),
        ("second.pt", "completed"),
    ]
