from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ai4sota.domain import ModuleKind, ResearchCommitManifest, RunManifest
from ai4sota.history import GitAdapter, ResearchCommitError, create_research_commit
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


def temporary_worktrees(project: ProjectLayout) -> tuple[Path, ...]:
    return tuple(project.root.parent.glob(".ai4sota-research-*"))


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
