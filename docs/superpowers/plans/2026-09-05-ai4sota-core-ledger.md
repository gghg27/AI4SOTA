# AI4SOTA Core and Research Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a headless, tested AI4SOTA core that owns versioned scientific contracts, project storage, compatibility decisions, immutable Runs, deterministic comparison, Research Commits, and a local module library.

**Architecture:** Promote the Phase 1 Python code into the workspace root without deleting the legacy directory, then replace loose dictionaries with Pydantic v2 domain models and focused services. Human-readable YAML/JSON/JSONL files are authoritative; SQLite and later APIs remain projections over these files.

**Tech Stack:** Python 3.11+, Pydantic 2, NumPy, PyYAML, pytest, Ruff, mypy, Git CLI

**Spec:** `docs/superpowers/specs/2026-09-05-ai4sota-desktop-agent-design.md`

## Global Constraints

- Preserve `AI4SOTA-MVP-Phase1/` as a read-only migration reference until the root regression suite passes.
- Use Data, Method, and Evaluation as the only module kinds; `TaskContract` is project-level.
- Manifests and append-only events are authoritative; every SQLite index must be rebuildable.
- Never run from the live workspace; every Run uses an immutable snapshot.
- Compatibility and comparability are deterministic and cannot be overridden by an LLM.
- Do not add FastAPI, provider, literature, or desktop code in this plan.
- Each task ends with the focused tests, the full current suite, and one Conventional Commit.

---

### Task 1: Root Python Package and Phase 1 Regression Baseline

**Files:**
- Create: `pyproject.toml`
- Create: `src/ai4sota/__init__.py`
- Create: `src/ai4sota/contracts.py`
- Create: `src/ai4sota/io_utils.py`
- Create: `src/ai4sota/loading.py`
- Create: `src/ai4sota/project.py`
- Create: `src/ai4sota/validation.py`
- Create: `src/ai4sota/runner.py`
- Create: `src/ai4sota/cli.py`
- Create: `src/ai4sota/__main__.py`
- Create: `src/ai4sota/templates/project/**`
- Create: `tests/test_phase1_regression.py`

**Interfaces:**
- Consumes: Phase 1 source files under `AI4SOTA-MVP-Phase1/src/ai4sota/`.
- Produces: importable root package `ai4sota` and unchanged `create_project`, `validate_project`, `run_project`, and `load_history` behavior.

- [ ] **Step 1: Initialize the repository and record the approved documents**

Run:

```powershell
if (-not (Test-Path .git)) { git init -b main }
if ((git branch --show-current) -ne "main") { throw "Expected the main branch before initial commit" }
git add README.md task_plan.md notes.md ai4sota-landscape.md docs .gitignore AI4SOTA-MVP-Phase1
git commit -m "docs: define ai4sota desktop architecture"
```

Expected: `git status --short` is empty; the approved specification and filtered Phase 1 migration source are in the initial commit, while the redundant ZIP and local skill workspace remain ignored.

- [ ] **Step 2: Copy the Phase 1 package and test into the root layout**

Create the root files with the same contents as their Phase 1 counterparts. Rename `tests/test_phase1.py` to `tests/test_phase1_regression.py`; do not edit behavior yet.

- [ ] **Step 3: Create the root package configuration**

```toml
[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[project]
name = "ai4sota"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "numpy>=2.0,<3",
  "pydantic>=2.10,<3",
  "PyYAML>=6.0,<7",
]

[project.optional-dependencies]
dev = ["mypy>=1.15,<2", "pytest>=8.3,<9", "pytest-cov>=6,<7", "ruff>=0.11,<1"]

[project.scripts]
ai4sota = "ai4sota.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
ai4sota = ["templates/**/*"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 88
target-version = "py311"
```

- [ ] **Step 4: Install and run the regression baseline**

