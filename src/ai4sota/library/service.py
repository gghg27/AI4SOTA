"""Durable, local-only publication and import of module trees."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Self
from uuid import uuid4

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from ai4sota.domain import (
    DataModuleSpec,
    DatasetSourceSpec,
    EvaluationSpec,
    MethodSpec,
    ModuleKind,
    PreprocessingSpec,
)
from ai4sota.domain.common import OriginType
from ai4sota.files.stable import StableReadError, stable_read_file
from ai4sota.projects import ProjectLayout
from ai4sota.storage import ManifestStore, atomic_write_bytes, canonical_manifest_hash
from ai4sota.storage.atomic import durable_make_directory, durable_replace

from .models import (
    LibraryValidationError,
    ModuleDraft,
    ModuleNotFound,
    PublishConflict,
    PublishedModule,
    VersionExists,
)

_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_VERSION_PATTERN = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\Z"
)
_PUBLICATION_RECORD = ".ai4sota-publication.json"
ModuleSchema = DataModuleSpec | EvaluationSpec | MethodSpec
_MODELS: dict[ModuleKind, type[ModuleSchema]] = {
    ModuleKind.DATA: DataModuleSpec,
    ModuleKind.METHOD: MethodSpec,
    ModuleKind.EVALUATION: EvaluationSpec,
}


@dataclass(frozen=True)
class _DirectoryIdentity:
    path: Path
    device: int
    inode: int


@dataclass(frozen=True)
class _TreeEntry:
    path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class _VerifiedPublication:
    root: _DirectoryIdentity
    content_hash: str


def hash_tree(path: Path) -> str:
    """Hash payload bytes, excluding the non-circular publication record."""
    _, digest = _tree_inventory(path)
    return digest


class ModuleLibrary:
    """Filesystem-backed global module library with immutable published versions."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def read(self, ref: str) -> PublishedModule:
        kind, name, version = _parse_ref(ref)
        root = _safe_existing_or_missing_directory(self.root)
        path = _safe_child(root, kind.value, name, version)
        if not path.exists():
            raise ModuleNotFound(ref)
        _validate_module_tree(path, kind, f"{kind.value}/{name}", version, True)
        verified = _verify_publication_tree(path, ref)
        _after_publication_verified(path)
        return PublishedModule(ref=ref, content_hash=verified.content_hash, path=path)

    def create_draft(self, ref: str) -> ModuleDraft:
        published = self.read(ref)
        kind, name, version = _parse_ref(ref)
        root = _safe_existing_directory(self.root)
        drafts_root = _safe_child(root, ".drafts", kind.value, name)
        _safe_create_directory(drafts_root)
        draft_path = _safe_child(drafts_root, f"{version}-{uuid4().hex}")
        draft_identity = _copy_tree(published.path, draft_path)
        _verify_publication_tree(draft_path, ref)
        _require_directory_identity(draft_identity)
        _safe_unlink(draft_path / _PUBLICATION_RECORD)
        if hash_tree(draft_path) != published.content_hash:
            raise LibraryValidationError("draft copy does not match published payload")
        return ModuleDraft(path=draft_path, module_id=f"{kind.value}/{name}", version=version)

    def publish(self, draft: ModuleDraft, expected_hash: str) -> PublishedModule:
        kind, name = _parse_module_id(draft.module_id)
        _validate_version(draft.version)
        actual_hash = hash_tree(draft.path)
        if actual_hash != expected_hash:
            raise PublishConflict(expected_hash, actual_hash)
        _validate_module_tree(draft.path, kind, draft.module_id, draft.version, False)

        root = _safe_create_directory(self.root)
        destination = _safe_child(root, kind.value, name, draft.version)
        _safe_create_directory(destination.parent)
        destination_parent_identity = _capture_directory(destination.parent)
        lock = _safe_child(root, ".locks", kind.value, name, f"{draft.version}.lock")
        with _PublicationLock(lock, draft.ref):
            _cleanup_interrupted_staging(destination.parent, destination.name)
            if destination.exists():
                raise VersionExists(draft.ref)
            staged = _safe_child(
                destination.parent, f".{destination.name}.{uuid4().hex}.staging"
            )
            staged_identity: _DirectoryIdentity | None = None
            try:
                staged_identity = _copy_tree(draft.path, staged)
                if hash_tree(staged) != actual_hash:
                    raise LibraryValidationError("staged module tree does not match draft")
                _validate_module_tree(staged, kind, draft.module_id, draft.version, False)
                _write_publication_record(staged, draft.ref)
                _verify_publication_tree(staged, draft.ref)
                _require_directory_identity(destination_parent_identity)
                _before_publish_rename(staged, destination)
                _require_directory_identity(staged_identity)
                if destination.exists():
                    raise VersionExists(draft.ref)
                durable_replace(staged, destination)
            except Exception:
                if staged_identity is not None:
                    _remove_staging_tree(staged, staged_identity)
                if destination.exists():
                    raise VersionExists(draft.ref) from None
                raise
        return self.read(draft.ref)

    def import_version(self, ref: str, project: ProjectLayout) -> Path:
        published = self.read(ref)
        kind, _, _ = _parse_ref(ref)
        project_root = _safe_existing_directory(project.root)
        target = _safe_child(project_root, "modules", kind.value, "current")
        target_identity = _capture_directory(target)
        target_parent_identity = _capture_directory(target.parent)
        if any(target.iterdir()):
            raise LibraryValidationError(
                f"project module directory is not empty: {target}"
            )

        staged = _safe_child(target.parent, f".{target.name}.{uuid4().hex}.staging")
        backup = _safe_child(target.parent, f".{target.name}.{uuid4().hex}.backup")
        staged_identity: _DirectoryIdentity | None = None
        try:
            staged_identity = _copy_tree(published.path, staged)
            _verify_publication_tree(staged, ref)
            _safe_unlink(staged / _PUBLICATION_RECORD)
            model = _read_module_manifest(staged / "module.yaml", kind)
            origin = model.origin.model_copy(
                update={"type": OriginType.IMPORTED, "based_on": ref}
            )
            updated = model.model_copy(
                update={"origin": origin, "content_hash": "sha256:" + "0" * 64}
            )
            updated = updated.model_copy(
                update={"content_hash": canonical_manifest_hash(updated)}
            )
            ManifestStore().write(staged / "module.yaml", updated)
            _validate_module_tree(staged, kind, updated.id, updated.version, False)
            _require_directory_identity(target_identity)
            _require_directory_identity(target_parent_identity)
            try:
                durable_replace(target, backup)
            except Exception:
                _restore_original_directory(
                    target, backup, target_identity, None, target_parent_identity
                )
                raise
            if not _matches_directory_identity(backup, target_identity):
                raise LibraryValidationError("original project module identity was lost")
            _require_directory_identity(target_parent_identity)
            _before_import_rename(staged, target)
            _require_directory_identity(staged_identity)
            try:
                durable_replace(staged, target)
            except Exception:
                _restore_original_directory(
                    target,
                    backup,
                    target_identity,
                    staged_identity,
                    target_parent_identity,
                )
                raise
            _capture_directory(backup)
            backup.rmdir()
        except Exception:
            if staged_identity is not None:
                _remove_staging_tree(staged, staged_identity)
            if _matches_directory_identity(backup, target_identity) and not _matches_directory_identity(
                target, target_identity
            ):
                _restore_original_directory(
                    target,
                    backup,
                    target_identity,
                    staged_identity,
                    target_parent_identity,
                )
            raise
        return target


