from __future__ import annotations

import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from ai4sota.domain import ModuleKind, ResearchCommitManifest, RunManifest
from ai4sota.files import stable_read_file
from ai4sota.history import (
    GitAdapter,
    ResearchCommitError,
    create_research_commit,
    research_commits,
)
from ai4sota.projects import ProjectLayout
from ai4sota.runs import aggregate_runs, hash_tree
from ai4sota.storage import ManifestStore, canonical_manifest_hash

ZERO_HASH = "sha256:" + "0" * 64
DRAFT = {
    "id": "research-commit-001",
    "project_id": "project/seed-emotion",
}


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


@pytest.fixture
def git_project(tmp_path: Path) -> ProjectLayout:
    project = ProjectLayout.create(tmp_path, "seed-emotion")
    git(project.root, "init", "-b", "main")
    git(project.root, "config", "user.name", "AI4SOTA Tests")
    git(project.root, "config", "user.email", "tests@ai4sota.invalid")
    GitAdapter().ensure_repository(project.root, "Initial project")
    return project


def project_files(project: ProjectLayout) -> dict[str, bytes]:
    return {
        path.relative_to(project.root).as_posix(): path.read_bytes()
        for path in project.root.rglob("*")
        if path.is_file() and ".git" not in path.parts
    }


def completed_run(
    project: ProjectLayout,
    *,
    run_id: str = "run-complete",
    method_source: str = "snapshot version",
    status: str = "succeeded",
    integrity_state: str = "verified",
    split_manifest_hash: str | None = None,
    seed: int | None = None,
    accuracy: float = 0.8,
    parent_research_commit: str | None = None,
) -> RunManifest:
    run_dir = project.runs_dir / run_id
    snapshot = run_dir / "snapshot"
    snapshot.mkdir(parents=True)
    for path in sorted(project.root.rglob("*")):
        if path.is_file() and ".git" not in path.parts and "runs" not in path.parts:
            destination = snapshot / path.relative_to(project.root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(path.read_bytes())
    method = snapshot / "modules" / "method" / "current" / "model.py"
    method.parent.mkdir(parents=True, exist_ok=True)
    method.write_text(method_source, encoding="utf-8")
    draft = RunManifest(
        id=run_id,
        content_hash=ZERO_HASH,
        project_id="project/seed-emotion",
        experiment_hash="sha256:" + "1" * 64,
        snapshot_hash=hash_tree(snapshot),
        data_fingerprint_hash="sha256:" + "2" * 64,
        task_contract_hash="sha256:" + "3" * 64,
        split_manifest_hash=split_manifest_hash or "sha256:" + "4" * 64,
        evaluation_protocol_hash="sha256:" + "5" * 64,
        metric_implementation_hash="sha256:" + "6" * 64,
        integrity_state=integrity_state,
        status=status,
        metrics={"accuracy": accuracy},
        seed=seed,
        parent_research_commit=parent_research_commit,
    )
    run = draft.model_copy(
        update={"content_hash": canonical_manifest_hash(draft)}
    )
    ManifestStore().write(run_dir / "manifest.yaml", run)
    return run


def rehash_run(project: ProjectLayout, run: RunManifest) -> RunManifest:
    run_dir = project.runs_dir / run.id
    draft = run.model_copy(
        update={
            "snapshot_hash": hash_tree(run_dir / "snapshot"),
            "content_hash": ZERO_HASH,
        }
    )
    updated = draft.model_copy(
        update={"content_hash": canonical_manifest_hash(draft)}
    )
    ManifestStore().write(run_dir / "manifest.yaml", updated)
    return updated


def test_commit_uses_old_run_snapshot_without_touching_live_workspace(
    git_project: ProjectLayout,
) -> None:
    run = completed_run(git_project, method_source="snapshot version")
    live = git_project.module_dir(ModuleKind.METHOD) / "model.py"
    live.write_text("new uncommitted version", encoding="utf-8")

    result = create_research_commit(git_project, DRAFT, [run.id])

    assert isinstance(result, ResearchCommitManifest)
    assert live.read_text(encoding="utf-8") == "new uncommitted version"
    assert (
        git(git_project.root, "show", f"{result.git_sha}:modules/method/current/model.py")
        == "snapshot version"
    )
    assert result.run_ids == (run.id,)
    assert git(git_project.root, "diff", "--cached") == ""


def test_promotion_rejects_missing_repository_without_mutating_project(
    tmp_path: Path,
) -> None:
    project = ProjectLayout.create(tmp_path, "seed-emotion")
    run = completed_run(project)
    files_before = project_files(project)

    with pytest.raises(ResearchCommitError, match="existing Git repository"):
        create_research_commit(project, DRAFT, [run.id])

    assert not (project.root / ".git").exists()
    assert project_files(project) == files_before
    assert not (project.research_commits_dir / DRAFT["id"]).exists()
    assert temporary_worktrees(project) == ()


def test_promotion_rejects_unborn_repository_without_mutating_git_state(
    tmp_path: Path,
) -> None:
    project = ProjectLayout.create(tmp_path, "seed-emotion")
    git(project.root, "init", "-b", "research-live")
    git(project.root, "config", "user.name", "AI4SOTA Tests")
    git(project.root, "config", "user.email", "tests@ai4sota.invalid")
    run = completed_run(project)
    files_before = project_files(project)
    status_before = git(project.root, "status", "--porcelain=v1")
    branch_before = git(project.root, "symbolic-ref", "HEAD")
    refs_before = git(project.root, "for-each-ref", "--format=%(refname) %(objectname)")
    index = project.root / ".git" / "index"
    assert not index.exists()

    with pytest.raises(ResearchCommitError, match="valid HEAD"):
        create_research_commit(project, DRAFT, [run.id])

    assert project_files(project) == files_before
    assert git(project.root, "status", "--porcelain=v1") == status_before
    assert git(project.root, "symbolic-ref", "HEAD") == branch_before
    assert git(project.root, "for-each-ref", "--format=%(refname) %(objectname)") == refs_before
    assert not index.exists()
    assert subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=project.root,
        capture_output=True,
        check=False,
    ).returncode != 0
    assert not (project.research_commits_dir / DRAFT["id"]).exists()
    assert temporary_worktrees(project) == ()


