from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from packaging.version import InvalidVersion, Version


GITHUB_REPO = "xy1215/file-organizer"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


@dataclass
class UpdateInfo:
    version: str
    download_url: str
    changelog: str


def _normalize_version(value: str) -> Version:
    cleaned = value.strip()
    if cleaned.lower().startswith("v"):
        cleaned = cleaned[1:]
    return Version(cleaned)


def check_for_update(current_version: str) -> UpdateInfo | None:
    try:
        with urllib.request.urlopen(LATEST_RELEASE_URL, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, json.JSONDecodeError):
        return None

    tag_name = str(payload.get("tag_name") or "").strip()
    if not tag_name:
        return None

    try:
        latest_version = _normalize_version(tag_name)
        installed_version = _normalize_version(current_version)
    except InvalidVersion:
        return None

    if latest_version <= installed_version:
        return None

    assets = payload.get("assets", [])
    if not isinstance(assets, list):
        return None

    download_url = ""
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        candidate = str(asset.get("browser_download_url") or "").strip()
        if candidate.lower().endswith(".zip"):
            download_url = candidate
            break

    if not download_url:
        return None

    return UpdateInfo(
        version=str(latest_version),
        download_url=download_url,
        changelog=str(payload.get("body") or "").strip(),
    )


def download_update(
    url: str,
    dest_dir: Path,
    on_progress: Callable[[int, int], None] | None = None,
) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dest_dir / "file-organizer-update.zip"
    with urllib.request.urlopen(url, timeout=30) as response, zip_path.open("wb") as handle:
        total = int(response.headers.get("Content-Length", "0") or 0)
        downloaded = 0
        while True:
            chunk = response.read(1024 * 128)
            if not chunk:
                break
            handle.write(chunk)
            downloaded += len(chunk)
            if on_progress:
                on_progress(downloaded, total)
    return zip_path


def apply_update(zip_path: Path, app_dir: Path) -> None:
    update_dir = app_dir / "_update"
    updater_script = app_dir / "_updater.bat"
    if update_dir.exists():
        shutil.rmtree(update_dir, ignore_errors=True)
    update_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as archive:
        archive.extractall(update_dir)

    script_content = """@echo off
timeout /t 2 /nobreak >nul
xcopy /s /y /q "_update\\*" "." >nul
rmdir /s /q "_update"
del "_updater.bat"
start "" "文件整理助手.exe"
"""
    updater_script.write_text(script_content, encoding="utf-8")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        ["cmd", "/c", str(updater_script.name)],
        cwd=str(app_dir),
        creationflags=creationflags,
    )


def make_download_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="file-organizer-update-"))
