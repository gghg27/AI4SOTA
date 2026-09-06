from __future__ import annotations

import contextlib
import io
import json
import random
import re
import sys
import traceback
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ValidationError

from .contracts import EvaluationResult, PredictionBundle
from .domain import (
    DataModuleSpec,
    DatasetSourceSpec,
    EvaluationSpec,
    MethodSpec,
    ModuleKind,
    RunManifest,
    SplitManifest,
)
from .files import (
    PathValidationError,
    StableReadError,
    resolve_bundle_file,
    resolve_file_location,
    stable_read_file,
)
from .io_utils import read_json, read_yaml, utc_now, write_json
from .loading import load_project_module, require_callable
from .project import resolve_project
from .projects import ProjectLayout
from .runs import (
    RunPersistenceError,
    RunRepository,
    prepare_run,
    verify_run_integrity,
)
from .storage import ManifestStore, atomic_write_bytes, canonical_manifest_hash
from .validation import validate_project

__all__ = [
    "execute_run",
    "load_history",
    "load_snapshot_dataset",
    "prepare_run",
    "run_project",
]

_ENTRYPOINT_PATTERN = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*"
)


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
    base = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    candidate = base
    suffix = 1
    while (project_dir / "runs" / candidate).exists():
        candidate = f"{base}_{suffix:02d}"
        suffix += 1
    return candidate


def load_snapshot_dataset(snapshot_root: Path) -> Any:
    """Load and validate Data output only from a captured snapshot tree."""
    snapshot = Path(snapshot_root)
    data = ManifestStore().read(
        snapshot / "modules" / "data" / "current" / "module.yaml",
        DataModuleSpec,
    )
    config = _module_config(snapshot, ModuleKind.DATA)
    load_dataset = _snapshot_callable(
        snapshot, ModuleKind.DATA, data.entrypoint, "data"
    )
    dataset = load_dataset(project_dir=snapshot, config=config)
    from .contracts import CanonicalDataset

    if not isinstance(dataset, CanonicalDataset):
        raise TypeError("data entrypoint must return CanonicalDataset")
    dataset.validate()
    return dataset


def execute_run(project: ProjectLayout, run_id: str) -> RunManifest:
    """Execute a prepared Run exclusively from its immutable snapshot."""
    repository = RunRepository(project)
    run_dir = repository.run_dir(run_id)
    logs = io.StringIO()
    try:
        verify_run_integrity(run_dir)
        repository.transition_run(run_id, "queued", "preparing")
        running = repository.transition_run(run_id, "preparing", "running")
        with contextlib.redirect_stdout(logs), contextlib.redirect_stderr(logs):
            snapshot = run_dir / "snapshot"
            _verify_snapshot_dataset_fingerprint(snapshot, project.root, running)
            with _sealed_seed(running.seed):
                dataset = load_snapshot_dataset(snapshot)
                dataset = _apply_split(snapshot, running, dataset)
                method = ManifestStore().read(
                    snapshot
                    / "modules"
                    / "method"
                    / "current"
                    / "module.yaml",
                    MethodSpec,
                )
                evaluation = ManifestStore().read(
                    snapshot
                    / "modules"
                    / "evaluation"
                    / "current"
                    / "module.yaml",
                    EvaluationSpec,
                )
                fit_predict = _snapshot_callable(
                    snapshot, ModuleKind.METHOD, method.entrypoint, "method"
                )
                evaluate = _snapshot_callable(
                    snapshot,
                    ModuleKind.EVALUATION,
                    evaluation.entrypoint,
                    "evaluation",
                )
                predictions = fit_predict(
                    dataset=dataset,
                    config=_module_config(snapshot, ModuleKind.METHOD),
                )
                if not isinstance(predictions, PredictionBundle):
                    raise TypeError("method entrypoint must return PredictionBundle")
                predictions.validate()
                result = evaluate(
                    dataset=dataset,
                    predictions=predictions,
                    config=_module_config(snapshot, ModuleKind.EVALUATION),
                )
                if not isinstance(result, EvaluationResult):
                    raise TypeError(
                        "evaluation entrypoint must return EvaluationResult"
                    )
                result.validate()

            atomic_write_bytes(
                run_dir / "metrics" / "metrics.json",
                _json_bytes(result.metrics),
            )
            if result.tables:
                atomic_write_bytes(
                    run_dir / "metrics" / "tables.json",
                    _json_bytes(result.tables),
                )
            repository.record_metrics(run_id, result.metrics)
            atomic_write_bytes(
                run_dir / "logs" / "worker.log",
                logs.getvalue().encode("utf-8"),
            )
            try:
                completed = repository.transition_run(
                    run_id, "running", "succeeded"
                )
            except RunPersistenceError:
                completed = repository.transition_run(
                    run_id, "running", "succeeded"
                )
        return completed
    except Exception as error:
        traceback.print_exc(file=logs)
        bookkeeping_errors: list[str] = []
        try:
            atomic_write_bytes(
                run_dir / "logs" / "worker.log",
                logs.getvalue().encode("utf-8"),
            )
        except Exception as bookkeeping_error:  # noqa: BLE001
            bookkeeping_errors.append(f"worker log: {bookkeeping_error}")
        try:
            repository.fail_run(run_id)
        except Exception as bookkeeping_error:  # noqa: BLE001
            bookkeeping_errors.append(f"failure state: {bookkeeping_error}")
        message = f"run failed; details saved in {run_dir}"
        if bookkeeping_errors:
            message += "; failure bookkeeping incomplete: " + "; ".join(
                bookkeeping_errors
            )
        raise RuntimeError(message) from error


