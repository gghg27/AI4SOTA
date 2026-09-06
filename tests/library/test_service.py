from __future__ import annotations

import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import TypeVar

import pytest
from pydantic import BaseModel

import ai4sota.library.service as library_service
from ai4sota.domain import (
    DataModuleSpec,
    DatasetSourceSpec,
    EvaluationSpec,
    MethodSpec,
    PreprocessingSpec,
)
from ai4sota.domain.common import OriginSpec, OriginType
from ai4sota.domain.modules import MetricSpec, SplitProtocolSpec
from ai4sota.library import (
    LibraryValidationError,
    ModuleDraft,
    ModuleLibrary,
    PublishConflict,
    VersionExists,
    hash_tree,
)
from ai4sota.projects import ProjectLayout
from ai4sota.storage import ManifestStore, canonical_manifest_hash

ModelT = TypeVar("ModelT", bound=BaseModel)


def _data_module(version: str) -> DataModuleSpec:
    value = {
        "api_version": "ai4sota/v1",
        "id": "data/seed",
        "version": version,
        "content_hash": "sha256:" + "0" * 64,
        "kind": "data",
        "origin": {"type": "project", "based_on": None, "remote_source": None},
        "source": "dataset.yaml",
        "preprocessing": "preprocessing.yaml",
        "entrypoint": "adapter:load",
        "canonical_outputs": ["signal"],
        "task_contract": "task/emotion",
        "task_contract_hash": "sha256:" + "a" * 64,
    }
    draft = DataModuleSpec.model_validate(value)
    return draft.model_copy(update={"content_hash": canonical_manifest_hash(draft)})


def _with_content_hash(model: ModelT) -> ModelT:
    return model.model_copy(update={"content_hash": canonical_manifest_hash(model)})


def _dataset_source() -> DatasetSourceSpec:
    return _with_content_hash(
        DatasetSourceSpec(
            id="dataset/seed",
            version="1.0.0",
            content_hash="sha256:" + "0" * 64,
            name="Seed dataset",
            locations=("data/seed.edf",),
            sampling_rate_hz=200,
            metadata_fields=("subject_id",),
            fingerprint_hash="sha256:" + "b" * 64,
        )
    )


def _preprocessing() -> PreprocessingSpec:
    return _with_content_hash(
        PreprocessingSpec(
            id="preprocessing/seed",
            version="1.0.0",
            content_hash="sha256:" + "0" * 64,
            transforms=(),
            graph_hash="sha256:" + "c" * 64,
        )
    )


def valid_draft(root: Path, module_id: str, version: str) -> ModuleDraft:
    path = root / "drafts" / module_id.replace("/", "-") / version
    path.mkdir(parents=True)
    ManifestStore().write(path / "module.yaml", _data_module(version))
    ManifestStore().write(path / "dataset.yaml", _dataset_source())
    ManifestStore().write(path / "preprocessing.yaml", _preprocessing())
    (path / "adapter.py").write_text("def load():\n    return None\n", encoding="utf-8")
    return ModuleDraft(path=path, module_id=module_id, version=version)


def valid_method_draft(root: Path, version: str) -> ModuleDraft:
    path = root / "method-draft" / version
    path.mkdir(parents=True)
    module = MethodSpec(
        id="method/seed",
        version=version,
        content_hash="sha256:" + "0" * 64,
        origin=OriginSpec(type=OriginType.PROJECT),
        framework="numpy",
        entrypoint="model:train",
        input_requirements={"layout": "batch,time,channel"},
        output_capabilities=("logits",),
    )
    ManifestStore().write(path / "module.yaml", _with_content_hash(module))
    return ModuleDraft(path=path, module_id="method/seed", version=version)


def valid_evaluation_draft(root: Path, version: str) -> ModuleDraft:
    path = root / "evaluation-draft" / version
    path.mkdir(parents=True)
    module = EvaluationSpec(
        id="evaluation/seed",
        version=version,
        content_hash="sha256:" + "0" * 64,
        origin=OriginSpec(type=OriginType.PROJECT),
        entrypoint="evaluator:run",
        task_contract="task/emotion",
        task_contract_hash="sha256:" + "a" * 64,
        required_predictions=("logits",),
        protocol=SplitProtocolSpec(kind="group_holdout", group_by="subject_id"),
        metrics=(MetricSpec(name="accuracy", primary=True, implementation="metric:run"),),
    )
    ManifestStore().write(path / "module.yaml", _with_content_hash(module))
    return ModuleDraft(path=path, module_id="evaluation/seed", version=version)