Run:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest tests\test_phase1_regression.py -v
.venv\Scripts\python -m ruff check src tests
```

Expected: all four Phase 1 tests pass and Ruff reports no errors.

- [ ] **Step 5: Commit the root baseline**

```powershell
git add pyproject.toml src tests
git commit -m "chore: promote phase one kernel to root package"
```

### Task 2: Versioned Scientific Schema Models

**Files:**
- Create: `src/ai4sota/domain/__init__.py`
- Create: `src/ai4sota/domain/common.py`
- Create: `src/ai4sota/domain/projects.py`
- Create: `src/ai4sota/domain/task.py`
- Create: `src/ai4sota/domain/modules.py`
- Create: `src/ai4sota/domain/experiments.py`
- Create: `src/ai4sota/domain/decisions.py`
- Test: `tests/domain/test_schemas.py`

**Interfaces:**
- Consumes: no internal interfaces.
- Produces: `SchemaHeader`, `ConversationScope`, `ProjectSpec`, `TaskContract`, `DatasetSourceSpec`, `PreprocessingSpec`, `DataModuleSpec`, `MethodSpec`, `EvaluationSpec`, `ExperimentSpec`, `SplitManifest`, `RunManifest`, `ResearchCommitManifest`, and `DecisionRecord`.

- [ ] **Step 1: Write failing validation and serialization tests**

```python
from pydantic import ValidationError
from ai4sota.domain.modules import DataModuleSpec, ModuleKind
from ai4sota.domain.task import TaskContract

def test_task_contract_rejects_duplicate_class_codes() -> None:
    with pytest.raises(ValidationError):
        TaskContract(
            id="task/emotion",
            prediction_unit="trial",
            target_type="multiclass",
            classes={"negative": 0, "neutral": 0},
            required_metadata=["subject_id"],
        )

def test_data_module_round_trips_with_remote_source_reserved() -> None:
    spec = DataModuleSpec.model_validate(DATA_MODULE_FIXTURE)
    assert spec.kind is ModuleKind.DATA
    assert spec.origin.remote_source is None
    assert DataModuleSpec.model_validate(spec.model_dump()).id == "data/seed"
```

- [ ] **Step 2: Run the tests and verify the models do not exist**

Run: `.venv\Scripts\python -m pytest tests\domain\test_schemas.py -v`

Expected: collection fails with `ModuleNotFoundError: ai4sota.domain`.

- [ ] **Step 3: Implement strict Pydantic models**

Use this shared base and exact enums:

```python
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

class ModuleKind(StrEnum):
    DATA = "data"
    METHOD = "method"
    EVALUATION = "evaluation"

class ConversationScope(StrEnum):
    PROJECT = "project"
    DATA = "data"
    METHOD = "method"
    EVALUATION = "evaluation"

class ProjectSpec(StrictModel):
    api_version: Literal["ai4sota/v1"] = "ai4sota/v1"
    id: str
    name: str
    active_task: str = "tasks/active.yaml"
    active_modules: dict[ModuleKind, str]
    default_provider_profile: str | None = None
    conversation_overrides: dict[ConversationScope, str] = Field(default_factory=dict)

class CompatibilityState(StrEnum):
    COMPATIBLE = "compatible"
    ADAPTABLE = "adaptable"
    REQUIRES_DECISION = "requires_decision"
    INCOMPATIBLE = "incompatible"

class ComparabilityState(StrEnum):
    DIRECT = "directly_comparable"
    CAVEATS = "comparable_with_caveats"
    NONE = "not_comparable"
