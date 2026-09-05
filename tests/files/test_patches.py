from __future__ import annotations

from pathlib import Path

import pytest

from ai4sota.files.hashing import sha256_file
from ai4sota.files.patches import PatchConflict, PatchSet, PatchTarget, apply_patch_set


def write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_stale_second_target_prevents_every_write(tmp_path: Path) -> None:
    """Catches a patch applying early targets before finding a stale later one."""
    first = write(tmp_path / "a.py", "old-a")
    second = write(tmp_path / "b.py", "old-b")
    patch = PatchSet(
        targets=[
            PatchTarget(path="a.py", expected_sha256=sha256_file(first), content="new-a"),
            PatchTarget(path="b.py", expected_sha256="0" * 64, content="new-b"),
        ]
    )

    with pytest.raises(PatchConflict) as error:
        apply_patch_set(tmp_path, patch)

    assert error.value.paths == ("b.py",)
    assert first.read_text(encoding="utf-8") == "old-a"
    assert second.read_text(encoding="utf-8") == "old-b"


def test_sha256_file_returns_a_canonical_digest(tmp_path: Path) -> None:
    """Catches hashes without the canonical prefix or with a wrong byte digest."""
    path = write(tmp_path / "source.py", "abc")

    assert sha256_file(path) == (
        "sha256:ba7816bf8f01cfea414140de5dae2223"
        "b00361a396177a9cb410ff61f20015ad"
    )


def test_matching_targets_are_replaced_and_reported(tmp_path: Path) -> None:
    """Catches valid patch content not reaching every hash-checked target."""
    first = write(tmp_path / "src" / "a.py", "old-a")
    second = write(tmp_path / "src" / "b.py", "old-b")
    patch = PatchSet(
        targets=[
            PatchTarget(path="src/a.py", expected_sha256=sha256_file(first), content="new-a"),
            PatchTarget(path="src/b.py", expected_sha256=sha256_file(second), content="new-b"),
        ]
    )

    applied = apply_patch_set(tmp_path, patch)

    assert applied.paths == ("src/a.py", "src/b.py")
    assert first.read_text(encoding="utf-8") == "new-a"
    assert second.read_text(encoding="utf-8") == "new-b"


def test_missing_target_is_reported_as_a_conflict_without_writing(tmp_path: Path) -> None:
    """Catches a missing target allowing an earlier valid target to be replaced."""
    existing = write(tmp_path / "existing.py", "old")
    patch = PatchSet(
        targets=[
            PatchTarget(path="existing.py", expected_sha256=sha256_file(existing), content="new"),
            PatchTarget(
                path="missing.py",
                expected_sha256="sha256:" + "0" * 64,
                content="created",
            ),
        ]
    )

    with pytest.raises(PatchConflict) as error:
        apply_patch_set(tmp_path, patch)

    assert error.value.paths == ("missing.py",)
    assert existing.read_text(encoding="utf-8") == "old"
    assert not (tmp_path / "missing.py").exists()


@pytest.mark.parametrize("path", ["../outside.py", ".\\..\\outside.py"])
def test_traversal_path_is_rejected_before_writing(tmp_path: Path, path: str) -> None:
    """Catches a relative patch target escaping the canonical project root."""
    inside = write(tmp_path / "inside.py", "inside")
    patch = PatchSet(
        targets=[
            PatchTarget(path=path, expected_sha256=sha256_file(inside), content="escaped")
        ]
    )

    with pytest.raises(ValueError, match="escapes project root"):
        apply_patch_set(tmp_path, patch)

    assert inside.read_text(encoding="utf-8") == "inside"


def test_absolute_path_is_rejected_before_writing(tmp_path: Path) -> None:
    """Catches a patch target bypassing the project root through an absolute path."""
    outside = write(tmp_path.parent / "outside.py", "outside")
    patch = PatchSet(
        targets=[
            PatchTarget(
                path=str(outside), expected_sha256=sha256_file(outside), content="escaped"
            )
        ]
    )

    with pytest.raises(ValueError, match="must be relative"):
        apply_patch_set(tmp_path, patch)

    assert outside.read_text(encoding="utf-8") == "outside"


def test_symlink_to_a_path_outside_project_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches hashing or replacing a project link whose target is external."""
    outside = write(tmp_path.parent / "outside.py", "outside")
    link = tmp_path / "linked.py"
    try:
        link.symlink_to(outside)
    except OSError:
        link.write_text("not-a-link", encoding="utf-8")
        original_resolve = Path.resolve

        def resolve_as_external(path: Path, strict: bool = False) -> Path:
            if path == link:
                return outside
            return original_resolve(path, strict=strict)

        monkeypatch.setattr(Path, "resolve", resolve_as_external)

    patch = PatchSet(
        targets=[
            PatchTarget(path="linked.py", expected_sha256=sha256_file(outside), content="escaped")
        ]
    )

    with pytest.raises(ValueError, match="escapes project root"):
        apply_patch_set(tmp_path, patch)

    assert outside.read_text(encoding="utf-8") == "outside"
