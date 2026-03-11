from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from jinja2 import Template


# A palette of 20 distinct hues for category color-coding.
CATEGORY_COLORS = [
    {"bg": "#eef2ff", "border": "#818cf8", "accent": "#4f46e5", "tag": "#e0e7ff"},  # indigo
    {"bg": "#fef3c7", "border": "#f59e0b", "accent": "#b45309", "tag": "#fde68a"},  # amber
    {"bg": "#ecfdf5", "border": "#34d399", "accent": "#059669", "tag": "#a7f3d0"},  # emerald
    {"bg": "#fce7f3", "border": "#f472b6", "accent": "#db2777", "tag": "#fbcfe8"},  # pink
    {"bg": "#e0f2fe", "border": "#38bdf8", "accent": "#0284c7", "tag": "#bae6fd"},  # sky
    {"bg": "#fef9c3", "border": "#facc15", "accent": "#a16207", "tag": "#fef08a"},  # yellow
    {"bg": "#f3e8ff", "border": "#a78bfa", "accent": "#7c3aed", "tag": "#ddd6fe"},  # violet
    {"bg": "#fff1f2", "border": "#fb7185", "accent": "#e11d48", "tag": "#fecdd3"},  # rose
    {"bg": "#f0fdfa", "border": "#2dd4bf", "accent": "#0d9488", "tag": "#99f6e4"},  # teal
    {"bg": "#fff7ed", "border": "#fb923c", "accent": "#c2410c", "tag": "#fed7aa"},  # orange
    {"bg": "#eff6ff", "border": "#60a5fa", "accent": "#2563eb", "tag": "#bfdbfe"},  # blue
    {"bg": "#f0fdf4", "border": "#4ade80", "accent": "#16a34a", "tag": "#bbf7d0"},  # green
    {"bg": "#faf5ff", "border": "#c084fc", "accent": "#9333ea", "tag": "#e9d5ff"},  # purple
    {"bg": "#fefce8", "border": "#a3e635", "accent": "#65a30d", "tag": "#d9f99d"},  # lime
    {"bg": "#f8fafc", "border": "#94a3b8", "accent": "#475569", "tag": "#cbd5e1"},  # slate
    {"bg": "#ecfeff", "border": "#22d3ee", "accent": "#0891b2", "tag": "#a5f3fc"},  # cyan
    {"bg": "#fdf4ff", "border": "#e879f9", "accent": "#c026d3", "tag": "#f5d0fe"},  # fuchsia
    {"bg": "#f5f5f4", "border": "#a8a29e", "accent": "#57534e", "tag": "#d6d3d1"},  # stone
    {"bg": "#fefce8", "border": "#fbbf24", "accent": "#92400e", "tag": "#fde68a"},  # gold
    {"bg": "#f0f9ff", "border": "#7dd3fc", "accent": "#0369a1", "tag": "#bae6fd"},  # light-blue
]


