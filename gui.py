from __future__ import annotations

import os
import sys
import webbrowser
from pathlib import Path
from typing import Any

import yaml
from PySide6.QtCore import QProcess, QProcessEnvironment, Qt
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
    QPlainTextEdit,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


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


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self._read_stdout)
        self.process.readyReadStandardError.connect(self._read_stderr)
        self.process.finished.connect(self._on_process_finished)

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
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setPlaceholderText("运行输出会显示在这里。")
        clear_button = QPushButton("清空日志")
        clear_button.clicked.connect(self.log_output.clear)

        layout.addWidget(self.status_label)
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
        self.batch_size_input.setValue(int(config.get("batch_size", 80) or 80))

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
        if self.process.state() != QProcess.NotRunning:
            QMessageBox.information(self, "任务进行中", "当前已有任务在运行，请等待完成。")
            return

        config = self._build_config_from_form()
        save_config(config)
        self.log_output.clear()
        self.status_label.setText(f"运行中：{' '.join(args)}")
        self._append_log(f"$ {sys.executable} main.py {' '.join(args)}")
        self._update_run_buttons(running=True)

        env = os.environ.copy()
        if config["llm"]["api_key"]:
            env["LLM_API_KEY"] = config["llm"]["api_key"]

        self.process.setWorkingDirectory(str(Path.cwd()))
        self.process.setProgram(sys.executable)
        self.process.setArguments(["main.py", *args])
        self.process.setProcessEnvironment(self._build_process_environment(env))
        self.process.start()

    def _build_process_environment(self, env: dict[str, str]):
        process_env = QProcessEnvironment.systemEnvironment()
        for key, value in env.items():
            process_env.insert(key, value)
        return process_env

    def _read_stdout(self) -> None:
        data = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="ignore")
        if data:
            self._append_log(data.rstrip())

    def _read_stderr(self) -> None:
        data = bytes(self.process.readAllStandardError()).decode("utf-8", errors="ignore")
        if data:
            self._append_log(data.rstrip())

    def _on_process_finished(self, exit_code: int) -> None:
        if exit_code == 0:
            self.status_label.setText("已完成")
        else:
            self.status_label.setText(f"执行失败，退出码 {exit_code}")
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
        self.log_output.appendPlainText(message)
        cursor = self.log_output.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_output.setTextCursor(cursor)


def run_gui() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run_gui())
