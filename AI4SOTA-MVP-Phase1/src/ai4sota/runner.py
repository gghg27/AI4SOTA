from __future__ import annotations

import contextlib
import io
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import EvaluationResult, PredictionBundle
from .io_utils import read_json, read_yaml, utc_now, write_json
from .loading import load_project_module, require_callable
from .project import resolve_project
from .validation import validate_project


def run_project(project_path: Path, note: str = "") -> dict[str, Any]:
    project_dir = resolve_project(project_path)
    run_id = _new_run_id(project_dir)
    run_dir = project_dir / "runs" / run_id
    run_dir.mkdir(parents=True)
    started_at = utc_now()
    logs = io.StringIO()
    report: dict[str, Any] | None = None

    try:
        with contextlib.redirect_stdout(logs), contextlib.redirect_stderr(logs):
            dataset, report = validate_project(project_dir)
            write_json(run_dir / "validation.json", report)

            method_module = load_project_module(project_dir, "method/model.py", "method")
            evaluation_module = load_project_module(
                project_dir, "evaluation/evaluator.py", "evaluation"
            )
            fit_predict = require_callable(method_module, "fit_predict", "method")
            evaluate = require_callable(evaluation_module, "evaluate", "evaluation")

            method_config = read_yaml(project_dir / "method" / "method.yaml")
            evaluation_config = read_yaml(
                project_dir / "evaluation" / "evaluation.yaml"
            )
            predictions = fit_predict(dataset=dataset, config=method_config)
            if not isinstance(predictions, PredictionBundle):
                raise TypeError("method.fit_predict must return PredictionBundle")
            prediction_report = predictions.validate()

            result = evaluate(
                dataset=dataset,
                predictions=predictions,
                config=evaluation_config,
            )
            if not isinstance(result, EvaluationResult):
                raise TypeError("evaluation.evaluate must return EvaluationResult")
            evaluation_report = result.validate()
            write_json(run_dir / "metrics.json", result.metrics)
            if result.tables:
                write_json(run_dir / "tables.json", result.tables)

            print(f"run_id: {run_id}")
            for name, value in result.metrics.items():
                print(f"{name}: {value:.6f}")

        run_record = {
            "run_id": run_id,
            "status": "success",
            "note": note,
            "started_at": started_at,
            "finished_at": utc_now(),
            "data_fingerprint": report["data_fingerprint"] if report else None,
            "metrics": result.metrics,
            "prediction_report": prediction_report,
            "evaluation_report": evaluation_report,
            "source_revision": "unversioned-phase1",
        }
        write_json(run_dir / "run.json", run_record)
        (run_dir / "logs.txt").write_text(logs.getvalue(), encoding="utf-8")
        return run_record
    except Exception as exc:
        traceback.print_exc(file=logs)
        run_record = {
            "run_id": run_id,
            "status": "failed",
            "note": note,
            "started_at": started_at,
            "finished_at": utc_now(),
            "error": f"{type(exc).__name__}: {exc}",
            "data_fingerprint": report.get("data_fingerprint") if report else None,
            "source_revision": "unversioned-phase1",
        }
        write_json(run_dir / "run.json", run_record)
        (run_dir / "logs.txt").write_text(logs.getvalue(), encoding="utf-8")
        raise RuntimeError(f"run failed; details saved in {run_dir}") from exc


def load_history(project_path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    project_dir = resolve_project(project_path)
    records: list[dict[str, Any]] = []
    for path in sorted((project_dir / "runs").glob("*/run.json"), reverse=True):
        records.append(read_json(path))
        if limit is not None and len(records) >= limit:
            break
    return records


def _new_run_id(project_dir: Path) -> str:
    base = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    candidate = base
    suffix = 1
    while (project_dir / "runs" / candidate).exists():
        candidate = f"{base}_{suffix:02d}"
        suffix += 1
    return candidate