HTML_TEMPLATE = Template(
    """\
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>文件整理报告</title>
  <style>
    :root {
      --bg: #f8fafc;
      --surface: #ffffff;
      --text: #1e293b;
      --muted: #64748b;
      --border: #e2e8f0;
      --shadow-sm: 0 1px 3px rgba(0,0,0,0.06);
      --shadow-md: 0 4px 12px rgba(0,0,0,0.08);
      --radius: 12px;
    }
    @media (prefers-color-scheme: dark) {
      :root {
        --bg: #0f172a;
        --surface: #1e293b;
        --text: #e2e8f0;
        --muted: #94a3b8;
        --border: #334155;
        --shadow-sm: 0 1px 3px rgba(0,0,0,0.3);
        --shadow-md: 0 4px 12px rgba(0,0,0,0.4);
      }
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.6;
    }

    /* ---- Header ---- */
    .header {
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      padding: 24px 0;
      position: sticky;
      top: 0;
      z-index: 100;
      box-shadow: var(--shadow-sm);
    }
    .container { max-width: 1400px; margin: 0 auto; padding: 0 24px; }
    .header-inner { display: flex; align-items: center; justify-content: space-between; gap: 20px; flex-wrap: wrap; }
    .header h1 { font-size: 22px; font-weight: 700; white-space: nowrap; }
    .header .meta { color: var(--muted); font-size: 13px; }
    .search-box {
      flex: 1;
      max-width: 400px;
      min-width: 200px;
      padding: 10px 16px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--bg);
      color: var(--text);
      font-size: 14px;
      outline: none;
      transition: border-color 0.2s;
    }
    .search-box:focus { border-color: #818cf8; }

    /* ---- Stats Bar ---- */
    .stats-bar {
      display: flex;
      gap: 12px;
      padding: 20px 0;
      flex-wrap: wrap;
    }
    .stat-chip {
      display: flex;
      align-items: baseline;
      gap: 6px;
      padding: 8px 16px;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 20px;
      font-size: 13px;
      color: var(--muted);
      box-shadow: var(--shadow-sm);
    }
    .stat-chip strong { font-size: 18px; color: var(--text); }

    /* ---- Index (table of contents) ---- */
    .index {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 20px 24px;
      margin-bottom: 24px;
      box-shadow: var(--shadow-sm);
    }
    .index h2 { font-size: 15px; font-weight: 600; margin-bottom: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }
    .index-grid {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .index-tag {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 14px;
      border-radius: 20px;
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      text-decoration: none;
      transition: transform 0.15s, box-shadow 0.15s;
      border: 1px solid transparent;
    }
    .index-tag:hover { transform: translateY(-1px); box-shadow: var(--shadow-md); }
    .index-tag .count { font-size: 11px; opacity: 0.7; }

    /* ---- Category Grid ---- */
    .cat-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
      gap: 16px;
      padding-bottom: 48px;
    }

    /* ---- Category Card (collapsed) ---- */
    .cat-card {
      border-radius: var(--radius);
      border: 1px solid var(--border);
      overflow: hidden;
      box-shadow: var(--shadow-sm);
      transition: box-shadow 0.2s;
      cursor: pointer;
      position: relative;
    }
    .cat-card:hover { box-shadow: var(--shadow-md); }
    .cat-card-header {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 16px 20px;
    }
    .cat-color-bar {
      width: 4px;
      height: 36px;
      border-radius: 2px;
      flex-shrink: 0;
    }
    .cat-info { flex: 1; min-width: 0; }
    .cat-name {
      font-size: 15px;
      font-weight: 600;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .cat-meta { font-size: 12px; color: var(--muted); margin-top: 2px; }
    .cat-badge {
      padding: 3px 10px;
      border-radius: 12px;
      font-size: 12px;
      font-weight: 600;
      flex-shrink: 0;
    }
    .cat-chevron {
      width: 20px;
      height: 20px;
      color: var(--muted);
      transition: transform 0.25s;
      flex-shrink: 0;
    }
    .cat-card.open .cat-chevron { transform: rotate(180deg); }

    /* ---- File list inside card (hidden by default) ---- */
    .cat-body {
      max-height: 0;
      overflow: hidden;
      transition: max-height 0.35s ease;
    }
    .cat-card.open .cat-body { max-height: none; }
    .cat-body-inner { padding: 0 20px 16px; }
    .file-row {
      display: flex;
      align-items: flex-start;
      gap: 12px;
      padding: 10px 12px;
      border-radius: 8px;
      margin-bottom: 2px;
      transition: background 0.15s;
    }
    .file-row:hover { background: rgba(0,0,0,0.03); }
    @media (prefers-color-scheme: dark) {
      .file-row:hover { background: rgba(255,255,255,0.04); }
    }
    .file-icon {
      width: 32px;
      height: 32px;
      border-radius: 6px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 14px;
      flex-shrink: 0;
      margin-top: 2px;
    }
    .file-details { flex: 1; min-width: 0; }
    .file-name {
      font-size: 13px;
      font-weight: 600;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .file-brief {
      font-size: 12px;
      color: var(--muted);
      margin-top: 1px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .file-path {
      font-size: 11px;
      color: var(--muted);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      margin-top: 2px;
    }
    .file-path a { color: inherit; text-decoration: none; }
    .file-path a:hover { text-decoration: underline; }
    .file-size {
      font-size: 11px;
      color: var(--muted);
      white-space: nowrap;
      flex-shrink: 0;
      margin-top: 4px;
    }

    /* ---- Show-all link ---- */
    .show-all {
      display: block;
      text-align: center;
      padding: 10px;
      font-size: 13px;
      color: var(--muted);
      cursor: pointer;
      border-top: 1px solid var(--border);
      margin-top: 8px;
    }
    .show-all:hover { color: var(--text); }

    /* ---- Overlay detail panel ---- */
    .overlay {
      display: none;
      position: fixed;
      inset: 0;
      z-index: 200;
      background: rgba(0,0,0,0.4);
      backdrop-filter: blur(4px);
    }
    .overlay.active { display: flex; align-items: center; justify-content: center; }
    .detail-panel {
      background: var(--surface);
      border-radius: 16px;
      width: 90vw;
      max-width: 900px;
      max-height: 85vh;
      overflow: auto;
      box-shadow: 0 24px 48px rgba(0,0,0,0.2);
      position: relative;
    }
    .detail-header {
      padding: 24px 28px 16px;
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: space-between;
      position: sticky;
      top: 0;
      background: var(--surface);
      z-index: 1;
      border-radius: 16px 16px 0 0;
    }
    .detail-header h2 { font-size: 20px; }
    .detail-close {
      width: 32px;
      height: 32px;
      border-radius: 8px;
      border: 1px solid var(--border);
      background: var(--bg);
      color: var(--muted);
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 18px;
    }
    .detail-close:hover { color: var(--text); }
    .detail-body { padding: 16px 28px 28px; }
    .detail-file {
      display: flex;
      align-items: flex-start;
      gap: 14px;
      padding: 14px 0;
      border-bottom: 1px solid var(--border);
    }
    .detail-file:last-child { border-bottom: none; }
    .detail-file .file-icon { width: 36px; height: 36px; font-size: 16px; }
    .detail-file .file-name { font-size: 14px; }
    .detail-file .file-brief { font-size: 13px; }
    .detail-file .file-meta-line { font-size: 12px; color: var(--muted); margin-top: 3px; }
    .detail-file .file-meta-line a { color: var(--muted); text-decoration: none; }
    .detail-file .file-meta-line a:hover { text-decoration: underline; }
    .detail-file .file-summary { font-size: 12px; color: var(--muted); margin-top: 4px; font-style: italic; white-space: pre-wrap; }

    /* ---- Responsive ---- */
    @media (max-width: 720px) {
      .cat-grid { grid-template-columns: 1fr; }
      .header-inner { flex-direction: column; align-items: stretch; }
      .search-box { max-width: 100%; }
    }

    /* ---- File extension icon colors ---- */
    .ext-doc { background: #dbeafe; color: #2563eb; }
    .ext-xls { background: #dcfce7; color: #16a34a; }
    .ext-ppt { background: #fee2e2; color: #dc2626; }
    .ext-pdf { background: #fce7f3; color: #db2777; }
    .ext-img { background: #fef3c7; color: #d97706; }
    .ext-code { background: #f3e8ff; color: #7c3aed; }
    .ext-zip { background: #f5f5f4; color: #57534e; }
    .ext-media { background: #ecfeff; color: #0891b2; }
    .ext-other { background: #f1f5f9; color: #64748b; }

    @media (prefers-color-scheme: dark) {
      .ext-doc { background: #1e3a5f; color: #60a5fa; }
      .ext-xls { background: #14532d; color: #4ade80; }
      .ext-ppt { background: #450a0a; color: #fca5a5; }
      .ext-pdf { background: #500724; color: #f9a8d4; }
      .ext-img { background: #451a03; color: #fbbf24; }
      .ext-code { background: #2e1065; color: #c4b5fd; }
      .ext-zip { background: #292524; color: #a8a29e; }
      .ext-media { background: #083344; color: #67e8f9; }
      .ext-other { background: #1e293b; color: #94a3b8; }
    }

    /* ---- No-results message ---- */
    .no-results {
      grid-column: 1 / -1;
      text-align: center;
      padding: 48px 20px;
      color: var(--muted);
      font-size: 15px;
    }
  </style>
</head>
<body>

  <!-- Sticky header -->
  <div class="header">
    <div class="container header-inner">
      <div>
        <h1>文件整理报告</h1>
        <div class="meta">{{ generated_at }} &middot; {{ total_files }} 个文件 &middot; {{ total_categories }} 个分类</div>
      </div>
      <input class="search-box" id="searchBox" type="text" placeholder="搜索文件名或分类...">
    </div>
  </div>

  <div class="container">
    <!-- Stats chips -->
    <div class="stats-bar">
      <div class="stat-chip"><strong>{{ total_files }}</strong> 文件</div>
      <div class="stat-chip"><strong>{{ total_categories }}</strong> 分类</div>
      {% for cat in categories %}
      <div class="stat-chip"><strong>{{ cat.count }}</strong> {{ cat.name }}</div>
      {% endfor %}
    </div>

    <!-- Index -->
    <div class="index">
      <h2>分类索引</h2>
      <div class="index-grid">
        {% for cat in categories %}
        <a class="index-tag" href="#cat-{{ loop.index0 }}" style="background:{{ cat.color.tag }};color:{{ cat.color.accent }};" onclick="scrollToCard(event, 'cat-{{ loop.index0 }}')">
          {{ cat.name }} <span class="count">{{ cat.count }}</span>
        </a>
        {% endfor %}
      </div>
    </div>

    <!-- Category grid -->
    <div class="cat-grid" id="catGrid">
      {% for cat in categories %}
      <div class="cat-card" id="cat-{{ loop.index0 }}" data-cat="{{ cat.name|lower }}" data-files='{{ cat.files_json }}'>
        <div class="cat-card-header" onclick="toggleCard(this.parentElement)" style="background:{{ cat.color.bg }};">
          <div class="cat-color-bar" style="background:{{ cat.color.border }};"></div>
          <div class="cat-info">
            <div class="cat-name">{{ cat.name }}</div>
            <div class="cat-meta">{{ cat.top_types }}</div>
          </div>
          <div class="cat-badge" style="background:{{ cat.color.tag }};color:{{ cat.color.accent }};">{{ cat.count }}</div>
          <svg class="cat-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
        </div>
        <div class="cat-body">
          <div class="cat-body-inner">
            {% for file in cat.files[:5] %}
            <div class="file-row" data-fname="{{ file.file_name|lower }}">
              <div class="file-icon {{ file.ext_class }}">{{ file.ext_label }}</div>
              <div class="file-details">
                <div class="file-name" title="{{ file.file_name }}">{{ file.file_name }}</div>
                {% if file.brief %}<div class="file-brief">{{ file.brief }}</div>{% endif %}
                <div class="file-path"><a href="{{ file.file_uri }}" title="{{ file.file_path }}">{{ file.file_path }}</a></div>
              </div>
              <div class="file-size">{{ file.file_size_human }}</div>
            </div>
            {% endfor %}
            {% if cat.count > 5 %}
            <div class="show-all" onclick="openDetail('{{ cat.name }}', {{ loop.index0 }})">查看全部 {{ cat.count }} 个文件 &rarr;</div>
            {% endif %}
          </div>
        </div>
      </div>
      {% endfor %}
    </div>
  </div>

  <!-- Detail overlay -->
  <div class="overlay" id="overlay" onclick="if(event.target===this)closeDetail()">
    <div class="detail-panel">
      <div class="detail-header">
        <h2 id="detailTitle">分类详情</h2>
        <button class="detail-close" onclick="closeDetail()">&times;</button>
      </div>
      <div class="detail-body" id="detailBody"></div>
    </div>
  </div>

  <script>
    /* ---- Toggle card expand/collapse ---- */
    function toggleCard(el) {
      el.classList.toggle('open');
    }

    /* ---- Index scroll ---- */
    function scrollToCard(e, id) {
      e.preventDefault();
      const card = document.getElementById(id);
      if (!card) return;
      card.scrollIntoView({behavior: 'smooth', block: 'center'});
      if (!card.classList.contains('open')) card.classList.add('open');
    }

    /* ---- Detail overlay ---- */
    const allCatData = {};
    document.querySelectorAll('.cat-card').forEach(card => {
      try {
        const name = card.querySelector('.cat-name').textContent;
        const raw = card.dataset.files;
        if (raw) allCatData[name] = JSON.parse(raw);
      } catch(e) {}
    });

    function openDetail(catName, idx) {
      const files = allCatData[catName] || [];
      const card = document.getElementById('cat-' + idx);
      const barColor = card ? card.querySelector('.cat-color-bar').style.background : '#818cf8';
      document.getElementById('detailTitle').textContent = catName + ' (' + files.length + ')';
      const body = document.getElementById('detailBody');
      body.innerHTML = files.map(f => {
        const brief = f.brief ? '<div class="file-brief">' + esc(f.brief) + '</div>' : '';
        const summary = f.summary ? '<div class="file-summary">' + esc(f.summary) + '</div>' : '';
        return '<div class="detail-file">' +
          '<div class="file-icon ' + f.ext_class + '">' + esc(f.ext_label) + '</div>' +
          '<div class="file-details" style="flex:1;min-width:0">' +
            '<div class="file-name">' + esc(f.file_name) + '</div>' +
            brief +
            '<div class="file-meta-line">' + esc(f.file_size_human) + ' &middot; ' + esc(f.modified_at) + '</div>' +
            '<div class="file-meta-line"><a href="' + esc(f.file_uri) + '">' + esc(f.file_path) + '</a></div>' +
            summary +
          '</div></div>';
      }).join('');
      document.getElementById('overlay').classList.add('active');
      document.body.style.overflow = 'hidden';
    }
    function closeDetail() {
      document.getElementById('overlay').classList.remove('active');
      document.body.style.overflow = '';
    }
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDetail(); });

    function esc(s) {
      if (!s) return '';
      const d = document.createElement('div');
      d.textContent = s;
      return d.innerHTML;
    }

    /* ---- Search ---- */
    const searchBox = document.getElementById('searchBox');
    searchBox.addEventListener('input', () => {
      const kw = searchBox.value.trim().toLowerCase();
      document.querySelectorAll('.cat-card').forEach(card => {
        if (!kw) { card.style.display = ''; return; }
        const catName = (card.dataset.cat || '');
        const rows = card.querySelectorAll('.file-row');
        let anyMatch = catName.includes(kw);
        rows.forEach(r => {
          const match = (r.dataset.fname || '').includes(kw);
          r.style.display = (!kw || match) ? '' : 'none';
          if (match) anyMatch = true;
        });
        card.style.display = anyMatch ? '' : 'none';
        if (anyMatch && kw && !card.classList.contains('open')) card.classList.add('open');
      });
    });
  </script>
</body>
</html>"""
)