def rewrite_data_module(path: Path, **updates: object) -> DataModuleSpec:
    current = ManifestStore().read(path, DataModuleSpec)
    draft = current.model_copy(update={**updates, "content_hash": "sha256:" + "0" * 64})
    updated = draft.model_copy(update={"content_hash": canonical_manifest_hash(draft)})
    ManifestStore().write(path, updated)
    return updated


def make_directory_link(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
        return
    except OSError:
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
            check=False,
            capture_output=True,
            text=True,
        )
    if result.returncode != 0:
        pytest.skip(f"link creation is unavailable: {result.stderr}")


def test_import_is_editable_but_published_source_is_immutable(tmp_path: Path) -> None:
    library = ModuleLibrary(tmp_path / "library")
    project = ProjectLayout.create(tmp_path, "seed-project")
    draft = valid_draft(tmp_path, "data/seed", "1.0.0")
    draft_hash = hash_tree(draft.path)

    published = library.publish(draft, expected_hash=draft_hash)
    imported = library.import_version(published.ref, project)

    (imported / "module.yaml").write_text("project edit", encoding="utf-8")

    assert library.read(published.ref).content_hash == published.content_hash
    with pytest.raises(VersionExists):
        library.publish(draft, expected_hash=draft_hash)


def test_publish_rejects_a_stale_expected_draft_hash(tmp_path: Path) -> None:
    library = ModuleLibrary(tmp_path / "library")
    draft = valid_draft(tmp_path, "data/seed", "1.0.0")
    expected_hash = hash_tree(draft.path)
    (draft.path / "adapter.py").write_text("CHANGED = True\n", encoding="utf-8")

    with pytest.raises(PublishConflict) as error:
        library.publish(draft, expected_hash=expected_hash)

    assert error.value.expected_hash == expected_hash
    assert error.value.actual_hash == hash_tree(draft.path)
    assert not (library.root / "data" / "seed" / "1.0.0").exists()


@pytest.mark.parametrize(
    "ref",
    [
        "task/seed@1.0.0",
        "data/seed@1.0",
        "data/seed@01.0.0",
        "data/../seed@1.0.0",
        "data/seed@@1.0.0",
        "data/seed",
    ],
)
def test_library_rejects_invalid_kinds_versions_and_references(
    tmp_path: Path, ref: str
) -> None:
    with pytest.raises(LibraryValidationError):
        ModuleLibrary(tmp_path / "library").read(ref)


def test_publish_rejects_a_schema_with_a_noncanonical_content_hash(
    tmp_path: Path,
) -> None:
    library = ModuleLibrary(tmp_path / "library")
    draft = valid_draft(tmp_path, "data/seed", "1.0.0")
    manifest = draft.path / "module.yaml"
    ManifestStore().write(
        manifest,
        _data_module("1.0.0").model_copy(
            update={"content_hash": "sha256:" + "f" * 64}
        ),
    )

    with pytest.raises(LibraryValidationError, match="content_hash is not canonical"):
        library.publish(draft, expected_hash=hash_tree(draft.path))

    assert not (library.root / "data" / "seed" / "1.0.0").exists()


def test_publish_rejects_linked_tree_entries(tmp_path: Path) -> None:
    draft = valid_draft(tmp_path, "data/seed", "1.0.0")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sentinel.py").write_text("SENTINEL = True\n", encoding="utf-8")
    make_directory_link(draft.path / "linked", outside)

    with pytest.raises(LibraryValidationError, match="link"):
        hash_tree(draft.path)


def test_import_rejects_a_linked_project_module_directory(tmp_path: Path) -> None:
    library = ModuleLibrary(tmp_path / "library")
    draft = valid_draft(tmp_path, "data/seed", "1.0.0")
    published = library.publish(draft, expected_hash=hash_tree(draft.path))
    project = ProjectLayout.create(tmp_path, "seed-project")
    target = project.module_dir("data")
    target.rmdir()
    outside = tmp_path / "outside-module"
    outside.mkdir()
    make_directory_link(target, outside)

    with pytest.raises(LibraryValidationError, match="link or reparse"):
        library.import_version(published.ref, project)

    assert list(outside.iterdir()) == []


