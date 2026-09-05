"""Disposable SQLite projection of authoritative project records."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import yaml  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from ai4sota.projects import ProjectLayout


class ResearchIndex:
    """Build a query projection without importing or executing project code."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def rebuild(self, project: ProjectLayout) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(
            f".{self.path.name}.{uuid4().hex}.rebuild.tmp"
        )
        try:
            with closing(sqlite3.connect(temporary)) as connection, connection:
                self._create_schema(connection)
                self._scan_project(connection, project.root)
            os.replace(temporary, self.path)
        finally:
            self._remove_temporary_database(temporary)

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE records (
                path TEXT PRIMARY KEY,
                record_type TEXT NOT NULL,
                record_id TEXT,
                api_version TEXT,
                content_hash TEXT,
                payload_json TEXT NOT NULL
            );
            CREATE INDEX records_by_type_and_id
                ON records(record_type, record_id);
            CREATE TABLE events (
                path TEXT NOT NULL,
                line_number INTEGER NOT NULL,
                event_id TEXT,
                event_type TEXT,
                payload_json TEXT NOT NULL,
                PRIMARY KEY(path, line_number)
            );
            PRAGMA user_version = 1;
            """
        )

    def _scan_project(self, connection: sqlite3.Connection, root: Path) -> None:
        resolved_root = root.resolve()
        for path in sorted(root.rglob("*")):
            if not path.is_file() or not _resolves_inside(path, resolved_root):
                continue
            relative = path.relative_to(root).as_posix()
            if _is_authoritative_event(relative):
                self._insert_events(connection, relative, path)
                continue
            record_type = _authoritative_record_type(relative)
            if record_type is not None:
                value = self._load_mapping(path)
                if value is not None:
                    self._insert_record(connection, relative, record_type, value)

    @staticmethod
    def _load_mapping(path: Path) -> dict[str, Any] | None:
        with path.open("r", encoding="utf-8") as stream:
            if path.suffix.lower() in {".yaml", ".yml"}:
                value = yaml.safe_load(stream)
            else:
                value = json.load(stream)
        return value if isinstance(value, dict) else None

    @staticmethod
    def _insert_record(
        connection: sqlite3.Connection,
        relative: str,
        record_type: str,
        value: dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO records(
                path, record_type, record_id, api_version, content_hash, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                relative,
                record_type,
                value.get("id"),
                value.get("api_version"),
                value.get("content_hash"),
                json.dumps(value, ensure_ascii=False, sort_keys=True),
            ),
        )

    @staticmethod
    def _insert_events(
        connection: sqlite3.Connection,
        relative: str,
        path: Path,
    ) -> None:
        with path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise TypeError(f"expected an object at {path}:{line_number}")
                connection.execute(
                    """
                    INSERT INTO events(
                        path, line_number, event_id, event_type, payload_json
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        relative,
                        line_number,
                        value.get("id"),
                        value.get("event_type", value.get("type")),
                        json.dumps(value, ensure_ascii=False, sort_keys=True),
                    ),
                )

    @staticmethod
    def _remove_temporary_database(temporary: Path) -> None:
        temporary.unlink(missing_ok=True)
        for suffix in ("-journal", "-wal", "-shm"):
            temporary.with_name(temporary.name + suffix).unlink(missing_ok=True)


def _resolves_inside(path: Path, resolved_root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(resolved_root)
    except OSError:
        return False


def _authoritative_record_type(relative: str) -> str | None:
    parts = PurePosixPath(relative).parts
    suffix = PurePosixPath(relative).suffix.lower()
    if suffix not in {".yaml", ".yml", ".json"}:
        return None
    if relative == "ai4sota.project.yaml":
        return "project"
    if relative == "tasks/active.yaml":
        return "task"
    if (
        len(parts) >= 4
        and parts[0] == "modules"
        and parts[1] in {"data", "method", "evaluation"}
        and parts[2] == "current"
    ):
        return f"{parts[1]}_module"
    if len(parts) >= 3 and parts[:2] == ("data", "fingerprints"):
        return "data_fingerprint"
    if len(parts) >= 3 and parts[:2] == ("data", "splits"):
        return "split"
    if len(parts) >= 2 and parts[0] == "decisions":
        return "decision"
    if len(parts) >= 2 and parts[0] == "references":
        return "reference"
    if len(parts) == 3 and parts[0] == "runs" and parts[2] == "manifest.yaml":
        return "run"
    if (
        len(parts) == 3
        and parts[0] == "research-commits"
        and parts[2] in {"manifest.yaml", "artifact-index.json"}
    ):
        return "research_commit"
    return None


def _is_authoritative_event(relative: str) -> bool:
    parts = PurePosixPath(relative).parts
    return relative == "conversations/events.jsonl" or (
        len(parts) == 3 and parts[0] == "runs" and parts[2] == "events.jsonl"
    )
