"""Create durable research-history records from immutable Run snapshots."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from types import TracebackType
from typing import Any
from uuid import uuid4

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from ai4sota.domain import (
    ComparabilityState,
    ProjectSpec,
    ResearchCommitManifest,
    RunManifest,
)
from ai4sota.files import StableFile, StableReadError, stable_read_file
from ai4sota.projects import ProjectLayout
from ai4sota.runs import (
    AggregatedResult,
    AggregationError,
    RunRepository,
    aggregate_runs,
    compare_runs,
    hash_tree,
    verify_run_integrity,
)
from ai4sota.storage import (
    atomic_write_bytes,
    canonical_manifest_hash,
    durable_make_directory,
)

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
    project_spec = _load_project_manifest(project.project_file)
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
    project_id = draft.get("project_id", runs[0].project_id)
    if project_id != runs[0].project_id:
        raise ResearchCommitError("draft project does not match selected Runs")

    git = GitAdapter()
    base_sha = _require_existing_head(git, project.root)
    parent_ids = _parent_ids(draft.get("parent_research_commit_ids", ()), runs)
    parents = _load_parents(project, git, parent_ids, project_spec.id)
    ref_name = f"refs/ai4sota/research/{commit_id}"
    with _publication_lock(project, git, commit_id) as pending_path:
        recovered = _recover_pending(project, git, pending_path, commit_id)
        if recovered is not None:
            if _manifest_matches_request(
                recovered,
                draft,
                requested_ids,
                runs,
                parent_ids,
                comparison_state,
                aggregation,
            ):
                return recovered
            raise FileExistsError(f"research commit already exists: {commit_id}")

        manifest_path = _manifest_path(project, commit_id)
        if manifest_path.exists() or _read_ref(git, project.root, ref_name) is not None:
            raise FileExistsError(f"research commit already exists: {commit_id}")

        snapshot = repository.run_dir(runs[0].id) / "snapshot"
        git_sha = _create_git_commit(
            project,
            git,
            snapshot,
            runs[0].snapshot_hash,
            commit_id,
            base_sha,
            tuple(parent.git_sha for parent in parents),
        )
        manifest_draft = ResearchCommitManifest(
            id=commit_id,
            version=str(draft.get("version", "1.0.0")),
            content_hash=ZERO_HASH,
            project_id=str(project_id),
            run_ids=requested_ids,
            run_manifest_hashes=tuple(run.content_hash for run in runs),
            git_sha=git_sha,
            snapshot_hash=runs[0].snapshot_hash,
            parent_research_commit_ids=parent_ids,
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
        transaction_id = uuid4().hex
        _write_pending(pending_path, transaction_id, manifest)
        try:
            _publish_transaction(
                project,
                git,
                pending_path,
                transaction_id,
                manifest,
                "0" * len(base_sha),
            )
        except Exception as publication_error:
            if _publication_is_complete(project, git, manifest):
                raise
            try:
                _rollback_transaction(
                    project, git, pending_path, transaction_id, manifest
                )
            except Exception as rollback_error:  # noqa: BLE001
                publication_error.add_note(
                    f"research transaction rollback was incomplete: {rollback_error}"
                )
            raise
        return manifest


def _require_existing_head(git: GitAdapter, root: Path) -> str:
    _reject_link_components(root)
    git_entry = root / ".git"
    if not git_entry.exists() or _is_link_or_reparse(git_entry):
        raise ResearchCommitError("promotion requires an existing Git repository")
    try:
        top_level = Path(git.run(root, "rev-parse", "--show-toplevel"))
        head = git.run(root, "rev-parse", "--verify", "HEAD")
    except subprocess.CalledProcessError as error:
        raise ResearchCommitError(
            "promotion requires an existing repository with a valid HEAD"
        ) from error
    if Path(os.path.abspath(top_level)) != Path(os.path.abspath(root)):
        raise ResearchCommitError("Git repository root does not match the project root")
    return head


def _create_git_commit(
    project: ProjectLayout,
    git: GitAdapter,
    snapshot: Path,
    snapshot_hash: str,
    commit_id: str,
    base_sha: str,
    parent_shas: tuple[str, ...],
) -> str:
    temporary_root = Path(
        tempfile.mkdtemp(prefix=".ai4sota-research-", dir=project.root.parent)
    )
    materialized = temporary_root / "snapshot"
    worktree = temporary_root / "worktree"
    result: str | None = None
    primary_error: BaseException | None = None
    primary_traceback: TracebackType | None = None
    try:
        _materialize_verified_snapshot(snapshot, materialized, snapshot_hash)
        git.run(project.root, "worktree", "add", "--detach", str(worktree), base_sha)
        _stage_exact_tree(git, worktree, materialized)
        tree_sha = git.run(worktree, "write-tree")
        commit_args: list[str] = ["commit-tree", tree_sha]
        for parent_sha in parent_shas or (base_sha,):
            commit_args.extend(("-p", parent_sha))
        commit_args.extend(("-m", f"research: {commit_id}"))
        result = git.run(worktree, *commit_args)
    except BaseException as error:  # noqa: BLE001
        primary_error = error
        primary_traceback = error.__traceback__

    cleanup_error: Exception | None = None
    try:
        _cleanup_temporary_worktree(project, git, temporary_root, worktree)
    except Exception as error:  # noqa: BLE001
        cleanup_error = error

    if primary_error is not None:
        if cleanup_error is not None:
            primary_error.add_note(f"temporary worktree cleanup failed: {cleanup_error}")
        raise primary_error.with_traceback(primary_traceback)
    if cleanup_error is not None:
        raise cleanup_error
    if result is None:
        raise RuntimeError("research commit creation produced no Git object")
    return result


def _cleanup_temporary_worktree(
    project: ProjectLayout,
    git: GitAdapter,
    temporary_root: Path,
    worktree: Path,
) -> None:
    remove_error: Exception | None = None
    try:
        registered: bool | None = _is_registered_worktree(project, git, worktree)
    except Exception as error:  # noqa: BLE001
        registered = None
        remove_error = error
    if registered is not False:
        try:
            git.run(project.root, "worktree", "remove", "--force", str(worktree))
        except Exception as error:  # noqa: BLE001
            remove_error = error
    if temporary_root.exists():
        _remove_trusted_temporary_root(project, temporary_root)

    try:
        still_registered = _is_registered_worktree(project, git, worktree)
    except Exception as error:  # noqa: BLE001
        still_registered = True
        remove_error = error
    if still_registered:
        try:
            git.run(project.root, "worktree", "prune", "--expire", "now")
        except Exception as error:  # noqa: BLE001
            remove_error = error
        try:
            still_registered = _is_registered_worktree(project, git, worktree)
        except Exception as error:  # noqa: BLE001
            still_registered = True
            remove_error = error
    if temporary_root.exists() or still_registered:
        if remove_error is not None:
            raise ResearchCommitError("temporary worktree cleanup failed") from remove_error
        raise ResearchCommitError("temporary worktree cleanup could not be verified")


def _is_registered_worktree(
    project: ProjectLayout,
    git: GitAdapter,
    worktree: Path,
) -> bool:
    target = os.path.normcase(os.path.abspath(worktree))
    output = git.run(project.root, "worktree", "list", "--porcelain")
    return any(
        os.path.normcase(os.path.abspath(line.removeprefix("worktree "))) == target
        for line in output.splitlines()
        if line.startswith("worktree ")
    )


def _remove_trusted_temporary_root(project: ProjectLayout, path: Path) -> None:
    parent = Path(os.path.abspath(project.root.parent))
    candidate = Path(os.path.abspath(path))
    if (
        candidate.parent != parent
        or not candidate.name.startswith(".ai4sota-research-")
        or _is_link_or_reparse(candidate)
    ):
        raise ResearchCommitError("refusing to remove untrusted temporary path")
    shutil.rmtree(candidate)


@contextmanager
def _publication_lock(
    project: ProjectLayout,
    git: GitAdapter,
    commit_id: str,
) -> Iterator[Path]:
    transaction_root = _transaction_root(project, git)
    key = hashlib.sha256(commit_id.encode("utf-8")).hexdigest()
    lock_path = transaction_root / f"{key}.lock"
    pending_path = transaction_root / f"{key}.pending.yaml"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(lock_path, flags, 0o600)
        opened = os.fstat(descriptor)
        current = lock_path.lstat()
        if (
            not stat.S_ISREG(opened.st_mode)
            or _is_link_or_reparse(lock_path)
            or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
        ):
            raise ResearchCommitError("research publication lock is not a stable file")
    except ResearchCommitError:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    except OSError as error:
        if descriptor >= 0:
            os.close(descriptor)
        raise ResearchCommitError("cannot open research publication lock") from error
    with os.fdopen(descriptor, "r+b") as stream:
        if lock_path.stat().st_size == 0:
            stream.write(b"\0")
            stream.flush()
            os.fsync(stream.fileno())
        stream.seek(0)
        _lock_file(stream.fileno())
        try:
            yield pending_path
        finally:
            stream.seek(0)
            _unlock_file(stream.fileno())


def _transaction_root(project: ProjectLayout, git: GitAdapter) -> Path:
    raw = Path(
        git.run(
            project.root,
            "rev-parse",
            "--git-path",
            "ai4sota/research-transactions",
        )
    )
    root = raw if raw.is_absolute() else project.root / raw
    root = Path(os.path.abspath(root))
    _reject_link_components(root)
    durable_make_directory(root)
    _reject_link_components(root)
    return root


def _write_pending(
    path: Path,
    transaction_id: str,
    manifest: ResearchCommitManifest,
) -> None:
    document = {
        "transaction_id": transaction_id,
        "commit_id": manifest.id,
        "manifest": manifest.model_dump(mode="json"),
    }
    data = yaml.safe_dump(document, allow_unicode=True, sort_keys=False).encode("utf-8")
    _write_exclusive_bytes(path, data)


def _recover_pending(
    project: ProjectLayout,
    git: GitAdapter,
    pending_path: Path,
    commit_id: str,
) -> ResearchCommitManifest | None:
    if not pending_path.exists() and not _is_link_or_reparse(pending_path):
        return None
    try:
        document = yaml.safe_load(stable_read_file(pending_path).data.decode("utf-8"))
        if not isinstance(document, Mapping):
            raise TypeError("pending transaction must be a mapping")
        transaction_id = document["transaction_id"]
        pending_id = document["commit_id"]
        manifest = ResearchCommitManifest.model_validate(document["manifest"])
    except (
        KeyError,
        OSError,
        StableReadError,
        UnicodeError,
        TypeError,
        yaml.YAMLError,
        ValidationError,
    ) as error:
        raise ResearchCommitError("pending research transaction is invalid") from error
    if (
        not isinstance(transaction_id, str)
        or len(transaction_id) != 32
        or pending_id != commit_id
        or manifest.id != commit_id
        or manifest.content_hash != canonical_manifest_hash(manifest)
    ):
        raise ResearchCommitError("pending research transaction is inconsistent")
    try:
        git.run(project.root, "cat-file", "-e", f"{manifest.git_sha}^{{commit}}")
    except subprocess.CalledProcessError as error:
        raise ResearchCommitError("pending research commit object is missing") from error
    _publish_transaction(
        project,
        git,
        pending_path,
        transaction_id,
        manifest,
        "0" * len(manifest.git_sha),
    )
    return manifest


def _publish_transaction(
    project: ProjectLayout,
    git: GitAdapter,
    pending_path: Path,
    transaction_id: str,
    manifest: ResearchCommitManifest,
    zero_oid: str,
) -> None:
    manifest_path = _manifest_path(project, manifest.id)
    owner_path = _reserve_manifest_directory(manifest_path, transaction_id, manifest)
    if manifest_path.exists():
        if _load_research_manifest(manifest_path, "research commit") != manifest:
            raise ResearchCommitError("research commit manifest publication conflict")
    else:
        _write_research_manifest(manifest_path, manifest)

    ref_name = f"refs/ai4sota/research/{manifest.id}"
    ref_sha = _read_ref(git, project.root, ref_name)
    if ref_sha is None:
        git.run(project.root, "update-ref", ref_name, manifest.git_sha, zero_oid)
    elif ref_sha != manifest.git_sha:
        raise ResearchCommitError("research commit ref publication conflict")

    if owner_path.exists():
        _remove_owned_file(owner_path, transaction_id.encode("ascii"))
    _remove_owned_pending(pending_path, transaction_id)


def _publication_is_complete(
    project: ProjectLayout,
    git: GitAdapter,
    manifest: ResearchCommitManifest,
) -> bool:
    try:
        persisted = _load_research_manifest(
            _manifest_path(project, manifest.id), "research commit"
        )
        ref_sha = _read_ref(
            git,
            project.root,
            f"refs/ai4sota/research/{manifest.id}",
        )
    except Exception:  # noqa: BLE001
        return False
    return persisted == manifest and ref_sha == manifest.git_sha


def _reserve_manifest_directory(
    manifest_path: Path,
    transaction_id: str,
    manifest: ResearchCommitManifest,
) -> Path:
    directory = manifest_path.parent
    owner_path = directory / ".publication-owner"
    if not directory.exists():
        durable_make_directory(directory.parent)
        _reject_link_components(directory.parent)
        try:
            directory.mkdir()
        except FileExistsError:
            pass
        else:
            _write_exclusive_bytes(owner_path, transaction_id.encode("ascii"))
            return owner_path
    if _is_link_or_reparse(directory) or not directory.is_dir():
        raise ResearchCommitError("research commit directory cannot contain links")
    if owner_path.exists():
        if stable_read_file(owner_path).data != transaction_id.encode("ascii"):
            raise ResearchCommitError("research commit directory has another owner")
        return owner_path
    if manifest_path.exists() and _load_research_manifest(
        manifest_path, "research commit"
    ) == manifest:
        return owner_path
    raise ResearchCommitError("research commit directory is not transaction-owned")


def _rollback_transaction(
    project: ProjectLayout,
    git: GitAdapter,
    pending_path: Path,
    transaction_id: str,
    manifest: ResearchCommitManifest,
) -> None:
    ref_name = f"refs/ai4sota/research/{manifest.id}"
    try:
        if _read_ref(git, project.root, ref_name) == manifest.git_sha:
            git.run(project.root, "update-ref", "-d", ref_name, manifest.git_sha)
    except Exception:  # noqa: BLE001,S110
        pass
    try:
        manifest_path = _manifest_path(project, manifest.id)
        owner_path = manifest_path.parent / ".publication-owner"
        try:
            owned = (
                owner_path.exists()
                and stable_read_file(owner_path).data
                == transaction_id.encode("ascii")
            )
            if (
                owned
                and manifest_path.exists()
                and _load_research_manifest(manifest_path, "research commit")
                == manifest
            ):
                manifest_path.unlink()
            if owned:
                _remove_owned_file(owner_path, transaction_id.encode("ascii"))
                manifest_path.parent.rmdir()
        except (OSError, StableReadError, ResearchCommitError):
            pass
    finally:
        _remove_owned_pending(pending_path, transaction_id)


def _read_ref(git: GitAdapter, root: Path, ref_name: str) -> str | None:
    try:
        return git.run(root, "show-ref", "--verify", "--hash", ref_name)
    except subprocess.CalledProcessError:
        return None


def _manifest_matches_request(
    manifest: ResearchCommitManifest,
    draft: Mapping[str, Any],
    requested_ids: tuple[str, ...],
    runs: Sequence[RunManifest],
    parent_ids: tuple[str, ...],
    comparison_state: str | None,
    aggregation: AggregatedResult | None,
) -> bool:
    expected_aggregation = (
        aggregation.model_dump(mode="json") if aggregation is not None else None
    )
    return (
        manifest.id == draft.get("id")
        and manifest.version == str(draft.get("version", "1.0.0"))
        and manifest.project_id == draft.get("project_id", runs[0].project_id)
        and manifest.run_ids == requested_ids
        and manifest.run_manifest_hashes
        == tuple(run.content_hash for run in runs)
        and manifest.snapshot_hash == runs[0].snapshot_hash
        and manifest.parent_research_commit_ids == parent_ids
        and manifest.comparison_state == comparison_state
        and manifest.aggregation == expected_aggregation
    )


def _load_research_manifest(path: Path, label: str) -> ResearchCommitManifest:
    try:
        document = yaml.safe_load(stable_read_file(path).data.decode("utf-8"))
        manifest = ResearchCommitManifest.model_validate(document)
    except (
        OSError,
        StableReadError,
        UnicodeError,
        yaml.YAMLError,
        ValidationError,
    ) as error:
        raise ResearchCommitError(f"{label} manifest cannot be verified") from error
    if manifest.content_hash != canonical_manifest_hash(manifest):
        raise ResearchCommitError(f"{label} manifest hash mismatch")
    return manifest


def _load_project_manifest(path: Path) -> ProjectSpec:
    try:
        document = yaml.safe_load(stable_read_file(path).data.decode("utf-8"))
        project = ProjectSpec.model_validate(document)
    except (
        OSError,
        StableReadError,
        UnicodeError,
        yaml.YAMLError,
        ValidationError,
    ) as error:
        raise ResearchCommitError("project manifest cannot be verified") from error
    if project.content_hash != canonical_manifest_hash(project):
        raise ResearchCommitError("project manifest is not integrity verified")
    return project


def _write_research_manifest(
    path: Path,
    manifest: ResearchCommitManifest,
) -> None:
    data = yaml.safe_dump(
        manifest.model_dump(mode="json"),
        allow_unicode=True,
        sort_keys=False,
    ).encode("utf-8")
    _reject_link_components(path.parent)
    _write_exclusive_bytes(path, data)


def _write_exclusive_bytes(path: Path, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    opened = os.fstat(descriptor)
    current = path.lstat()
    if (
        not stat.S_ISREG(opened.st_mode)
        or _is_link_or_reparse(path)
        or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
    ):
        os.close(descriptor)
        raise ResearchCommitError("exclusive transaction file is not stable")
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _remove_owned_file(path: Path, expected: bytes) -> None:
    if not path.exists() or stable_read_file(path).data != expected:
        raise ResearchCommitError("refusing to remove a file not owned by transaction")
    path.unlink()


def _remove_owned_pending(path: Path, transaction_id: str) -> None:
    document = yaml.safe_load(stable_read_file(path).data.decode("utf-8"))
    if not isinstance(document, Mapping) or document.get("transaction_id") != transaction_id:
        raise ResearchCommitError("pending transaction ownership changed")
    path.unlink()


def _reject_link_components(path: Path) -> None:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if _is_link_or_reparse(current):
            raise ResearchCommitError(f"trusted path contains links: {current}")


def _lock_file(file_descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(file_descriptor, msvcrt.LK_LOCK, 1)
        return
    import fcntl

    fcntl.flock(file_descriptor, fcntl.LOCK_EX)  # type: ignore[attr-defined]


def _unlock_file(file_descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(file_descriptor, msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(file_descriptor, fcntl.LOCK_UN)  # type: ignore[attr-defined]


def _parent_ids(raw: object, runs: Sequence[RunManifest]) -> tuple[str, ...]:
    if not isinstance(raw, (list, tuple)):
        raise ResearchCommitError("parent research commit ids must be a sequence")
    parent_ids = tuple(raw)
    if any(not isinstance(parent_id, str) for parent_id in parent_ids):
        raise ResearchCommitError("parent research commit ids must be strings")
    if len(set(parent_ids)) != len(parent_ids):
        raise ResearchCommitError("duplicate parent research commit id")
    try:
        validated = tuple(_validate_commit_id(parent_id) for parent_id in parent_ids)
    except ResearchCommitError as error:
        raise ResearchCommitError("invalid parent research commit id") from error
    run_parents = {
        run.parent_research_commit
        for run in runs
        if run.parent_research_commit is not None
    }
    if run_parents != set(validated):
        raise ResearchCommitError(
            "parent research commit ids do not match selected Run provenance"
        )
    return validated


def _load_parents(
    project: ProjectLayout,
    git: GitAdapter,
    parent_ids: Sequence[str],
    project_id: str,
) -> tuple[ResearchCommitManifest, ...]:
    parents: list[ResearchCommitManifest] = []
    for parent_id in parent_ids:
        path = _manifest_path(project, parent_id)
        parent = _load_research_manifest(path, "parent research commit")
        if parent.id != parent_id:
            raise ResearchCommitError("parent research commit id is inconsistent")
        if parent.project_id != project_id:
            raise ResearchCommitError("parent research commit belongs to another project")
        try:
            ref_sha = git.run(
                project.root,
                "rev-parse",
                f"refs/ai4sota/research/{parent_id}",
            )
        except subprocess.CalledProcessError as error:
            raise ResearchCommitError("parent research commit ref is missing") from error
        if ref_sha != parent.git_sha:
            raise ResearchCommitError("parent research commit ref disagrees with manifest")
        parents.append(parent)
    return tuple(parents)


def _materialize_verified_snapshot(
    snapshot: Path,
    destination: Path,
    expected_hash: str,
) -> None:
    _reject_link_components(snapshot)
    if _is_link_or_reparse(snapshot) or not snapshot.is_dir():
        raise ResearchCommitError("Run snapshot root must be a real directory")
    destination.mkdir()
    try:
        paths = sorted(snapshot.rglob("*"), key=lambda item: item.as_posix())
        for path in paths:
            relative = path.relative_to(snapshot)
            if any(part.casefold() == ".git" for part in relative.parts):
                raise ResearchCommitError("Run snapshot cannot contain Git metadata")
            if _is_link_or_reparse(path):
                raise ResearchCommitError("Run snapshot cannot contain links")
            target = destination / relative
            if path.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif path.is_file():
                value = _read_snapshot_file(path)
                atomic_write_bytes(target, value.data)
        if hash_tree(destination) != expected_hash:
            raise ResearchCommitError("Run snapshot changed during materialization")
    except ResearchCommitError:
        raise
    except (OSError, StableReadError) as error:
        raise ResearchCommitError(
            "Run snapshot changed during materialization"
        ) from error


def _read_snapshot_file(path: Path) -> StableFile:
    return stable_read_file(path)


def _stage_exact_tree(git: GitAdapter, worktree: Path, source: Path) -> None:
    git.run(worktree, "read-tree", "--empty")
    for path in sorted(source.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file():
            continue
        relative = path.relative_to(source).as_posix()
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
    _reject_link_components(root)
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


def _is_link_or_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(attributes & reparse_flag)


__all__ = ["ResearchCommitError", "create_research_commit"]
