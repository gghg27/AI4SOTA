"""Append-only Run events and lifecycle rules."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import Field

from ai4sota.domain import RunManifest
from ai4sota.domain.common import NonEmptyStr, StrictModel
from ai4sota.storage import ManifestStore

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"awaiting_approval"}),
    "awaiting_approval": frozenset({"queued", "cancelled"}),
    "queued": frozenset({"preparing", "cancelled"}),
    "preparing": frozenset({"running", "failed", "cancelled"}),
    "running": frozenset({"succeeded", "failed", "cancelled", "interrupted"}),
}
TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled", "interrupted"})


def utc_now() -> datetime:
    return datetime.now(UTC)


class RunEvent(StrictModel):
    """One immutable fact in a Run's local event stream."""

    id: NonEmptyStr
    run_id: NonEmptyStr
    event_type: NonEmptyStr
    occurred_at: datetime = Field(default_factory=utc_now)
    previous_status: NonEmptyStr | None = None
    status: NonEmptyStr | None = None
    details: dict[str, Any] = Field(default_factory=dict)


def append_run_event(run_dir: Path, event: RunEvent) -> None:
    """Durably append one event without replacing prior ledger bytes."""
    directory = Path(run_dir)
    if not directory.is_dir():
        raise FileNotFoundError(f"run directory does not exist: {directory}")
    manifest_path = directory / "manifest.yaml"
    run_id = (
        ManifestStore().read(manifest_path, RunManifest).id
        if manifest_path.is_file()
        else directory.name
    )
    if event.run_id != run_id:
        raise ValueError(
            f"event run id {event.run_id!r} does not match ledger Run {run_id!r}"
        )
    _append_json_line(directory / "events.jsonl", event.model_dump_json())


def _append_json_line(path: Path, serialized: str) -> None:
    if path.exists() and path.is_symlink():
        raise ValueError(f"append-only ledger cannot be a symlink: {path}")
    encoded = (serialized + "\n").encode("utf-8")
    with path.open("ab") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