def temporary_worktrees(project: ProjectLayout) -> tuple[Path, ...]:
    return tuple(project.root.parent.glob(".ai4sota-research-*"))


def transaction_dir(project: ProjectLayout) -> Path:
    value = Path(
        git(
            project.root,
            "rev-parse",
            "--git-path",
            "ai4sota/research-transactions",
        )
    )
    return value if value.is_absolute() else project.root / value


def test_commit_persists_authoritative_manifest_ref_and_exact_snapshot_tree(
    git_project: ProjectLayout,
) -> None:
    run = completed_run(git_project)

    result = create_research_commit(git_project, DRAFT, [run.id])

    assert (
        git(
            git_project.root,
            "rev-parse",
            "refs/ai4sota/research/research-commit-001",
        )
        == result.git_sha
    )
    stored = ManifestStore().read(
        git_project.research_commits_dir / result.id / "manifest.yaml",
        ResearchCommitManifest,
    )
    assert stored == result
    committed_files = set(
        git(git_project.root, "ls-tree", "-r", "--name-only", result.git_sha).splitlines()
    )
    snapshot_files = {
        path.relative_to(git_project.runs_dir / run.id / "snapshot").as_posix()
        for path in (git_project.runs_dir / run.id / "snapshot").rglob("*")
        if path.is_file()
    }
    assert committed_files == snapshot_files
    assert temporary_worktrees(git_project) == ()


def test_commit_allows_snapshot_tree_identical_to_base_head(tmp_path: Path) -> None:
    project = ProjectLayout.create(tmp_path, "seed-emotion")
    method = project.module_dir(ModuleKind.METHOD) / "model.py"
    method.write_text("snapshot version", encoding="utf-8")
    git(project.root, "init", "-b", "main")
    git(project.root, "config", "user.name", "AI4SOTA Tests")
    git(project.root, "config", "user.email", "tests@ai4sota.invalid")
    base_sha = GitAdapter().ensure_repository(project.root, "Initial project")
    run = completed_run(project, method_source="snapshot version")

    result = create_research_commit(project, DRAFT, [run.id])

    assert result.git_sha != base_sha
    assert git(project.root, "rev-parse", f"{result.git_sha}^") == base_sha
    assert git(
        project.root,
        "diff-tree",
        "--no-commit-id",
        "--name-only",
        "-r",
        result.git_sha,
    ) == ""
    assert temporary_worktrees(project) == ()