def _parse_ref(ref: str) -> tuple[ModuleKind, str, str]:
    if ref.count("@") != 1:
        raise LibraryValidationError(f"invalid module reference: {ref}")
    module_id, version = ref.split("@", maxsplit=1)
    kind, name = _parse_module_id(module_id)
    _validate_version(version)
    return kind, name, version


def _parse_module_id(module_id: str) -> tuple[ModuleKind, str]:
    parts = module_id.split("/")
    if len(parts) != 2:
        raise LibraryValidationError(f"invalid module id: {module_id}")
    try:
        kind = ModuleKind(parts[0])
    except ValueError as error:
        raise LibraryValidationError(f"unsupported module kind: {parts[0]}") from error
    if _NAME_PATTERN.fullmatch(parts[1]) is None:
        raise LibraryValidationError(f"invalid module id: {module_id}")
    return kind, parts[1]


def _validate_version(version: str) -> None:
    if _VERSION_PATTERN.fullmatch(version) is None:
        raise LibraryValidationError(f"invalid semantic version: {version}")


def _validate_module_tree(
    root: Path,
    kind: ModuleKind,
    module_id: str,
    version: str,
    allows_publication_record: bool,
) -> ModuleSchema:
    _capture_directory(root)
    record = _safe_child(root, _PUBLICATION_RECORD)
    if record.exists() and not allows_publication_record:
        raise LibraryValidationError("draft tree cannot contain a publication record")
    hash_tree(root)
    model = _read_module_manifest(_safe_child(root, "module.yaml"), kind)
    if model.id != module_id or model.version != version:
        raise LibraryValidationError(
            f"module manifest does not match requested version: {module_id}@{version}"
        )
    if model.content_hash != canonical_manifest_hash(model):
        raise LibraryValidationError("module manifest content_hash is not canonical")
    _validate_kind_closure(root, model)
    return model


