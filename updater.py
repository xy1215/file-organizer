from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
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


@dataclass
class UpdateCheckResult:
    info: UpdateInfo | None
    reason: str | None = None


class UpdateCancelled(Exception):
    pass


def _normalize_version(value: str) -> Version:
    cleaned = value.strip()
    if cleaned.lower().startswith("v"):
        cleaned = cleaned[1:]
    return Version(cleaned)


def check_for_update_status(current_version: str) -> UpdateCheckResult:
    try:
        request = urllib.request.Request(
            LATEST_RELEASE_URL,
            headers={
                "User-Agent": "file-organizer-updater",
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return UpdateCheckResult(info=None, reason="更新源未发布可用 Release，当前无法检查更新。")
        if exc.code == 403:
            return UpdateCheckResult(info=None, reason="GitHub 更新接口暂时受限，请稍后再试。")
        return UpdateCheckResult(info=None, reason=f"更新检查失败（HTTP {exc.code}）。")
    except (urllib.error.URLError, TimeoutError, OSError):
        return UpdateCheckResult(info=None, reason="无法连接更新服务器。")
    except json.JSONDecodeError:
        return UpdateCheckResult(info=None, reason="更新服务器返回了无法识别的数据。")

    tag_name = str(payload.get("tag_name") or "").strip()
    if not tag_name:
        return UpdateCheckResult(info=None, reason="更新源缺少版本标签信息。")

    try:
        latest_version = _normalize_version(tag_name)
        installed_version = _normalize_version(current_version)
    except InvalidVersion:
        return UpdateCheckResult(info=None, reason="版本号格式无法识别。")

    if latest_version <= installed_version:
        return UpdateCheckResult(info=None, reason=f"当前已是最新版本 v{installed_version}。")

    assets = payload.get("assets", [])
    if not isinstance(assets, list):
        return UpdateCheckResult(info=None, reason="更新源缺少可下载资源列表。")

    download_url = ""
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        candidate = str(asset.get("browser_download_url") or "").strip()
        if candidate.lower().endswith(".zip"):
            download_url = candidate
            break

    if not download_url:
        return UpdateCheckResult(info=None, reason="最新 Release 未附带可下载的 ZIP 安装包。")

    return UpdateCheckResult(
        info=UpdateInfo(
            version=str(latest_version),
            download_url=download_url,
            changelog=str(payload.get("body") or "").strip(),
        ),
    )


def check_for_update(current_version: str) -> UpdateInfo | None:
    return check_for_update_status(current_version).info


def download_update(
    url: str,
    dest_dir: Path,
    on_progress: Callable[[int, int], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dest_dir / "file-organizer-update.zip"
    try:
        with urllib.request.urlopen(url, timeout=30) as response, zip_path.open("wb") as handle:
            total = int(response.headers.get("Content-Length", "0") or 0)
            downloaded = 0
            while True:
                if is_cancelled and is_cancelled():
                    raise UpdateCancelled()
                chunk = response.read(1024 * 128)
                if not chunk:
                    break
                handle.write(chunk)
                downloaded += len(chunk)
                if on_progress:
                    on_progress(downloaded, total)
    except Exception:
        if zip_path.exists():
            zip_path.unlink(missing_ok=True)
        raise
    return zip_path


def apply_update(zip_path: Path, app_dir: Path) -> None:
    if sys.platform != "win32":
        raise RuntimeError("自动更新仅支持 Windows 打包版。")
    update_dir = app_dir / "_update"
    updater_script = app_dir / "_updater.bat"
    exe_path = app_dir / "文件整理助手.exe"
    if update_dir.exists():
        shutil.rmtree(update_dir, ignore_errors=True)
    update_dir.mkdir(parents=True, exist_ok=True)

    resolved_update_dir = update_dir.resolve()
    with zipfile.ZipFile(zip_path, "r") as archive:
        for info in archive.infolist():
            target = (update_dir / info.filename).resolve()
            if os.path.commonpath([str(resolved_update_dir), str(target)]) != str(resolved_update_dir):
                raise ValueError(f"危险路径: {info.filename}")
        archive.extractall(update_dir)

    script_content = f"""@echo off
set "APP_DIR=%~dp0"
set "APP_EXE={exe_path.name}"
cd /d "%~dp0"
timeout /t 2 /nobreak >nul
xcopy /s /y /q "_update\\*" "." >nul
rmdir /s /q "_update"
for /l %%I in (1,1,10) do (
  if exist "%APP_EXE%" (
    start "" "%APP_DIR%%APP_EXE%"
    goto :cleanup
  )
  timeout /t 1 /nobreak >nul
)
:cleanup
del "_updater.bat"
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
