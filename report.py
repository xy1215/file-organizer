from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from app_paths import app_path, resource_path
from jinja2 import Template


CATEGORY_COLORS = [
    {"surface": "#f6efe7", "border": "#d28d52", "accent": "#8b4b21", "pill": "#f0d6bc"},
    {"surface": "#edf4ec", "border": "#659f68", "accent": "#285c30", "pill": "#d6ead6"},
    {"surface": "#eef2fa", "border": "#6f88c9", "accent": "#314d87", "pill": "#d9e2f6"},
    {"surface": "#fbefef", "border": "#cf6f6f", "accent": "#8d3131", "pill": "#f4d6d6"},
    {"surface": "#f4eef8", "border": "#9372c9", "accent": "#5a3d8b", "pill": "#e5d8f5"},
    {"surface": "#eef7f6", "border": "#58a9a4", "accent": "#1f6d68", "pill": "#d2eeeb"},
    {"surface": "#fff4e8", "border": "#df9350", "accent": "#995314", "pill": "#f7dcc0"},
    {"surface": "#eff5f6", "border": "#6ea0a8", "accent": "#325d63", "pill": "#d9e9ec"},
]


HTML_TEMPLATE = Template(resource_path("report_template.html").read_text(encoding="utf-8"), autoescape=True)


_EXT_MAP = {
    ".doc": ("ext-doc", "W"),
    ".docx": ("ext-doc", "W"),
    ".odt": ("ext-doc", "W"),
    ".rtf": ("ext-doc", "W"),
    ".xls": ("ext-xls", "X"),
    ".xlsx": ("ext-xls", "X"),
    ".csv": ("ext-xls", "X"),
    ".ods": ("ext-xls", "X"),
    ".ppt": ("ext-ppt", "P"),
    ".pptx": ("ext-ppt", "P"),
    ".odp": ("ext-ppt", "P"),
    ".pdf": ("ext-pdf", "PDF"),
    ".jpg": ("ext-img", "IMG"),
    ".jpeg": ("ext-img", "IMG"),
    ".png": ("ext-img", "IMG"),
    ".gif": ("ext-img", "IMG"),
    ".bmp": ("ext-img", "IMG"),
    ".svg": ("ext-img", "IMG"),
    ".webp": ("ext-img", "IMG"),
    ".ico": ("ext-img", "IMG"),
    ".tiff": ("ext-img", "IMG"),
    ".mp3": ("ext-media", "A"),
    ".wav": ("ext-media", "A"),
    ".flac": ("ext-media", "A"),
    ".aac": ("ext-media", "A"),
    ".ogg": ("ext-media", "A"),
    ".wma": ("ext-media", "A"),
    ".mp4": ("ext-media", "V"),
    ".avi": ("ext-media", "V"),
    ".mkv": ("ext-media", "V"),
    ".mov": ("ext-media", "V"),
    ".wmv": ("ext-media", "V"),
    ".flv": ("ext-media", "V"),
    ".py": ("ext-code", "<>"),
    ".js": ("ext-code", "<>"),
    ".ts": ("ext-code", "<>"),
    ".java": ("ext-code", "<>"),
    ".c": ("ext-code", "<>"),
    ".cpp": ("ext-code", "<>"),
    ".h": ("ext-code", "<>"),
    ".go": ("ext-code", "<>"),
    ".rs": ("ext-code", "<>"),
    ".rb": ("ext-code", "<>"),
    ".php": ("ext-code", "<>"),
    ".html": ("ext-code", "<>"),
    ".css": ("ext-code", "<>"),
    ".json": ("ext-code", "{}"),
    ".xml": ("ext-code", "<>"),
    ".yaml": ("ext-code", "<>"),
    ".yml": ("ext-code", "<>"),
    ".sh": ("ext-code", "$"),
    ".bat": ("ext-code", "$"),
    ".ps1": ("ext-code", "$"),
    ".sql": ("ext-code", "DB"),
    ".zip": ("ext-zip", "ZIP"),
    ".rar": ("ext-zip", "ZIP"),
    ".7z": ("ext-zip", "ZIP"),
    ".tar": ("ext-zip", "ZIP"),
    ".gz": ("ext-zip", "ZIP"),
    ".bz2": ("ext-zip", "ZIP"),
    ".iso": ("ext-zip", "ISO"),
    ".dmg": ("ext-zip", "DMG"),
    ".exe": ("ext-zip", "EXE"),
    ".msi": ("ext-zip", "MSI"),
    ".deb": ("ext-zip", "PKG"),
    ".txt": ("ext-other", "TXT"),
    ".md": ("ext-other", "MD"),
    ".log": ("ext-other", "LOG"),
}