def _validate_kind_closure(root: Path, model: ModuleSchema) -> None:
    if isinstance(model, DataModuleSpec):
        source = _read_referenced_manifest(
            root, model.source, DatasetSourceSpec, "dataset source"
        )
        preprocessing = _read_referenced_manifest(
            root, model.preprocessing, PreprocessingSpec, "preprocessing"
        )
        if source.content_hash != canonical_manifest_hash(source):
            raise LibraryValidationError("dataset source content_hash is not canonical")
        if preprocessing.content_hash != canonical_manifest_hash(preprocessing):
            raise LibraryValidationError("preprocessing content_hash is not canonical")
        _resolve_entrypoint(root, model.entrypoint, "data entrypoint")
    elif isinstance(model, MethodSpec):
        _resolve_entrypoint(root, model.entrypoint, "method entrypoint")
    else:
        _resolve_entrypoint(root, model.entrypoint, "evaluation entrypoint")
        for metric in model.metrics:
            _resolve_entrypoint(root, metric.implementation, "metric implementation")


def _read_referenced_manifest(
    root: Path,
    reference: str,
    model: type[DatasetSourceSpec | PreprocessingSpec],
    label: str,
) -> DatasetSourceSpec | PreprocessingSpec:
    path = _resolve_regular_reference(root, reference, label)
    try:
        value = yaml.safe_load(stable_read_file(path).data)
        return model.model_validate(value)
    except (StableReadError, ValidationError, yaml.YAMLError) as error:
        raise LibraryValidationError(f"invalid {label} manifest: {path}") from error


def _resolve_entrypoint(root: Path, entrypoint: str, label: str) -> Path:
    parts = entrypoint.split(":")
    if len(parts) != 2 or not all(parts):
        raise LibraryValidationError(f"{label} must use module:callable syntax")
    module_name = parts[0]
    if "/" in module_name or "\\" in module_name:
        raise LibraryValidationError(f"{label} must resolve inside the module tree")
    names = module_name.split(".")
    if any(_NAME_PATTERN.fullmatch(name) is None for name in names):
        raise LibraryValidationError(f"{label} must resolve inside the module tree")
    return _resolve_regular_reference(root, "/".join(names) + ".py", label)


def _resolve_regular_reference(root: Path, reference: str, label: str) -> Path:
    candidate_path = Path(reference)
    if (
        not reference
        or candidate_path.is_absolute()
        or candidate_path.drive
        or "\\" in reference
        or any(part in {"", ".", ".."} for part in candidate_path.parts)
    ):
        raise LibraryValidationError(f"{label} must be a canonical in-tree path")
    root_path = _safe_existing_directory(root)
    candidate = _safe_child(root_path, *candidate_path.parts)
    try:
        stable_read_file(candidate)
    except (FileNotFoundError, StableReadError) as error:
        raise LibraryValidationError(f"{label} must be a regular in-tree file") from error
    return candidate