def test_commit_creates_ref_in_sha256_repository_when_supported(
    tmp_path: Path,
) -> None:
    project = ProjectLayout.create(tmp_path, "seed-emotion")
    initialized = subprocess.run(
        ["git", "init", "--object-format=sha256", "-b", "main"],
        cwd=project.root,
        capture_output=True,
        text=True,
        check=False,
    )
    if initialized.returncode != 0:
        pytest.skip("installed Git does not support SHA-256 repositories")
    git(project.root, "config", "user.name", "AI4SOTA Tests")
    git(project.root, "config", "user.email", "tests@ai4sota.invalid")
    GitAdapter().ensure_repository(project.root, "Initial project")
    run = completed_run(project)

    result = create_research_commit(project, DRAFT, [run.id])

    assert len(result.git_sha) == 64
    assert git(
        project.root,
        "rev-parse",
        "refs/ai4sota/research/research-commit-001",
    ) == result.git_sha


def test_commit_accepts_a_verified_parent_and_uses_it_as_git_parent(
    git_project: ProjectLayout,
) -> None:
    parent_run = completed_run(git_project, run_id="run-parent")
    parent = create_research_commit(git_project, DRAFT, [parent_run.id])
    child_run = completed_run(
        git_project,
        run_id="run-child",
        parent_research_commit=parent.id,
    )
    child_draft = {
        **DRAFT,
        "id": "research-commit-002",
        "parent_research_commit_ids": [parent.id],
    }

    child = create_research_commit(git_project, child_draft, [child_run.id])

    assert git(git_project.root, "rev-parse", f"{child.git_sha}^") == parent.git_sha
    assert child.parent_research_commit_ids == (parent.id,)


@pytest.mark.parametrize(
    "parent_ids",
    [
        ["../outside"],
        ["research-commit-404"],
        ["research-commit-001", "research-commit-001"],
    ],
)
def test_commit_rejects_invalid_duplicate_or_missing_parents(
    git_project: ProjectLayout, parent_ids: list[str]
) -> None:
    run = completed_run(
        git_project,
        parent_research_commit=parent_ids[0],
    )
    draft = {**DRAFT, "parent_research_commit_ids": parent_ids}

    with pytest.raises(ResearchCommitError, match="parent"):
        create_research_commit(git_project, draft, [run.id])


def test_commit_rejects_parent_list_inconsistent_with_run_provenance(
    git_project: ProjectLayout,
) -> None:
    parent_run = completed_run(git_project, run_id="run-parent")
    parent = create_research_commit(git_project, DRAFT, [parent_run.id])
    child_run = completed_run(git_project, run_id="run-child")

    with pytest.raises(ResearchCommitError, match="parent.*Run"):
        create_research_commit(
            git_project,
            {
                **DRAFT,
                "id": "research-commit-002",
                "parent_research_commit_ids": [parent.id],
            },
            [child_run.id],
        )


def test_commit_rejects_tampered_parent_manifest(
    git_project: ProjectLayout,
) -> None:
    parent_run = completed_run(git_project, run_id="run-parent")
    parent = create_research_commit(git_project, DRAFT, [parent_run.id])
    parent_path = git_project.research_commits_dir / parent.id / "manifest.yaml"
    parent_path.write_text(
        parent_path.read_text(encoding="utf-8").replace("1.0.0", "1.0.1"),
        encoding="utf-8",
    )
    child_run = completed_run(
        git_project,
        run_id="run-child",
        parent_research_commit=parent.id,
    )

    with pytest.raises(ResearchCommitError, match="parent.*hash"):
        create_research_commit(
            git_project,
            {
                **DRAFT,
                "id": "research-commit-002",
                "parent_research_commit_ids": [parent.id],
            },
            [child_run.id],
        )