```

Every persisted object includes `api_version: Literal["ai4sota/v1"]`, a stable ID, and content-addressable fields. Validate unique class codes, non-empty entrypoints, positive sampling rates, and one primary metric.

- [ ] **Step 4: Verify schemas and static quality**

Run:

```powershell
.venv\Scripts\python -m pytest tests\domain\test_schemas.py -v
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m ruff check src tests
.venv\Scripts\python -m mypy src\ai4sota\domain
```

Expected: all commands succeed.

- [ ] **Step 5: Commit the schema layer**

```powershell
git add src/ai4sota/domain tests/domain
git commit -m "feat: add versioned scientific schemas"
```

### Task 3: Atomic Manifest Store and Project Layout

**Files:**
- Create: `src/ai4sota/storage/__init__.py`
- Create: `src/ai4sota/storage/atomic.py`
- Create: `src/ai4sota/storage/index.py`
- Create: `src/ai4sota/storage/manifests.py`
- Create: `src/ai4sota/storage/migrations.py`
- Create: `src/ai4sota/projects/__init__.py`
- Create: `src/ai4sota/projects/layout.py`
- Create: `src/ai4sota/templates/v1/**`
- Modify: `src/ai4sota/project.py`
- Test: `tests/storage/test_manifest_store.py`
- Test: `tests/storage/test_index_and_migrations.py`
- Test: `tests/projects/test_layout.py`

**Interfaces:**
- Consumes: Pydantic models from Task 2 and the Phase 1 fixture schemas.
- Produces: `atomic_write_bytes(path, data)`, `ManifestStore.read(path, model)`, `ManifestStore.write(path, value)`, `ResearchIndex.rebuild(project)`, `plan_schema_migration(path, target) -> MigrationPlan`, `apply_schema_migration(plan, expected_hash)`, and `ProjectLayout.create(root, name)`.

- [ ] **Step 1: Write failing atomicity and layout tests**

```python
def test_manifest_write_is_readable_and_leaves_no_temp_file(tmp_path: Path) -> None:
    store = ManifestStore()
    path = tmp_path / "tasks" / "active.yaml"
    store.write(path, TASK_FIXTURE)
    assert store.read(path, TaskContract).id == "task/emotion"
    assert list(path.parent.glob("*.tmp")) == []

def test_project_layout_creates_authoritative_directories(tmp_path: Path) -> None:
    layout = ProjectLayout.create(tmp_path, "seed-emotion")
    assert layout.project_file.is_file()
    assert layout.module_dir(ModuleKind.DATA).is_dir()
    assert layout.events_file.parent.is_dir()
    assert layout.index_file.parent.name == ".ai4sota"

def test_deleted_index_rebuilds_from_authoritative_files(project_with_run: ProjectLayout) -> None:
    project_with_run.index_file.unlink(missing_ok=True)
    ResearchIndex(project_with_run.index_file).rebuild(project_with_run)
    assert query_run_ids(project_with_run.index_file) == ["run-001"]

def test_schema_migration_requires_preview_and_preserves_original(tmp_path: Path) -> None:
    path = write_phase1_data_schema(tmp_path)
    plan = plan_schema_migration(path, target="ai4sota/v1")
    assert plan.diff
    backup = apply_schema_migration(plan, expected_hash=plan.original_hash)
    assert backup.read_bytes() == PHASE1_DATA_BYTES
    assert load_yaml(path)["api_version"] == "ai4sota/v1"
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `.venv\Scripts\python -m pytest tests\storage tests\projects -v`

Expected: imports fail for `ai4sota.storage` and `ai4sota.projects`.

- [ ] **Step 3: Implement atomic writes and the exact project paths**

```python
def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    with temporary.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
```

`ResearchIndex.rebuild` deletes only its own temporary rebuild database, scans manifests and JSONL records without executing project code, then atomically replaces `.ai4sota/index.sqlite`. `plan_schema_migration` supports the checked Phase 1 project/data/method/evaluation fixtures through an explicit `(source_version, target_version, kind)` registry; applying a plan rechecks the original hash and writes a sibling hash-named backup before atomic replacement.

`ProjectLayout` must expose `tasks/active.yaml`, `modules/<kind>/current`, `adapters`, `data/fingerprints`, `data/splits`, `conversations/events.jsonl`, `decisions`, `references`, `runs`, `research-commits`, and `.ai4sota/index.sqlite`.

- [ ] **Step 4: Run focused and regression tests**

Run:

```powershell
.venv\Scripts\python -m pytest tests\storage tests\projects -v
.venv\Scripts\python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit project persistence**

```powershell
git add src/ai4sota/storage src/ai4sota/projects src/ai4sota/project.py src/ai4sota/templates/v1 tests/storage tests/projects
git commit -m "feat: add atomic project manifest storage"
```

### Task 4: Hash-Checked File Patch Service

**Files:**
- Create: `src/ai4sota/files/__init__.py`
- Create: `src/ai4sota/files/hashing.py`
- Create: `src/ai4sota/files/patches.py`
- Test: `tests/files/test_patches.py`

**Interfaces:**
- Consumes: `atomic_write_bytes` from Task 3.
- Produces: `sha256_file(path) -> str`, `PatchTarget`, `PatchSet`, `PatchConflict`, and `apply_patch_set(project_root, patch_set) -> AppliedPatch`.

- [ ] **Step 1: Write failing all-or-nothing conflict tests**

```python
def test_stale_second_target_prevents_every_write(tmp_path: Path) -> None:
    first = write(tmp_path / "a.py", "old-a")
    second = write(tmp_path / "b.py", "old-b")
    patch = PatchSet(targets=[
        PatchTarget(path="a.py", expected_sha256=sha256_file(first), content="new-a"),
        PatchTarget(path="b.py", expected_sha256="0" * 64, content="new-b"),
    ])
    with pytest.raises(PatchConflict) as error:
        apply_patch_set(tmp_path, patch)
    assert error.value.paths == ("b.py",)
    assert first.read_text() == "old-a"
    assert second.read_text() == "old-b"
```

- [ ] **Step 2: Run and verify the missing service failure**

Run: `.venv\Scripts\python -m pytest tests\files\test_patches.py -v`

Expected: import failure for `ai4sota.files.patches`.

- [ ] **Step 3: Implement canonical path checks and two-phase application**

```python
def apply_patch_set(project_root: Path, patch_set: PatchSet) -> AppliedPatch:
    resolved = [_resolve_inside(project_root, item.path) for item in patch_set.targets]
    conflicts = tuple(
        item.path for item, path in zip(patch_set.targets, resolved, strict=True)
        if sha256_file(path) != item.expected_sha256
    )
    if conflicts:
        raise PatchConflict(conflicts)
    for item, path in zip(patch_set.targets, resolved, strict=True):
        atomic_write_bytes(path, item.content.encode("utf-8"))
    return AppliedPatch(paths=tuple(item.path for item in patch_set.targets))
```

Reject traversal and symlinks or junctions that resolve outside `project_root` before reading hashes.

- [ ] **Step 4: Verify conflicts, traversal, and successful writes**

Run:

```powershell
.venv\Scripts\python -m pytest tests\files\test_patches.py -v
.venv\Scripts\python -m pytest -q
```

Expected: the stale-target, path-escape, and success tests pass.

- [ ] **Step 5: Commit patch safety**

```powershell
git add src/ai4sota/files tests/files
git commit -m "feat: add hash checked atomic patches"
```

### Task 5: Deterministic Compatibility Compiler

**Files:**
- Create: `src/ai4sota/compatibility/__init__.py`
- Create: `src/ai4sota/compatibility/models.py`
- Create: `src/ai4sota/compatibility/rules.py`
- Create: `src/ai4sota/compatibility/compiler.py`
- Test: `tests/compatibility/test_compiler.py`

**Interfaces:**
- Consumes: Data, Method, Evaluation, TaskContract, and `CompatibilityState` from Task 2.
- Produces: `compile_compatibility(data, method, evaluation, task) -> CompatibilityReport` and versioned `MechanicalAdapterSpec`.

- [ ] **Step 1: Write failing verdict tests**

```python
@pytest.mark.parametrize((fixture, expected), [
    ("exact", CompatibilityState.COMPATIBLE),
    ("axis_transpose", CompatibilityState.ADAPTABLE),
    ("resample", CompatibilityState.REQUIRES_DECISION),
    ("missing_subject_id", CompatibilityState.INCOMPATIBLE),
])
def test_compiler_returns_deterministic_verdict(fixture: str, expected: CompatibilityState) -> None:
    report = compile_compatibility(**load_case(fixture))
    assert report.state is expected
    assert report.contract_hash == compile_compatibility(**load_case(fixture)).contract_hash
    assert report.findings
```

- [ ] **Step 2: Run and verify compiler absence**

Run: `.venv\Scripts\python -m pytest tests\compatibility\test_compiler.py -v`

Expected: import failure for `ai4sota.compatibility`.

- [ ] **Step 3: Implement ordered rules and aggregate severity**

```python
STATE_RANK = {
    CompatibilityState.COMPATIBLE: 0,
    CompatibilityState.ADAPTABLE: 1,
    CompatibilityState.REQUIRES_DECISION: 2,
    CompatibilityState.INCOMPATIBLE: 3,
}

def compile_compatibility(data, method, evaluation, task) -> CompatibilityReport:
    findings = tuple(rule.evaluate(data, method, evaluation, task) for rule in RULES)
    state = max((item.state for item in findings), key=STATE_RANK.__getitem__)
    payload = canonical_json({"findings": findings, "ruleset": RULESET_VERSION})
    return CompatibilityReport(state=state, findings=findings, contract_hash=sha256(payload).hexdigest())
```

Rules must be pure, stably ordered, and limited to the approved mechanical whitelist.

- [ ] **Step 4: Run deterministic compiler tests and the full suite**

Run:

```powershell
.venv\Scripts\python -m pytest tests\compatibility -v
.venv\Scripts\python -m pytest -q
```

Expected: every verdict and hash stability assertion passes.

- [ ] **Step 5: Commit compatibility compilation**

```powershell
git add src/ai4sota/compatibility tests/compatibility
git commit -m "feat: compile scientific module compatibility"
```

### Task 6: Subject-Safe Split Manifest

**Files:**
- Create: `src/ai4sota/evaluation/__init__.py`
- Create: `src/ai4sota/evaluation/splits.py`
- Test: `tests/evaluation/test_splits.py`

**Interfaces:**
- Consumes: `CanonicalDataset`, `EvaluationSpec`, and `SplitManifest`.
- Produces: `materialize_split(dataset, evaluation, seed) -> SplitManifest` and `validate_no_group_leakage(manifest, group_by)`.

- [ ] **Step 1: Write a failing leakage and determinism test**

```python
def test_group_split_is_subject_safe_and_repeatable() -> None:
    first = materialize_split(DATASET, EVALUATION, seed=17)
    second = materialize_split(DATASET, EVALUATION, seed=17)
    assert first == second
    train_subjects = subjects_in(first, "train")
    test_subjects = subjects_in(first, "test")
    assert train_subjects.isdisjoint(test_subjects)
```

- [ ] **Step 2: Run and verify the split service is missing**

Run: `.venv\Scripts\python -m pytest tests\evaluation\test_splits.py -v`

Expected: import failure for `ai4sota.evaluation.splits`.

- [ ] **Step 3: Implement deterministic group assignment**

```python
def materialize_split(dataset: CanonicalDataset, evaluation: EvaluationSpec, seed: int) -> SplitManifest:
    sample_ids = tuple(str(value) for value in dataset.sample_ids)
    groups = tuple(str(value) for value in dataset.metadata[evaluation.protocol.group_by])
    assignments = assign_groups(groups, evaluation.protocol, seed)
    members = tuple(SplitMember(sample_id=sid, partition=assignments[group]) for sid, group in zip(sample_ids, groups, strict=True))
    manifest = SplitManifest(seed=seed, group_by=evaluation.protocol.group_by, members=members)
    validate_no_group_leakage(manifest, groups)
    return manifest
```

Fail with a field-specific error if any required ID is absent, null, or duplicated.

- [ ] **Step 4: Run split, domain, and regression tests**

Run:

```powershell
.venv\Scripts\python -m pytest tests\evaluation tests\domain -v
.venv\Scripts\python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit split ownership**

```powershell
git add src/ai4sota/evaluation tests/evaluation
git commit -m "feat: materialize subject safe split manifests"
```

### Task 7: Immutable Run Snapshots and Append-Only Ledger

**Files:**
- Create: `src/ai4sota/runs/__init__.py`
- Create: `src/ai4sota/runs/snapshots.py`
- Create: `src/ai4sota/runs/repository.py`
- Create: `src/ai4sota/runs/lifecycle.py`
- Create: `src/ai4sota/runs/artifacts.py`
- Modify: `src/ai4sota/runner.py`
- Test: `tests/runs/test_snapshots.py`
- Test: `tests/runs/test_repository.py`
- Test: `tests/runs/test_artifact_cleanup.py`

**Interfaces:**
- Consumes: project layout, `ExperimentSpec`, content hashes, and split manifest.
- Produces: `prepare_run(project, experiment) -> RunManifest`, `append_run_event(run_dir, event)`, `transition_run(run_id, expected, target)`, and `cleanup_artifacts(run_dir, paths, expected_manifest_hash) -> ArtifactCleanupRecord`.

- [ ] **Step 1: Write failing snapshot isolation tests**

```python
def test_workspace_edit_after_prepare_does_not_change_snapshot(project: ProjectLayout) -> None:
    manifest = prepare_run(project, EXPERIMENT)
    live = project.module_dir(ModuleKind.METHOD) / "model.py"
    snapshot = project.run_dir(manifest.id) / "snapshot" / "modules" / "method" / "current" / "model.py"
    before = sha256_file(snapshot)
    live.write_text("changed after approval", encoding="utf-8")
    assert sha256_file(snapshot) == before
    assert manifest.snapshot_hash == hash_tree(snapshot.parents[3])

def test_artifact_cleanup_keeps_scientific_record_and_writes_tombstone(completed_run: Path) -> None:
    payload = completed_run / "artifacts" / "checkpoint.pt"
    record = cleanup_artifacts(completed_run, ["checkpoint.pt"], expected_manifest_hash=manifest_hash(completed_run))
    assert not payload.exists()
    assert (completed_run / "manifest.yaml").exists()
    assert (completed_run / "metrics").is_dir()
    assert record.items[0].sha256 == CHECKPOINT_HASH
    assert "checkpoint.pt" in (completed_run / "artifact-tombstones.jsonl").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run and verify Run services are absent**

Run: `.venv\Scripts\python -m pytest tests\runs -v`

Expected: import failure for `ai4sota.runs`.

- [ ] **Step 3: Implement lifecycle and durable event writes**

```python
ALLOWED_TRANSITIONS = {
    "draft": {"awaiting_approval"},
    "awaiting_approval": {"queued", "cancelled"},
    "queued": {"preparing", "cancelled"},
    "preparing": {"running", "failed", "cancelled"},
    "running": {"succeeded", "failed", "cancelled", "interrupted"},
}

def append_run_event(run_dir: Path, event: RunEvent) -> None:
    with (run_dir / "events.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(event.model_dump_json() + "\n")
        stream.flush()
        os.fsync(stream.fileno())
```

Copy code, schemas, generated adapters, configs, and small manifests into `snapshot/`; record strong fingerprints for external datasets instead of copying them. Artifact cleanup resolves each selected relative path strictly below `artifacts/`, rechecks the Run manifest hash, records path/hash/size/reason/time in append-only `artifact-tombstones.jsonl`, and never removes manifests, metrics, logs, snapshots, or prior tombstones.

- [ ] **Step 4: Verify snapshot, transition, failure, and interruption behavior**

Run:

```powershell
.venv\Scripts\python -m pytest tests\runs -v
.venv\Scripts\python -m pytest -q
```

Expected: immutable snapshot and append-only event assertions pass.

- [ ] **Step 5: Commit the Run ledger**

```powershell
git add src/ai4sota/runs src/ai4sota/runner.py tests/runs
git commit -m "feat: add immutable run snapshots and ledger"
```

### Task 8: Comparability and Multi-Run Aggregation

**Files:**
- Create: `src/ai4sota/runs/comparison.py`
- Create: `src/ai4sota/runs/aggregation.py`
- Test: `tests/runs/test_comparison.py`
- Test: `tests/runs/test_aggregation.py`

**Interfaces:**
- Consumes: completed `RunManifest` values and metrics.
- Produces: `compare_runs(runs) -> ComparabilityReport` and `aggregate_runs(runs, dimensions) -> AggregatedResult`.

- [ ] **Step 1: Write failing comparison policy tests**

```python
def test_different_test_members_suppress_delta_language() -> None:
    report = compare_runs([RUN_A, RUN_WITH_DIFFERENT_SPLIT])
    assert report.state is ComparabilityState.NONE
    assert report.metric_deltas is None
    assert "split_manifest_hash" in report.blocking_fields

def test_only_declared_seed_may_be_aggregated() -> None:
    result = aggregate_runs([RUN_SEED_7, RUN_SEED_17], dimensions={"seed"})
    assert result.count == 2
    assert result.metrics["macro_f1"].mean == pytest.approx(0.81)
```

- [ ] **Step 2: Run and verify comparison modules are absent**

Run: `.venv\Scripts\python -m pytest tests\runs\test_comparison.py tests\runs\test_aggregation.py -v`

Expected: import failures for the new modules.

- [ ] **Step 3: Implement field policies and aggregation rejection**

```python
BLOCKING_FIELDS = (
    "data_fingerprint_hash",
    "task_contract_hash",
    "split_manifest_hash",
    "evaluation_protocol_hash",
    "metric_implementation_hash",
    "integrity_state",
)

def compare_runs(runs: Sequence[RunManifest]) -> ComparabilityReport:
    differences = field_differences(runs)
    blocking = tuple(name for name in BLOCKING_FIELDS if name in differences)
    if blocking:
        return ComparabilityReport(state=ComparabilityState.NONE, blocking_fields=blocking, metric_deltas=None)
    return classify_non_blocking_differences(runs, differences)
```

Aggregation rejects every differing field outside the declared repetition dimensions before calculating statistics.

- [ ] **Step 4: Run focused and full tests**

Run:

```powershell
.venv\Scripts\python -m pytest tests\runs\test_comparison.py tests\runs\test_aggregation.py -v
.venv\Scripts\python -m pytest -q
```

Expected: all comparison and aggregation policies pass.

- [ ] **Step 5: Commit deterministic comparison**

```powershell
git add src/ai4sota/runs tests/runs
git commit -m "feat: enforce deterministic run comparability"
```

### Task 9: Exact-Snapshot Research Commits

**Files:**
- Create: `src/ai4sota/history/__init__.py`
- Create: `src/ai4sota/history/git.py`
- Create: `src/ai4sota/history/research_commits.py`
- Test: `tests/history/test_research_commits.py`

**Interfaces:**
- Consumes: qualified Run snapshots and optional `AggregatedResult`.
- Produces: `GitAdapter.ensure_repository(root, initial_message) -> str` and `create_research_commit(project, draft, run_ids) -> ResearchCommitManifest`.

- [ ] **Step 1: Write a failing diverged-workspace integration test**

```python
def test_commit_uses_old_run_snapshot_without_touching_live_workspace(git_project: ProjectLayout) -> None:
    run = completed_run(git_project, method_source="snapshot version")
    live = git_project.module_dir(ModuleKind.METHOD) / "model.py"
    live.write_text("new uncommitted version", encoding="utf-8")
    result = create_research_commit(git_project, DRAFT, [run.id])
    assert live.read_text(encoding="utf-8") == "new uncommitted version"
    assert git_show(result.git_sha, "modules/method/current/model.py") == "snapshot version"
    assert result.run_ids == (run.id,)
```

- [ ] **Step 2: Run and verify history services are absent**

Run: `.venv\Scripts\python -m pytest tests\history\test_research_commits.py -v`

Expected: import failure for `ai4sota.history`.

- [ ] **Step 3: Implement Git through structured argument arrays**

```python
class GitAdapter:
    def run(self, cwd: Path, *args: str) -> str:
        completed = subprocess.run(
            ["git", *args], cwd=cwd, check=True, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        return completed.stdout.strip()

    def ensure_repository(self, root: Path, initial_message: str) -> str:
        if not (root / ".git").exists():
            self.run(root, "init", "-b", "main")
        try:
            return self.run(root, "rev-parse", "--verify", "HEAD")
        except subprocess.CalledProcessError:
            self.run(root, "add", ".")
            self.run(root, "commit", "-m", initial_message)
            return self.run(root, "rev-parse", "--verify", "HEAD")
```

Materialize the selected snapshot in an isolated temporary worktree, write `research-commits/<id>/manifest.yaml`, commit there, create `refs/ai4sota/research/<id>`, and remove the temporary worktree in `finally`. Never run checkout, reset, or clean in the live worktree.

- [ ] **Step 4: Verify exact tree, aggregation gate, and cleanup**

Run:

```powershell
.venv\Scripts\python -m pytest tests\history -v
.venv\Scripts\python -m pytest -q
```

Expected: Git integration tests pass and no temporary worktree remains.

- [ ] **Step 5: Commit Research Commit support**

```powershell
git add src/ai4sota/history tests/history
git commit -m "feat: create research commits from run snapshots"
```

### Task 10: Immutable Local Module Library

**Files:**
- Create: `src/ai4sota/library/__init__.py`
- Create: `src/ai4sota/library/models.py`
- Create: `src/ai4sota/library/service.py`
- Test: `tests/library/test_service.py`

**Interfaces:**
- Consumes: module schemas, project layout, hashing, and atomic storage.
- Produces: `ModuleLibrary.import_version(ref, project)`, `create_draft(ref)`, and `publish(draft, expected_hash) -> PublishedModule`.

- [ ] **Step 1: Write failing immutable-publication tests**

```python
def test_import_is_editable_but_published_source_is_immutable(library: ModuleLibrary, project: ProjectLayout) -> None:
    published = library.publish(valid_draft("data/seed", "1.0.0"), expected_hash=DRAFT_HASH)
    imported = library.import_version(published.ref, project)
    (imported / "module.yaml").write_text("project edit", encoding="utf-8")
    assert library.read(published.ref).content_hash == published.content_hash
    with pytest.raises(VersionExists):
        library.publish(valid_draft("data/seed", "1.0.0"), expected_hash=DRAFT_HASH)
```

- [ ] **Step 2: Run and verify library services are absent**

Run: `.venv\Scripts\python -m pytest tests\library\test_service.py -v`

Expected: import failure for `ai4sota.library`.

- [ ] **Step 3: Implement draft, validation, publication, and import**

```python
class ModuleLibrary:
    def publish(self, draft: ModuleDraft, expected_hash: str) -> PublishedModule:
        actual = hash_tree(draft.path)
        if actual != expected_hash:
            raise PublishConflict(expected_hash, actual)
        destination = self.root / draft.kind / draft.id / draft.version
        if destination.exists():
            raise VersionExists(draft.ref)
        validate_publish_gate(draft)
        copy_tree_atomic(draft.path, destination)
        return PublishedModule(ref=draft.ref, content_hash=hash_tree(destination))
```

Store optional `remote_source` as metadata only. Import copies files and records `origin.based_on`; it never executes code from the global directory.

- [ ] **Step 4: Run library and full tests**

Run:

```powershell
.venv\Scripts\python -m pytest tests\library -v
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m ruff check src tests
```

Expected: all tests pass.

- [ ] **Step 5: Commit the local module library**

```powershell
git add src/ai4sota/library tests/library
git commit -m "feat: add immutable local module library"
```

### Task 11: Headless Scientific Vertical Slice

**Files:**
- Create: `src/ai4sota/workflows/__init__.py`
- Create: `src/ai4sota/workflows/scientific_run.py`
- Modify: `src/ai4sota/cli.py`
- Modify: `src/ai4sota/runner.py`
- Create: `tests/integration/test_scientific_vertical_slice.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: every service created in Tasks 2-10.
- Produces: `prepare_experiment(project)`, `execute_approved_run(project, approval)`, CLI commands `compile`, `prepare-run`, `run-approved`, `compare`, and `research-commit`.

- [ ] **Step 1: Write the failing full-flow test**

```python
def test_two_runs_compare_and_promote_to_research_commit(tmp_path: Path) -> None:
    project = create_v1_demo_project(tmp_path / "demo")
    report = compile_project(project)
    assert report.state is CompatibilityState.COMPATIBLE
    first = execute_approved_run(project, approve(prepare_experiment(project)))
    edit_method_parameter(project, learning_rate=0.02)
    second = execute_approved_run(project, approve(prepare_experiment(project)))
    comparison = compare_runs([first, second])
    assert comparison.state is ComparabilityState.DIRECT
    commit = create_research_commit(project, accepted_draft(comparison), [second.id])
    assert commit.git_sha
```

- [ ] **Step 2: Run and verify the workflow is incomplete**

Run: `.venv\Scripts\python -m pytest tests\integration\test_scientific_vertical_slice.py -v`

Expected: import or command failure for the unimplemented workflow.

- [ ] **Step 3: Implement the orchestration without duplicating domain logic**

```python
def prepare_experiment(project: ProjectLayout) -> PreparedExperiment:
    specs = load_active_specs(project)
    compatibility = compile_compatibility(**specs)
    if compatibility.state in {CompatibilityState.REQUIRES_DECISION, CompatibilityState.INCOMPATIBLE}:
        raise ExperimentBlocked(compatibility)
    split = materialize_split(specs.dataset, specs.evaluation, specs.seed)
    experiment = build_experiment_spec(specs, compatibility, split)
    return PreparedExperiment(spec=experiment, approval_hash=hash_model(experiment))
```

The CLI serializes machine-readable output with `--json`; it never bypasses approval hashes.

- [ ] **Step 4: Run the complete quality gate**

Run:

```powershell
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m pytest --cov=ai4sota --cov-report=term-missing
.venv\Scripts\python -m ruff check src tests
.venv\Scripts\python -m mypy src\ai4sota\domain src\ai4sota\compatibility src\ai4sota\runs
```

Expected: all tests pass, core service coverage is at least 85%, Ruff is clean, and mypy reports no errors in the listed packages.

- [ ] **Step 5: Commit the headless vertical slice**

```powershell
git add src/ai4sota tests/integration README.md
git commit -m "feat: complete headless scientific workflow"
```

## Plan Completion Gate

Run:

```powershell
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m ruff check src tests
git status --short
```

Expected: tests and lint pass; `git status --short` is empty. Demonstrate one local project containing two immutable Runs, one deterministic comparison, and one exact-snapshot Research Commit before starting the control-service plan.