def _read_module_manifest(path: Path, kind: ModuleKind) -> ModuleSchema:
    try:
        stable = stable_read_file(path)
        value = yaml.safe_load(stable.data)
        return _MODELS[kind].model_validate(value)
    except (StableReadError, ValidationError, yaml.YAMLError) as error:
        raise LibraryValidationError(f"invalid module manifest: {path}") from error


def _tree_inventory(root: Path) -> tuple[tuple[_TreeEntry, ...], str]:
    identity = _capture_directory(root)
    entries: list[_TreeEntry] = []
    digest = hashlib.sha256()
    for file_path in _iter_regular_files(root):
        relative = file_path.relative_to(root).as_posix()
        if relative == _PUBLICATION_RECORD:
            continue
        try:
            stable = stable_read_file(file_path)
        except StableReadError as error:
            raise LibraryValidationError(str(error)) from error
        path_bytes = relative.encode("utf-8")
        digest.update(len(path_bytes).to_bytes(8, "big"))
        digest.update(path_bytes)
        digest.update(len(stable.data).to_bytes(8, "big"))
        digest.update(stable.data)
        entries.append(_TreeEntry(relative, stable.sha256, len(stable.data)))
        _require_directory_identity(identity)
    if not entries:
        raise LibraryValidationError(f"module tree is empty: {root}")
    _require_directory_identity(identity)
    return tuple(entries), f"sha256:{digest.hexdigest()}"