def test_commit_rejects_parent_ref_that_disagrees_with_manifest(
    git_project: ProjectLayout,
) -> None:
    base_sha = git(git_project.root, "rev-parse", "HEAD")
    parent_run = completed_run(git_project, run_id="run-parent")
    parent = create_research_commit(git_project, DRAFT, [parent_run.id])
    git(
        git_project.root,
        "update-ref",
        f"refs/ai4sota/research/{parent.id}",
        base_sha,
        parent.git_sha,
    )
    child_run = completed_run(
        git_project,
        run_id="run-child",
        parent_research_commit=parent.id,
    )

    with pytest.raises(ResearchCommitError, match="parent.*ref"):
        create_research_commit(
            git_project,
            {
                **DRAFT,
                "id": "research-commit-002",
                "parent_research_commit_ids": [parent.id],
            },
            [child_run.id],
        )


def test_commit_rejects_parent_from_another_project(
    git_project: ProjectLayout,
) -> None:
    parent_run = completed_run(git_project, run_id="run-parent")
    parent = create_research_commit(git_project, DRAFT, [parent_run.id])
    parent_path = git_project.research_commits_dir / parent.id / "manifest.yaml"
    foreign_draft = parent.model_copy(
        update={"project_id": "project/other", "content_hash": ZERO_HASH}
    )
    foreign = foreign_draft.model_copy(
        update={"content_hash": canonical_manifest_hash(foreign_draft)}
    )
    ManifestStore().write(parent_path, foreign)
    child_run = completed_run(
        git_project,
        run_id="run-child",
        parent_research_commit=parent.id,
    )

    with pytest.raises(ResearchCommitError, match="another project"):
        create_research_commit(
            git_project,
            {
                **DRAFT,
                "id": "research-commit-002",
                "parent_research_commit_ids": [parent.id],
            },
            [child_run.id],
        )


def test_commit_includes_ignored_snapshot_files_with_exact_bytes(
    git_project: ProjectLayout,
) -> None:
    run = completed_run(git_project)
    snapshot = git_project.runs_dir / run.id / "snapshot"
    (snapshot / ".gitignore").write_text("ignored.bin\n", encoding="utf-8")
    expected = b"\x00\r\nexact ignored payload\xff"
    (snapshot / "ignored.bin").write_bytes(expected)
    run = rehash_run(git_project, run)

    result = create_research_commit(git_project, DRAFT, [run.id])

    blob = subprocess.run(
        ["git", "show", f"{result.git_sha}:ignored.bin"],
        cwd=git_project.root,
        check=True,
        capture_output=True,
    ).stdout
    assert blob == expected


