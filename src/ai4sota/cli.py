from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from .history import create_research_commit
from .project import create_project
from .projects import ProjectLayout
from .runner import load_history, run_project
from .runs import RunRepository, compare_runs, verify_run_integrity
from .storage import ManifestStore
from .validation import validate_project
from .workflows import (
    ApprovalValidationError,
    ExperimentApproval,
    bind_experiment_approval,
    compile_project,
    execute_approved_run,
    prepare_experiment,
)


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

    compile_parser = subparsers.add_parser(
        "compile", help="compile active scientific module compatibility"
    )
    compile_parser.add_argument("project", type=Path)
    compile_parser.add_argument("--json", action="store_true", dest="as_json")

    prepare_parser = subparsers.add_parser(
        "prepare-run", help="materialize an exact experiment approval candidate"
    )
    prepare_parser.add_argument("project", type=Path)
    prepare_parser.add_argument("--approval-id", required=True)
    prepare_parser.add_argument("--output", type=Path, required=True)
    prepare_parser.add_argument("--json", action="store_true", dest="as_json")

    approved_parser = subparsers.add_parser(
        "run-approved", help="execute an exact approved experiment snapshot"
    )
    approved_parser.add_argument("project", type=Path)
    approved_parser.add_argument("approval", type=Path)
    approved_parser.add_argument("--approval-hash", required=True)
    approved_parser.add_argument("--json", action="store_true", dest="as_json")

    compare_parser = subparsers.add_parser(
        "compare", help="compare completed immutable Runs"
    )
    compare_parser.add_argument("project", type=Path)
    compare_parser.add_argument("run_ids", nargs="+")
    compare_parser.add_argument("--json", action="store_true", dest="as_json")

    commit_parser = subparsers.add_parser(
        "research-commit", help="promote exact Run snapshot evidence"
    )
    commit_parser.add_argument("project", type=Path)
    commit_parser.add_argument("draft", type=Path)
    commit_parser.add_argument("run_ids", nargs="+")
    commit_parser.add_argument("--json", action="store_true", dest="as_json")
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

        if args.command == "compile":
            compatibility_report = compile_project(_project_layout(args.project))
            if args.as_json:
                _print_model_json(compatibility_report)
            else:
                print(f"compatibility: {compatibility_report.state.value}")
                for finding in compatibility_report.findings:
                    print(f"  {finding.field}: {finding.state.value}")
            return 0

        if args.command == "prepare-run":
            project = _project_layout(args.project)
            prepared = prepare_experiment(project)
            approval = bind_experiment_approval(prepared, args.approval_id)
            ManifestStore().write(args.output, approval)
            if args.as_json:
                _print_model_json(approval)
            else:
                print(f"approval candidate: {args.output}")
                print(f"approval hash: {approval.approval_hash}")
            return 0

        if args.command == "run-approved":
            approval = ManifestStore().read(args.approval, ExperimentApproval)
            if args.approval_hash != approval.approval_hash:
                raise ApprovalValidationError(
                    "approval hash does not match the approval candidate"
                )
            run = execute_approved_run(
                _project_layout(args.project), approval
            )
            if args.as_json:
                _print_model_json(run)
            else:
                print(f"run completed: {run.id}")
                for name, value in run.metrics.items():
                    print(f"  {name}: {value:.6f}")
            return 0

        if args.command == "compare":
            if len(args.run_ids) < 2:
                raise ValueError("at least two Run ids are required for comparison")
            repository = RunRepository(_project_layout(args.project))
            comparison = compare_runs(
                [
                    verify_run_integrity(repository.run_dir(run_id))
                    for run_id in args.run_ids
                ]
            )
            if args.as_json:
                _print_model_json(comparison)
            else:
                print(f"comparability: {comparison.state.value}")
                if comparison.blocking_fields:
                    print(f"blocking fields: {', '.join(comparison.blocking_fields)}")
                if comparison.caveat_fields:
                    print(f"caveat fields: {', '.join(comparison.caveat_fields)}")
            return 0

        if args.command == "research-commit":
            project = _project_layout(args.project)
            repository = RunRepository(project)
            if len(args.run_ids) > 1:
                compare_runs(
                    [repository.load(run_id) for run_id in args.run_ids]
                )
            commit = create_research_commit(
                project, _read_mapping(args.draft), args.run_ids
            )
            if args.as_json:
                _print_model_json(commit)
            else:
                print(f"research commit: {commit.id}")
                print(f"git sha: {commit.git_sha}")
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


def _project_layout(path: Path) -> ProjectLayout:
    root = path.expanduser().resolve()
    if not (root / "ai4sota.project.yaml").is_file():
        raise FileNotFoundError(f"not an AI4SOTA v1 project: {root}")
    return ProjectLayout(root)


def _print_model_json(value: object) -> None:
    document = value.model_dump(mode="json")  # type: ignore[attr-defined]
    print(json.dumps(document, ensure_ascii=False, indent=2))


def _read_mapping(path: Path) -> dict[str, object]:
    suffix = path.suffix.lower()
    with path.open("r", encoding="utf-8") as stream:
        if suffix == ".json":
            value = json.load(stream)
        elif suffix in {".yaml", ".yml"}:
            value = yaml.safe_load(stream)
        else:
            raise ValueError(f"unsupported draft format: {path.suffix}")
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("research commit draft must be a string-keyed mapping")
    return value