@contextlib.contextmanager
def _sealed_seed(seed: int | None):
    python_state = random.getstate()
    numpy_state = np.random.get_state()
    try:
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed % (2**32))
        yield
    finally:
        random.setstate(python_state)
        np.random.set_state(numpy_state)


def _snapshot_callable(
    snapshot: Path,
    kind: ModuleKind,
    entrypoint: str,
    role: str,
) -> Callable[..., Any]:
    parts = entrypoint.split(":")
    if (
        len(parts) != 2
        or _ENTRYPOINT_PATTERN.fullmatch(parts[0]) is None
        or _ENTRYPOINT_PATTERN.fullmatch(parts[1]) is None
    ):
        raise ValueError(f"invalid {role} entrypoint: {entrypoint!r}")
    relative = Path(*parts[0].split(".")).with_suffix(".py")
    module_root = snapshot / "modules" / kind.value / "current"
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        module = load_project_module(module_root, relative.as_posix(), role)
    finally:
        sys.dont_write_bytecode = previous
    return require_callable(module, parts[1], role)


def _module_config(snapshot: Path, kind: ModuleKind) -> dict[str, Any]:
    path = snapshot / "modules" / kind.value / "current" / "config.yaml"
    if not path.exists():
        return {}
    return read_yaml(path)


def _apply_split(snapshot: Path, run: RunManifest, dataset: Any) -> Any:
    from .contracts import CanonicalDataset

    split = _load_selected_manifest(
        snapshot / "data" / "splits",
        SplitManifest,
        run.split_manifest_hash,
        "split manifest",
    )
    assignments = {member.sample_id: member.partition for member in split.members}
    sample_ids = tuple(str(value) for value in np.asarray(dataset.sample_ids))
    if set(sample_ids) != set(assignments) or len(sample_ids) != len(assignments):
        raise ValueError("Run split members do not match the loaded dataset")
    metadata = dict(dataset.metadata)
    metadata["split"] = np.asarray(
        [assignments[sample_id] for sample_id in sample_ids]
    )
    result = CanonicalDataset(
        sample_ids=np.asarray(dataset.sample_ids),
        inputs=dict(dataset.inputs),
        targets=dict(dataset.targets),
        metadata=metadata,
        schema=dict(dataset.schema),
    )
    result.validate()
    return result


def _verify_snapshot_dataset_fingerprint(
    snapshot: Path, project_root: Path, run: RunManifest
) -> None:
    data_root = snapshot / "modules" / "data" / "current"
    data = ManifestStore().read(data_root / "module.yaml", DataModuleSpec)
    source = _load_manifest_reference(
        data_root, DatasetSourceSpec, data.source, "dataset source"
    )
    if len(source.locations) != 1:
        raise ValueError("Run requires exactly one external dataset location")
    location = resolve_file_location(project_root, source.locations[0])
    actual = stable_read_file(location).sha256
    if actual != run.data_fingerprint_hash:
        raise ValueError(
            f"external dataset fingerprint changed: expected "
            f"{run.data_fingerprint_hash}, found {actual}"
        )


def _load_manifest_reference(
    root: Path,
    model: type[BaseModel],
    reference: str,
    label: str,
) -> Any:
    try:
        path = resolve_bundle_file(root, reference)
        document = yaml.safe_load(stable_read_file(path).data.decode("utf-8"))
        value = model.model_validate(document)
    except (
        OSError,
        PathValidationError,
        StableReadError,
        UnicodeError,
        ValidationError,
        yaml.YAMLError,
    ) as error:
        raise ValueError(f"invalid referenced {label}: {reference!r}") from error
    if getattr(value, "content_hash", None) != canonical_manifest_hash(value):
        raise ValueError(f"referenced {label} content hash is not canonical")
    return value


def _load_selected_manifest(
    root: Path,
    model: type[BaseModel],
    expected_hash: str,
    label: str,
) -> Any:
    matches: list[BaseModel] = []
    for path in sorted(root.glob("*.yaml")):
        try:
            value = ManifestStore().read(path, model)
        except ValidationError:
            continue
        if getattr(value, "content_hash", None) == expected_hash:
            matches.append(value)
    if len(matches) != 1:
        raise ValueError(f"{label} hash matched {len(matches)} manifests")
    return matches[0]


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            default=_json_default,
        )
        + "\n"
    ).encode("utf-8")


def _json_default(value: object) -> object:
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"cannot serialize {type(value).__name__}")