def test_import_records_origin_and_isolates_the_published_source(tmp_path: Path) -> None:
    library = ModuleLibrary(tmp_path / "library")
    draft = valid_draft(tmp_path, "data/seed", "1.0.0")
    published = library.publish(draft, expected_hash=hash_tree(draft.path))
    project = ProjectLayout.create(tmp_path, "seed-project")

    imported = library.import_version(published.ref, project)
    imported_module = ManifestStore().read(imported / "module.yaml", DataModuleSpec)
    (imported / "adapter.py").write_text("PROJECT_ONLY = True\n", encoding="utf-8")

    assert imported_module.origin.type.value == "imported"
    assert imported_module.origin.based_on == published.ref
    assert imported_module.content_hash == canonical_manifest_hash(imported_module)
    assert library.read(published.ref).content_hash == published.content_hash
    assert (published.path / "adapter.py").read_text(encoding="utf-8") != (
        imported / "adapter.py"
    ).read_text(encoding="utf-8")


def test_create_draft_copies_a_published_version_without_mutating_it(tmp_path: Path) -> None:
    library = ModuleLibrary(tmp_path / "library")
    source = valid_draft(tmp_path, "data/seed", "1.0.0")
    published = library.publish(source, expected_hash=hash_tree(source.path))

    draft = library.create_draft(published.ref)
    (draft.path / "adapter.py").write_text("DRAFT = True\n", encoding="utf-8")

    assert draft.ref == published.ref
    assert library.read(published.ref).content_hash == published.content_hash
    assert (published.path / "adapter.py").read_text(encoding="utf-8") == (
        "def load():\n    return None\n"
    )


def test_concurrent_publication_never_overwrites_an_existing_version(tmp_path: Path) -> None:
    library = ModuleLibrary(tmp_path / "library")
    first = valid_draft(tmp_path / "first", "data/seed", "1.0.0")
    second = valid_draft(tmp_path / "second", "data/seed", "1.0.0")
    expected_hash = hash_tree(first.path)
    barrier = Barrier(2)

    def publish(draft: ModuleDraft) -> object:
        barrier.wait()
        try:
            return library.publish(draft, expected_hash=expected_hash)
        except VersionExists as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(publish, (first, second)))

    assert sum(not isinstance(result, VersionExists) for result in results) == 1
    assert sum(isinstance(result, VersionExists) for result in results) == 1
    assert library.read("data/seed@1.0.0").content_hash == expected_hash
    assert list((library.root / "data" / "seed").glob(".*.staging")) == []
    assert (library.root / ".locks" / "data" / "seed" / "1.0.0.lock").is_file()


def test_failed_publication_cleans_up_its_staging_tree(tmp_path: Path) -> None:
    library = ModuleLibrary(tmp_path / "library")
    draft = valid_draft(tmp_path, "data/seed", "1.0.0")
    (draft.path / "module.yaml").write_text("kind: data\n", encoding="utf-8")

    with pytest.raises(LibraryValidationError, match="invalid module manifest"):
        library.publish(draft, expected_hash=hash_tree(draft.path))

    destination_parent = library.root / "data" / "seed"
    assert not (destination_parent / "1.0.0").exists()
    assert list(destination_parent.glob(".*.staging")) == []
    assert list((library.root / ".locks" / "data" / "seed").glob("*.lock")) == []


def test_read_and_import_reject_a_tampered_published_payload(tmp_path: Path) -> None:
    library = ModuleLibrary(tmp_path / "library")
    draft = valid_draft(tmp_path, "data/seed", "1.0.0")
    published = library.publish(draft, expected_hash=hash_tree(draft.path))
    (published.path / "adapter.py").write_text("TAMPERED = True\n", encoding="utf-8")
    project = ProjectLayout.create(tmp_path, "seed-project")

    with pytest.raises(LibraryValidationError, match="publication integrity"):
        library.read(published.ref)
    with pytest.raises(LibraryValidationError, match="publication integrity"):
        library.import_version(published.ref, project)


