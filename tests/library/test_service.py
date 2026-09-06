from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from ai4sota.domain import DataModuleSpec
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


def valid_draft(root: Path, module_id: str, version: str) -> ModuleDraft:
    path = root / "drafts" / module_id.replace("/", "-") / version
    path.mkdir(parents=True)
    ManifestStore().write(path / "module.yaml", _data_module(version))
    (path / "adapter.py").write_text("def load():\n    return None\n", encoding="utf-8")
    return ModuleDraft(path=path, module_id=module_id, version=version)


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

    with pytest.raises(LibraryValidationError, match="real directory"):
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
    assert list((library.root / ".locks" / "data" / "seed").glob("*.lock")) == []


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
