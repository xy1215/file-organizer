from __future__ import annotations

import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

import yaml
from PySide6.QtCore import QThread, Qt, QTimer, Signal, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QProgressDialog,
    QPlainTextEdit,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app_paths import app_path, get_app_dir
from common import OperationCancelled, ensure_dict, ensure_str_list
from main import RuntimeHooks, run_report, run_scan, run_stats, run_summarize
from main import run_sync
from updater import (
    UpdateCancelled,
    UpdateCheckResult,
    UpdateInfo,
    apply_update,
    check_for_update_status,
    download_update,
    make_download_dir,
)
from version import __version__


CONFIG_PATH = app_path("config.yaml")
REPORT_PATH = app_path("report.html")


class UpdateCheckWorker(QThread):
    checked = Signal(object)

    def run(self) -> None:
        self.checked.emit(check_for_update_status(__version__))


class UpdateDownloadWorker(QThread):
    progress_changed = Signal(int, int)
    finished_update = Signal(str, str, bool)

    def __init__(self, update_info: UpdateInfo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.update_info = update_info
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            zip_path = download_update(
                self.update_info.download_url,
                make_download_dir(),
                on_progress=lambda current, total: self.progress_changed.emit(current, total),
                is_cancelled=self._cancel_event.is_set,
            )
        except UpdateCancelled:
            self.finished_update.emit("", "", True)
            return
        except Exception as exc:
            self.finished_update.emit("", str(exc), False)
            return
        self.finished_update.emit(str(zip_path), "", False)


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
            "default_paths": {
                "desktop": True,
                "documents": True,
                "downloads": True,
            },
            "paths": [],
            "exclude_patterns": ["node_modules", ".git", "__pycache__", "AppData"],
        },
        "batch_size": 30,
        "classification_workers": 2,
        "summary_workers": 4,
        "automation": {
            "auto_scan_enabled": False,
            "interval_minutes": 60,
        },
    }


def load_config() -> dict[str, Any]:
    config = default_config()
    if not CONFIG_PATH.exists():
        return config
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle)
    except yaml.YAMLError:
        return config
    if not loaded:
        return config
    if not isinstance(loaded, dict):
        return config

    llm = ensure_dict(loaded.get("llm", {}))
    scan = ensure_dict(loaded.get("scan", {}))
    default_paths = ensure_dict(scan.get("default_paths", {}))
    automation = ensure_dict(loaded.get("automation", {}))

    config["llm"].update(
        {
            "provider": str(llm.get("provider") or config["llm"]["provider"]).strip() or "openai",
            "api_key": str(llm.get("api_key") or "").strip(),
            "model": str(llm.get("model") or config["llm"]["model"]).strip() or config["llm"]["model"],
            "summary_model": str(llm.get("summary_model") or config["llm"]["summary_model"]).strip()
            or config["llm"]["summary_model"],
            "base_url": str(llm.get("base_url") or "").strip(),
        }
    )
    config["scan"].update(
        {
            "default_paths": {
                "desktop": bool(default_paths.get("desktop", config["scan"]["default_paths"]["desktop"])),
                "documents": bool(default_paths.get("documents", config["scan"]["default_paths"]["documents"])),
                "downloads": bool(default_paths.get("downloads", config["scan"]["default_paths"]["downloads"])),
            },
            "paths": ensure_str_list(scan.get("paths", [])),
            "exclude_patterns": ensure_str_list(scan.get("exclude_patterns", [])),
        }
    )
    config["batch_size"] = normalize_batch_size(loaded.get("batch_size", config["batch_size"]))
    config["classification_workers"] = normalize_classification_workers(
        loaded.get("classification_workers", config["classification_workers"])
    )
    config["summary_workers"] = normalize_summary_workers(
        loaded.get("summary_workers", config["summary_workers"])
    )
    config["automation"].update(
        {
            "auto_scan_enabled": bool(automation.get("auto_scan_enabled", config["automation"]["auto_scan_enabled"])),
            "interval_minutes": normalize_auto_scan_interval(
                automation.get("interval_minutes", config["automation"]["interval_minutes"])
            ),
        }
    )
    return config


def save_config(config: dict[str, Any]) -> None:
    with CONFIG_PATH.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, allow_unicode=True, sort_keys=False)


def normalize_batch_size(raw_value: Any) -> int:
    try:
        value = int(raw_value or 30)
    except (TypeError, ValueError):
        return 30
    return min(100, max(10, value))


def normalize_summary_workers(raw_value: Any) -> int:
    try:
        value = int(raw_value or 4)
    except (TypeError, ValueError):
        return 4
    return min(8, max(1, value))