def test_import_uses_verified_staged_bytes_when_source_changes_during_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = ModuleLibrary(tmp_path / "library")
    draft = valid_draft(tmp_path, "data/seed", "1.0.0")
    published = library.publish(draft, expected_hash=hash_tree(draft.path))
    project = ProjectLayout.create(tmp_path, "seed-project")
    real_copy = library_service._copy_tree

    def copy_then_tamper(
        source: Path, destination: Path
    ) -> library_service._DirectoryIdentity:
        copied = real_copy(source, destination)
        if source == published.path:
            (source / "adapter.py").write_text("RACED = True\n", encoding="utf-8")
        return copied

    monkeypatch.setattr(library_service, "_copy_tree", copy_then_tamper)

    imported = library.import_version(published.ref, project)

    assert (imported / "adapter.py").read_text(encoding="utf-8") == (
        "def load():\n    return None\n"
    )
    with pytest.raises(LibraryValidationError, match="publication integrity"):
        library.read(published.ref)


def test_publish_requires_data_references_to_existing_matching_manifests(
    tmp_path: Path,
) -> None:
    library = ModuleLibrary(tmp_path / "library")
    draft = valid_draft(tmp_path, "data/seed", "1.0.0")
    (draft.path / "dataset.yaml").unlink()

    with pytest.raises(LibraryValidationError, match="dataset source"):
        library.publish(draft, expected_hash=hash_tree(draft.path))

    draft = valid_draft(tmp_path / "mismatch", "data/seed", "1.0.1")
    rewrite_data_module(draft.path / "module.yaml", source="preprocessing.yaml")
    with pytest.raises(LibraryValidationError, match="dataset source"):
        library.publish(draft, expected_hash=hash_tree(draft.path))


def test_publish_rejects_data_references_that_escape_the_module_tree(
    tmp_path: Path,
) -> None:
    library = ModuleLibrary(tmp_path / "library")
    draft = valid_draft(tmp_path, "data/seed", "1.0.0")
    rewrite_data_module(draft.path / "module.yaml", source="../dataset.yaml")

    with pytest.raises(LibraryValidationError, match="canonical in-tree"):
        library.publish(draft, expected_hash=hash_tree(draft.path))


def test_publish_requires_method_and_evaluation_executables_in_tree(
    tmp_path: Path,
) -> None:
    library = ModuleLibrary(tmp_path / "library")
    method = valid_method_draft(tmp_path, "1.0.0")
    evaluation = valid_evaluation_draft(tmp_path, "1.0.0")

    with pytest.raises(LibraryValidationError, match="entrypoint"):
        library.publish(method, expected_hash=hash_tree(method.path))
    with pytest.raises(LibraryValidationError, match="entrypoint"):
        library.publish(evaluation, expected_hash=hash_tree(evaluation.path))

    (evaluation.path / "evaluator.py").write_text("def run():\n    return None\n", encoding="utf-8")
    with pytest.raises(LibraryValidationError, match="metric implementation"):
        library.publish(evaluation, expected_hash=hash_tree(evaluation.path))


