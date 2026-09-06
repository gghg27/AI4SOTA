from __future__ import annotations

import hashlib
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
from ai4sota.storage import ManifestStore, ResearchIndex, canonical_manifest_hash
from ai4sota.storage.migrations import (
    apply_schema_migration,
    plan_schema_migration,
)

CONTENT_HASH = "sha256:" + "b" * 64
PHASE1_TASK_CONTRACT_HASH = (
    "sha256:bdc75a386dfae7886c01e32d6bb88a04"
    "e165901ca15ff570375db1b36d84a324"
)
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


def migrate_phase1_manifest(
    tmp_path: Path,
    relative_path: str,
    original: bytes,
    model: type[BaseModel],
) -> BaseModel:
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(original)
    plan = plan_schema_migration(path, target="ai4sota/v1")
    apply_schema_migration(plan, expected_hash=plan.original_hash)
    return ManifestStore().read(path, model)


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


def query_indexed_paths(path: Path, table: str) -> list[str]:
    if table not in {"records", "events"}:
        raise ValueError(f"unexpected index table: {table}")
    with sqlite3.connect(path) as connection:
        rows = connection.execute(f"SELECT DISTINCT path FROM {table}").fetchall()
    return sorted(row[0] for row in rows)


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


def test_index_rebuild_ignores_records_outside_the_authoritative_allowlist(
    project_with_run: ProjectLayout,
) -> None:
    """Catches recursive extension matching indexing unrelated project files."""
    unrelated_yaml = project_with_run.root / "notes.yaml"
    unrelated_yaml.write_text("id: unrelated-yaml\n", encoding="utf-8")
    unrelated_jsonl = project_with_run.events_file.parent / "scratch.jsonl"
    unrelated_jsonl.write_text('{"id":"unrelated-event"}\n', encoding="utf-8")

    ResearchIndex(project_with_run.index_file).rebuild(project_with_run)

    assert "notes.yaml" not in query_indexed_paths(
        project_with_run.index_file, "records"
    )
    assert "conversations/scratch.jsonl" not in query_indexed_paths(
        project_with_run.index_file, "events"
    )
    assert query_run_ids(project_with_run.index_file) == ["run-001"]


