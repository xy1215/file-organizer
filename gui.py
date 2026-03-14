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
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
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
    QProgressDialog,
    QPlainTextEdit,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app_paths import app_path, get_app_dir, resource_path
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

MODEL_PRESETS = {
    "deepseek": {
        "label": "DeepSeek（推荐）",
        "provider": "openai",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "summary_model": "deepseek-chat",
    },
    "zhipu": {
        "label": "智谱 AI (GLM)",
        "provider": "openai",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
        "summary_model": "glm-4-flash",
    },
    "moonshot": {
        "label": "月之暗面 (Kimi)",
        "provider": "openai",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
        "summary_model": "moonshot-v1-8k",
    },
    "qwen": {
        "label": "通义千问 (Qwen)",
        "provider": "openai",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "summary_model": "qwen-plus",
    },
    "siliconflow": {
        "label": "硅基流动 (SiliconFlow)",
        "provider": "openai",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "Qwen/Qwen2.5-7B-Instruct",
        "summary_model": "Qwen/Qwen2.5-7B-Instruct",
    },
}
CUSTOM_PRESET_KEY = "custom"
USER_GUIDE_HTML = """
<h2>文件整理助手使用说明</h2>
<p>这个工具的作用，是帮你扫描电脑里的文件，自动做分类和简要说明，并生成一份可以在浏览器里查看的整理报告。</p>

<h3>一、第一次使用</h3>
<ol>
  <li>在左侧的 <b>LLM 模型设置</b> 里，先选择一个服务商。</li>
  <li>在 <b>API Key</b> 输入框里填入你申请到的密钥。</li>
  <li>如果你不熟悉模型参数，直接使用系统自动填入的推荐配置即可。</li>
  <li>确认扫描范围后，点击底部的 <b>保存配置</b>。</li>
</ol>

<h3>二、顶部几个主要按钮怎么用</h3>
<ul>
  <li><b>开始整理</b>：执行完整流程，包括扫描、分类，并刷新整理结果。适合日常直接使用。</li>
  <li><b>快速整理</b>：只做扫描和分类，适合快速更新结果。</li>
  <li><b>打开报告</b>：打开已经生成好的 HTML 报告，在浏览器中查看分类结果。</li>
  <li><b>取消</b>：任务运行中才会出现。点击后会尽量在当前步骤结束后安全停止。</li>
  <li><b>自动整理</b>：打开后，程序会按照右侧设置的时间间隔自动执行一次整理。</li>
</ul>

<h3>三、左侧配置区说明</h3>
<ul>
  <li><b>快速选择服务商</b>：可直接套用推荐的接口地址和模型配置。</li>
  <li><b>服务商</b>：一般保持为自动填入的内容即可，进阶用户可以手动修改。</li>
  <li><b>分类模型 / 摘要模型</b>：分别用于文件分类和内容摘要。默认推荐值通常已经够用。</li>
  <li><b>Base URL</b>：接口地址。只有在使用自定义服务或代理时才需要自己调整。</li>
  <li><b>扫描范围</b>：可以勾选 Desktop、Documents、Downloads，也可以手动添加额外目录。</li>
  <li><b>排除目录名</b>：填写后，这些目录会在扫描时自动跳过。</li>
  <li><b>性能参数</b>：影响处理速度。一般不建议频繁修改，保持默认值更稳妥。</li>
  <li><b>摘要生成</b>：可以只给某个文件生成摘要，也可以按分类或全部生成。</li>
</ul>

<h3>四、菜单栏说明</h3>
<ul>
  <li><b>帮助 → 检查更新</b>：手动检查是否有新版本。</li>
  <li><b>工具 → 重新检查所有文件</b>：忽略已有缓存，从头重新扫描。</li>
  <li><b>工具 → 重新生成报告</b>：重新生成 HTML 报告。</li>
  <li><b>工具 → 查看处理情况</b>：查看当前缓存和处理情况。</li>
</ul>

<h3>五、右侧运行日志怎么看</h3>
<p>右侧会显示程序的执行过程。正常情况下，你会看到“开始执行”“正在分类”“正在生成报告”“任务执行完成”等提示。出现问题时，也可以把这里的报错信息发给我排查。</p>

<h3>六、如果不知道怎么选</h3>
<p>如果你只是想尽快用起来，可以按这个顺序操作：</p>
<ol>
  <li>选择一个服务商预设</li>
  <li>填写 API Key</li>
  <li>点击 <b>保存配置</b></li>
  <li>点击 <b>开始整理</b></li>
  <li>完成后点击 <b>打开报告</b></li>
</ol>

<p>如果任务执行失败，先不要着急，通常是 API Key、模型名或接口地址配置不对。先检查左侧配置是否正确，再重新运行即可。</p>
"""