def test_publish_rejects_a_library_root_with_a_reparse_ancestor(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    redirected = tmp_path / "redirected"
    make_directory_link(redirected, outside)
    library = ModuleLibrary(redirected / "library")
    draft = valid_draft(tmp_path, "data/seed", "1.0.0")

    with pytest.raises(LibraryValidationError, match="link or reparse"):
        library.publish(draft, expected_hash=hash_tree(draft.path))

    assert not (outside / "library").exists()


def test_import_rejects_a_project_module_ancestor_reparse_point(tmp_path: Path) -> None:
    library = ModuleLibrary(tmp_path / "library")
    draft = valid_draft(tmp_path, "data/seed", "1.0.0")
    published = library.publish(draft, expected_hash=hash_tree(draft.path))
    project = ProjectLayout.create(tmp_path, "seed-project")
    modules = project.root / "modules"
    outside = tmp_path / "outside-modules"
    outside.mkdir()
    shutil.rmtree(modules)
    (outside / "data" / "current").mkdir(parents=True)
    make_directory_link(modules, outside)

    with pytest.raises(LibraryValidationError, match="link or reparse"):
        library.import_version(published.ref, project)

    assert list((outside / "data" / "current").iterdir()) == []


def test_import_restores_the_original_current_directory_after_rename_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = ModuleLibrary(tmp_path / "library")
    draft = valid_draft(tmp_path, "data/seed", "1.0.0")
    published = library.publish(draft, expected_hash=hash_tree(draft.path))
    project = ProjectLayout.create(tmp_path, "seed-project")
    target = project.module_dir("data")
    real_replace = library_service.durable_replace

    def fail_staged_import(source: Path, destination: Path) -> None:
        if source.name.endswith(".staging") and destination == target:
            raise OSError("simulated import rename failure")
        real_replace(source, destination)

    monkeypatch.setattr(library_service, "durable_replace", fail_staged_import)

    with pytest.raises(OSError, match="simulated import rename failure"):
        library.import_version(published.ref, project)

    assert target.is_dir()
    assert list(target.iterdir()) == []


def test_retry_recovers_a_subprocess_interrupted_publication(tmp_path: Path) -> None:
    library = ModuleLibrary(tmp_path / "library")
    draft = valid_draft(tmp_path, "data/seed", "1.0.0")
    staging = library.root / "data" / "seed" / ".1.0.0.dead.staging"
    lock = library.root / ".locks" / "data" / "seed" / "1.0.0.lock"
    script = (
        "from pathlib import Path; "
        f"Path({str(staging)!r}).mkdir(parents=True); "
        f"Path({str(lock)!r}).parent.mkdir(parents=True); "
        f"Path({str(lock)!r}).write_text('dead', encoding='utf-8')"
    )
    subprocess.run([sys.executable, "-c", script], check=True)

    published = library.publish(draft, expected_hash=hash_tree(draft.path))

    assert published.ref == "data/seed@1.0.0"
    assert not staging.exists()
    assert lock.is_file()


def test_read_returns_the_verified_digest_when_payload_changes_after_anchor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = ModuleLibrary(tmp_path / "library")
    draft = valid_draft(tmp_path, "data/seed", "1.0.0")
    published = library.publish(draft, expected_hash=hash_tree(draft.path))

    def mutate_after_anchor(path: Path) -> None:
        if path == published.path:
            (path / "adapter.py").write_text("AFTER_ANCHOR = True\n", encoding="utf-8")

    monkeypatch.setattr(
        library_service, "_after_publication_verified", mutate_after_anchor, raising=False
    )

    observed = library.read(published.ref)

    assert (published.path / "adapter.py").read_text(encoding="utf-8") == (
        "AFTER_ANCHOR = True\n"
    )
    assert observed.content_hash == published.content_hash


def test_create_draft_and_import_reject_payload_changed_after_read_anchor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = ModuleLibrary(tmp_path / "library")
    draft = valid_draft(tmp_path, "data/seed", "1.0.0")
    published = library.publish(draft, expected_hash=hash_tree(draft.path))

    def mutate_after_anchor(path: Path) -> None:
        if path == published.path:
            (path / "adapter.py").write_text("AFTER_ANCHOR = True\n", encoding="utf-8")

    monkeypatch.setattr(
        library_service, "_after_publication_verified", mutate_after_anchor, raising=False
    )

    with pytest.raises(LibraryValidationError, match="publication integrity"):
        library.create_draft(published.ref)
    with pytest.raises(LibraryValidationError, match="publication integrity"):
        library.import_version(published.ref, ProjectLayout.create(tmp_path, "project"))


def test_publish_rejects_a_staged_directory_swap_before_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = ModuleLibrary(tmp_path / "library")
    draft = valid_draft(tmp_path, "data/seed", "1.0.0")
    replacement: Path | None = None

    def swap_staged_directory(staged: Path, destination: Path) -> None:
        nonlocal replacement
        replacement = staged.with_name(staged.name + ".replacement")
        staged.rename(replacement)
        staged.mkdir()

    monkeypatch.setattr(
        library_service, "_before_publish_rename", swap_staged_directory, raising=False
    )

    with pytest.raises(LibraryValidationError, match="directory identity changed"):
        library.publish(draft, expected_hash=hash_tree(draft.path))

    assert replacement is not None and replacement.is_dir()
    assert not (library.root / "data" / "seed" / "1.0.0").exists()


def test_import_rejects_a_staged_directory_swap_and_restores_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = ModuleLibrary(tmp_path / "library")
    draft = valid_draft(tmp_path, "data/seed", "1.0.0")
    published = library.publish(draft, expected_hash=hash_tree(draft.path))
    project = ProjectLayout.create(tmp_path, "project")
    target = project.module_dir("data")
    replacement: Path | None = None

    def swap_staged_directory(staged: Path, import_target: Path) -> None:
        nonlocal replacement
        replacement = staged.with_name(staged.name + ".replacement")
        staged.rename(replacement)
        staged.mkdir()

    monkeypatch.setattr(
        library_service, "_before_import_rename", swap_staged_directory, raising=False
    )

    with pytest.raises(LibraryValidationError, match="directory identity changed"):
        library.import_version(published.ref, project)

    assert target.is_dir() and list(target.iterdir()) == []
    assert replacement is not None and replacement.is_dir()


@pytest.mark.parametrize("failure_stage", ["original", "staged"])
def test_import_restores_original_after_a_rename_reports_failure_post_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_stage: str
) -> None:
    library = ModuleLibrary(tmp_path / "library")
    draft = valid_draft(tmp_path, "data/seed", "1.0.0")
    published = library.publish(draft, expected_hash=hash_tree(draft.path))
    project = ProjectLayout.create(tmp_path, "project")
    target = project.module_dir("data")
    real_replace = library_service.durable_replace

    def replace_then_fail(source: Path, destination: Path) -> None:
        real_replace(source, destination)
        if failure_stage == "original" and source == target:
            raise OSError("original rename durability failure")
        if failure_stage == "staged" and source.name.endswith(".staging"):
            raise OSError("staged rename durability failure")

    monkeypatch.setattr(library_service, "durable_replace", replace_then_fail)

    with pytest.raises(OSError, match="rename durability failure"):
        library.import_version(published.ref, project)

    assert target.is_dir() and list(target.iterdir()) == []