def test_index_rebuild_ignores_authoritative_symlink_that_resolves_outside_project(
    project_with_run: ProjectLayout,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches an allowlisted symlink reading a manifest outside the project."""
    outside = tmp_path / "outside.yaml"
    outside.write_text("id: escaped-record\n", encoding="utf-8")
    link = project_with_run.decisions_dir / "escaped.yaml"
    try:
        link.symlink_to(outside)
    except OSError:
        link.write_text("id: escaped-record\n", encoding="utf-8")
        original_resolve = Path.resolve

        def resolve_with_escape(path: Path, strict: bool = False) -> Path:
            if path == link:
                return outside
            return original_resolve(path, strict=strict)

        monkeypatch.setattr(Path, "resolve", resolve_with_escape)

    ResearchIndex(project_with_run.index_file).rebuild(project_with_run)

    assert "decisions/escaped.yaml" not in query_indexed_paths(
        project_with_run.index_file, "records"
    )


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
    persisted = ManifestStore().read(path, model)
    assert persisted.api_version == "ai4sota/v1"
    assert persisted.content_hash == canonical_manifest_hash(persisted)


def test_phase1_module_migration_preserves_a_cross_module_field_contract(
    tmp_path: Path,
) -> None:
    """Catches raw storage keys replacing canonical cross-module field names."""
    data = migrate_phase1_manifest(
        tmp_path, "data/dataset.yaml", PHASE1_DATA_BYTES, DataModuleSpec
    )
    method = migrate_phase1_manifest(
        tmp_path, "method/method.yaml", PHASE1_METHOD_BYTES, MethodSpec
    )
    evaluation = migrate_phase1_manifest(
        tmp_path,
        "evaluation/evaluation.yaml",
        PHASE1_EVALUATION_BYTES,
        EvaluationSpec,
    )
    assert isinstance(data, DataModuleSpec)
    assert isinstance(method, MethodSpec)
    assert isinstance(evaluation, EvaluationSpec)

    assert data.canonical_outputs == ("features", "label", "split", "sample_ids")
    method_inputs = {str(value) for value in method.input_requirements.values()}
    evaluation_inputs = set(
        evaluation.required_predictions + evaluation.required_metadata
    )
    assert method_inputs <= set(data.canonical_outputs)
    assert evaluation_inputs <= set(data.canonical_outputs)


@pytest.mark.parametrize(
    ("relative_path", "original", "model"),
    [
        ("data/dataset.yaml", PHASE1_DATA_BYTES, DataModuleSpec),
        ("method/method.yaml", PHASE1_METHOD_BYTES, MethodSpec),
        ("evaluation/evaluation.yaml", PHASE1_EVALUATION_BYTES, EvaluationSpec),
    ],
)
def test_phase1_module_migration_separates_content_hash_from_legacy_provenance(
    tmp_path: Path,
    relative_path: str,
    original: bytes,
    model: type[BaseModel],
) -> None:
    """Catches a legacy file digest being mislabeled as migrated content."""
    path = tmp_path / relative_path
    migrated = migrate_phase1_manifest(tmp_path, relative_path, original, model)
    document = yaml.safe_load(path.read_bytes())
    legacy_hash = f"sha256:{hashlib.sha256(original).hexdigest()}"
    assert isinstance(migrated, (DataModuleSpec, MethodSpec, EvaluationSpec))

    assert document["content_hash"] == canonical_manifest_hash(document)
    assert document["content_hash"] != legacy_hash
    assert migrated.origin.based_on == legacy_hash


def test_phase1_data_and_evaluation_share_the_default_task_contract_hash(
    tmp_path: Path,
) -> None:
    """Catches cross-module task references being derived from unrelated files."""
    data = migrate_phase1_manifest(
        tmp_path, "data/dataset.yaml", PHASE1_DATA_BYTES, DataModuleSpec
    )
    evaluation = migrate_phase1_manifest(
        tmp_path,
        "evaluation/evaluation.yaml",
        PHASE1_EVALUATION_BYTES,
        EvaluationSpec,
    )
    task_document = yaml.safe_load(
        (Path(__file__).parents[2] / "src/ai4sota/templates/v1/tasks/active.yaml")
        .read_bytes()
    )
    assert isinstance(data, DataModuleSpec)
    assert isinstance(evaluation, EvaluationSpec)

    assert task_document["content_hash"] == PHASE1_TASK_CONTRACT_HASH
    assert canonical_manifest_hash(task_document) == PHASE1_TASK_CONTRACT_HASH
    assert data.task_contract_hash == PHASE1_TASK_CONTRACT_HASH
    assert evaluation.task_contract_hash == PHASE1_TASK_CONTRACT_HASH
    assert evaluation.protocol.evaluate_split == "test"


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


@pytest.mark.parametrize("winner_matches", [True, False])
def test_schema_migration_exclusively_creates_and_verifies_a_racing_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    winner_matches: bool,
) -> None:
    """Catches migration overwriting a backup won by another writer."""
    path = tmp_path / "method" / "method.yaml"
    path.parent.mkdir(parents=True)
    path.write_bytes(PHASE1_METHOD_BYTES)
    plan = plan_schema_migration(path, target="ai4sota/v1")
    digest = plan.original_hash.removeprefix("sha256:")
    backup = path.with_name(f"{path.name}.{digest}.bak")
    competing_bytes = plan.original_bytes if winner_matches else b"other writer"
    original_open = Path.open
    raced = False

    def open_after_competitor(
        target: Path, mode: str = "r", *args: object, **kwargs: object
    ):
        nonlocal raced
        if target == backup and mode == "xb" and not raced:
            raced = True
            with original_open(target, "wb") as stream:
                stream.write(competing_bytes)
        return original_open(target, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_after_competitor)

    if winner_matches:
        assert apply_schema_migration(plan, plan.original_hash) == backup
        assert yaml.safe_load(path.read_bytes())["api_version"] == "ai4sota/v1"
    else:
        with pytest.raises(FileExistsError, match="unexpected content"):
            apply_schema_migration(plan, plan.original_hash)
        assert path.read_bytes() == PHASE1_METHOD_BYTES
    assert raced
    assert backup.read_bytes() == competing_bytes