def _write_publication_record(root: Path, ref: str) -> None:
    entries, digest = _tree_inventory(root)
    record = {
        "api_version": "ai4sota/library-publication/v1",
        "ref": ref,
        "tree_hash": digest,
        "inventory": [entry.__dict__ for entry in entries],
    }
    atomic_write_bytes(
        _safe_child(root, _PUBLICATION_RECORD),
        (json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8"),
    )


def _verify_publication_tree(root: Path, ref: str) -> _VerifiedPublication:
    identity = _capture_directory(root)
    record_path = _safe_child(root, _PUBLICATION_RECORD)
    try:
        record = json.loads(stable_read_file(record_path).data)
        entries, digest = _tree_inventory(root)
    except (StableReadError, json.JSONDecodeError, LibraryValidationError) as error:
        raise LibraryValidationError("publication integrity check failed") from error
    expected_inventory = [entry.__dict__ for entry in entries]
    if (
        not isinstance(record, dict)
        or record.get("api_version") != "ai4sota/library-publication/v1"
        or record.get("ref") != ref
        or record.get("tree_hash") != digest
        or record.get("inventory") != expected_inventory
    ):
        raise LibraryValidationError("publication integrity check failed")
    _require_directory_identity(identity)
    return _VerifiedPublication(root=identity, content_hash=digest)


def _after_publication_verified(path: Path) -> None:
    """Test seam for changes arriving after an anchored publication verification."""


def _before_publish_rename(staged: Path, destination: Path) -> None:
    """Test seam immediately before a verified staged publication is renamed."""


def _before_import_rename(staged: Path, target: Path) -> None:
    """Test seam immediately before a verified staged import is renamed."""


def _after_staging_directory_created(staged: Path) -> None:
    """Test seam after a new staging directory has an anchored identity."""


def _iter_regular_files(root: Path) -> list[Path]:
    files: list[Path] = []

    def visit(directory: Path) -> None:
        try:
            entries = sorted(directory.iterdir(), key=lambda entry: entry.name)
        except OSError as error:
            raise LibraryValidationError(f"cannot inspect module tree: {directory}") from error
        for entry in entries:
            try:
                metadata = entry.lstat()
            except OSError as error:
                raise LibraryValidationError(f"cannot inspect module entry: {entry}") from error
            if stat.S_ISLNK(metadata.st_mode) or _is_reparse(metadata):
                raise LibraryValidationError(f"module tree contains a link: {entry}")
            if stat.S_ISDIR(metadata.st_mode):
                visit(entry)
            elif stat.S_ISREG(metadata.st_mode):
                files.append(entry)
            else:
                raise LibraryValidationError(f"module tree contains a non-file entry: {entry}")

    visit(root)
    return files


def _safe_existing_or_missing_directory(path: Path) -> Path:
    candidate = Path(os.path.abspath(path))
    _assert_safe_existing_components(candidate)
    if candidate.exists():
        return _safe_existing_directory(candidate)
    return candidate


def _safe_existing_directory(path: Path) -> Path:
    candidate = Path(os.path.abspath(path))
    _assert_safe_existing_components(candidate)
    try:
        metadata = candidate.lstat()
    except OSError as error:
        raise LibraryValidationError(f"module directory is unavailable: {path}") from error
    if not stat.S_ISDIR(metadata.st_mode):
        raise LibraryValidationError(f"module directory must be a real directory: {path}")
    return candidate


def _safe_create_directory(path: Path) -> Path:
    candidate = _safe_existing_or_missing_directory(path)
    durable_make_directory(candidate)
    return _safe_existing_directory(candidate)


def _safe_child(root: Path, *parts: str) -> Path:
    base = Path(os.path.abspath(root))
    candidate = base.joinpath(*parts)
    try:
        candidate.relative_to(base)
    except ValueError as error:
        raise LibraryValidationError("path escapes configured root") from error
    _assert_safe_existing_components(candidate)
    return candidate


def _assert_safe_existing_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            return
        except OSError as error:
            raise LibraryValidationError(f"cannot inspect path component: {current}") from error
        if stat.S_ISLNK(metadata.st_mode) or _is_reparse(metadata):
            raise LibraryValidationError(f"path contains a link or reparse point: {current}")


def _capture_directory(path: Path) -> _DirectoryIdentity:
    candidate = _safe_existing_directory(path)
    metadata = candidate.lstat()
    return _DirectoryIdentity(candidate, metadata.st_dev, metadata.st_ino)


def _require_directory_identity(identity: _DirectoryIdentity) -> None:
    candidate = _safe_existing_directory(identity.path)
    metadata = candidate.lstat()
    if (metadata.st_dev, metadata.st_ino) != (identity.device, identity.inode):
        raise LibraryValidationError(f"directory identity changed: {identity.path}")


def _is_reparse(metadata: os.stat_result) -> bool:
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _copy_tree(source: Path, destination: Path) -> _DirectoryIdentity:
    source_identity = _capture_directory(source)
    if destination.exists():
        raise FileExistsError(destination)
    destination_identity = _capture_directory(_safe_create_directory(destination))
    try:
        _after_staging_directory_created(destination)
        for source_file in _iter_regular_files(source_identity.path):
            _require_directory_identity(source_identity)
            _require_directory_identity(destination_identity)
            relative = source_file.relative_to(source_identity.path)
            try:
                data = stable_read_file(source_file).data
            except StableReadError as error:
                raise LibraryValidationError(str(error)) from error
            destination_file = _safe_child(destination, *relative.parts)
            _safe_create_directory(destination_file.parent)
            _require_directory_identity(destination_identity)
            atomic_write_bytes(destination_file, data)
            _require_directory_identity(source_identity)
            _require_directory_identity(destination_identity)
        _require_directory_identity(source_identity)
        _require_directory_identity(destination_identity)
        return destination_identity
    except Exception:
        _remove_staging_tree(destination, destination_identity)
        raise


def _safe_unlink(path: Path) -> None:
    _assert_safe_existing_components(path)
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode) or _is_reparse(metadata):
        raise LibraryValidationError(f"refusing to remove non-regular file: {path}")
    path.unlink()


def _remove_staging_tree(path: Path, expected_identity: _DirectoryIdentity) -> None:
    if not path.exists():
        return
    identity = _capture_directory(path)
    if identity != expected_identity:
        return
    _iter_regular_files(path)
    shutil.rmtree(path)