def _load_theme() -> str:
    theme_path = resource_path("theme.qss")
    if theme_path.exists():
        return theme_path.read_text(encoding="utf-8")
    return ""


# ---------------------------------------------------------------------------
#  Workers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
#  Config helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
#  Collapsible section helper
# ---------------------------------------------------------------------------

class CollapsibleSection(QWidget):
    """A section with a clickable header that toggles content visibility."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._toggle_button = QPushButton(f"▸ {title}")
        self._toggle_button.setObjectName("sectionToggle")
        self._toggle_button.setCursor(Qt.PointingHandCursor)
        self._toggle_button.clicked.connect(self._on_toggle)
        self._title = title

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 8, 0, 4)
        self._content_layout.setSpacing(8)
        self._content.setVisible(False)

        layout.addWidget(self._toggle_button)
        layout.addWidget(self._content)

    def content_layout(self) -> QVBoxLayout:
        return self._content_layout

    def set_expanded(self, expanded: bool) -> None:
        self._content.setVisible(expanded)
        arrow = "▾" if expanded else "▸"
        self._toggle_button.setText(f"{arrow} {self._title}")

    def _on_toggle(self) -> None:
        self.set_expanded(not self._content.isVisible())


# ---------------------------------------------------------------------------
#  Main window
# ---------------------------------------------------------------------------

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
        self.resize(960, 700)
        self.setMinimumSize(720, 520)
        self.setStyleSheet(_load_theme())
        self._setup_menu_bar()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        central = QWidget()
        central.setObjectName("centralSurface")
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 16, 20, 20)
        root.setSpacing(12)

        # --- Title bar ---
        root.addWidget(self._build_title_bar())
        # --- Update banner (hidden by default) ---
        root.addWidget(self._build_update_banner())
        # --- Action toolbar ---
        root.addWidget(self._build_action_toolbar())
        # --- Status strip ---
        root.addWidget(self._build_status_strip())
        # --- Main area: config left, log right ---
        root.addLayout(self._build_main_area(), stretch=1)

        scroll.setWidget(central)
        self.setCentralWidget(scroll)
        self._load_into_form(load_config())
        self.current_command: list[str] = []
        self._update_run_buttons()
        self._start_update_check()

    # ── Menu bar ──────────────────────────────────────────────────────

    def _setup_menu_bar(self) -> None:
        help_menu = self.menuBar().addMenu("帮助")

        version_action = QAction(f"当前版本 v{__version__}", self)
        version_action.setEnabled(False)
        help_menu.addAction(version_action)

        guide_action = QAction("使用说明", self)
        guide_action.triggered.connect(self._show_user_guide)
        help_menu.addAction(guide_action)

        check_update_action = QAction("检查更新", self)
        check_update_action.triggered.connect(self._check_for_updates_manually)
        help_menu.addAction(check_update_action)

        tools_menu = self.menuBar().addMenu("工具")

        force_scan_action = QAction("重新检查所有文件", self)
        force_scan_action.triggered.connect(lambda: self._run_command(["scan", "--force"]))
        tools_menu.addAction(force_scan_action)

        refresh_report_action = QAction("重新生成报告", self)
        refresh_report_action.triggered.connect(lambda: self._run_command(["report"]))
        tools_menu.addAction(refresh_report_action)

        stats_action = QAction("查看处理情况", self)
        stats_action.triggered.connect(lambda: self._run_command(["stats"]))
        tools_menu.addAction(stats_action)

    # ── Title bar (replaces hero) ─────────────────────────────────────

    def _build_title_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("toolbarFrame")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(12)

        title = QLabel("文件整理助手")
        title.setStyleSheet("font-size: 20px; font-weight: 800; color: #1c1917;")

        version_badge = QLabel(f"v{__version__}")
        version_badge.setStyleSheet(
            "background: #fef3c7; color: #92400e; font-size: 11px; font-weight: 700;"
            " padding: 3px 8px; border-radius: 6px;"
        )

        layout.addWidget(title)
        layout.addWidget(version_badge)
        layout.addStretch(1)

        return frame

    # ── Update banner ─────────────────────────────────────────────────

    def _build_update_banner(self) -> QFrame:
        self.update_banner = QFrame()
        self.update_banner.setObjectName("updateBanner")
        layout = QHBoxLayout(self.update_banner)
        layout.setContentsMargins(16, 10, 16, 10)
        self.update_label = QLabel("发现新版本")
        self.update_label.setStyleSheet("font-weight: 700; color: #1d4ed8;")
        self.update_now_button = QPushButton("立即更新")
        self.update_now_button.setProperty("role", "accent")
        self.update_now_button.clicked.connect(self._handle_update_now)
        self.update_ignore_button = QPushButton("忽略")
        self.update_ignore_button.clicked.connect(self._ignore_current_update)
        layout.addWidget(self.update_label, stretch=1)
        layout.addWidget(self.update_now_button)
        layout.addWidget(self.update_ignore_button)
        self.update_banner.hide()
        return self.update_banner

    # ── Action toolbar ────────────────────────────────────────────────

    def _build_action_toolbar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("toolbarFrame")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(10)

        self.sync_button = QPushButton("开始整理")
        self.sync_button.setProperty("role", "primary")
        self.sync_button.setMinimumWidth(120)
        self.sync_button.clicked.connect(lambda: self._run_command(["sync"]))

        self.scan_button = QPushButton("快速整理")
        self.scan_button.clicked.connect(lambda: self._run_command(["scan"]))

        self.open_report_button = QPushButton("打开报告")
        self.open_report_button.setProperty("role", "accent")
        self.open_report_button.clicked.connect(self._open_report)

        self.cancel_button = QPushButton("取消")
        self.cancel_button.setProperty("role", "danger")
        self.cancel_button.clicked.connect(self._cancel_running_task)
        self.cancel_button.setEnabled(False)
        self.cancel_button.setVisible(False)

        self.auto_scan_checkbox = QCheckBox("自动整理")
        self.auto_scan_checkbox.toggled.connect(lambda _: self._sync_auto_scan_timer())
        self.auto_scan_interval_input = QSpinBox()
        self.auto_scan_interval_input.setRange(15, 1440)
        self.auto_scan_interval_input.setSuffix(" 分钟")
        self.auto_scan_interval_input.setFixedWidth(100)
        self.auto_scan_interval_input.valueChanged.connect(lambda _: self._sync_auto_scan_timer())

        layout.addWidget(self.sync_button)
        layout.addWidget(self.scan_button)
        layout.addWidget(self.open_report_button)
        layout.addWidget(self.cancel_button)
        layout.addStretch(1)
        layout.addWidget(self.auto_scan_checkbox)
        layout.addWidget(self.auto_scan_interval_input)

        return frame

    # ── Status strip ──────────────────────────────────────────────────

    def _build_status_strip(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("statusStrip")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(16)

        self._status_value = QLabel("空闲")
        self._status_value.setObjectName("statusStripValue")
        self._phase_value = QLabel("等待开始")
        self._phase_value.setObjectName("statusStripLabel")
        self._elapsed_value = QLabel("00:00")
        self._elapsed_value.setObjectName("statusStripLabel")
        self._progress_value = QLabel("—")
        self._progress_value.setObjectName("statusStripLabel")

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("")
        self.progress_bar.setFixedWidth(160)
        self.progress_bar.setFixedHeight(14)

        layout.addWidget(self._status_value)
        layout.addWidget(self._make_separator())
        layout.addWidget(self._phase_value)
        layout.addWidget(self._make_separator())
        layout.addWidget(self._elapsed_value)
        layout.addWidget(self._make_separator())
        layout.addWidget(self._progress_value)
        layout.addStretch(1)
        layout.addWidget(self.progress_bar)

        return frame

    @staticmethod
    def _make_separator() -> QLabel:
        sep = QLabel("·")
        sep.setStyleSheet("color: #d6d3d1; font-size: 16px;")
        return sep

    # ── Main area ─────────────────────────────────────────────────────

    def _build_main_area(self) -> QHBoxLayout:
        layout = QBoxLayout(QBoxLayout.LeftToRight)
        self._main_area_layout = layout
        layout.setSpacing(12)
        layout.addWidget(self._build_config_panel(), stretch=2)
        layout.addWidget(self._build_log_panel(), stretch=3)
        return layout

    # ── Config panel (with collapsible sections) ──────────────────────

    def _build_config_panel(self) -> QGroupBox:
        box = QGroupBox("配置")
        outer = QVBoxLayout(box)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(4)

        # -- LLM section (expanded by default) --
        llm_section = CollapsibleSection("LLM 模型设置")
        llm_form = QFormLayout()
        llm_form.setSpacing(8)
        llm_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.provider_preset_combo = QComboBox()
        self.provider_preset_combo.addItem("自定义", CUSTOM_PRESET_KEY)
        for preset_key, preset in MODEL_PRESETS.items():
            self.provider_preset_combo.addItem(str(preset["label"]), preset_key)
        self.provider_preset_combo.currentIndexChanged.connect(self._apply_selected_model_preset)
        preset_hint = QLabel("选择服务商后会自动填入推荐配置，API Key 需要自行申请填写")
        preset_hint.setObjectName("mutedLabel")

        self.provider_input = QLineEdit()
        self.provider_input.setPlaceholderText("openai / anthropic")
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.api_key_input.setPlaceholderText("优先读取环境变量")
        self.model_input = QLineEdit()
        self.summary_model_input = QLineEdit()
        self.base_url_input = QLineEdit()
        self.base_url_input.setPlaceholderText("留空使用官方地址")

        llm_form.addRow("快速选择服务商", self.provider_preset_combo)
        llm_form.addRow("", preset_hint)
        llm_form.addRow("服务商", self.provider_input)
        llm_form.addRow("API Key", self.api_key_input)
        llm_form.addRow("分类模型", self.model_input)
        llm_form.addRow("摘要模型", self.summary_model_input)
        llm_form.addRow("Base URL", self.base_url_input)
        llm_section.content_layout().addLayout(llm_form)
        llm_section.set_expanded(True)

        # -- Scan paths section --
        scan_section = CollapsibleSection("扫描范围")
        self.scan_desktop_checkbox = QCheckBox("Desktop")
        self.scan_documents_checkbox = QCheckBox("Documents")
        self.scan_downloads_checkbox = QCheckBox("Downloads")
        self.scan_desktop_checkbox.setChecked(True)
        self.scan_documents_checkbox.setChecked(True)
        self.scan_downloads_checkbox.setChecked(True)
        defaults_row = QHBoxLayout()
        defaults_row.setSpacing(16)
        defaults_row.addWidget(self.scan_desktop_checkbox)
        defaults_row.addWidget(self.scan_documents_checkbox)
        defaults_row.addWidget(self.scan_downloads_checkbox)
        defaults_row.addStretch(1)
        scan_section.content_layout().addLayout(defaults_row)

        extra_label = QLabel("额外扫描目录")
        extra_label.setObjectName("mutedLabel")
        scan_section.content_layout().addWidget(extra_label)
        self.path_list = QListWidget()
        self.path_list.setMaximumHeight(100)
        path_buttons = QHBoxLayout()
        add_path_button = QPushButton("添加目录")
        add_path_button.clicked.connect(self._add_scan_path)
        remove_path_button = QPushButton("移除选中")
        remove_path_button.clicked.connect(self._remove_selected_path)
        path_buttons.addWidget(add_path_button)
        path_buttons.addWidget(remove_path_button)
        path_buttons.addStretch(1)
        scan_section.content_layout().addWidget(self.path_list)
        scan_section.content_layout().addLayout(path_buttons)

        exclude_label = QLabel("排除目录名")
        exclude_label.setObjectName("mutedLabel")
        scan_section.content_layout().addWidget(exclude_label)
        self.exclude_input = QPlainTextEdit()
        self.exclude_input.setPlaceholderText("每行一个，例如 node_modules")
        self.exclude_input.setMaximumHeight(80)
        scan_section.content_layout().addWidget(self.exclude_input)
        scan_section.set_expanded(True)

        # -- Performance section (collapsed by default) --
        perf_section = CollapsibleSection("性能参数")
        perf_form = QFormLayout()
        perf_form.setSpacing(8)
        self.batch_size_input = QSpinBox()
        self.batch_size_input.setRange(10, 100)
        self.classification_workers_input = QSpinBox()
        self.classification_workers_input.setRange(1, 4)
        self.summary_workers_input = QSpinBox()
        self.summary_workers_input.setRange(1, 8)
        perf_form.addRow("批次大小", self.batch_size_input)
        perf_form.addRow("分类并发", self.classification_workers_input)
        perf_form.addRow("摘要并发", self.summary_workers_input)
        perf_section.content_layout().addLayout(perf_form)

        # -- Summarize section (collapsed by default) --
        summary_section = CollapsibleSection("摘要生成")
        self.summary_file_radio = QRadioButton("按单个文件")
        self.summary_category_radio = QRadioButton("按分类")
        self.summary_all_radio = QRadioButton("全部已分类文件")
        self.summary_file_radio.setChecked(True)

        self.summary_file_input = QLineEdit()
        self.summary_file_input.setPlaceholderText("选择一个文件")
        choose_file_button = QPushButton("选择")
        choose_file_button.clicked.connect(self._choose_summary_file)
        file_row = QHBoxLayout()
        file_row.addWidget(self.summary_file_input, stretch=1)
        file_row.addWidget(choose_file_button)

        self.summary_category_input = QLineEdit()
        self.summary_category_input.setPlaceholderText("分类名称，例如 财务/税务")

        self.run_summary_button = QPushButton("生成摘要")
        self.run_summary_button.setProperty("role", "primary")
        self.run_summary_button.clicked.connect(self._run_summary_command)

        summary_section.content_layout().addWidget(self.summary_file_radio)
        summary_section.content_layout().addLayout(file_row)
        summary_section.content_layout().addWidget(self.summary_category_radio)
        summary_section.content_layout().addWidget(self.summary_category_input)
        summary_section.content_layout().addWidget(self.summary_all_radio)
        summary_section.content_layout().addWidget(self.run_summary_button)

        # -- Save button --
        save_button = QPushButton("保存配置")
        save_button.setProperty("role", "primary")
        save_button.clicked.connect(self._save_form_config)

        outer.addWidget(llm_section)
        outer.addWidget(scan_section)
        outer.addWidget(perf_section)
        outer.addWidget(summary_section)
        outer.addStretch(1)
        outer.addWidget(save_button)

        return box

    # ── Log panel ─────────────────────────────────────────────────────

    def _build_log_panel(self) -> QGroupBox:
        box = QGroupBox("运行日志")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        self.log_output = QPlainTextEdit()
        self.log_output.setObjectName("logOutput")
        self.log_output.setReadOnly(True)
        self.log_output.setPlaceholderText("运行输出会显示在这里。")

        clear_button = QPushButton("清空日志")
        clear_button.clicked.connect(self.log_output.clear)

        layout.addWidget(self.log_output, stretch=1)
        layout.addWidget(clear_button, alignment=Qt.AlignRight)
        return box

    # ── Config load / save ────────────────────────────────────────────

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
        self._select_preset_for_base_url(str(llm.get("base_url", "")))
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

    def _apply_selected_model_preset(self) -> None:
        preset_key = str(self.provider_preset_combo.currentData() or CUSTOM_PRESET_KEY)
        if preset_key == CUSTOM_PRESET_KEY:
            return
        preset = MODEL_PRESETS.get(preset_key)
        if not preset:
            return
        self.provider_input.setText(str(preset["provider"]))
        self.base_url_input.setText(str(preset["base_url"]))
        self.model_input.setText(str(preset["model"]))
        self.summary_model_input.setText(str(preset["summary_model"]))

    def _select_preset_for_base_url(self, base_url: str) -> None:
        normalized = base_url.strip().rstrip("/")
        preset_key = CUSTOM_PRESET_KEY
        for candidate_key, preset in MODEL_PRESETS.items():
            preset_base_url = str(preset["base_url"]).strip().rstrip("/")
            if normalized and normalized == preset_base_url:
                preset_key = candidate_key
                break
        index = self.provider_preset_combo.findData(preset_key)
        if index < 0:
            index = 0
        self.provider_preset_combo.blockSignals(True)
        self.provider_preset_combo.setCurrentIndex(index)
        self.provider_preset_combo.blockSignals(False)

    def _save_form_config(self) -> None:
        config = self._build_config_from_form()
        save_config(config)
        self._sync_auto_scan_timer()
        self._append_log("配置已保存到 config.yaml")
        QMessageBox.information(self, "保存成功", "配置已保存。")

    def _ensure_saved_config_for_run(self, config: dict[str, Any]) -> bool:
        saved_config = load_config()
        if config == saved_config:
            return True
        reply = QMessageBox.question(
            self,
            "配置尚未保存",
            "当前表单配置与已保存配置不一致。执行任务前需要先保存配置，是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return False
        save_config(config)
        self._append_log("运行前已保存当前配置。")
        return True

    # ── Path / file pickers ───────────────────────────────────────────

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

    # ── Run commands ──────────────────────────────────────────────────

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
        if not self._ensure_saved_config_for_run(config):
            return
        self._sync_auto_scan_timer()
        self.current_command = list(args)
        self.current_total = 0
        self.current_progress = 0
        self.started_at = time.monotonic()
        # Insert separator instead of clearing log
        if self.log_output.toPlainText().strip():
            timestamp = time.strftime("%H:%M:%S")
            self._append_log(f"\n{'─' * 40}")
            self._append_log(f"  {' '.join(args)} @ {timestamp}")
            self._append_log(f"{'─' * 40}")
        self._set_status("运行中", f"{' '.join(args)}", "00:00", "准备中")
        self._set_busy_progress()
        self.elapsed_timer.start()
        self._append_log(f"开始执行：{' '.join(args)}")
        self._update_run_buttons(running=True)

        self.worker = CommandWorker(args=args)
        self.worker.log.connect(self._append_log)
        self.worker.progress.connect(self._apply_progress_update)
        self.worker.finished_status.connect(self._on_worker_finished)
        self.worker.start()

    def _on_worker_finished(self, success: bool, message: str, cancelled: bool) -> None:
        self.elapsed_timer.stop()
        self._refresh_elapsed_time()
        self.worker = None
        status = "已完成" if success else ("已取消" if cancelled else "执行失败")
        phase = "任务完成" if success else ("任务已取消" if cancelled else "任务失败")
        self._status_value.setText(status)
        self._phase_value.setText(phase)
        if self.current_total:
            final = self.current_total if success else self.current_progress
            self._progress_value.setText(f"{final}/{self.current_total}")
        else:
            self._progress_value.setText("已完成" if success else ("已取消" if cancelled else "已中断"))
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100 if success else 0)
        self.progress_bar.setFormat("完成" if success else ("已取消" if cancelled else "失败"))
        if message:
            self._append_log(message)
        elif success:
            self._append_log("任务执行完成。")
        self._update_run_buttons(running=False)

    def _update_run_buttons(self, running: bool = False) -> None:
        enabled = not running
        self.sync_button.setEnabled(enabled)
        self.scan_button.setEnabled(enabled)
        self.run_summary_button.setEnabled(enabled)
        self.cancel_button.setEnabled(running)
        self.cancel_button.setVisible(running)

    def _set_status(self, status: str, phase: str, elapsed: str, progress: str) -> None:
        self._status_value.setText(status)
        self._phase_value.setText(phase)
        self._elapsed_value.setText(elapsed)
        self._progress_value.setText(progress)

    def _show_user_guide(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("使用说明")
        dialog.resize(720, 620)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        browser = QTextBrowser(dialog)
        browser.setOpenExternalLinks(True)
        browser.setHtml(USER_GUIDE_HTML)

        close_button = QPushButton("关闭")
        close_button.clicked.connect(dialog.accept)

        layout.addWidget(browser, stretch=1)
        layout.addWidget(close_button, alignment=Qt.AlignRight)
        dialog.exec()

    # ── Update logic ──────────────────────────────────────────────────

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
                QMessageBox.information(self, "检查更新", "当前未发现可用更新，或暂时无法连接更新服务器。")
            return
        if update_info.info is None:
            if manual:
                QMessageBox.information(self, "检查更新", update_info.reason or "当前未发现可用更新。")
            return
        if self.ignored_update_version == update_info.info.version:
            if manual:
                self.ignored_update_version = None
                self.available_update = update_info.info
                self.update_label.setText(f"发现新版本 v{update_info.info.version}，点击更新")
                self.update_banner.show()
                QMessageBox.information(
                    self, "检查更新", f"已重新显示新版本 v{update_info.info.version} 的更新提示。"
                )
            return
        self.available_update = update_info.info
        self.update_label.setText(f"发现新版本 v{update_info.info.version}，点击更新")
        self.update_banner.show()
        if manual:
            QMessageBox.information(
                self, "检查更新", f"发现新版本 v{update_info.info.version}，可通过顶部提示条立即更新。"
            )

    def _ignore_current_update(self) -> None:
        if self.available_update is not None:
            self.ignored_update_version = self.available_update.version
        self.update_banner.hide()

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
        if self.update_progress_dialog is None:
            return
        if self.update_download_worker and self.update_download_worker.isRunning():
            self.update_progress_dialog.setLabelText("正在取消下载...")
            self.update_download_worker.cancel()

    def _on_update_download_finished(self, zip_path: str, error: str, cancelled: bool) -> None:
        if self.update_progress_dialog is not None:
            self.update_progress_dialog.close()
            self.update_progress_dialog = None
        self.update_download_worker = None
        if cancelled:
            QMessageBox.information(self, "已取消", "更新下载已取消。")
            return
        if error:
            QMessageBox.warning(self, "更新失败", f"下载更新失败：{error}")
            return
        if not zip_path:
            return
        reply = QMessageBox.question(
            self, "更新已下载", "更新将在重启后生效，是否立即重启？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return
        apply_update(Path(zip_path), get_app_dir())
        QApplication.quit()

    # ── Task control ──────────────────────────────────────────────────

    def _cancel_running_task(self) -> None:
        if not self.worker or not self.worker.isRunning():
            return
        self.worker.cancel()
        self._append_log("已请求取消当前任务，正在等待当前步骤安全结束...")
        self._phase_value.setText("正在取消...")
        self.cancel_button.setEnabled(False)

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
            self, "打开失败", f"无法自动打开 HTML 报告，请手动打开：\n{REPORT_PATH.resolve()}"
        )

    # ── Log / progress helpers ────────────────────────────────────────

    def _append_log(self, message: str) -> None:
        self.log_output.appendPlainText(message)
        cursor = self.log_output.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_output.setTextCursor(cursor)

    def _set_busy_progress(self) -> None:
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFormat("")

    def _apply_progress_update(self, phase: str, current: int, total: int, detail: str) -> None:
        if phase == "scan":
            self._phase_value.setText(detail or "正在扫描目录...")
            self._set_busy_progress()
            return
        if phase == "classify":
            self.current_progress = current
            self.current_total = total
            pct = int(current * 100 / total) if total else 0
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(pct)
            self.progress_bar.setFormat(f"{current}/{total}")
            self._progress_value.setText(f"{current}/{total}")
            self._phase_value.setText(detail or "正在分类...")
            return
        if phase == "summarize":
            self.current_progress = current
            self.current_total = total
            pct = int(current * 100 / total) if total else 0
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(pct)
            self.progress_bar.setFormat(f"{current}/{total}")
            self._progress_value.setText(f"{current}/{total}")
            self._phase_value.setText(detail or "正在生成摘要...")
            return
        if phase == "report":
            self._phase_value.setText(detail or "正在生成报告...")
            self._set_busy_progress()
            return
        if phase == "stats":
            self._phase_value.setText(detail or "正在读取统计...")
            self._set_busy_progress()
            return
        if phase == "done":
            self._phase_value.setText(detail or "任务完成")

    def _refresh_elapsed_time(self) -> None:
        if self.started_at is None:
            self._elapsed_value.setText("00:00")
            return
        seconds = max(0, int(time.monotonic() - self.started_at))
        minutes, remaining = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            self._elapsed_value.setText(f"{hours:02d}:{minutes:02d}:{remaining:02d}")
        else:
            self._elapsed_value.setText(f"{minutes:02d}:{remaining:02d}")

    def _sync_auto_scan_timer(self) -> None:
        if not self.auto_scan_checkbox.isChecked():
            self.auto_scan_timer.stop()
            return
        interval_ms = self.auto_scan_interval_input.value() * 60 * 1000
        self.auto_scan_timer.start(interval_ms)

    def _trigger_auto_sync(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        self._append_log(
            f"自动整理已触发：每 {self.auto_scan_interval_input.value()} 分钟执行一次检查和结果更新。"
        )
        self._run_command(["sync"])

    # ── Responsive ────────────────────────────────────────────────────

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        width = self.width()
        self._main_area_layout.setDirection(
            QBoxLayout.TopToBottom if width < 900 else QBoxLayout.LeftToRight
        )


def run_gui() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run_gui())
