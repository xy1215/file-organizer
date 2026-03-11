from __future__ import annotations

import re
import sys
import webbrowser
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any

import yaml
from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QPlainTextEdit,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from main import run_report, run_scan, run_stats, run_summarize


CONFIG_PATH = Path("config.yaml")
REPORT_PATH = Path("report.html")


def default_config() -> dict[str, Any]:
    return {
        "llm": {
            "provider": "openai",
            "api_key": "",
            "model": "gpt-4o-mini",
            "summary_model": "gpt-4o-mini",
            "base_url": "",
        },
        "scan": {
            "paths": [],
            "exclude_patterns": ["node_modules", ".git", "__pycache__", "AppData"],
        },
        "batch_size": 80,
    }


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return default_config()
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or default_config()


def save_config(config: dict[str, Any]) -> None:
    with CONFIG_PATH.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, allow_unicode=True, sort_keys=False)


def normalize_batch_size(raw_value: Any) -> int:
    try:
        value = int(raw_value or 80)
    except (TypeError, ValueError):
        return 80
    return min(100, max(80, value))


class SignalStream(StringIO):
    def __init__(self, callback) -> None:
        super().__init__()
        self.callback = callback

    def write(self, s: str) -> int:
        if s and s.strip():
            self.callback(s.rstrip())
        return len(s)