def test_import_preserves_the_original_backup_when_rollback_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = ModuleLibrary(tmp_path / "library")
    draft = valid_draft(tmp_path, "data/seed", "1.0.0")
    published = library.publish(draft, expected_hash=hash_tree(draft.path))
    project = ProjectLayout.create(tmp_path, "project")
    target = project.module_dir("data")
    real_replace = library_service.durable_replace

    def replace_with_failed_rollback(source: Path, destination: Path) -> None:
        if source.name.endswith(".backup") and destination == target:
            raise OSError("rollback durability failure")
        real_replace(source, destination)
        if source == target:
            raise OSError("original rename durability failure")

    monkeypatch.setattr(library_service, "durable_replace", replace_with_failed_rollback)

    with pytest.raises(LibraryValidationError, match="rollback incomplete"):
        library.import_version(published.ref, project)

    backups = list(target.parent.glob("*.backup"))
    assert len(backups) == 1 and backups[0].is_dir() and list(backups[0].iterdir()) == []
    assert not target.exists()


def test_retry_reuses_a_persistent_lock_after_a_holder_subprocess_dies(
    tmp_path: Path,
) -> None:
    library = ModuleLibrary(tmp_path / "library")
    draft = valid_draft(tmp_path, "data/seed", "1.0.0")
    staging = library.root / "data" / "seed" / ".1.0.0.dead.staging"
    lock = library.root / ".locks" / "data" / "seed" / "1.0.0.lock"
    script = (
        "import os; from pathlib import Path; "
        "from ai4sota.library.service import _PublicationLock; "
        f"Path({str(staging)!r}).mkdir(parents=True); "
        f"holder = _PublicationLock(Path({str(lock)!r}), 'data/seed@1.0.0'); "
        "holder.__enter__(); os._exit(0)"
    )
    subprocess.run([sys.executable, "-c", script], check=True)
    before = lock.stat().st_ino

    published = library.publish(draft, expected_hash=hash_tree(draft.path))

    assert published.ref == "data/seed@1.0.0"
    assert lock.is_file() and lock.stat().st_ino == before
    assert not staging.exists()


def test_live_publisher_holds_the_single_persistent_lock_identity(
    tmp_path: Path,
) -> None:
    library = ModuleLibrary(tmp_path / "library")
    lock = library.root / ".locks" / "data" / "seed" / "1.0.0.lock"
    library_service._safe_create_directory(lock.parent)

    with library_service._PublicationLock(lock, "data/seed@1.0.0"):
        first_identity = lock.stat().st_ino
        with (
            pytest.raises(VersionExists),
            library_service._PublicationLock(lock, "data/seed@1.0.0"),
        ):
            pass

    with library_service._PublicationLock(lock, "data/seed@1.0.0"):
        assert lock.stat().st_ino == first_identity
