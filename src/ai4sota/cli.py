from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .project import create_project
from .runner import load_history, run_project
from .validation import validate_project


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai4sota",
        description="AI4SOTA MVP phase 1 command-line workbench",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    new_parser = subparsers.add_parser("new", help="create a new three-layer project")
    new_parser.add_argument("name", help="project directory name")
    new_parser.add_argument("--output", type=Path, required=True, help="parent directory")
    source = new_parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--data", type=Path, help="existing .npz dataset")
    source.add_argument("--demo", action="store_true", help="create demo .npz data")

    validate_parser = subparsers.add_parser("validate", help="validate project and data")
    validate_parser.add_argument("project", type=Path)

    run_parser = subparsers.add_parser("run", help="run data, method and evaluation")
    run_parser.add_argument("project", type=Path)
    run_parser.add_argument("--note", default="", help="human-readable experiment note")

    history_parser = subparsers.add_parser("history", help="list previous runs")
    history_parser.add_argument("project", type=Path)
    history_parser.add_argument("--limit", type=int, default=None)
    history_parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "new":
            created = create_project(
                args.name,
                args.output,
                data_path=args.data,
                demo=args.demo,
            )
            print(f"created project: {created.project_dir}")
            print(f"data source: {created.data_path}")
            print(f"next: ai4sota validate \"{created.project_dir}\"")
            return 0

        if args.command == "validate":
            _, report = validate_project(args.project)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0

        if args.command == "run":
            record = run_project(args.project, note=args.note)
            print(f"run completed: {record['run_id']}")
            for name, value in record["metrics"].items():
                print(f"  {name}: {value:.6f}")
            return 0

        if args.command == "history":
            if args.limit is not None and args.limit < 1:
                raise ValueError("--limit must be at least 1")
            records = load_history(args.project, limit=args.limit)
            if args.as_json:
                print(json.dumps(records, ensure_ascii=False, indent=2))
            else:
                _print_history(records)
            return 0
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 2


def _print_history(records: list[dict]) -> None:
    if not records:
        print("no runs yet")
        return
    print("RUN ID              STATUS   METRICS                       NOTE")
    print("-" * 78)
    for record in records:
        metrics = ", ".join(
            f"{name}={float(value):.4f}"
            for name, value in record.get("metrics", {}).items()
        )
        note = str(record.get("note", "")).replace("\n", " ")
        print(f"{record['run_id']:<19} {record['status']:<8} {metrics:<29} {note}")
