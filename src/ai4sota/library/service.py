"""Durable, local-only publication and import of module trees."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
from pathlib import Path
from uuid import uuid4

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from ai4sota.domain import (
    DataModuleSpec,
    EvaluationSpec,
    MethodSpec,
    ModuleKind,
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
ModuleSchema = DataModuleSpec | EvaluationSpec | MethodSpec

_MODELS: dict[ModuleKind, type[ModuleSchema]] = {
    ModuleKind.DATA: DataModuleSpec,
    ModuleKind.METHOD: MethodSpec,
    ModuleKind.EVALUATION: EvaluationSpec,
}


def hash_tree(path: Path) -> str:
    """Hash a complete regular-file tree without following links or reparses."""
    root = _require_safe_directory(path)
    digest = hashlib.sha256()
    files = tuple(_iter_regular_files(root))
    if not files:
        raise LibraryValidationError(f"module tree is empty: {path}")
    for file_path in files:
        relative = file_path.relative_to(root).as_posix().encode("utf-8")
        try:
            content = stable_read_file(file_path).data
        except StableReadError as error:
            raise LibraryValidationError(str(error)) from error
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return f"sha256:{digest.hexdigest()}"


class ModuleLibrary:
    """Filesystem-backed global module library with immutable published versions."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def read(self, ref: str) -> PublishedModule:
        kind, name, version = _parse_ref(ref)
        path = self.root / kind.value / name / version
        if not path.exists():
            raise ModuleNotFound(ref)
        _validate_module_tree(path, kind, f"{kind.value}/{name}", version)
        return PublishedModule(ref=ref, content_hash=hash_tree(path), path=path)

    def create_draft(self, ref: str) -> ModuleDraft:
        published = self.read(ref)
        kind, name, version = _parse_ref(ref)
        drafts_root = self.root / ".drafts" / kind.value / name
        durable_make_directory(drafts_root)
        draft_path = drafts_root / f"{version}-{uuid4().hex}"
        _copy_tree(published.path, draft_path)
        return ModuleDraft(path=draft_path, module_id=f"{kind.value}/{name}", version=version)

    def publish(self, draft: ModuleDraft, expected_hash: str) -> PublishedModule:
        kind, name = _parse_module_id(draft.module_id)
        _validate_version(draft.version)
        actual_hash = hash_tree(draft.path)
        if actual_hash != expected_hash:
            raise PublishConflict(expected_hash, actual_hash)

        destination = self.root / kind.value / name / draft.version
        lock = self.root / ".locks" / kind.value / name / f"{draft.version}.lock"
        _acquire_lock(lock, draft.ref)
        try:
            if destination.exists():
                raise VersionExists(draft.ref)
            _validate_module_tree(draft.path, kind, draft.module_id, draft.version)
            durable_make_directory(destination.parent)
            staged = destination.with_name(f".{destination.name}.{uuid4().hex}.staging")
            try:
                _copy_tree(draft.path, staged)
                if hash_tree(staged) != actual_hash:
                    raise LibraryValidationError("staged module tree does not match draft")
                _validate_module_tree(staged, kind, draft.module_id, draft.version)
                if destination.exists():
                    raise VersionExists(draft.ref)
                durable_replace(staged, destination)
            except Exception:
                _remove_staging_tree(staged)
                if destination.exists():
                    raise VersionExists(draft.ref) from None
                raise
        finally:
            lock.unlink(missing_ok=True)

        return self.read(draft.ref)

    def import_version(self, ref: str, project: ProjectLayout) -> Path:
        published = self.read(ref)
        kind, _, _ = _parse_ref(ref)
        target = project.module_dir(kind)
        _require_safe_directory(project.root)
        _require_safe_directory(target)
        if any(target.iterdir()):
            raise LibraryValidationError(
                f"project module directory is not empty: {target}"
            )

        staged = target.with_name(f".{target.name}.{uuid4().hex}.staging")
        try:
            _copy_tree(published.path, staged)
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
            _validate_module_tree(staged, kind, updated.id, updated.version)
            target.rmdir()
            durable_replace(staged, target)
        except Exception:
            _remove_staging_tree(staged)
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
    root: Path, kind: ModuleKind, module_id: str, version: str
) -> ModuleSchema:
    _require_safe_directory(root)
    hash_tree(root)
    model = _read_module_manifest(root / "module.yaml", kind)
    if model.id != module_id or model.version != version:
        raise LibraryValidationError(
            f"module manifest does not match requested version: {module_id}@{version}"
        )
    if model.content_hash != canonical_manifest_hash(model):
        raise LibraryValidationError("module manifest content_hash is not canonical")
    return model


def _read_module_manifest(path: Path, kind: ModuleKind) -> ModuleSchema:
    try:
        stable = stable_read_file(path)
        value = yaml.safe_load(stable.data)
        return _MODELS[kind].model_validate(value)
    except (StableReadError, ValidationError, yaml.YAMLError) as error:
        raise LibraryValidationError(f"invalid module manifest: {path}") from error


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


def _require_safe_directory(path: Path) -> Path:
    candidate = Path(os.path.abspath(path))
    try:
        metadata = candidate.lstat()
    except OSError as error:
        raise LibraryValidationError(f"module directory is unavailable: {path}") from error
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or _is_reparse(metadata)
    ):
        raise LibraryValidationError(f"module directory must be a real directory: {path}")
    return candidate


def _is_reparse(metadata: os.stat_result) -> bool:
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _copy_tree(source: Path, destination: Path) -> None:
    source_root = _require_safe_directory(source)
    if destination.exists():
        raise FileExistsError(destination)
    durable_make_directory(destination)
    try:
        for source_file in _iter_regular_files(source_root):
            relative = source_file.relative_to(source_root)
            try:
                data = stable_read_file(source_file).data
            except StableReadError as error:
                raise LibraryValidationError(str(error)) from error
            destination_file = destination / relative
            atomic_write_bytes(destination_file, data)
    except Exception:
        _remove_staging_tree(destination)
        raise


def _acquire_lock(lock: Path, ref: str) -> None:
    durable_make_directory(lock.parent)
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise VersionExists(ref) from error
    os.close(descriptor)


def _remove_staging_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


__all__ = ["ModuleLibrary", "hash_tree"]
