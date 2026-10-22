from __future__ import annotations

import subprocess
import sys
import time
import zipfile

import pytest

import updater


def test_updater_script_is_ascii():
    # Must not depend on the system ANSI code page (the exe name is passed as an argument).
    updater.UPDATER_SCRIPT.encode("ascii")


def test_apply_update_rejects_zip_slip(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../escape.txt", "x")
    with pytest.raises(ValueError):
        updater.apply_update(archive, tmp_path / "app")
    assert not (tmp_path / "escape.txt").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="runs the real Windows updater script")
def test_apply_update_waits_for_exit_then_replaces_and_relaunches(tmp_path):
    app_dir = tmp_path / "应用 目录"
    app_dir.mkdir()
    (app_dir / "data.txt").write_text("old", encoding="ascii")
    exe_name = "启动.cmd"  # Non-ASCII on purpose: CI runners use a non-Chinese code page.

    archive = tmp_path / "update.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("data.txt", "new")
        handle.writestr("sub/extra.txt", "extra")
        handle.writestr(exe_name, '@echo launched> "%~dp0launched.txt"\r\n')

    blocker = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(4)"])
    try:
        updater.apply_update(archive, app_dir, exe_name=exe_name, wait_pid=blocker.pid)
        time.sleep(1.5)
        assert (app_dir / "data.txt").read_text(encoding="ascii") == "old", "must wait for the app to exit"
    finally:
        blocker.wait(timeout=30)

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if (app_dir / "launched.txt").exists() and not (app_dir / updater.UPDATER_SCRIPT_NAME).exists():
            break
        time.sleep(0.5)
    assert (app_dir / "data.txt").read_text(encoding="ascii") == "new"
    assert (app_dir / "sub" / "extra.txt").read_text(encoding="ascii") == "extra"
    assert (app_dir / "launched.txt").exists(), "updated app was not relaunched"
    assert not (app_dir / "_update").exists()
    assert not (app_dir / updater.UPDATER_SCRIPT_NAME).exists()
