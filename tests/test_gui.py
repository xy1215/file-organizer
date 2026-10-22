from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", reason="PySide6 / Qt system libraries not available")

import shiboken6
import yaml
from PySide6.QtCore import QTimer

import gui
from common import OperationCancelled


@pytest.fixture
def window(monkeypatch, tmp_path):
    monkeypatch.setattr(gui, "CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(gui, "check_for_update_status", lambda version: None)
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", staticmethod(lambda *a, **k: QtWidgets.QMessageBox.Yes))
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", staticmethod(lambda *a, **k: None))
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    win = gui.MainWindow()
    win._confirm_llm_usage_if_needed = lambda args: True
    win._ensure_saved_config_for_run = lambda config: True
    yield app, win
    win.deleteLater()


def test_close_during_task_cancels_and_waits(window, monkeypatch):
    app, win = window

    def slow_dispatch(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self._cancel_event.is_set():
                raise OperationCancelled()
            time.sleep(0.05)

    monkeypatch.setattr(gui.CommandWorker, "_dispatch", slow_dispatch)
    win.show()
    win._run_command(["report"])
    worker = win.worker
    QTimer.singleShot(200, win.close)
    QTimer.singleShot(4000, app.quit)  # safety net if the window never closes
    started = time.monotonic()
    app.exec()
    assert time.monotonic() - started < 3, "close should cancel the task instead of waiting it out"
    assert not win.isVisible()
    assert win.worker is None
    # The finished worker is released via deleteLater; if it still exists it must have stopped.
    assert not shiboken6.isValid(worker) or not worker.isRunning()


def test_save_config_round_trip_is_atomic(window):
    _, win = window
    config = gui.default_config()
    config["llm"]["api_key"] = "sk-test"
    gui.save_config(config)
    assert yaml.safe_load(gui.CONFIG_PATH.read_text(encoding="utf-8"))["llm"]["api_key"] == "sk-test"
    assert not gui.CONFIG_PATH.with_name("config.yaml.tmp").exists()
    assert gui.load_config()["llm"]["api_key"] == "sk-test"


def test_auto_sync_never_opens_dialogs(window, monkeypatch):
    app, win = window
    started = []
    monkeypatch.setattr(gui.CommandWorker, "_dispatch", lambda self: started.append(self.args))

    def fail(*args, **kwargs):
        raise AssertionError("auto sync must not open a dialog")

    win._confirm_llm_usage_if_needed = fail
    win._ensure_saved_config_for_run = fail
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", staticmethod(fail))
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", staticmethod(fail))

    # No API key saved: skipped with a log line, no dialog.
    win._trigger_auto_sync()
    assert win.worker is None
    assert "没有 API Key" in win.log_output.toPlainText()

    config = gui.default_config()
    config["llm"]["api_key"] = "sk-test"
    gui.save_config(config)
    win._trigger_auto_sync()
    assert win.worker is not None
    win.worker.wait(5000)
    app.processEvents()
    assert started == [["sync"]]


def test_run_gui_exits_promptly_despite_lingering_worker_threads(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    script = tmp_path / "launch.py"
    script.write_text(
        "import sys, threading, time\n"
        f"sys.path.insert(0, {str(Path(gui.__file__).parent)!r})\n"
        "import gui\n"
        "from PySide6.QtCore import QTimer\n"
        "from PySide6.QtWidgets import QApplication\n"
        "gui.check_for_update_status = lambda version: None\n"
        "threading.Thread(target=time.sleep, args=(60,)).start()  # like an abandoned LLM call\n"
        "original_show = gui.MainWindow.show\n"
        "def show(self):\n"
        "    original_show(self)\n"
        "    QTimer.singleShot(300, QApplication.quit)\n"
        "gui.MainWindow.show = show\n"
        "gui.run_gui()\n",
        encoding="utf-8",
    )
    started = time.monotonic()
    completed = subprocess.run([sys.executable, str(script)], cwd=tmp_path, timeout=45)
    assert completed.returncode == 0
    assert time.monotonic() - started < 30