class CommandWorker(QThread):
    log = Signal(str)
    finished_status = Signal(bool, str)

    def __init__(self, args: list[str]) -> None:
        super().__init__()
        self.args = args

    def run(self) -> None:
        stream = SignalStream(self.log.emit)
        try:
            with redirect_stdout(stream), redirect_stderr(stream):
                self._dispatch()
        except Exception as exc:
            self.finished_status.emit(False, f"执行失败：{exc}")
        else:
            self.finished_status.emit(True, "")

    def _dispatch(self) -> None:
        if self.args == ["scan"]:
            run_scan(force=False)
            return
        if self.args == ["scan", "--force"]:
            run_scan(force=True)
            return
        if self.args == ["report"]:
            run_report()
            return
        if self.args == ["stats"]:
            run_stats()
            return
        if self.args == ["summarize", "--all"]:
            run_summarize(summarize_all=True)
            return
        if len(self.args) >= 3 and self.args[:2] == ["summarize", "--category"]:
            run_summarize(category_name=self.args[2])
            return
        if len(self.args) >= 3 and self.args[:2] == ["summarize", "--file"]:
            run_summarize(file_path=self.args[2])
            return
        raise RuntimeError(f"不支持的命令: {' '.join(self.args)}")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.worker: CommandWorker | None = None

        self.setWindowTitle("文件整理助手")
        self.resize(1100, 760)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        title = QLabel("本地文件整理与摘要工具")
        title.setStyleSheet("font-size: 24px; font-weight: 700;")
        subtitle = QLabel("面向电脑小白的桌面界面。先配置，再点击按钮执行扫描、摘要和报告。")
        subtitle.setStyleSheet("color: #586271;")

        root.addWidget(title)
        root.addWidget(subtitle)
        root.addLayout(self._build_top_area())
        root.addWidget(self._build_log_area(), stretch=1)

        self.setCentralWidget(central)
        self._load_into_form(load_config())
        self.current_command: list[str] = []
        self._update_run_buttons()

    def _build_top_area(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(14)
        layout.addWidget(self._build_config_panel(), stretch=3)
        layout.addWidget(self._build_action_panel(), stretch=2)
        return layout

    def _build_config_panel(self) -> QGroupBox:
        box = QGroupBox("配置")
        layout = QVBoxLayout(box)
        form = QFormLayout()

        self.provider_input = QLineEdit()
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.model_input = QLineEdit()
        self.summary_model_input = QLineEdit()
        self.base_url_input = QLineEdit()
        self.batch_size_input = QSpinBox()
        self.batch_size_input.setRange(80, 100)

        form.addRow("服务商", self.provider_input)
        form.addRow("API Key", self.api_key_input)
        form.addRow("分类模型", self.model_input)
        form.addRow("摘要模型", self.summary_model_input)
        form.addRow("Base URL", self.base_url_input)
        form.addRow("批次大小", self.batch_size_input)
        layout.addLayout(form)

        path_row = QHBoxLayout()
        self.path_list = QListWidget()
        add_path_button = QPushButton("添加扫描目录")
        add_path_button.clicked.connect(self._add_scan_path)
        remove_path_button = QPushButton("移除选中目录")
        remove_path_button.clicked.connect(self._remove_selected_path)
        path_buttons = QVBoxLayout()
        path_buttons.addWidget(add_path_button)
        path_buttons.addWidget(remove_path_button)
        path_buttons.addStretch(1)
        path_row.addWidget(self.path_list, stretch=1)
        path_row.addLayout(path_buttons)

        self.exclude_input = QPlainTextEdit()
        self.exclude_input.setPlaceholderText("每行一个排除目录名，例如 node_modules")
        self.exclude_input.setFixedHeight(120)

        save_button = QPushButton("保存配置")
        save_button.clicked.connect(self._save_form_config)

        layout.addWidget(QLabel("额外扫描目录"))
        layout.addLayout(path_row)
        layout.addWidget(QLabel("排除目录名"))
        layout.addWidget(self.exclude_input)
        layout.addWidget(save_button, alignment=Qt.AlignRight)
        return box

    def _build_action_panel(self) -> QGroupBox:
        box = QGroupBox("操作")
        layout = QVBoxLayout(box)
        layout.setSpacing(10)

        self.scan_button = QPushButton("开始扫描并分类")
        self.scan_button.clicked.connect(lambda: self._run_command(["scan"]))
        self.force_scan_button = QPushButton("强制重新扫描")
        self.force_scan_button.clicked.connect(lambda: self._run_command(["scan", "--force"]))
        self.report_button = QPushButton("刷新报告")
        self.report_button.clicked.connect(lambda: self._run_command(["report"]))
        self.open_report_button = QPushButton("打开 HTML 报告")
        self.open_report_button.clicked.connect(self._open_report)
        self.stats_button = QPushButton("查看缓存统计")
        self.stats_button.clicked.connect(lambda: self._run_command(["stats"]))

        summarize_box = QGroupBox("摘要")
        summarize_layout = QVBoxLayout(summarize_box)
        self.summary_file_radio = QRadioButton("按单个文件")
        self.summary_category_radio = QRadioButton("按分类")
        self.summary_all_radio = QRadioButton("全部已分类文件")
        self.summary_file_radio.setChecked(True)

        self.summary_file_input = QLineEdit()
        self.summary_file_input.setPlaceholderText("选择一个文件")
        choose_file_button = QPushButton("选择文件")
        choose_file_button.clicked.connect(self._choose_summary_file)
        file_row = QHBoxLayout()
        file_row.addWidget(self.summary_file_input, stretch=1)
        file_row.addWidget(choose_file_button)

        self.summary_category_input = QLineEdit()
        self.summary_category_input.setPlaceholderText("输入分类名称，例如 财务/税务")

        self.run_summary_button = QPushButton("生成摘要")
        self.run_summary_button.clicked.connect(self._run_summary_command)

        summarize_layout.addWidget(self.summary_file_radio)
        summarize_layout.addLayout(file_row)
        summarize_layout.addWidget(self.summary_category_radio)
        summarize_layout.addWidget(self.summary_category_input)
        summarize_layout.addWidget(self.summary_all_radio)
        summarize_layout.addWidget(self.run_summary_button)

        layout.addWidget(self.scan_button)
        layout.addWidget(self.force_scan_button)
        layout.addWidget(self.report_button)
        layout.addWidget(self.open_report_button)
        layout.addWidget(self.stats_button)
        layout.addWidget(summarize_box)
        layout.addStretch(1)
        return box

    def _build_log_area(self) -> QGroupBox:
        box = QGroupBox("运行日志")
        layout = QVBoxLayout(box)
        self.status_label = QLabel("空闲")
        self.status_label.setStyleSheet("font-weight: 600;")
        self.phase_label = QLabel("等待开始")
        self.phase_label.setStyleSheet("color: #586271;")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("未开始")
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setPlaceholderText("运行输出会显示在这里。")
        clear_button = QPushButton("清空日志")
        clear_button.clicked.connect(self.log_output.clear)

        layout.addWidget(self.status_label)
        layout.addWidget(self.phase_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.log_output, stretch=1)
        layout.addWidget(clear_button, alignment=Qt.AlignRight)
        return box

    def _load_into_form(self, config: dict[str, Any]) -> None:
        llm = config.get("llm", {})
        scan = config.get("scan", {})
        self.provider_input.setText(str(llm.get("provider", "openai")))
        self.api_key_input.setText(str(llm.get("api_key", "")))
        self.model_input.setText(str(llm.get("model", "gpt-4o-mini")))
        self.summary_model_input.setText(str(llm.get("summary_model", "gpt-4o-mini")))
        self.base_url_input.setText(str(llm.get("base_url", "")))
        self.batch_size_input.setValue(normalize_batch_size(config.get("batch_size", 80)))

        self.path_list.clear()
        for path in scan.get("paths", []):
            self.path_list.addItem(QListWidgetItem(str(path)))
        self.exclude_input.setPlainText("\n".join(scan.get("exclude_patterns", [])))

    def _build_config_from_form(self) -> dict[str, Any]:
        return {
            "llm": {
                "provider": self.provider_input.text().strip() or "openai",
                "api_key": self.api_key_input.text().strip(),
                "model": self.model_input.text().strip() or "gpt-4o-mini",
                "summary_model": self.summary_model_input.text().strip() or "gpt-4o-mini",
                "base_url": self.base_url_input.text().strip(),
            },
            "scan": {
                "paths": [self.path_list.item(i).text() for i in range(self.path_list.count())],
                "exclude_patterns": [
                    line.strip()
                    for line in self.exclude_input.toPlainText().splitlines()
                    if line.strip()
                ],
            },
            "batch_size": self.batch_size_input.value(),
        }

    def _save_form_config(self) -> None:
        config = self._build_config_from_form()
        save_config(config)
        self._append_log("配置已保存到 config.yaml")
        QMessageBox.information(self, "保存成功", "配置已保存。")

    def _add_scan_path(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择需要扫描的目录")
        if not directory:
            return
        items = {self.path_list.item(i).text() for i in range(self.path_list.count())}
        if directory not in items:
            self.path_list.addItem(QListWidgetItem(directory))

    def _remove_selected_path(self) -> None:
        row = self.path_list.currentRow()
        if row >= 0:
            self.path_list.takeItem(row)

    def _choose_summary_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "选择要生成摘要的文件")
        if file_path:
            self.summary_file_input.setText(file_path)
            self.summary_file_radio.setChecked(True)

    def _run_summary_command(self) -> None:
        if self.summary_all_radio.isChecked():
            self._run_command(["summarize", "--all"])
            return

        if self.summary_category_radio.isChecked():
            category = self.summary_category_input.text().strip()
            if not category:
                QMessageBox.warning(self, "缺少分类", "请输入分类名称。")
                return
            self._run_command(["summarize", "--category", category])
            return

        file_path = self.summary_file_input.text().strip()
        if not file_path:
            QMessageBox.warning(self, "缺少文件", "请先选择一个文件。")
            return
        self._run_command(["summarize", "--file", file_path])

    def _run_command(self, args: list[str]) -> None:
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "任务进行中", "当前已有任务在运行，请等待完成。")
            return

        config = self._build_config_from_form()
        save_config(config)
        self.current_command = list(args)
        self.log_output.clear()
        self.status_label.setText(f"运行中：{' '.join(args)}")
        self.phase_label.setText("任务已启动，正在准备...")
        self._set_busy_progress()
        self._append_log(f"开始执行：{' '.join(args)}")
        self._update_run_buttons(running=True)

        self.worker = CommandWorker(args=args)
        self.worker.log.connect(self._append_log)
        self.worker.finished_status.connect(self._on_worker_finished)
        self.worker.start()

    def _on_worker_finished(self, success: bool, message: str) -> None:
        self.status_label.setText("已完成" if success else "执行失败")
        self.phase_label.setText("任务完成" if success else "任务失败")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100 if success else 0)
        self.progress_bar.setFormat("完成" if success else "失败")
        if message:
            self._append_log(message)
        elif success:
            self._append_log("任务执行完成。")
        self._update_run_buttons(running=False)

    def _update_run_buttons(self, running: bool = False) -> None:
        enabled = not running
        for button in [
            self.scan_button,
            self.force_scan_button,
            self.report_button,
            self.stats_button,
            self.run_summary_button,
        ]:
            button.setEnabled(enabled)

    def _open_report(self) -> None:
        if not REPORT_PATH.exists():
            QMessageBox.information(self, "报告不存在", "还没有 report.html，请先执行扫描或生成报告。")
            return
        webbrowser.open(REPORT_PATH.resolve().as_uri())

    def _append_log(self, message: str) -> None:
        self._update_progress_from_log(message)
        self.log_output.appendPlainText(message)
        cursor = self.log_output.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_output.setTextCursor(cursor)

    def _set_busy_progress(self) -> None:
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFormat("处理中...")

    def _update_progress_from_log(self, message: str) -> None:
        plain = self._strip_rich_markup(message)
        if "正在扫描目录" in plain:
            self.phase_label.setText("正在扫描目录...")
            self._set_busy_progress()
            return
        if "正在检查缓存" in plain:
            self.phase_label.setText("扫描完成，正在检查缓存...")
            self._set_busy_progress()
            return
        if "开始分类" in plain or "缓存检查完成，开始分类" in plain:
            self.phase_label.setText("正在调用模型进行分类...")
            self._set_busy_progress()
        if "正在生成摘要" in plain or "开始生成摘要" in plain:
            self.phase_label.setText("正在生成摘要...")
            self._set_busy_progress()
        if "正在生成报告" in plain or "正在刷新报告" in plain:
            self.phase_label.setText("正在生成报告...")
            self._set_busy_progress()
            return
        if "正在读取缓存统计" in plain:
            self.phase_label.setText("正在读取缓存统计...")
            self._set_busy_progress()
            return

        match = re.search(r"进度：(\d+)/(\d+)", plain)
        if match:
            current = int(match.group(1))
            total = int(match.group(2))
            value = int(current * 100 / total) if total else 0
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(value)
            self.progress_bar.setFormat(f"{current}/{total}")
            self.phase_label.setText(plain)
            return

        if "执行失败" in plain or "摘要失败" in plain:
            self.phase_label.setText("任务出现错误，请查看日志。")
            return
        if "扫描完成" in plain or "摘要任务完成" in plain or "报告已生成" in plain:
            self.phase_label.setText(plain)

    def _strip_rich_markup(self, message: str) -> str:
        return re.sub(r"\[[^\]]+\]", "", message).strip()


def run_gui() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run_gui())