def test_snapshot_mutation_during_materialization_is_rejected(
    git_project: ProjectLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = completed_run(git_project)
    snapshot = git_project.runs_dir / run.id / "snapshot"
    target = snapshot / "modules" / "method" / "current" / "model.py"
    mutated = False

    def mutate_then_read(path: Path):  # type: ignore[no-untyped-def]
        nonlocal mutated
        if path == target and not mutated:
            mutated = True
            target.write_text("mutated during copy", encoding="utf-8")
        return stable_read_file(path)

    monkeypatch.setattr(
        research_commits,
        "_read_snapshot_file",
        mutate_then_read,
        raising=False,
    )

    with pytest.raises(ResearchCommitError, match="changed during materialization"):
        create_research_commit(git_project, DRAFT, [run.id])

    assert mutated
    assert not (git_project.research_commits_dir / DRAFT["id"]).exists()
    assert subprocess.run(
        [
            "git",
            "show-ref",
            "--verify",
            "--quiet",
            "refs/ai4sota/research/research-commit-001",
        ],
        cwd=git_project.root,
        check=False,
    ).returncode != 0
    assert temporary_worktrees(git_project) == ()


def test_commit_rejects_nested_git_metadata_in_a_snapshot(
    git_project: ProjectLayout,
) -> None:
    run = completed_run(git_project)
    metadata = (
        git_project.runs_dir
        / run.id
        / "snapshot"
        / "modules"
        / "method"
        / "current"
        / "nested"
        / ".git"
    )
    metadata.mkdir(parents=True)
    (metadata / "config").write_text("not a repository", encoding="utf-8")
    run = rehash_run(git_project, run)

    with pytest.raises(ResearchCommitError, match="Git metadata"):
        create_research_commit(git_project, DRAFT, [run.id])

    assert temporary_worktrees(git_project) == ()


@pytest.mark.parametrize(
    ("status", "integrity_state"),
    [("failed", "verified"), ("succeeded", "unchecked")],
)
def test_commit_rejects_unqualified_runs(
    git_project: ProjectLayout, status: str, integrity_state: str
) -> None:
    run = completed_run(
        git_project, status=status, integrity_state=integrity_state
    )

    with pytest.raises(ResearchCommitError, match="succeeded and verified"):
        create_research_commit(git_project, DRAFT, [run.id])

    assert temporary_worktrees(git_project) == ()
    assert not (
        git_project.research_commits_dir / "research-commit-001"
    ).exists()


def test_commit_rejects_runs_blocked_by_comparison_policy(
    git_project: ProjectLayout,
) -> None:
    first = completed_run(git_project, run_id="run-a")
    second = completed_run(
        git_project,
        run_id="run-b",
        split_manifest_hash="sha256:" + "9" * 64,
    )

    with pytest.raises(ResearchCommitError, match="not comparable"):
        create_research_commit(git_project, DRAFT, [first.id, second.id])


def test_commit_rejects_a_run_claiming_a_different_project(
    git_project: ProjectLayout,
) -> None:
    run = completed_run(git_project)
    run_dir = git_project.runs_dir / run.id
    foreign_draft = run.model_copy(
        update={
            "project_id": "project/other",
            "content_hash": ZERO_HASH,
        }
    )
    foreign = foreign_draft.model_copy(
        update={"content_hash": canonical_manifest_hash(foreign_draft)}
    )
    ManifestStore().write(run_dir / "manifest.yaml", foreign)

    with pytest.raises(ResearchCommitError, match="project"):
        create_research_commit(
            git_project,
            {**DRAFT, "project_id": "project/other"},
            [foreign.id],
        )


def test_commit_persists_a_validated_aggregation(
    git_project: ProjectLayout,
) -> None:
    first = completed_run(
        git_project, run_id="run-seed-7", seed=7, accuracy=0.8
    )
    second = completed_run(
        git_project, run_id="run-seed-17", seed=17, accuracy=0.82
    )
    aggregation = aggregate_runs([first, second], {"seed"})

    result = create_research_commit(
        git_project, DRAFT, [first.id, second.id], aggregation
    )

    assert result.comparison_state == "comparable_with_caveats"
    assert result.aggregation == aggregation.model_dump(mode="json")


def test_commit_rejects_an_aggregation_for_different_runs(
    git_project: ProjectLayout,
) -> None:
    first = completed_run(
        git_project, run_id="run-seed-7", seed=7, accuracy=0.8
    )
    second = completed_run(
        git_project, run_id="run-seed-17", seed=17, accuracy=0.82
    )
    aggregation = aggregate_runs([first, second], {"seed"}).model_copy(
        update={"count": 3}
    )

    with pytest.raises(ResearchCommitError, match="aggregation"):
        create_research_commit(
            git_project, DRAFT, [first.id, second.id], aggregation
        )


def test_commit_rejects_unsafe_id_without_writing_outside_project(
    git_project: ProjectLayout,
) -> None:
    run = completed_run(git_project)
    unsafe = {**DRAFT, "id": "../escaped"}

    with pytest.raises(ResearchCommitError, match="invalid research commit id"):
        create_research_commit(git_project, unsafe, [run.id])

    assert not (git_project.root / "escaped").exists()
    assert temporary_worktrees(git_project) == ()


def test_commit_rejects_a_linked_research_commit_root(
    git_project: ProjectLayout,
) -> None:
    run = completed_run(git_project)
    outside = git_project.root.parent / "outside-research-history"
    outside.mkdir()
    git_project.research_commits_dir.rmdir()
    try:
        git_project.research_commits_dir.symlink_to(
            outside, target_is_directory=True
        )
    except OSError as error:
        if getattr(error, "winerror", None) == 1314:
            subprocess.run(
                [
                    "cmd",
                    "/c",
                    "mklink",
                    "/J",
                    str(git_project.research_commits_dir),
                    str(outside),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        else:
            raise

    with pytest.raises(ResearchCommitError, match="links"):
        create_research_commit(git_project, DRAFT, [run.id])

    assert tuple(outside.iterdir()) == ()
    assert temporary_worktrees(git_project) == ()


@pytest.mark.parametrize("commit_id", ["bad..id", ".hidden", "bad\nid"])
def test_commit_rejects_ids_that_cannot_be_safe_git_refs(
    git_project: ProjectLayout, commit_id: str
) -> None:
    run = completed_run(git_project)

    with pytest.raises(ResearchCommitError, match="invalid research commit id"):
        create_research_commit(
            git_project, {**DRAFT, "id": commit_id}, [run.id]
        )

    assert temporary_worktrees(git_project) == ()
    assert not (git_project.research_commits_dir / commit_id).exists()


def test_git_commit_failure_preserves_live_state_and_cleans_worktree(
    git_project: ProjectLayout,
) -> None:
    run = completed_run(git_project)
    git(git_project.root, "config", "user.name", "")
    status_before = git(git_project.root, "status", "--porcelain=v1")
    worktrees_before = git(git_project.root, "worktree", "list", "--porcelain")

    with pytest.raises(subprocess.CalledProcessError):
        create_research_commit(git_project, DRAFT, [run.id])

    assert git(git_project.root, "status", "--porcelain=v1") == status_before
    assert (
        git(git_project.root, "worktree", "list", "--porcelain")
        == worktrees_before
    )
    assert temporary_worktrees(git_project) == ()
    assert not (
        git_project.research_commits_dir / "research-commit-001"
    ).exists()


def test_partial_worktree_registration_is_detected_and_removed(
    git_project: ProjectLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = completed_run(git_project)
    original_run = GitAdapter.run
    worktrees_before = git(git_project.root, "worktree", "list", "--porcelain")

    def register_then_report_failure(self, cwd, *args):  # type: ignore[no-untyped-def]
        result = original_run(self, cwd, *args)
        if args[:2] == ("worktree", "add"):
            raise subprocess.CalledProcessError(1, ["git", *args])
        return result

    monkeypatch.setattr(GitAdapter, "run", register_then_report_failure)
    with pytest.raises(subprocess.CalledProcessError):
        create_research_commit(git_project, DRAFT, [run.id])

    monkeypatch.setattr(GitAdapter, "run", original_run)
    assert (
        git(git_project.root, "worktree", "list", "--porcelain")
        == worktrees_before
    )
    assert temporary_worktrees(git_project) == ()


def test_cleanup_fallback_preserves_primary_error(
    git_project: ProjectLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PrimaryFailure(RuntimeError):
        pass

    class RemoveFailure(RuntimeError):
        pass

    run = completed_run(git_project)
    original_run = GitAdapter.run
    worktrees_before = git(git_project.root, "worktree", "list", "--porcelain")

    def fail_commit_and_remove(self, cwd, *args):  # type: ignore[no-untyped-def]
        if args and args[0] == "commit-tree":
            raise PrimaryFailure("primary commit failure")
        if args[:2] == ("worktree", "remove"):
            raise RemoveFailure("normal removal failed")
        return original_run(self, cwd, *args)

    monkeypatch.setattr(GitAdapter, "run", fail_commit_and_remove)
    with pytest.raises(PrimaryFailure, match="primary commit failure"):
        create_research_commit(git_project, DRAFT, [run.id])

    monkeypatch.setattr(GitAdapter, "run", original_run)
    assert (
        git(git_project.root, "worktree", "list", "--porcelain")
        == worktrees_before
    )
    assert temporary_worktrees(git_project) == ()


def test_cleanup_fallback_runs_when_worktree_registry_query_fails(
    git_project: ProjectLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PrimaryFailure(RuntimeError):
        pass

    class RegistryFailure(RuntimeError):
        pass

    run = completed_run(git_project)
    original_run = GitAdapter.run
    worktrees_before = git(git_project.root, "worktree", "list", "--porcelain")
    registry_failed = False

    def fail_commit_and_first_registry_query(  # type: ignore[no-untyped-def]
        self, cwd, *args
    ):
        nonlocal registry_failed
        if args and args[0] == "commit-tree":
            raise PrimaryFailure("primary commit failure")
        if args[:3] == ("worktree", "list", "--porcelain") and not registry_failed:
            registry_failed = True
            raise RegistryFailure("registry query failed")
        return original_run(self, cwd, *args)

    monkeypatch.setattr(GitAdapter, "run", fail_commit_and_first_registry_query)
    with pytest.raises(PrimaryFailure, match="primary commit failure"):
        create_research_commit(git_project, DRAFT, [run.id])

    monkeypatch.setattr(GitAdapter, "run", original_run)
    assert registry_failed
    assert git(git_project.root, "worktree", "list", "--porcelain") == worktrees_before
    assert temporary_worktrees(git_project) == ()


def test_failed_duplicate_promotion_preserves_live_state_and_cleans_worktree(
    git_project: ProjectLayout,
) -> None:
    run = completed_run(git_project)
    first = create_research_commit(git_project, DRAFT, [run.id])
    manifest_path = git_project.research_commits_dir / first.id / "manifest.yaml"
    manifest_bytes = manifest_path.read_bytes()
    ref_sha = git(
        git_project.root,
        "rev-parse",
        "refs/ai4sota/research/research-commit-001",
    )
    staged_before = git(git_project.root, "diff", "--cached")

    with pytest.raises(FileExistsError, match="already exists"):
        create_research_commit(git_project, DRAFT, [run.id])

    assert manifest_path.read_bytes() == manifest_bytes
    assert git(
        git_project.root,
        "rev-parse",
        "refs/ai4sota/research/research-commit-001",
    ) == ref_sha
    assert git(git_project.root, "diff", "--cached") == staged_before
    assert temporary_worktrees(git_project) == ()


def test_concurrent_same_id_promotion_preserves_one_complete_winner(
    git_project: ProjectLayout,
) -> None:
    run = completed_run(git_project)
    barrier = threading.Barrier(2)

    def promote() -> ResearchCommitManifest | Exception:
        barrier.wait()
        try:
            return create_research_commit(git_project, DRAFT, [run.id])
        except Exception as error:  # noqa: BLE001
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(lambda _: promote(), range(2)))

    winners = tuple(
        outcome
        for outcome in outcomes
        if isinstance(outcome, ResearchCommitManifest)
    )
    failures = tuple(outcome for outcome in outcomes if isinstance(outcome, Exception))
    assert len(winners) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], FileExistsError)
    winner = winners[0]
    stored = ManifestStore().read(
        git_project.research_commits_dir / winner.id / "manifest.yaml",
        ResearchCommitManifest,
    )
    assert stored == winner
    assert git(
        git_project.root,
        "rev-parse",
        f"refs/ai4sota/research/{winner.id}",
    ) == winner.git_sha
    assert temporary_worktrees(git_project) == ()


def test_retry_recovers_crash_between_manifest_and_ref_publication(
    git_project: ProjectLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = completed_run(git_project)
    original_write = research_commits._write_research_manifest

    def write_then_crash(path: Path, value: ResearchCommitManifest) -> None:
        original_write(path, value)
        raise SystemExit("simulated process termination")

    monkeypatch.setattr(research_commits, "_write_research_manifest", write_then_crash)
    with pytest.raises(SystemExit, match="simulated process termination"):
        create_research_commit(git_project, DRAFT, [run.id])

    manifest_path = git_project.research_commits_dir / DRAFT["id"] / "manifest.yaml"
    assert manifest_path.exists()
    pending = tuple(
        transaction_dir(git_project).glob("*.yaml")
    )
    assert len(pending) == 1
    assert subprocess.run(
        [
            "git",
            "show-ref",
            "--verify",
            "--quiet",
            "refs/ai4sota/research/research-commit-001",
        ],
        cwd=git_project.root,
        check=False,
    ).returncode != 0

    monkeypatch.setattr(research_commits, "_write_research_manifest", original_write)
    recovered = create_research_commit(git_project, DRAFT, [run.id])

    assert ManifestStore().read(manifest_path, ResearchCommitManifest) == recovered
    assert git(
        git_project.root,
        "rev-parse",
        "refs/ai4sota/research/research-commit-001",
    ) == recovered.git_sha
    assert tuple(
        transaction_dir(git_project).glob("*.yaml")
    ) == ()
    assert temporary_worktrees(git_project) == ()


def test_retry_recovers_crash_after_manifest_and_ref_are_complete(
    git_project: ProjectLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = completed_run(git_project)
    original_remove = research_commits._remove_owned_pending
    crashed = False

    def crash_before_pending_cleanup(path: Path, transaction_id: str) -> None:
        nonlocal crashed
        if not crashed:
            crashed = True
            raise SystemExit("simulated termination after ref publication")
        original_remove(path, transaction_id)

    monkeypatch.setattr(
        research_commits,
        "_remove_owned_pending",
        crash_before_pending_cleanup,
    )
    with pytest.raises(SystemExit, match="after ref publication"):
        create_research_commit(git_project, DRAFT, [run.id])

    assert crashed
    manifest_path = git_project.research_commits_dir / DRAFT["id"] / "manifest.yaml"
    persisted = ManifestStore().read(manifest_path, ResearchCommitManifest)
    assert git(
        git_project.root,
        "rev-parse",
        "refs/ai4sota/research/research-commit-001",
    ) == persisted.git_sha
    assert len(tuple(transaction_dir(git_project).glob("*.yaml"))) == 1

    monkeypatch.setattr(
        research_commits,
        "_remove_owned_pending",
        original_remove,
    )
    recovered = create_research_commit(git_project, DRAFT, [run.id])

    assert recovered == persisted
    assert tuple(transaction_dir(git_project).glob("*.yaml")) == ()


def test_retry_recovers_error_after_manifest_and_ref_are_complete(
    git_project: ProjectLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CleanupFailure(RuntimeError):
        pass

    run = completed_run(git_project)
    original_remove = research_commits._remove_owned_pending
    failed = False

    def fail_first_pending_cleanup(path: Path, transaction_id: str) -> None:
        nonlocal failed
        if not failed:
            failed = True
            raise CleanupFailure("pending cleanup failed")
        original_remove(path, transaction_id)

    monkeypatch.setattr(
        research_commits,
        "_remove_owned_pending",
        fail_first_pending_cleanup,
    )
    with pytest.raises(CleanupFailure, match="pending cleanup failed"):
        create_research_commit(git_project, DRAFT, [run.id])

    assert failed
    manifest_path = git_project.research_commits_dir / DRAFT["id"] / "manifest.yaml"
    persisted = ManifestStore().read(manifest_path, ResearchCommitManifest)
    assert git(
        git_project.root,
        "rev-parse",
        "refs/ai4sota/research/research-commit-001",
    ) == persisted.git_sha
    assert len(tuple(transaction_dir(git_project).glob("*.yaml"))) == 1

    monkeypatch.setattr(
        research_commits,
        "_remove_owned_pending",
        original_remove,
    )
    recovered = create_research_commit(git_project, DRAFT, [run.id])

    assert recovered == persisted
    assert tuple(transaction_dir(git_project).glob("*.yaml")) == ()


def test_rollback_does_not_follow_commit_directory_reparse_race(
    git_project: ProjectLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PublicationFailure(RuntimeError):
        pass

    run = completed_run(git_project)
    outside = git_project.root.parent / "outside-rollback"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    original_run = GitAdapter.run

    def replace_directory_before_ref(self, cwd, *args):  # type: ignore[no-untyped-def]
        if args and args[0] == "update-ref" and "research-commit-001" in args[1]:
            directory = git_project.research_commits_dir / "research-commit-001"
            for child in directory.iterdir():
                child.unlink()
            directory.rmdir()
            linked = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(directory), str(outside)],
                capture_output=True,
                text=True,
                check=False,
            )
            if linked.returncode != 0:
                pytest.skip("directory junction creation is unavailable")
            raise PublicationFailure("ref publication failed after path replacement")
        return original_run(self, cwd, *args)

    monkeypatch.setattr(GitAdapter, "run", replace_directory_before_ref)
    with pytest.raises(PublicationFailure, match="ref publication failed"):
        create_research_commit(git_project, DRAFT, [run.id])

    monkeypatch.setattr(GitAdapter, "run", original_run)
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert tuple(outside.iterdir()) == (sentinel,)
    assert tuple(transaction_dir(git_project).glob("*.yaml")) == ()
    assert subprocess.run(
        [
            "git",
            "show-ref",
            "--verify",
            "--quiet",
            "refs/ai4sota/research/research-commit-001",
        ],
        cwd=git_project.root,
        check=False,
    ).returncode != 0
    assert temporary_worktrees(git_project) == ()
