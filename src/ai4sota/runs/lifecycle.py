"""Append-only Run events and lifecycle rules."""

from __future__ import annotations

import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import Field

from ai4sota.domain.common import NonEmptyStr, StrictModel
from ai4sota.storage import atomic_write_bytes

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
    from .repository import _exclusive_run_lock, load_run_manifest

    with _exclusive_run_lock(directory):
        manifest = load_run_manifest(directory)
        _append_run_event_locked(directory, event, manifest.id)


def _append_run_event_locked(
    run_dir: Path,
    event: RunEvent,
    run_id: str,
    *,
    allow_state_transition: bool = False,
) -> None:
    if event.run_id != run_id:
        raise ValueError(
            f"event run id {event.run_id!r} does not match ledger Run {run_id!r}"
        )
    if event.event_type == "run_state_transition" and not allow_state_transition:
        raise ValueError("run_state_transition is reserved for lifecycle operations")
    _append_json_line(run_dir / "events.jsonl", event.model_dump_json())


def _append_json_line(path: Path, serialized: str) -> None:
    from .repository import _is_link_or_reparse

    if _is_link_or_reparse(path):
        raise ValueError(f"append-only ledger cannot be a link: {path}")
    if path.exists() and not path.is_file():
        raise ValueError(f"append-only ledger must be a regular file: {path}")
    if not path.exists():
        atomic_write_bytes(path, b"")

    encoded = (serialized + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_APPEND | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        current = path.lstat()
        if (
            not stat.S_ISREG(opened.st_mode)
            or _is_link_or_reparse(path)
            or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
        ):
            raise ValueError(
                f"append-only ledger must be a stable regular file: {path}"
            )
        written = os.write(descriptor, encoded)
        if written != len(encoded):
            raise OSError(f"short append to ledger: {path}")
        os.fsync(descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
