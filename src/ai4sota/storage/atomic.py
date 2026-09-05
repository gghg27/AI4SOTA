"""Crash-resistant local file replacement primitives."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

_DIRECTORY_FSYNC_SUPPORTED = os.name == "posix"
_USE_WINDOWS_WRITE_THROUGH = os.name == "nt"


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write, replace, and durably flush file content and replacement metadata."""
    durable_make_directory(path.parent)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        durable_replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def durable_make_directory(path: Path) -> None:
    """Create missing directory levels and persist every new parent entry."""
    directory = Path(path)
    missing: list[Path] = []
    current = directory
    while not current.exists():
        missing.append(current)
        parent = current.parent
        if parent == current:
            break
        current = parent

    for candidate in reversed(missing):
        try:
            candidate.mkdir()
        except FileExistsError:
            if not candidate.is_dir():
                raise
        else:
            if _DIRECTORY_FSYNC_SUPPORTED:
                _fsync_parent_directory(candidate.parent)
    if not directory.is_dir():
        raise FileExistsError(f"directory path is not a directory: {directory}")


def sync_directory_tree(root: Path) -> None:
    """Persist every directory in a staged tree from leaves to root on POSIX."""
    if not _DIRECTORY_FSYNC_SUPPORTED:
        return
    directory = Path(root)
    if not directory.is_dir():
        raise NotADirectoryError(f"directory tree root does not exist: {directory}")
    directories = [directory]
    directories.extend(path for path in directory.rglob("*") if path.is_dir())
    for path in sorted(
        directories, key=lambda item: (-len(item.parts), item.as_posix())
    ):
        _fsync_directory(path)


def durable_replace(source: Path, destination: Path) -> None:
    """Replace a file or publish a directory with durable parent metadata."""
    source_path = Path(source)
    destination_path = Path(destination)
    if source_path.is_dir():
        sync_directory_tree(source_path)
    if _USE_WINDOWS_WRITE_THROUGH:
        _replace_windows_write_through(source_path, destination_path)
        return
    source_parent = source_path.parent
    destination_parent = destination_path.parent
    os.replace(source_path, destination_path)
    if _DIRECTORY_FSYNC_SUPPORTED:
        _fsync_parent_directory(source_parent)
        if destination_parent != source_parent:
            _fsync_parent_directory(destination_parent)


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
    _fsync_directory(directory)


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
