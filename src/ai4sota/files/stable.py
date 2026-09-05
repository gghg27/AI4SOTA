"""Race-aware reads for bytes used as durable provenance."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path


class StableReadError(OSError):
    """Raised when a file cannot be read without following mutable links."""


@dataclass(frozen=True)
class StableFile:
    data: bytes
    sha256: str


def stable_read_file(path: Path) -> StableFile:
    """Read exact bytes while rejecting links and identity changes."""
    candidate = Path(os.path.abspath(path))
    _reject_link_components(candidate)
    try:
        before = candidate.lstat()
    except OSError as error:
        raise StableReadError(f"cannot inspect file: {path}") from error
    if not stat.S_ISREG(before.st_mode) or _is_reparse(before):
        raise StableReadError(f"file must be a regular non-link: {path}")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(candidate, flags)
        opened = os.fstat(descriptor)
        if _identity(opened) != _identity(before):
            raise StableReadError(f"file identity changed before reading: {path}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after_open = os.fstat(descriptor)
    except OSError as error:
        if isinstance(error, StableReadError):
            raise
        raise StableReadError(f"cannot read file: {path}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    _reject_link_components(candidate)
    try:
        after_path = candidate.lstat()
    except OSError as error:
        raise StableReadError(f"file disappeared after reading: {path}") from error
    expected = _stable_signature(before)
    if (
        _stable_signature(opened) != expected
        or _stable_signature(after_open) != expected
        or _stable_signature(after_path) != expected
    ):
        raise StableReadError(f"file changed while being read: {path}")

    data = b"".join(chunks)
    return StableFile(data=data, sha256=f"sha256:{hashlib.sha256(data).hexdigest()}")


def _reject_link_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            if current == path:
                raise
            raise StableReadError(f"file ancestor does not exist: {current}") from None
        if stat.S_ISLNK(metadata.st_mode) or _is_reparse(metadata):
            raise StableReadError(
                f"file path contains a link or reparse point: {current}"
            )


def _identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _stable_signature(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _is_reparse(metadata: os.stat_result) -> bool:
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)