def _ext_info(filename: str) -> tuple[str, str]:
    ext = Path(filename).suffix.lower()
    return _EXT_MAP.get(ext, ("ext-other", ext[1:].upper()[:3] if ext else "?"))


def human_size(size: int) -> str:
    value = float(size)
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def file_uri(file_path: str) -> str:
    normalized = file_path.replace("\\", "/")
    if normalized.startswith("/"):
        return f"file://{quote(normalized, safe='/')}"
    return f"file:///{quote(normalized, safe=':/')}"


def display_brief(record: dict) -> str:
    summary = str(record.get("summary") or "").strip()
    if summary:
        first_line = summary.splitlines()[0].strip()
        if first_line:
            return first_line
    brief = str(record.get("brief") or "").strip()
    return brief or "暂时没有简短描述"


def _clean_category_name(value: object) -> str:
    name = str(value or "").strip()
    return name or "未分类"


def _format_modified_time(value: object) -> str:
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return "未知时间"
    if timestamp > 1e18:  # nanoseconds
        timestamp /= 1e9
    elif timestamp > 1e15:  # microseconds
        timestamp /= 1e6
    elif timestamp > 1e12:  # milliseconds
        timestamp /= 1e3
    try:
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return "未知时间"


def _safe_file_size(value: object) -> int:
    try:
        size = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(size, 0)


def prepare_records(records: list[dict]) -> list[dict]:
    prepared: list[dict] = []
    for record in records:
        file_path = str(record.get("file_path") or "")
        if not file_path:
            continue
        path = Path(file_path)
        ext_class, ext_label = _ext_info(path.name)
        prepared.append(
            {
                **record,
                "file_name": path.name,
                "file_size_human": human_size(_safe_file_size(record.get("file_size"))),
                "modified_at": _format_modified_time(record.get("modified_time")),
                "file_uri": file_uri(file_path),
                "ext_class": ext_class,
                "ext_label": ext_label,
                "display_brief": display_brief(record),
            }
        )
    return prepared


def _top_extensions(files: list[dict], n: int = 3) -> str:
    counts: dict[str, int] = defaultdict(int)
    for file in files:
        ext = Path(file["file_name"]).suffix.lower()
        counts[ext or "无后缀"] += 1
    top = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:n]
    return " · ".join(f"{ext} {count}" for ext, count in top)


def _category_search_text(category_name: str, files: list[dict]) -> str:
    parts = [category_name.lower()]
    for file in files:
        parts.extend(
            [
                str(file.get("file_name") or "").lower(),
                str(file.get("brief") or "").lower(),
                str(file.get("display_brief") or "").lower(),
            ]
        )
    return " ".join(parts)


def _safe_json_for_script(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def generate_reports(
    records: list[dict],
    html_path: str | None = None,
    json_path: str | None = None,
) -> None:
    html_output_path = Path(html_path) if html_path is not None else app_path("report.html")
    json_output_path = Path(json_path) if json_path is not None else app_path("report.json")
    prepared = prepare_records(records)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for record in prepared:
        grouped[_clean_category_name(record.get("category"))].append(record)

    grouped = dict(sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])))

    categories: list[dict] = []
    for index, (category_name, files) in enumerate(grouped.items()):
        color = CATEGORY_COLORS[index % len(CATEGORY_COLORS)]
        preview_files = files[:3]
        category_id = f"cat-{index}"
        categories.append(
            {
                "id": category_id,
                "name": category_name,
                "count": len(files),
                "preview_count": len(preview_files),
                "preview_files": preview_files,
                "files": files,
                "top_types": _top_extensions(files),
                "color": color,
                "search_text": _category_search_text(category_name, files),
            }
        )

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_files": len(prepared),
        "categories": {category["name"]: category["files"] for category in categories},
    }
    json_output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    report_data = {
        "categories": [
            {
                "id": category["id"],
                "name": category["name"],
                "count": category["count"],
                "top_types": category["top_types"],
                "files": [
                    {
                        "file_name": file["file_name"],
                        "file_size_human": file["file_size_human"],
                        "modified_at": file["modified_at"],
                        "file_path": file["file_path"],
                        "file_uri": file["file_uri"],
                        "ext_class": file["ext_class"],
                        "ext_label": file["ext_label"],
                        "display_brief": file["display_brief"],
                        "summary": file.get("summary") or "",
                    }
                    for file in category["files"]
                ],
            }
            for category in categories
        ]
    }

    html = HTML_TEMPLATE.render(
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        total_files=len(prepared),
        total_categories=len(categories),
        categorized_files=sum(1 for record in prepared if _clean_category_name(record.get("category")) != "未分类"),
        summarized_files=sum(1 for record in prepared if str(record.get("summary") or "").strip()),
        categories=categories,
        report_data_json=_safe_json_for_script(report_data),
    )
    html_output_path.write_text(html, encoding="utf-8")
