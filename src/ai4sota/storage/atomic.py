"""Crash-resistant local file replacement primitives."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Durably write bytes to a sibling temporary file before replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
