from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from scanner import compact_scan_roots, is_under_any_root, is_valid_file, scan_files


def test_is_valid_file():
    assert is_valid_file(Path("report.PDF"), 10)
    assert not is_valid_file(Path("~$report.docx"), 10)
    assert not is_valid_file(Path(".hidden.txt"), 10)
    assert not is_valid_file(Path("photo.jpg"), 10)
    assert not is_valid_file(Path("empty.txt"), 0)


def test_compact_scan_roots_drops_nested(tmp_path):
    outer = tmp_path / "a"
    inner = outer / "b"
    other = tmp_path / "c"
    assert compact_scan_roots([inner, other, outer]) == sorted([outer, other], key=lambda p: (len(str(p)), str(p)))


def test_is_under_any_root(tmp_path):
    root = tmp_path / "share"
    assert is_under_any_root(str(root / "x" / "y.pdf"), [root])
    assert is_under_any_root(str(root), [root])
    # Sibling with a shared name prefix must not match.
    assert not is_under_any_root(str(tmp_path / "share2" / "y.pdf"), [root])
    assert not is_under_any_root(str(tmp_path / "y.pdf"), [])


def test_scan_files_filters_and_excludes(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "plan.docx").write_bytes(b"x")
    (tmp_path / "docs" / "empty.txt").write_bytes(b"")
    (tmp_path / "docs" / "image.png").write_bytes(b"x")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "readme.md").write_bytes(b"x")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "notes.txt").write_bytes(b"x")

    flags = {"desktop": False, "documents": False, "downloads": False}
    # The same root listed twice (and nested) must not produce duplicates.
    found = scan_files(
        paths=[str(tmp_path), str(tmp_path / "docs")],
        exclude_patterns=["Node_Modules"],
        default_path_flags=flags,
    )
    assert [Path(item.file_path).name for item in found] == ["plan.docx"]
    assert os.path.isabs(found[0].file_path)


def test_default_folder_falls_back_to_home(monkeypatch, tmp_path):
    import scanner

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(scanner, "_windows_known_folder", lambda folder_id: None)
    assert scanner.get_default_folder("Documents") == tmp_path / "Documents"


def test_default_folder_prefers_redirected_location(monkeypatch, tmp_path):
    import scanner

    redirected = tmp_path / "OneDrive" / "文档"
    monkeypatch.setattr(scanner, "_windows_known_folder", lambda folder_id: redirected)
    assert scanner.get_enabled_default_paths({"desktop": False, "documents": True, "downloads": False}) == [redirected]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows shell API")
def test_windows_known_folder_lookup_returns_real_directory():
    import scanner

    for folder in ("Desktop", "Documents", "Downloads"):
        located = scanner._windows_known_folder(scanner._WINDOWS_KNOWN_FOLDER_IDS[folder])
        assert located is not None and located.is_absolute(), folder
    assert scanner._windows_known_folder("00000000-0000-0000-0000-000000000000") is None