def normalize_classification_workers(raw_value: Any) -> int:
    try:
        value = int(raw_value or 2)
    except (TypeError, ValueError):
        return 2
    return min(4, max(1, value))


def normalize_auto_scan_interval(raw_value: Any) -> int:
    try:
        value = int(raw_value or 60)
    except (TypeError, ValueError):
        return 60
    return min(1440, max(15, value))


class CommandWorker(QThread):
    log = Signal(str)
    progress = Signal(str, int, int, str)
    finished_status = Signal(bool, str, bool)

    def __init__(self, args: list[str]) -> None:
        super().__init__()
        self.args = args
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            self._dispatch()
        except OperationCancelled:
            self.finished_status.emit(False, "任务已取消。", True)
        except Exception as exc:
            self.finished_status.emit(False, f"执行失败：{exc}", False)
        else:
            self.finished_status.emit(True, "", False)

    def _dispatch(self) -> None:
        hooks = RuntimeHooks(
            log=self.log.emit,
            progress=self.progress.emit,
            is_cancelled=self._cancel_event.is_set,
        )
        if self.args == ["scan"]:
            run_scan(force=False, hooks=hooks)
            return
        if self.args == ["scan", "--force"]:
            run_scan(force=True, hooks=hooks)
            return
        if self.args == ["report"]:
            run_report(hooks=hooks)
            return
        if self.args == ["stats"]:
            run_stats(hooks=hooks)
            return
        if self.args == ["sync"]:
            run_sync(hooks=hooks)
            return
        if self.args == ["summarize", "--all"]:
            run_summarize(summarize_all=True, hooks=hooks)
            return
        if len(self.args) >= 3 and self.args[:2] == ["summarize", "--category"]:
            run_summarize(category_name=self.args[2], hooks=hooks)
            return
        if len(self.args) >= 3 and self.args[:2] == ["summarize", "--file"]:
            run_summarize(file_path=self.args[2], hooks=hooks)
            return
        raise RuntimeError(f"不支持的命令: {' '.join(self.args)}")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.worker: CommandWorker | None = None
        self.update_check_worker: UpdateCheckWorker | None = None
        self.update_download_worker: UpdateDownloadWorker | None = None
        self.available_update: UpdateInfo | None = None
        self.ignored_update_version: str | None = None
        self._manual_update_check_pending = False
        self.update_progress_dialog: QProgressDialog | None = None
        self.current_total = 0
        self.current_progress = 0
        self.started_at: float | None = None
        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.setInterval(1000)
        self.elapsed_timer.timeout.connect(self._refresh_elapsed_time)
        self.auto_scan_timer = QTimer(self)
        self.auto_scan_timer.timeout.connect(self._trigger_auto_sync)

        self.setWindowTitle(f"文件整理助手 v{__version__}")
        self.resize(920, 680)
        self.setMinimumSize(760, 560)
        self._apply_theme()
        self._setup_menu_bar()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        central = QWidget()
        central.setObjectName("centralSurface")
        root = QVBoxLayout(central)
        root.setContentsMargins(24, 22, 24, 24)
        root.setSpacing(16)

        root.addWidget(self._build_hero_section())
        root.addWidget(self._build_update_banner())
        root.addLayout(self._build_top_area())
        root.addWidget(self._build_log_area(), stretch=1)

        scroll.setWidget(central)
        self.setCentralWidget(scroll)
        self._load_into_form(load_config())
        self.current_command: list[str] = []
        self._update_run_buttons()
        self._refresh_status_badges()
        self._apply_responsive_layouts()
        self._start_update_check()

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow {
                background: #f5efe6;
            }
            QWidget#centralSurface {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #f8f2ea, stop:0.55 #f4eee5, stop:1 #efe6db);
            }
            QMenuBar {
                background: rgba(255, 255, 255, 0.72);
                color: #433129;
                border: 1px solid rgba(125, 86, 55, 0.18);
                border-radius: 10px;
                padding: 6px 10px;
                spacing: 10px;
            }
            QMenuBar::item {
                padding: 6px 10px;
                border-radius: 8px;
                background: transparent;
            }
            QMenuBar::item:selected {
                background: #ead9c9;
            }
            QMenu {
                background: #fffaf5;
                border: 1px solid #d9c5b3;
                padding: 8px;
            }
            QMenu::item {
                padding: 8px 14px;
                border-radius: 8px;
            }
            QMenu::item:selected {
                background: #f0dfcf;
            }
            QFrame#heroCard, QFrame#statusCard, QFrame#updateBanner {
                background: rgba(255, 251, 246, 0.92);
                border: 1px solid rgba(130, 93, 67, 0.16);
                border-radius: 18px;
            }
            QFrame#heroCard {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #fff7ef, stop:0.6 #f3e4d4, stop:1 #e9d7c3);
            }
            QLabel#eyebrow {
                color: #8b5e3c;
                font-size: 12px;
                font-weight: 700;
                letter-spacing: 1px;
                text-transform: uppercase;
            }
            QLabel#heroTitle {
                color: #2d211c;
                font-size: 30px;
                font-weight: 800;
            }
            QLabel#heroSubtitle {
                color: #6c584d;
                font-size: 14px;
                line-height: 1.4;
            }
            QLabel#heroBadge {
                background: rgba(255, 250, 244, 0.88);
                border: 1px solid rgba(109, 74, 48, 0.14);
                border-radius: 14px;
                color: #5a4337;
                font-weight: 600;
                padding: 8px 12px;
            }
            QGroupBox {
                color: #3f2f27;
                font-size: 15px;
                font-weight: 700;
                background: rgba(255, 251, 246, 0.9);
                border: 1px solid rgba(130, 93, 67, 0.16);
                border-radius: 18px;
                margin-top: 14px;
                padding-top: 18px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 16px;
                padding: 0 8px;
                color: #7b5439;
            }
            QLabel {
                color: #3f2f27;
            }
            QLabel#mutedLabel {
                color: #6e5c51;
            }
            QLabel#statusValue {
                color: #2a201c;
                font-size: 18px;
                font-weight: 800;
            }
            QLabel#statusCaption {
                color: #7a6658;
                font-size: 12px;
                font-weight: 600;
            }
            QLineEdit, QPlainTextEdit, QListWidget, QSpinBox {
                background: rgba(255, 255, 255, 0.82);
                border: 1px solid #d9c7b6;
                border-radius: 12px;
                padding: 8px 10px;
                color: #2e241f;
                selection-background-color: #c57f45;
            }
            QLineEdit:focus, QPlainTextEdit:focus, QListWidget:focus, QSpinBox:focus {
                border: 1px solid #bb6f33;
                background: #fffdfb;
            }
            QListWidget {
                padding: 6px;
            }
            QListWidget::item {
                border-radius: 8px;
                padding: 7px 8px;
                margin: 2px 0;
            }
            QListWidget::item:selected {
                background: #f0dfcf;
                color: #2e241f;
            }
            QPushButton {
                background: #efe0d1;
                color: #452f24;
                border: 1px solid rgba(129, 88, 58, 0.18);
                border-radius: 12px;
                padding: 10px 14px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: #e8d5c3;
            }
            QPushButton:pressed {
                background: #dec4ac;
            }
            QPushButton:disabled {
                background: #e8ddd2;
                color: #a08e81;
                border-color: rgba(129, 88, 58, 0.1);
            }
            QPushButton[role="primary"] {
                background: #b7652f;
                color: #fffaf5;
                border: none;
            }
            QPushButton[role="primary"]:hover {
                background: #a85a28;
            }
            QPushButton[role="primary"]:pressed {
                background: #954d1f;
            }
            QPushButton[role="accent"] {
                background: #2f6c63;
                color: #f4fbf8;
                border: none;
            }
            QPushButton[role="accent"]:hover {
                background: #285c55;
            }
            QPushButton[role="danger"] {
                background: #a84c4c;
                color: #fff8f6;
                border: none;
            }
            QPushButton[role="danger"]:hover {
                background: #963f3f;
            }
            QCheckBox, QRadioButton {
                color: #4a3931;
                spacing: 8px;
            }
            QProgressBar {
                min-height: 16px;
                border-radius: 8px;
                background: #eadccd;
                border: none;
                text-align: center;
                color: #4a3931;
                font-weight: 700;
            }
            QProgressBar::chunk {
                border-radius: 8px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #b8662f, stop:1 #d49a59);
            }
            QPlainTextEdit {
                background: #fffdf9;
                font-family: Menlo, Monaco, monospace;
                font-size: 12px;
            }
            """
        )

    def _setup_menu_bar(self) -> None:
        help_menu = self.menuBar().addMenu("帮助")

        version_action = QAction(f"当前版本 v{__version__}", self)
        version_action.setEnabled(False)
        help_menu.addAction(version_action)

        check_update_action = QAction("检查更新", self)
        check_update_action.triggered.connect(self._check_for_updates_manually)
        help_menu.addAction(check_update_action)

    def _build_hero_section(self) -> QFrame:
        card = QFrame()
        card.setObjectName("heroCard")
        layout = QBoxLayout(QBoxLayout.LeftToRight, card)
        self.hero_layout = layout
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(18)

        text_column = QVBoxLayout()
        text_column.setSpacing(6)

        eyebrow = QLabel("Desktop Organizer")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("文件整理助手")
        title.setObjectName("heroTitle")
        subtitle = QLabel("把扫描、分类、摘要和报告放在一个桌面工作台里。先配置，再开始巡检。")
        subtitle.setObjectName("heroSubtitle")
        subtitle.setWordWrap(True)

        badge_row = QHBoxLayout()
        badge_row.setSpacing(10)
        for text in [f"v{__version__}", "本地优先", "HTML 报告"]:
            badge = QLabel(text)
            badge.setObjectName("heroBadge")
            badge_row.addWidget(badge)
        badge_row.addStretch(1)

        text_column.addWidget(eyebrow)
        text_column.addWidget(title)
        text_column.addWidget(subtitle)
        text_column.addLayout(badge_row)

        summary_column = QVBoxLayout()
        summary_column.setSpacing(10)
        summary_column.addWidget(self._make_status_tile("当前状态", "空闲", "准备开始"), stretch=1)
        summary_column.addWidget(self._make_status_tile("最近动作", "等待中", "尚未开始任务"), stretch=1)

        layout.addLayout(text_column, stretch=3)
        layout.addLayout(summary_column, stretch=2)
        return card

    def _make_status_tile(self, title: str, value: str, caption: str) -> QFrame:
        card = QFrame()
        card.setObjectName("statusCard")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)

        heading = QLabel(title)
        heading.setObjectName("statusCaption")
        heading.setProperty("class", "caption")
        value_label = QLabel(value)
        value_label.setObjectName("statusValue")
        caption_label = QLabel(caption)
        caption_label.setObjectName("statusCaption")

        layout.addWidget(heading)
        layout.addWidget(value_label)
        layout.addWidget(caption_label)

        if title == "当前状态":
            self.hero_status_value = value_label
            self.hero_status_caption = caption_label
        else:
            self.hero_phase_value = value_label
            self.hero_phase_caption = caption_label
        return card

    def _build_update_banner(self) -> QFrame:
        self.update_banner = QFrame()
        self.update_banner.setObjectName("updateBanner")
        layout = QHBoxLayout(self.update_banner)
        layout.setContentsMargins(18, 12, 18, 12)
        self.update_label = QLabel("发现新版本")
        self.update_label.setStyleSheet("font-weight: 700; color: #214e67;")
        self.update_now_button = QPushButton("立即更新")
        self.update_now_button.setProperty("role", "primary")
        self.update_now_button.clicked.connect(self._handle_update_now)
        self.update_ignore_button = QPushButton("忽略")
        self.update_ignore_button.clicked.connect(self._ignore_current_update)
        layout.addWidget(self.update_label, stretch=1)
        layout.addWidget(self.update_now_button)
        layout.addWidget(self.update_ignore_button)
        self.update_banner.hide()
        return self.update_banner

    def _build_top_area(self) -> QHBoxLayout:
        layout = QBoxLayout(QBoxLayout.LeftToRight)
        self.top_area_layout = layout
        layout.setSpacing(14)
        layout.addWidget(self._build_config_panel(), stretch=3)
        layout.addWidget(self._build_action_panel(), stretch=2)
        return layout

    def _build_config_panel(self) -> QGroupBox:
        box = QGroupBox("配置")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.provider_input = QLineEdit()
        self.provider_input.setPlaceholderText("openai / anthropic")
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.api_key_input.setPlaceholderText("优先读取环境变量，也可直接填写")
        self.model_input = QLineEdit()
        self.summary_model_input = QLineEdit()
        self.base_url_input = QLineEdit()
        self.base_url_input.setPlaceholderText("留空使用官方 API 地址")
        self.batch_size_input = QSpinBox()
        self.batch_size_input.setRange(10, 100)
        self.classification_workers_input = QSpinBox()
        self.classification_workers_input.setRange(1, 4)
        self.summary_workers_input = QSpinBox()
        self.summary_workers_input.setRange(1, 8)
        self.auto_scan_checkbox = QCheckBox("开启每小时自动巡检")
        self.auto_scan_checkbox.toggled.connect(lambda _: self._sync_auto_scan_timer())
        self.auto_scan_interval_input = QSpinBox()
        self.auto_scan_interval_input.setRange(15, 1440)
        self.auto_scan_interval_input.setSuffix(" 分钟")
        self.auto_scan_interval_input.valueChanged.connect(lambda _: self._sync_auto_scan_timer())

        form.addRow("服务商", self.provider_input)
        form.addRow("API Key", self.api_key_input)
        form.addRow("分类模型", self.model_input)
        form.addRow("摘要模型", self.summary_model_input)
        form.addRow("Base URL", self.base_url_input)
        form.addRow("批次大小", self.batch_size_input)
        form.addRow("分类并发", self.classification_workers_input)
        form.addRow("摘要并发", self.summary_workers_input)
        form.addRow("自动巡检", self.auto_scan_checkbox)
        form.addRow("巡检间隔", self.auto_scan_interval_input)
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
        save_button.setProperty("role", "primary")
        save_button.clicked.connect(self._save_form_config)

        helper = QLabel("建议先确认模型与扫描范围，再开始巡检。默认目录可单独勾选或取消。")
        helper.setObjectName("mutedLabel")
        helper.setWordWrap(True)
        layout.addWidget(helper)
        layout.addWidget(QLabel("额外扫描目录"))
        default_path_box = QGroupBox("默认扫描目录")
        default_path_layout = QVBoxLayout(default_path_box)
        default_path_layout.setContentsMargins(14, 16, 14, 12)
        self.scan_desktop_checkbox = QCheckBox("Desktop")
        self.scan_documents_checkbox = QCheckBox("Documents")
        self.scan_downloads_checkbox = QCheckBox("Downloads")
        self.scan_desktop_checkbox.setChecked(True)
        self.scan_documents_checkbox.setChecked(True)
        self.scan_downloads_checkbox.setChecked(True)
        default_path_layout.addWidget(self.scan_desktop_checkbox)
        default_path_layout.addWidget(self.scan_documents_checkbox)
        default_path_layout.addWidget(self.scan_downloads_checkbox)
        layout.addWidget(default_path_box)
        layout.addLayout(path_row)
        layout.addWidget(QLabel("排除目录名"))
        layout.addWidget(self.exclude_input)
        layout.addWidget(save_button, alignment=Qt.AlignRight)
        return box

    def _build_action_panel(self) -> QGroupBox:
        box = QGroupBox("操作")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        self.scan_button = QPushButton("开始扫描并分类")
        self.scan_button.setProperty("role", "primary")
        self.scan_button.clicked.connect(lambda: self._run_command(["scan"]))
        self.force_scan_button = QPushButton("强制重新扫描")
        self.force_scan_button.clicked.connect(lambda: self._run_command(["scan", "--force"]))
        self.report_button = QPushButton("刷新报告")
        self.report_button.clicked.connect(lambda: self._run_command(["report"]))
        self.open_report_button = QPushButton("打开 HTML 报告")
        self.open_report_button.setProperty("role", "accent")
        self.open_report_button.clicked.connect(self._open_report)
        self.stats_button = QPushButton("查看缓存统计")
        self.stats_button.clicked.connect(lambda: self._run_command(["stats"]))
        self.sync_button = QPushButton("增量巡检并刷新报告")
        self.sync_button.setProperty("role", "accent")
        self.sync_button.clicked.connect(lambda: self._run_command(["sync"]))
        self.cancel_button = QPushButton("取消当前任务")
        self.cancel_button.setProperty("role", "danger")
        self.cancel_button.clicked.connect(self._cancel_running_task)
        self.cancel_button.setEnabled(False)

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
        self.run_summary_button.setProperty("role", "primary")
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
        layout.addWidget(self.sync_button)
        layout.addWidget(self.cancel_button)
        layout.addWidget(summarize_box)
        layout.addStretch(1)
        return box

    def _build_log_area(self) -> QGroupBox:
        box = QGroupBox("运行日志")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        status_row = QGridLayout()
        status_row.setHorizontalSpacing(10)
        status_row.setVerticalSpacing(10)
        self.status_label = self._make_metric_card("状态", "空闲")
        self.phase_label = self._make_metric_card("阶段", "等待开始")
        self.elapsed_label = self._make_metric_card("耗时", "00:00")
        self.progress_detail_label = self._make_metric_card("进度", "未开始")
        status_row.addWidget(self.status_label, 0, 0)
        status_row.addWidget(self.phase_label, 0, 1)
        status_row.addWidget(self.elapsed_label, 1, 0)
        status_row.addWidget(self.progress_detail_label, 1, 1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("未开始")
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setPlaceholderText("运行输出会显示在这里。")
        clear_button = QPushButton("清空日志")
        clear_button.clicked.connect(self.log_output.clear)

        layout.addLayout(status_row)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.log_output, stretch=1)
        layout.addWidget(clear_button, alignment=Qt.AlignRight)
        return box

    def _make_metric_card(self, title: str, value: str) -> QLabel:
        label = QLabel(f"{title}\n{value}")
        label.setObjectName("heroBadge")
        label.setMinimumHeight(68)
        label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        return label

    def _load_into_form(self, config: dict[str, Any]) -> None:
        llm = ensure_dict(config.get("llm", {}))
        scan = ensure_dict(config.get("scan", {}))
        default_paths = ensure_dict(scan.get("default_paths", {}))
        automation = ensure_dict(config.get("automation", {}))
        self.provider_input.setText(str(llm.get("provider", "openai")))
        self.api_key_input.setText(str(llm.get("api_key", "")))
        self.model_input.setText(str(llm.get("model", "gpt-4o-mini")))
        self.summary_model_input.setText(str(llm.get("summary_model", "gpt-4o-mini")))
        self.base_url_input.setText(str(llm.get("base_url", "")))
        self.batch_size_input.setValue(normalize_batch_size(config.get("batch_size", 30)))
        self.classification_workers_input.setValue(
            normalize_classification_workers(config.get("classification_workers", 2))
        )
        self.summary_workers_input.setValue(normalize_summary_workers(config.get("summary_workers", 4)))
        self.auto_scan_checkbox.setChecked(bool(automation.get("auto_scan_enabled", False)))
        self.auto_scan_interval_input.setValue(
            normalize_auto_scan_interval(automation.get("interval_minutes", 60))
        )
        self.scan_desktop_checkbox.setChecked(bool(default_paths.get("desktop", True)))
        self.scan_documents_checkbox.setChecked(bool(default_paths.get("documents", True)))
        self.scan_downloads_checkbox.setChecked(bool(default_paths.get("downloads", True)))

        self.path_list.clear()
        for path in ensure_str_list(scan.get("paths", [])):
            self.path_list.addItem(QListWidgetItem(str(path)))
        self.exclude_input.setPlainText("\n".join(ensure_str_list(scan.get("exclude_patterns", []))))
        self._sync_auto_scan_timer()

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
                "default_paths": {
                    "desktop": self.scan_desktop_checkbox.isChecked(),
                    "documents": self.scan_documents_checkbox.isChecked(),
                    "downloads": self.scan_downloads_checkbox.isChecked(),
                },
                "paths": [self.path_list.item(i).text() for i in range(self.path_list.count())],
                "exclude_patterns": [
                    line.strip()
                    for line in self.exclude_input.toPlainText().splitlines()
                    if line.strip()
                ],
            },
            "batch_size": self.batch_size_input.value(),
            "classification_workers": self.classification_workers_input.value(),
            "summary_workers": self.summary_workers_input.value(),
            "automation": {
                "auto_scan_enabled": self.auto_scan_checkbox.isChecked(),
                "interval_minutes": self.auto_scan_interval_input.value(),
            },
        }

    def _save_form_config(self) -> None:
        config = self._build_config_from_form()
        save_config(config)
        self._sync_auto_scan_timer()
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
        self._sync_auto_scan_timer()
        self.current_command = list(args)
        self.current_total = 0
        self.current_progress = 0
        self.started_at = time.monotonic()
        self.log_output.clear()
        self.status_label.setText(f"状态\n运行中：{' '.join(args)}")
        self.phase_label.setText("阶段\n任务已启动")
        self.elapsed_label.setText("耗时\n00:00")
        self.progress_detail_label.setText("进度\n准备中")
        self._set_busy_progress()
        self.elapsed_timer.start()
        self._append_log(f"开始执行：{' '.join(args)}")
        self._update_run_buttons(running=True)
        self._refresh_status_badges()

        self.worker = CommandWorker(args=args)
        self.worker.log.connect(self._append_log)
        self.worker.progress.connect(self._apply_progress_update)
        self.worker.finished_status.connect(self._on_worker_finished)
        self.worker.start()

    def _on_worker_finished(self, success: bool, message: str, cancelled: bool) -> None:
        self.elapsed_timer.stop()
        self._refresh_elapsed_time()
        self.status_label.setText("状态\n" + ("已完成" if success else ("已取消" if cancelled else "执行失败")))
        self.phase_label.setText("阶段\n" + ("任务完成" if success else ("任务已取消" if cancelled else "任务失败")))
        if self.current_total:
            final_progress = self.current_total if success else self.current_progress
            self.progress_detail_label.setText(f"进度\n{final_progress}/{self.current_total}")
        else:
            self.progress_detail_label.setText("进度\n" + ("已完成" if success else ("已取消" if cancelled else "已中断")))
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100 if success else 0)
        self.progress_bar.setFormat("完成" if success else ("已取消" if cancelled else "失败"))
        if message:
            self._append_log(message)
        elif success:
            self._append_log("任务执行完成。")
        self._update_run_buttons(running=False)
        self._refresh_status_badges()
        self.worker = None

    def _update_run_buttons(self, running: bool = False) -> None:
        enabled = not running
        for button in [
            self.scan_button,
            self.force_scan_button,
            self.report_button,
            self.stats_button,
            self.sync_button,
            self.run_summary_button,
        ]:
            button.setEnabled(enabled)
        self.cancel_button.setEnabled(running)

    def _start_update_check(self, *, manual: bool = False) -> None:
        if self.update_check_worker and self.update_check_worker.isRunning():
            if manual:
                QMessageBox.information(self, "正在检查更新", "当前已经在检查更新，请稍候。")
            return
        self._manual_update_check_pending = manual
        self.update_check_worker = UpdateCheckWorker(self)
        self.update_check_worker.checked.connect(self._on_update_check_finished)
        self.update_check_worker.start()

    def _check_for_updates_manually(self) -> None:
        self._start_update_check(manual=True)

    def _on_update_check_finished(self, update_info: object) -> None:
        manual = self._manual_update_check_pending
        self._manual_update_check_pending = False
        self.update_check_worker = None
        if not isinstance(update_info, UpdateCheckResult):
            if manual:
                QMessageBox.information(
                    self,
                    "检查更新",
                    "当前未发现可用更新，或暂时无法连接更新服务器。",
                )
            return
        if update_info.info is None:
            if manual:
                QMessageBox.information(
                    self,
                    "检查更新",
                    update_info.reason or "当前未发现可用更新。",
                )
            return
        if self.ignored_update_version == update_info.info.version:
            if manual:
                QMessageBox.information(
                    self,
                    "检查更新",
                    f"发现新版本 v{update_info.info.version}，但已在本次启动中忽略。你仍可点击顶部提示条继续更新。",
                )
            return
        self.available_update = update_info.info
        self.update_label.setText(f"发现新版本 v{update_info.info.version}，点击更新")
        self.update_banner.show()
        self._refresh_status_badges()
        if manual:
            QMessageBox.information(
                self,
                "检查更新",
                f"发现新版本 v{update_info.info.version}，可通过顶部提示条立即更新。",
            )

    def _ignore_current_update(self) -> None:
        if self.available_update is not None:
            self.ignored_update_version = self.available_update.version
        self.update_banner.hide()
        self._refresh_status_badges()

    def _handle_update_now(self) -> None:
        if self.available_update is None:
            return
        if sys.platform != "win32":
            QMessageBox.information(self, "当前平台不支持", "自动更新仅支持 Windows 打包版。")
            return
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "任务进行中", "请先等待当前任务完成，再执行更新。")
            return

        self.update_progress_dialog = QProgressDialog("正在下载更新...", "取消", 0, 100, self)
        self.update_progress_dialog.setWindowTitle("下载更新")
        self.update_progress_dialog.setAutoClose(False)
        self.update_progress_dialog.setAutoReset(False)
        self.update_progress_dialog.setValue(0)

        self.update_download_worker = UpdateDownloadWorker(self.available_update, self)
        self.update_download_worker.progress_changed.connect(self._on_update_download_progress)
        self.update_download_worker.finished_update.connect(self._on_update_download_finished)
        self.update_progress_dialog.canceled.connect(self._on_update_download_cancel_requested)
        self.update_download_worker.start()
        self.update_progress_dialog.show()

    def _on_update_download_progress(self, current: int, total: int) -> None:
        if self.update_progress_dialog is None:
            return
        if total > 0:
            self.update_progress_dialog.setMaximum(total)
            self.update_progress_dialog.setValue(current)
        else:
            self.update_progress_dialog.setMaximum(0)

    def _on_update_download_cancel_requested(self) -> None:
        if self.update_download_worker and self.update_download_worker.isRunning():
            self.update_progress_dialog.setLabelText("正在取消下载...")
            self.update_download_worker.cancel()

    def _on_update_download_finished(self, zip_path: str, error: str, cancelled: bool) -> None:
        if self.update_progress_dialog is not None:
            self.update_progress_dialog.close()
            self.update_progress_dialog = None
        if cancelled:
            QMessageBox.information(self, "已取消", "更新下载已取消。")
            return
        if error:
            QMessageBox.warning(self, "更新失败", f"下载更新失败：{error}")
            return
        if not zip_path:
            return
        reply = QMessageBox.question(
            self,
            "更新已下载",
            "更新将在重启后生效，是否立即重启？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return
        apply_update(Path(zip_path), get_app_dir())
        QApplication.quit()

    def _cancel_running_task(self) -> None:
        if not self.worker or not self.worker.isRunning():
            return
        self.worker.cancel()
        self._append_log("已请求取消当前任务，正在等待当前步骤安全结束...")
        self.phase_label.setText("阶段\n正在取消任务")
        self.cancel_button.setEnabled(False)
        self._refresh_status_badges()

    def _open_report(self) -> None:
        if not REPORT_PATH.exists():
            QMessageBox.information(self, "报告不存在", "还没有 report.html，请先执行扫描或生成报告。")
            return
        report_url = QUrl.fromLocalFile(str(REPORT_PATH.resolve()))
        if QDesktopServices.openUrl(report_url):
            return
        if webbrowser.open(report_url.toString()):
            return
        QMessageBox.warning(
            self,
            "打开失败",
            f"无法自动打开 HTML 报告，请手动打开：\n{REPORT_PATH.resolve()}",
        )

    def _append_log(self, message: str) -> None:
        self.log_output.appendPlainText(message)
        cursor = self.log_output.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_output.setTextCursor(cursor)

    def _set_busy_progress(self) -> None:
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFormat("处理中...")

    def _apply_progress_update(self, phase: str, current: int, total: int, detail: str) -> None:
        if phase == "scan":
            self.phase_label.setText("阶段\n" + (detail or "正在扫描目录..."))
            self._set_busy_progress()
            self._refresh_status_badges()
            return
        if phase == "classify":
            self.current_progress = current
            self.current_total = total
            value = int(current * 100 / total) if total else 0
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(value)
            self.progress_bar.setFormat(f"{current}/{total}")
            self.progress_detail_label.setText(f"进度\n{current}/{total}")
            self.phase_label.setText("阶段\n" + (detail or "正在调用模型进行分类..."))
            self._refresh_status_badges()
            return
        if phase == "summarize":
            self.current_progress = current
            self.current_total = total
            value = int(current * 100 / total) if total else 0
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(value)
            self.progress_bar.setFormat(f"{current}/{total}")
            self.progress_detail_label.setText(f"进度\n{current}/{total}")
            self.phase_label.setText("阶段\n" + (detail or "正在生成摘要..."))
            self._refresh_status_badges()
            return
        if phase == "report":
            self.phase_label.setText("阶段\n" + (detail or "正在生成报告..."))
            self._set_busy_progress()
            self._refresh_status_badges()
            return
        if phase == "stats":
            self.phase_label.setText("阶段\n" + (detail or "正在读取缓存统计..."))
            self._set_busy_progress()
            self._refresh_status_badges()
            return
        if phase == "done":
            self.phase_label.setText("阶段\n" + (detail or "任务完成"))
            self._refresh_status_badges()

    def _refresh_status_badges(self) -> None:
        status_text = self.status_label.text().split("\n", 1)[-1] if "\n" in self.status_label.text() else self.status_label.text()
        phase_text = self.phase_label.text().split("\n", 1)[-1] if "\n" in self.phase_label.text() else self.phase_label.text()
        self.hero_status_value.setText(status_text)
        self.hero_status_caption.setText("有新版本可用" if self.update_banner.isVisible() else "当前未挂起更新")
        self.hero_phase_value.setText("自动巡检开启" if self.auto_scan_checkbox.isChecked() else "手动模式")
        self.hero_phase_caption.setText(phase_text)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_responsive_layouts()

    def _apply_responsive_layouts(self) -> None:
        width = self.width()
        self.hero_layout.setDirection(QBoxLayout.TopToBottom if width < 980 else QBoxLayout.LeftToRight)
        self.top_area_layout.setDirection(QBoxLayout.TopToBottom if width < 1080 else QBoxLayout.LeftToRight)

    def _refresh_elapsed_time(self) -> None:
        if self.started_at is None:
            self.elapsed_label.setText("耗时\n00:00")
            return
        seconds = max(0, int(time.monotonic() - self.started_at))
        minutes, remaining = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            self.elapsed_label.setText(f"耗时\n{hours:02d}:{minutes:02d}:{remaining:02d}")
            return
        self.elapsed_label.setText(f"耗时\n{minutes:02d}:{remaining:02d}")

    def _sync_auto_scan_timer(self) -> None:
        if not self.auto_scan_checkbox.isChecked():
            self.auto_scan_timer.stop()
            self._refresh_status_badges()
            return
        interval_ms = self.auto_scan_interval_input.value() * 60 * 1000
        self.auto_scan_timer.start(interval_ms)
        self._refresh_status_badges()

    def _trigger_auto_sync(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        self._append_log(
            f"自动巡检触发：每 {self.auto_scan_interval_input.value()} 分钟执行一次增量扫描、摘要与报告刷新。"
        )
        self._run_command(["sync"])


def run_gui() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run_gui())
