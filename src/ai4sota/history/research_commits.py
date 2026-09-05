"""Create durable research-history records from immutable Run snapshots."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from ai4sota.domain import ComparabilityState, ProjectSpec, ResearchCommitManifest
from ai4sota.projects import ProjectLayout
from ai4sota.runs import (
    AggregatedResult,
    AggregationError,
    RunRepository,
    aggregate_runs,
    compare_runs,
    verify_run_integrity,
)
from ai4sota.storage import ManifestStore, canonical_manifest_hash

from .git import GitAdapter

ZERO_HASH = "sha256:" + "0" * 64


class ResearchCommitError(ValueError):
    """Raised when Runs cannot be promoted into one research commit."""


def create_research_commit(
    project: ProjectLayout,
    draft: Mapping[str, Any],
    run_ids: Sequence[str],
    aggregation: AggregatedResult | None = None,
) -> ResearchCommitManifest:
    """Commit the selected immutable snapshot without changing the live checkout."""
    requested_ids = tuple(run_ids)
    if not requested_ids:
        raise ResearchCommitError("at least one Run is required")
    if len(set(requested_ids)) != len(requested_ids):
        raise ResearchCommitError("duplicate Run id in research commit")

    repository = RunRepository(project)
    runs = tuple(
        verify_run_integrity(repository.run_dir(run_id)) for run_id in requested_ids
    )
    project_spec = ManifestStore().read(project.project_file, ProjectSpec)
    if project_spec.content_hash != canonical_manifest_hash(project_spec):
        raise ResearchCommitError("project manifest is not integrity verified")
    if any(run.status != "succeeded" or run.integrity_state != "verified" for run in runs):
        raise ResearchCommitError("all selected Runs must be succeeded and verified")
    if any(run.project_id != project_spec.id for run in runs):
        raise ResearchCommitError("selected Runs must belong to the project")
    if any(run.snapshot_hash != runs[0].snapshot_hash for run in runs):
        raise ResearchCommitError("selected Runs must share one exact snapshot")

    comparison_state: str | None = None
    if len(runs) > 1:
        comparison = compare_runs(runs)
        if comparison.state is ComparabilityState.NONE:
            raise ResearchCommitError(
                "selected Runs are not comparable: "
                f"{list(comparison.blocking_fields)}"
            )
        comparison_state = comparison.state.value
    requested_comparison_state = draft.get("comparison_state")
    if (
        requested_comparison_state is not None
        and requested_comparison_state != comparison_state
    ):
        raise ResearchCommitError("draft comparison state does not match Run policy")

    if aggregation is not None:
        try:
            expected_aggregation = aggregate_runs(runs, set(aggregation.dimensions))
        except AggregationError as error:
            raise ResearchCommitError("selected Runs cannot be aggregated") from error
        if expected_aggregation != aggregation:
            raise ResearchCommitError(
                "aggregation does not match the selected Run manifests"
            )

    commit_id = _validate_commit_id(draft.get("id"))
    manifest_path = _manifest_path(project, commit_id)
    if manifest_path.exists():
        raise FileExistsError(f"research commit already exists: {commit_id}")
    project_id = draft.get("project_id", runs[0].project_id)
    if project_id != runs[0].project_id:
        raise ResearchCommitError("draft project does not match selected Runs")

    git = GitAdapter()
    base_sha = git.ensure_repository(project.root, "Initialize AI4SOTA project")
    ref_name = f"refs/ai4sota/research/{commit_id}"
    try:
        git.run(project.root, "show-ref", "--verify", "--quiet", ref_name)
    except subprocess.CalledProcessError:
        pass
    else:
        raise FileExistsError(f"research commit ref already exists: {commit_id}")
    snapshot = repository.run_dir(runs[0].id) / "snapshot"
    _validate_snapshot_tree(snapshot)
    temporary_parent = project.root.parent
    worktree = Path(
        tempfile.mkdtemp(prefix=".ai4sota-research-", dir=temporary_parent)
    )
    registered = False
    try:
        worktree.rmdir()
        git.run(project.root, "worktree", "add", "--detach", str(worktree), base_sha)
        registered = True
        _replace_worktree_contents(worktree, snapshot)
        _stage_exact_tree(git, worktree)
        git.run(
            worktree,
            "commit",
            "--no-verify",
            "-m",
            f"research: {commit_id}",
        )
        git_sha = git.run(worktree, "rev-parse", "HEAD")
    finally:
        if registered:
            git.run(project.root, "worktree", "remove", "--force", str(worktree))
        elif worktree.exists():
            shutil.rmtree(worktree)

    parent_ids = draft.get("parent_research_commit_ids", ())
    if not isinstance(parent_ids, (list, tuple)):
        raise ResearchCommitError("parent research commit ids must be a sequence")
    manifest_draft = ResearchCommitManifest(
        id=commit_id,
        version=str(draft.get("version", "1.0.0")),
        content_hash=ZERO_HASH,
        project_id=str(project_id),
        run_ids=requested_ids,
        run_manifest_hashes=tuple(run.content_hash for run in runs),
        git_sha=git_sha,
        snapshot_hash=runs[0].snapshot_hash,
        parent_research_commit_ids=tuple(parent_ids),
        comparison_state=comparison_state,
        aggregation=(
            aggregation.model_dump(mode="json")
            if aggregation is not None
            else None
        ),
    )
    manifest = manifest_draft.model_copy(
        update={"content_hash": canonical_manifest_hash(manifest_draft)}
    )
    ManifestStore().write(manifest_path, manifest)
    try:
        git.run(
            project.root,
            "update-ref",
            ref_name,
            git_sha,
            "0" * 40,
        )
    except Exception:
        _remove_new_manifest(manifest_path, project.research_commits_dir)
        raise
    return manifest


def _replace_worktree_contents(worktree: Path, snapshot: Path) -> None:
    for child in worktree.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    shutil.copytree(snapshot, worktree, dirs_exist_ok=True)


def _validate_snapshot_tree(snapshot: Path) -> None:
    for path in snapshot.rglob("*"):
        relative = path.relative_to(snapshot)
        if any(part.casefold() == ".git" for part in relative.parts):
            raise ResearchCommitError("Run snapshot cannot contain Git metadata")


def _stage_exact_tree(git: GitAdapter, worktree: Path) -> None:
    git.run(worktree, "read-tree", "--empty")
    for path in sorted(worktree.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or path.name == ".git":
            continue
        relative = path.relative_to(worktree).as_posix()
        mode = "100755" if path.stat().st_mode & 0o111 else "100644"
        blob = git.run(worktree, "hash-object", "-w", "--no-filters", str(path))
        git.run(
            worktree,
            "update-index",
            "--add",
            "--cacheinfo",
            f"{mode},{blob},{relative}",
        )


def _validate_commit_id(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ResearchCommitError("research commit id must be a non-empty string")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or "\\" in value
        or any(part in {"", ".", ".."} for part in path.parts)
        or any(character in value for character in " ~^:?*[\\")
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or ".." in value
        or any(part.startswith(".") for part in path.parts)
        or any(part.endswith((".", ".lock")) for part in path.parts)
        or value.endswith("/")
        or "//" in value
        or "@{" in value
    ):
        raise ResearchCommitError(f"invalid research commit id: {value!r}")
    return value


def _manifest_path(project: ProjectLayout, commit_id: str) -> Path:
    root = Path(os.path.abspath(project.research_commits_dir))
    if _is_link_or_reparse(root) or not root.is_dir():
        raise ResearchCommitError("research commit root cannot contain links")
    path = root.joinpath(*PurePosixPath(commit_id).parts, "manifest.yaml")
    parent = path.parent
    current = root
    for part in parent.relative_to(root).parts:
        current /= part
        if _is_link_or_reparse(current):
            raise ResearchCommitError("research commit path cannot contain links")
    return path


def _remove_new_manifest(path: Path, boundary: Path) -> None:
    path.unlink(missing_ok=True)
    current = path.parent
    resolved_boundary = boundary.resolve()
    while current != resolved_boundary:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def _is_link_or_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(attributes & reparse_flag)


__all__ = ["ResearchCommitError", "create_research_commit"]
