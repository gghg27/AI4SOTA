"""Crash-resistant local file replacement primitives."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write, replace, and durably flush file content and replacement metadata."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        durable_replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def durable_replace(source: Path, destination: Path) -> None:
    """Replace a file or publish a directory with durable parent metadata."""
    if os.name == "nt":
        _replace_windows_write_through(source, destination)
        return
    os.replace(source, destination)
    if os.name == "posix":
        _fsync_parent_directory(destination.parent)


def _replace_windows_write_through(source: Path, destination: Path) -> None:
    """Use MoveFileExW so replacement metadata is flushed before returning."""
    import ctypes

    move_file_ex = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
    move_file_ex.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    move_file_ex.restype = ctypes.c_int
    replace_existing = 0x1
    write_through = 0x8
    succeeded = move_file_ex(
        os.path.abspath(os.fspath(source)),
        os.path.abspath(os.fspath(destination)),
        replace_existing | write_through,
    )
    if not succeeded:
        raise ctypes.WinError(ctypes.get_last_error())


def _fsync_parent_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
