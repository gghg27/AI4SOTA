"""Disposable SQLite projection of authoritative project records."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
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
        for path in sorted(root.rglob("*")):
            if not path.is_file() or self._is_ignored(path, root):
                continue
            relative = path.relative_to(root).as_posix()
            if path.suffix.lower() == ".jsonl":
                self._insert_events(connection, relative, path)
            elif path.suffix.lower() in {".yaml", ".yml", ".json"}:
                value = self._load_mapping(path)
                if value is not None:
                    self._insert_record(connection, relative, value)

    @staticmethod
    def _is_ignored(path: Path, root: Path) -> bool:
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] in {".ai4sota", ".git"}:
            return True
        return path.suffix.lower() in {".bak", ".tmp"}

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
                _record_type(relative),
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


def _record_type(relative: str) -> str:
    parts = Path(relative).parts
    if relative == "ai4sota.project.yaml":
        return "project"
    if parts and parts[0] == "runs" and Path(relative).name == "manifest.yaml":
        return "run"
    if parts and parts[0] == "research-commits":
        return "research_commit"
    if parts and parts[0] == "decisions":
        return "decision"
    if parts and parts[0] == "tasks":
        return "task"
    if len(parts) >= 2 and parts[0] == "modules":
        return f"{parts[1]}_module"
    return "manifest"
