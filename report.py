from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from jinja2 import Template


HTML_TEMPLATE = Template(
    """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>文件整理报告</title>
  <style>
    :root {
      color-scheme: light dark;
      --bg: #f5f7fb;
      --card: rgba(255,255,255,0.9);
      --text: #152033;
      --muted: #5a6881;
      --accent: #227c9d;
      --border: rgba(34,124,157,0.16);
      --shadow: 0 18px 40px rgba(31, 41, 55, 0.08);
    }
    @media (prefers-color-scheme: dark) {
      :root {
        --bg: #0f172a;
        --card: rgba(15,23,42,0.82);
        --text: #e5eefb;
        --muted: #aab8cf;
        --accent: #7dd3fc;
        --border: rgba(125,211,252,0.16);
        --shadow: 0 18px 40px rgba(2, 6, 23, 0.35);
      }
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      background:
        radial-gradient(circle at top left, rgba(34,124,157,0.18), transparent 28%),
        radial-gradient(circle at top right, rgba(244,114,182,0.12), transparent 24%),
        var(--bg);
      color: var(--text);
    }
    .wrap {
      max-width: 1200px;
      margin: 0 auto;
      padding: 32px 20px 64px;
    }
    .hero {
      margin-bottom: 24px;
      padding: 24px;
      border: 1px solid var(--border);
      border-radius: 24px;
      background: linear-gradient(135deg, var(--card), rgba(255,255,255,0.5));
      box-shadow: var(--shadow);
      backdrop-filter: blur(12px);
    }
    h1 { margin: 0 0 12px; font-size: 30px; }
    .meta { color: var(--muted); margin-bottom: 16px; }
    input {
      width: 100%;
      padding: 14px 16px;
      border-radius: 14px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,0.66);
      color: var(--text);
      font-size: 15px;
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 12px;
      margin-top: 18px;
    }
    .stat {
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 16px;
      background: rgba(255,255,255,0.46);
    }
    .category {
      margin-top: 22px;
      padding: 18px;
      border-radius: 22px;
      border: 1px solid var(--border);
      background: var(--card);
      box-shadow: var(--shadow);
    }
    .category h2 { margin: 0 0 14px; font-size: 22px; }
    .count { color: var(--muted); font-size: 14px; }
    .file {
      padding: 16px;
      border-radius: 16px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,0.38);
      margin-bottom: 12px;
    }
    .file-name { font-size: 17px; font-weight: 600; }
    .file-meta, .summary { color: var(--muted); white-space: pre-wrap; line-height: 1.6; }
    .path-link {
      color: var(--accent);
      text-decoration: none;
      word-break: break-all;
    }
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <h1>文件整理报告</h1>
      <div class="meta">生成时间：{{ generated_at }}</div>
      <input id="searchBox" type="text" placeholder="输入文件名关键词进行筛选">
      <div class="stats">
        <div class="stat">总文件数<br><strong>{{ total_files }}</strong></div>
        <div class="stat">分类数<br><strong>{{ total_categories }}</strong></div>
      </div>
    </section>
    {% for category, files in grouped_files.items() %}
    <section class="category" data-category="{{ category }}">
      <h2>{{ category }} <span class="count">共 {{ files|length }} 个文件</span></h2>
      {% for file in files %}
      <article class="file" data-file-name="{{ file.file_name|lower }}">
        <div class="file-name">{{ file.file_name }}</div>
        <div class="file-meta">大小：{{ file.file_size_human }} ｜ 修改时间：{{ file.modified_at }}</div>
        <div class="file-meta">路径：<a class="path-link" href="{{ file.file_uri }}">{{ file.file_path }}</a></div>
        {% if file.summary %}
        <div class="summary">{{ file.summary }}</div>
        {% endif %}
      </article>
      {% endfor %}
    </section>
    {% endfor %}
  </div>
  <script>
    const searchBox = document.getElementById('searchBox');
    searchBox.addEventListener('input', () => {
      const keyword = searchBox.value.trim().toLowerCase();
      document.querySelectorAll('.file').forEach((item) => {
        const name = item.dataset.fileName || '';
        item.style.display = !keyword || name.includes(keyword) ? '' : 'none';
      });
    });
  </script>
</body>
</html>
"""
)


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
    return f"file:///{quote(normalized, safe=':/')}"


def prepare_records(records: list[dict]) -> list[dict]:
    prepared: list[dict] = []
    for record in records:
        path = Path(record["file_path"])
        prepared.append(
            {
                **record,
                "file_name": path.name,
                "file_size_human": human_size(int(record.get("file_size") or 0)),
                "modified_at": datetime.fromtimestamp(record["modified_time"]).strftime("%Y-%m-%d %H:%M:%S"),
                "file_uri": file_uri(record["file_path"]),
            }
        )
    return prepared


def generate_reports(records: list[dict], html_path: str = "report.html", json_path: str = "report.json") -> None:
    prepared = prepare_records(records)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for record in prepared:
        grouped[record.get("category") or "未分类"].append(record)

    grouped = dict(sorted(grouped.items(), key=lambda item: item[0]))
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_files": len(prepared),
        "categories": grouped,
    }
    Path(json_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    html = HTML_TEMPLATE.render(
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        total_files=len(prepared),
        total_categories=len(grouped),
        grouped_files=grouped,
    )
    Path(html_path).write_text(html, encoding="utf-8")