# ---- Extension icon mapping ----

_EXT_MAP = {
    ".doc": ("ext-doc", "W"), ".docx": ("ext-doc", "W"), ".odt": ("ext-doc", "W"), ".rtf": ("ext-doc", "W"),
    ".xls": ("ext-xls", "X"), ".xlsx": ("ext-xls", "X"), ".csv": ("ext-xls", "X"), ".ods": ("ext-xls", "X"),
    ".ppt": ("ext-ppt", "P"), ".pptx": ("ext-ppt", "P"), ".odp": ("ext-ppt", "P"),
    ".pdf": ("ext-pdf", "PDF"),
    ".jpg": ("ext-img", "IMG"), ".jpeg": ("ext-img", "IMG"), ".png": ("ext-img", "IMG"),
    ".gif": ("ext-img", "IMG"), ".bmp": ("ext-img", "IMG"), ".svg": ("ext-img", "IMG"),
    ".webp": ("ext-img", "IMG"), ".ico": ("ext-img", "IMG"), ".tiff": ("ext-img", "IMG"),
    ".mp3": ("ext-media", "♪"), ".wav": ("ext-media", "♪"), ".flac": ("ext-media", "♪"),
    ".aac": ("ext-media", "♪"), ".ogg": ("ext-media", "♪"), ".wma": ("ext-media", "♪"),
    ".mp4": ("ext-media", "▶"), ".avi": ("ext-media", "▶"), ".mkv": ("ext-media", "▶"),
    ".mov": ("ext-media", "▶"), ".wmv": ("ext-media", "▶"), ".flv": ("ext-media", "▶"),
    ".py": ("ext-code", "<>"), ".js": ("ext-code", "<>"), ".ts": ("ext-code", "<>"),
    ".java": ("ext-code", "<>"), ".c": ("ext-code", "<>"), ".cpp": ("ext-code", "<>"),
    ".h": ("ext-code", "<>"), ".go": ("ext-code", "<>"), ".rs": ("ext-code", "<>"),
    ".rb": ("ext-code", "<>"), ".php": ("ext-code", "<>"), ".html": ("ext-code", "<>"),
    ".css": ("ext-code", "<>"), ".json": ("ext-code", "{}"), ".xml": ("ext-code", "<>"),
    ".yaml": ("ext-code", "<>"), ".yml": ("ext-code", "<>"), ".sh": ("ext-code", "$"),
    ".bat": ("ext-code", "$"), ".ps1": ("ext-code", "$"), ".sql": ("ext-code", "DB"),
    ".zip": ("ext-zip", "ZIP"), ".rar": ("ext-zip", "ZIP"), ".7z": ("ext-zip", "ZIP"),
    ".tar": ("ext-zip", "ZIP"), ".gz": ("ext-zip", "ZIP"), ".bz2": ("ext-zip", "ZIP"),
    ".iso": ("ext-zip", "ISO"), ".dmg": ("ext-zip", "DMG"),
    ".exe": ("ext-zip", "EXE"), ".msi": ("ext-zip", "MSI"), ".deb": ("ext-zip", "PKG"),
    ".txt": ("ext-other", "TXT"), ".md": ("ext-other", "MD"), ".log": ("ext-other", "LOG"),
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
    return f"file:///{quote(normalized, safe=':/')}"


def prepare_records(records: list[dict]) -> list[dict]:
    prepared: list[dict] = []
    from datetime import datetime as _dt

    for record in records:
        path = Path(record["file_path"])
        ext_class, ext_label = _ext_info(path.name)
        prepared.append(
            {
                **record,
                "file_name": path.name,
                "file_size_human": human_size(int(record.get("file_size") or 0)),
                "modified_at": _dt.fromtimestamp(record["modified_time"]).strftime(
                    "%Y-%m-%d %H:%M"
                ),
                "file_uri": file_uri(record["file_path"]),
                "ext_class": ext_class,
                "ext_label": ext_label,
            }
        )
    return prepared


def _top_extensions(files: list[dict], n: int = 3) -> str:
    counts: dict[str, int] = defaultdict(int)
    for f in files:
        ext = Path(f["file_name"]).suffix.lower()
        if ext:
            counts[ext] += 1
    top = sorted(counts.items(), key=lambda x: -x[1])[:n]
    return "  ".join(f"{ext} ({cnt})" for ext, cnt in top) if top else ""


def generate_reports(
    records: list[dict],
    html_path: str = "report.html",
    json_path: str = "report.json",
) -> None:
    prepared = prepare_records(records)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for record in prepared:
        grouped[record.get("category") or "未分类"].append(record)

    grouped = dict(sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])))

    # Build category list with colors
    categories = []
    for idx, (cat_name, files) in enumerate(grouped.items()):
        color = CATEGORY_COLORS[idx % len(CATEGORY_COLORS)]
        # Serialize files for the detail overlay (only safe fields)
        safe_files = []
        for f in files:
            safe_files.append(
                {
                    "file_name": f["file_name"],
                    "file_size_human": f["file_size_human"],
                    "modified_at": f["modified_at"],
                    "file_path": f["file_path"],
                    "file_uri": f["file_uri"],
                    "ext_class": f["ext_class"],
                    "ext_label": f["ext_label"],
                    "brief": f.get("brief") or "",
                    "summary": f.get("summary") or "",
                }
            )
        categories.append(
            {
                "name": cat_name,
                "count": len(files),
                "color": color,
                "files": files,
                "files_json": json.dumps(safe_files, ensure_ascii=False),
                "top_types": _top_extensions(files),
            }
        )

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_files": len(prepared),
        "categories": {cat["name"]: cat["files"] for cat in categories},
    }
    Path(json_path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    html = HTML_TEMPLATE.render(
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        total_files=len(prepared),
        total_categories=len(categories),
        categories=categories,
    )
    Path(html_path).write_text(html, encoding="utf-8")
