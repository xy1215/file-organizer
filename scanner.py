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
    paths: list[Path] = []
    for path in get_default_paths():
        paths.append(path.expanduser())
    for path in extra_paths or []:
        expanded = Path(path).expanduser()
        if expanded not in paths:
            paths.append(expanded)
    return paths


def should_exclude_dir(dir_name: str, exclude_patterns: list[str]) -> bool:
    return dir_name.startswith(".") or dir_name in set(exclude_patterns)


def is_valid_file(path: Path) -> bool:
    if path.name.startswith("~$") or path.name.startswith("."):
        return False
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return False
    try:
        if path.stat().st_size == 0:
            return False
    except OSError:
        logging.exception("读取文件大小失败: %s", path)
        return False
    return True


def scan_files(paths: list[str] | None = None, exclude_patterns: list[str] | None = None) -> list[ScannedFile]:
    exclude_patterns = exclude_patterns or []
    scanned: list[ScannedFile] = []
    for root in normalize_scan_paths(paths):
        if not root.exists():
            continue
        for current_root, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not should_exclude_dir(d, exclude_patterns)]
            for filename in filenames:
                file_path = Path(current_root) / filename
                if not is_valid_file(file_path):
                    continue
                try:
                    stat = file_path.stat()
                except OSError:
                    logging.exception("读取文件信息失败: %s", file_path)
                    continue
                scanned.append(
                    ScannedFile(
                        file_path=str(file_path.resolve()),
                        name=file_path.name,
                        size=stat.st_size,
                        modified_time=stat.st_mtime,
                    )
                )
    scanned.sort(key=lambda item: item.file_path.lower())
    return scanned