def _matches_directory_identity(path: Path, expected: _DirectoryIdentity) -> bool:
    try:
        actual = _capture_directory(path)
        return (actual.device, actual.inode) == (expected.device, expected.inode)
    except LibraryValidationError:
        return False


def _restore_original_directory(
    target: Path,
    backup: Path,
    original: _DirectoryIdentity,
    imported: _DirectoryIdentity | None,
    parent: _DirectoryIdentity,
) -> None:
    """Reconcile uncertain rename outcomes without discarding the original tree."""
    _require_directory_identity(parent)
    if _matches_directory_identity(target, original):
        return
    if not _matches_directory_identity(backup, original):
        raise LibraryValidationError("rollback incomplete: original backup is unavailable")
    if target.exists():
        if imported is None or not _matches_directory_identity(target, imported):
            raise LibraryValidationError("rollback incomplete: target identity is unknown")
        discarded = _safe_child(
            target.parent, f".{target.name}.{uuid4().hex}.rollback"
        )
        try:
            durable_replace(target, discarded)
        except Exception as error:
            if _matches_directory_identity(discarded, imported):
                _remove_staging_tree(discarded, imported)
            elif _matches_directory_identity(target, imported):
                raise LibraryValidationError(
                    "rollback incomplete: imported target was retained"
                ) from error
        else:
            _remove_staging_tree(discarded, imported)
    try:
        durable_replace(backup, target)
    except Exception as error:
        if _matches_directory_identity(target, original):
            return
        if _matches_directory_identity(backup, original):
            raise LibraryValidationError(
                "rollback incomplete: original backup was preserved"
            ) from error
        raise LibraryValidationError("rollback incomplete: original identity was lost") from error
    if not _matches_directory_identity(target, original):
        raise LibraryValidationError("rollback incomplete: original identity was not restored")


def _cleanup_interrupted_staging(parent: Path, version: str) -> None:
    parent_identity = _capture_directory(parent)
    prefix = f".{version}."
    for candidate in parent.iterdir():
        if candidate.name.startswith(prefix) and candidate.name.endswith(".staging"):
            _remove_staging_tree(candidate, _capture_directory(candidate))
    _require_directory_identity(parent_identity)


class _PublicationLock:
    """OS-released lock; stale staging is removed only by the next lock owner."""

    def __init__(self, path: Path, ref: str) -> None:
        self.path = path
        self.ref = ref
        self.descriptor = -1
        self.identity: tuple[int, int] | None = None

    def __enter__(self) -> Self:
        _safe_create_directory(self.path.parent)
        _assert_safe_existing_components(self.path)
        flags = (
            os.O_CREAT
            | os.O_RDWR
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            self.descriptor = os.open(self.path, flags)
            opened = os.fstat(self.descriptor)
            after = self.path.lstat()
            if (
                not stat.S_ISREG(opened.st_mode)
                or stat.S_ISLNK(after.st_mode)
                or _is_reparse(after)
                or (opened.st_dev, opened.st_ino) != (after.st_dev, after.st_ino)
            ):
                raise LibraryValidationError("publication lock identity changed")
            self.identity = (opened.st_dev, opened.st_ino)
            if opened.st_size == 0:
                os.write(self.descriptor, b"0")
            os.lseek(self.descriptor, 0, os.SEEK_SET)
            self._lock()
        except LibraryValidationError:
            self._close()
            raise
        except OSError as error:
            self._close()
            raise VersionExists(self.ref) from error
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._unlock()
        self._close()

    def _lock(self) -> None:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self.descriptor, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(  # type: ignore[attr-defined]
                self.descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB  # type: ignore[attr-defined]
            )

    def _unlock(self) -> None:
        if self.descriptor < 0:
            return
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(self.descriptor, 0, os.SEEK_SET)
                msvcrt.locking(self.descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(  # type: ignore[attr-defined]
                    self.descriptor, fcntl.LOCK_UN  # type: ignore[attr-defined]
                )
        except OSError:
            pass

    def _close(self) -> None:
        if self.descriptor >= 0:
            os.close(self.descriptor)
            self.descriptor = -1


__all__ = ["ModuleLibrary", "hash_tree"]
