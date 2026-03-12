from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path


SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".doc",
    ".xlsx",
    ".xls",
    ".pptx",
    ".ppt",
    ".txt",
    ".md",
    ".csv",
}

DEFAULT_SCAN_DIRS = ["Desktop", "Documents", "Downloads"]


@dataclass
class ScannedFile:
    file_path: str
    name: str
    size: int
    modified_time: float


def get_default_paths() -> list[Path]:
    home = Path.home()
    return [home / folder for folder in DEFAULT_SCAN_DIRS]


def normalize_scan_paths(extra_paths: list[str] | None = None) -> list[Path]:
    normalized: list[Path] = []
    seen: set[str] = set()
    for path in [*get_default_paths(), *(Path(item) for item in (extra_paths or []))]:
        expanded = path.expanduser()
        try:
            resolved = expanded.resolve(strict=False)
        except OSError:
            resolved = expanded
        key = os.path.normcase(str(resolved))
        if key in seen:
            continue
        seen.add(key)
        normalized.append(resolved)
    return normalized


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def compact_scan_roots(roots: list[Path]) -> list[Path]:
    """Drop nested scan roots to avoid duplicate traversal for overlapping paths."""
    compacted: list[Path] = []
    for root in sorted(roots, key=lambda item: (len(str(item)), os.path.normcase(str(item)))):
        if any(_is_relative_to(root, existing) for existing in compacted):
            continue
        compacted.append(root)
    return compacted


def should_exclude_dir(dir_name: str, exclude_patterns: set[str]) -> bool:
    return dir_name.startswith(".") or dir_name.lower() in exclude_patterns


def is_valid_file(path: Path, file_size: int) -> bool:
    if path.name.startswith("~$") or path.name.startswith("."):
        return False
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return False
    if file_size == 0:
        return False
    return True


def scan_files(paths: list[str] | None = None, exclude_patterns: list[str] | None = None) -> list[ScannedFile]:
    exclude_set = {
        str(pattern).strip().lower()
        for pattern in (exclude_patterns or [])
        if str(pattern).strip()
    }
    scanned: list[ScannedFile] = []
    seen_files: set[str] = set()
    for root in compact_scan_roots(normalize_scan_paths(paths)):
        if not root.exists():
            continue
        for current_root, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not should_exclude_dir(d, exclude_set)]
            for filename in filenames:
                file_path = Path(current_root) / filename
                try:
                    stat = file_path.stat()
                except OSError:
                    logging.exception("读取文件信息失败: %s", file_path)
                    continue
                if not is_valid_file(file_path, stat.st_size):
                    continue
                try:
                    resolved_file = file_path.resolve()
                except OSError:
                    logging.exception("规范化文件路径失败: %s", file_path)
                    continue
                resolved_key = os.path.normcase(str(resolved_file))
                if resolved_key in seen_files:
                    continue
                seen_files.add(resolved_key)
                scanned.append(
                    ScannedFile(
                        file_path=str(resolved_file),
                        name=file_path.name,
                        size=stat.st_size,
                        modified_time=stat.st_mtime,
                    )
                )
    scanned.sort(key=lambda item: os.path.normcase(item.file_path))
    return scanned
