from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel

from ai4sota.domain import (
    DataModuleSpec,
    EvaluationSpec,
    MethodSpec,
    ProjectSpec,
    RunManifest,
)
from ai4sota.projects import ProjectLayout
from ai4sota.storage import ManifestStore, ResearchIndex
from ai4sota.storage.migrations import (
    apply_schema_migration,
    plan_schema_migration,
)

CONTENT_HASH = "sha256:" + "b" * 64
PHASE1_TEMPLATES = (
    Path(__file__).parents[2]
    / "AI4SOTA-MVP-Phase1"
    / "src"
    / "ai4sota"
    / "templates"
    / "project"
)
PHASE1_PROJECT_BYTES = (PHASE1_TEMPLATES / "project.yaml").read_bytes()
PHASE1_DATA_BYTES = (PHASE1_TEMPLATES / "data" / "dataset.yaml").read_bytes()
PHASE1_METHOD_BYTES = (PHASE1_TEMPLATES / "method" / "method.yaml").read_bytes()
PHASE1_EVALUATION_BYTES = (
    PHASE1_TEMPLATES / "evaluation" / "evaluation.yaml"
).read_bytes()


@pytest.fixture
def project_with_run(tmp_path: Path) -> ProjectLayout:
    layout = ProjectLayout.create(tmp_path, "seed-emotion")
    run = RunManifest(
        id="run-001",
        content_hash=CONTENT_HASH,
        project_id="project/seed-emotion",
        experiment_hash=CONTENT_HASH,
        snapshot_hash=CONTENT_HASH,
        data_fingerprint_hash=CONTENT_HASH,
        task_contract_hash=CONTENT_HASH,
        split_manifest_hash=CONTENT_HASH,
        evaluation_protocol_hash=CONTENT_HASH,
        metric_implementation_hash=CONTENT_HASH,
        integrity_state="verified",
        status="succeeded",
        metrics={"accuracy": 0.75},
    )
    ManifestStore().write(layout.runs_dir / "run-001" / "manifest.yaml", run)
    return layout


def query_run_ids(path: Path) -> list[str]:
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT record_id FROM records WHERE record_type = 'run' ORDER BY record_id"
        ).fetchall()
    return [row[0] for row in rows]


def test_deleted_index_rebuilds_from_authoritative_files(
    project_with_run: ProjectLayout,
) -> None:
    """Catches a disposable index that cannot recover persisted Run manifests."""
    project_with_run.index_file.unlink(missing_ok=True)

    ResearchIndex(project_with_run.index_file).rebuild(project_with_run)

    assert query_run_ids(project_with_run.index_file) == ["run-001"]


def test_index_rebuild_never_executes_project_code(
    project_with_run: ProjectLayout,
) -> None:
    """Catches index discovery importing executable files from the project."""
    marker = project_with_run.root / "executed.txt"
    code = project_with_run.module_dir("method") / "model.py"
    code.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n",
        encoding="utf-8",
    )

    ResearchIndex(project_with_run.index_file).rebuild(project_with_run)

    assert not marker.exists()


@pytest.mark.parametrize(
    ("relative_path", "original", "model"),
    [
        ("project.yaml", PHASE1_PROJECT_BYTES, ProjectSpec),
        ("data/dataset.yaml", PHASE1_DATA_BYTES, DataModuleSpec),
        ("method/method.yaml", PHASE1_METHOD_BYTES, MethodSpec),
        ("evaluation/evaluation.yaml", PHASE1_EVALUATION_BYTES, EvaluationSpec),
    ],
)
def test_phase1_migration_registry_produces_valid_v1_manifests(
    tmp_path: Path,
    relative_path: str,
    original: bytes,
    model: type[BaseModel],
) -> None:
    """Catches a missing or structurally invalid explicit Phase 1 migration."""
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(original)

    plan = plan_schema_migration(path, target="ai4sota/v1")
    backup = apply_schema_migration(plan, expected_hash=plan.original_hash)

    assert plan.diff
    assert backup.read_bytes() == original
    assert ManifestStore().read(path, model).api_version == "ai4sota/v1"


def test_schema_migration_requires_preview_and_preserves_original(
    tmp_path: Path,
) -> None:
    """Catches migration replacement without a reviewable diff and exact backup."""
    path = tmp_path / "data" / "dataset.yaml"
    path.parent.mkdir(parents=True)
    path.write_bytes(PHASE1_DATA_BYTES)

    plan = plan_schema_migration(path, target="ai4sota/v1")
    backup = apply_schema_migration(plan, expected_hash=plan.original_hash)

    assert plan.diff
    assert backup.read_bytes() == PHASE1_DATA_BYTES
    assert yaml.safe_load(path.read_bytes())["api_version"] == "ai4sota/v1"


def test_schema_migration_rejects_a_stale_plan_without_overwriting(
    tmp_path: Path,
) -> None:
    """Catches a preview applying after another editor changes the source file."""
    path = tmp_path / "method" / "method.yaml"
    path.parent.mkdir(parents=True)
    path.write_bytes(PHASE1_METHOD_BYTES)
    plan = plan_schema_migration(path, target="ai4sota/v1")
    changed = PHASE1_METHOD_BYTES + b"notes: changed after preview\n"
    path.write_bytes(changed)

    with pytest.raises(ValueError, match="hash"):
        apply_schema_migration(plan, expected_hash=plan.original_hash)

    assert path.read_bytes() == changed
    assert list(path.parent.glob("*.bak")) == []
