from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

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
      color-scheme: light dark;
      --bg: #f3f0ea;
      --paper: rgba(255,255,255,0.82);
      --panel: rgba(255,255,255,0.9);
      --text: #1f2933;
      --muted: #667085;
      --line: rgba(36, 53, 71, 0.12);
      --shadow: 0 14px 36px rgba(52, 64, 84, 0.10);
      --radius-xl: 28px;
      --radius-lg: 22px;
      --radius-md: 16px;
      --radius-sm: 12px;
    }
    @media (prefers-color-scheme: dark) {
      :root {
        --bg: #16181c;
        --paper: rgba(26,28,33,0.82);
        --panel: rgba(31,34,40,0.92);
        --text: #edf2f7;
        --muted: #9aa6b2;
        --line: rgba(237, 242, 247, 0.10);
        --shadow: 0 18px 40px rgba(0, 0, 0, 0.35);
      }
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; padding: 0; }
    body {
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(210,141,82,0.16), transparent 26%),
        radial-gradient(circle at top right, rgba(111,136,201,0.12), transparent 24%),
        linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0)),
        var(--bg);
      min-height: 100vh;
    }
    a { color: inherit; }
    .shell {
      max-width: 1480px;
      margin: 0 auto;
      padding: 28px 20px 56px;
    }
    .hero {
      display: grid;
      grid-template-columns: 1.3fr 0.9fr;
      gap: 18px;
      margin-bottom: 18px;
    }
    .hero-panel, .toolbar, .detail, .empty-state {
      background: var(--paper);
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
      backdrop-filter: blur(14px);
    }
    .hero-panel {
      border-radius: var(--radius-xl);
      padding: 28px;
    }
    .eyebrow {
      font-size: 12px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 10px;
    }
    .hero h1 {
      margin: 0;
      font-size: clamp(30px, 4vw, 54px);
      line-height: 1.02;
      letter-spacing: -0.03em;
    }
    .hero p {
      margin: 14px 0 0;
      max-width: 760px;
      color: var(--muted);
      font-size: 15px;
    }
    .meta-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      align-content: start;
    }
    .meta-card {
      border-radius: var(--radius-lg);
      padding: 20px;
      background: var(--panel);
      border: 1px solid var(--line);
    }
    .meta-card strong {
      display: block;
      font-size: 28px;
      line-height: 1;
      margin-bottom: 6px;
    }
    .meta-card span {
      color: var(--muted);
      font-size: 13px;
    }
    .toolbar {
      border-radius: var(--radius-xl);
      padding: 18px 20px;
      margin-bottom: 20px;
      display: flex;
      gap: 16px;
      align-items: center;
      flex-wrap: wrap;
    }
    .toolbar .field {
      flex: 1;
      min-width: 220px;
    }
    .toolbar label {
      display: block;
      font-size: 12px;
      color: var(--muted);
      margin-bottom: 6px;
    }
    .toolbar input {
      width: 100%;
      padding: 12px 14px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.58);
      color: var(--text);
      outline: none;
    }
    .toolbar input:focus {
      border-color: rgba(111,136,201,0.7);
      box-shadow: 0 0 0 4px rgba(111,136,201,0.12);
    }
    .legend {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 12px;
    }
    .legend .dot {
      width: 10px;
      height: 10px;
      border-radius: 999px;
      display: inline-block;
    }
    .cluster-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(285px, 1fr));
      gap: 16px;
    }
    .cluster-card {
      border-radius: var(--radius-lg);
      border: 1px solid var(--line);
      overflow: hidden;
      background: var(--panel);
      box-shadow: var(--shadow);
      min-height: 214px;
      display: flex;
      flex-direction: column;
      transition: transform 0.18s ease, box-shadow 0.18s ease;
    }
    .cluster-card:hover {
      transform: translateY(-2px);
      box-shadow: 0 18px 34px rgba(52, 64, 84, 0.14);
    }
    .cluster-header {
      padding: 18px 18px 14px;
      border-bottom: 1px solid rgba(0,0,0,0.04);
    }
    .cluster-topline {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: flex-start;
      margin-bottom: 10px;
    }
    .cluster-name {
      margin: 0;
      font-size: 18px;
      line-height: 1.15;
    }
    .cluster-count {
      flex-shrink: 0;
      padding: 5px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
    }
    .cluster-meta {
      color: var(--muted);
      font-size: 12px;
    }
    .cluster-body {
      padding: 14px 18px 18px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      flex: 1;
    }
    .cluster-preview {
      display: flex;
      flex-direction: column;
      gap: 9px;
      flex: 1;
    }
    .preview-item {
      display: grid;
      grid-template-columns: 36px 1fr;
      gap: 10px;
      align-items: start;
      padding: 10px 12px;
      border-radius: var(--radius-sm);
      background: rgba(255,255,255,0.36);
      border: 1px solid rgba(255,255,255,0.22);
      min-height: 64px;
    }
    .icon-badge {
      width: 36px;
      height: 36px;
      border-radius: 12px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.05em;
      background: rgba(255,255,255,0.7);
    }
    .ext-doc { color: #2751a3; background: rgba(205, 224, 255, 0.92); }
    .ext-xls { color: #1f7a46; background: rgba(206, 240, 214, 0.92); }
    .ext-ppt { color: #b54725; background: rgba(252, 221, 213, 0.92); }
    .ext-pdf { color: #b42344; background: rgba(252, 216, 228, 0.92); }
    .ext-img { color: #946200; background: rgba(250, 236, 190, 0.92); }
    .ext-media { color: #0f766e; background: rgba(210, 244, 238, 0.92); }
    .ext-code { color: #5b3cc4; background: rgba(229, 220, 255, 0.92); }
    .ext-zip { color: #5f4b32; background: rgba(232, 225, 215, 0.92); }
    .ext-other { color: #52606d; background: rgba(227, 233, 240, 0.92); }
    .preview-title {
      font-size: 13px;
      font-weight: 700;
      line-height: 1.3;
      margin-bottom: 2px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .preview-brief {
      font-size: 12px;
      line-height: 1.35;
      color: var(--muted);
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .cluster-actions {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding-top: 6px;
    }
    .cluster-actions span {
      font-size: 12px;
      color: var(--muted);
    }
    .cluster-link {
      border: 0;
      background: rgba(255,255,255,0.72);
      color: var(--text);
      padding: 10px 14px;
      border-radius: 999px;
      cursor: pointer;
      font-size: 13px;
      font-weight: 700;
      border: 1px solid rgba(0,0,0,0.06);
    }
    .cluster-link:hover {
      filter: brightness(0.98);
    }
    .detail {
      display: none;
      border-radius: var(--radius-xl);
      padding: 22px;
      margin-top: 22px;
    }
    .detail.active {
      display: block;
    }
    .detail-head {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
      margin-bottom: 18px;
      flex-wrap: wrap;
    }
    .back-link {
      border: 0;
      border-radius: 999px;
      padding: 11px 16px;
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
      background: rgba(255,255,255,0.66);
      color: var(--text);
      border: 1px solid var(--line);
    }
    .detail-title {
      margin: 0;
      font-size: 30px;
      line-height: 1.05;
    }
    .detail-subtitle {
      margin-top: 8px;
      color: var(--muted);
      font-size: 14px;
    }
    .detail-list {
      display: grid;
      gap: 14px;
    }
    .detail-item {
      border-radius: var(--radius-md);
      padding: 16px 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.48);
      display: grid;
      grid-template-columns: 42px 1fr auto;
      gap: 14px;
      align-items: start;
    }
    .detail-main {
      min-width: 0;
    }
    .detail-file {
      font-size: 15px;
      font-weight: 700;
      line-height: 1.35;
      margin-bottom: 4px;
      word-break: break-word;
    }
    .detail-brief {
      font-size: 13px;
      color: var(--muted);
      margin-bottom: 6px;
      word-break: break-word;
    }
    .detail-source {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      margin-bottom: 8px;
      padding: 3px 8px;
      border-radius: 999px;
      font-size: 11px;
      letter-spacing: 0.02em;
      color: #6a5643;
      background: rgba(210, 141, 82, 0.14);
      border: 1px solid rgba(210, 141, 82, 0.24);
    }
    .detail-summary {
      margin-top: 10px;
      padding-top: 10px;
      border-top: 1px dashed var(--line);
      font-size: 12px;
      color: var(--muted);
      white-space: pre-wrap;
    }
    .detail-meta {
      font-size: 12px;
      color: var(--muted);
      word-break: break-word;
    }
    .detail-meta a {
      text-decoration: none;
    }
    .detail-meta a:hover {
      text-decoration: underline;
    }
    .detail-size {
      font-size: 12px;
      color: var(--muted);
      white-space: nowrap;
      margin-top: 4px;
    }
    .empty-state {
      border-radius: var(--radius-xl);
      padding: 48px 24px;
      text-align: center;
      color: var(--muted);
      display: none;
    }
    .empty-state.active {
      display: block;
    }
    .footnote {
      margin-top: 18px;
      font-size: 12px;
      color: var(--muted);
    }
    .detail-load-more {
      margin-top: 16px;
      display: none;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 12px;
    }
    .detail-load-more.active {
      display: flex;
    }
    .detail-load-more button {
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.72);
      color: var(--text);
      padding: 9px 14px;
      border-radius: 999px;
      cursor: pointer;
      font-size: 13px;
      font-weight: 700;
    }
    .detail-load-more button:hover {
      filter: brightness(0.98);
    }
    @media (max-width: 980px) {
      .hero {
        grid-template-columns: 1fr;
      }
      .detail-item {
        grid-template-columns: 42px 1fr;
      }
      .detail-size {
        grid-column: 2;
      }
    }
    @media (max-width: 640px) {
      .shell {
        padding: 18px 14px 42px;
      }
      .hero-panel, .toolbar, .detail {
        border-radius: 22px;
        padding: 18px;
      }
      .cluster-grid {
        grid-template-columns: 1fr;
      }
      .meta-grid {
        grid-template-columns: 1fr 1fr;
      }
    }
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <div class="hero-panel">
        <div class="eyebrow">Local File Organizer</div>
        <h1>文件被整理成一组一组可浏览的 cluster</h1>
        <p>首页默认折叠展示分类，方便同时扫视很多 cluster。点开任一 cluster 后，会切换到完整详情视图，查看这一类下的全部文件、推测描述与已有摘要。</p>
      </div>
      <div class="meta-grid">
        <div class="meta-card"><strong>{{ total_files }}</strong><span>文件总数</span></div>
        <div class="meta-card"><strong>{{ total_categories }}</strong><span>分类数量</span></div>
        <div class="meta-card"><strong>{{ categorized_files }}</strong><span>已分类文件</span></div>
        <div class="meta-card"><strong>{{ summarized_files }}</strong><span>已有摘要</span></div>
      </div>
    </section>

    <section class="toolbar" id="homeToolbar">
      <div class="field">
        <label for="searchBox">快速搜索</label>
        <input id="searchBox" type="text" placeholder="按分类名、文件名、简短描述搜索">
      </div>
      <div class="legend">
        <span>生成时间：{{ generated_at }}</span>
        <span class="dot" style="background:#d28d52;"></span><span>折叠浏览</span>
        <span class="dot" style="background:#6f88c9;"></span><span>点击进入详情</span>
      </div>
    </section>

    <section class="cluster-grid" id="clusterGrid">
      {% for category in categories %}
      <article
        class="cluster-card"
        data-category-id="{{ category.id }}"
        data-search="{{ category.search_text }}"
        style="background:{{ category.color.surface }}; border-color:{{ category.color.border }};"
      >
        <div class="cluster-header">
          <div class="cluster-topline">
            <h2 class="cluster-name">{{ category.name }}</h2>
            <div class="cluster-count" style="background:{{ category.color.pill }}; color:{{ category.color.accent }};">{{ category.count }} 个</div>
          </div>
          <div class="cluster-meta">{{ category.top_types or "混合文件类型" }}</div>
        </div>
        <div class="cluster-body">
          <div class="cluster-preview">
            {% for file in category.preview_files %}
            <div class="preview-item">
              <div class="icon-badge {{ file.ext_class }}">{{ file.ext_label }}</div>
              <div>
                <div class="preview-title" title="{{ file.file_name }}">{{ file.file_name }}</div>
                <div class="preview-brief">{{ file.display_brief }}</div>
              </div>
            </div>
            {% endfor %}
          </div>
          <div class="cluster-actions">
            <span>默认折叠，仅展示 {{ category.preview_count }} 个预览文件</span>
            <button class="cluster-link" type="button" data-open-category="{{ category.id }}">查看完整分类</button>
          </div>
        </div>
      </article>
      {% endfor %}
    </section>

    <section class="empty-state" id="emptyState">
      没有匹配到任何 cluster。可以换个关键词，或清空搜索重新浏览。
    </section>

    <section class="detail" id="detailView">
      <div class="detail-head">
        <div>
          <div class="eyebrow" id="detailEyebrow">Cluster Detail</div>
          <h2 class="detail-title" id="detailTitle">分类详情</h2>
          <div class="detail-subtitle" id="detailSubtitle"></div>
        </div>
        <button class="back-link" id="backButton" type="button">返回所有 cluster</button>
      </div>
      <div class="detail-list" id="detailList"></div>
      <div class="detail-load-more" id="detailLoadMore">
        <span id="detailLoadMoreText"></span>
        <button id="detailLoadMoreButton" type="button">加载更多</button>
      </div>
      <div class="footnote">说明：若文件还没有正式摘要，这里显示的是基于文件名和路径推测的简短描述。</div>
    </section>
  </div>

  <script>
    const reportData = {{ report_data_json | safe }};
    const clusterGrid = document.getElementById('clusterGrid');
    const detailView = document.getElementById('detailView');
    const detailTitle = document.getElementById('detailTitle');
    const detailSubtitle = document.getElementById('detailSubtitle');
    const detailList = document.getElementById('detailList');
    const detailLoadMore = document.getElementById('detailLoadMore');
    const detailLoadMoreText = document.getElementById('detailLoadMoreText');
    const detailLoadMoreButton = document.getElementById('detailLoadMoreButton');
    const backButton = document.getElementById('backButton');
    const searchBox = document.getElementById('searchBox');
    const emptyState = document.getElementById('emptyState');
    const detailPageSize = 120;
    let currentDetailCategory = null;
    let detailRenderedCount = 0;

    function escapeHtml(value) {
      const div = document.createElement('div');
      div.textContent = value || '';
      return div.innerHTML;
    }

    function buildDetailItem(file) {
      const hasSummary = Boolean(file.summary);
      const source = hasSummary
        ? '<div class="detail-source">已读取正文生成摘要</div>'
        : '<div class="detail-source">当前仅根据文件名和路径推测</div>';
      const brief = file.display_brief
        ? `<div class="detail-brief">${escapeHtml(file.display_brief)}</div>`
        : '';
      const summary = hasSummary
        ? `<div class="detail-summary">${escapeHtml(file.summary)}</div>`
        : '';
      return `
        <article class="detail-item">
          <div class="icon-badge ${escapeHtml(file.ext_class)}">${escapeHtml(file.ext_label)}</div>
          <div class="detail-main">
            <div class="detail-file">${escapeHtml(file.file_name)}</div>
            ${source}
            ${brief}
            <div class="detail-meta">${escapeHtml(file.modified_at)} · <a href="${escapeHtml(file.file_uri)}">${escapeHtml(file.file_path)}</a></div>
            ${summary}
          </div>
          <div class="detail-size">${escapeHtml(file.file_size_human)}</div>
        </article>
      `;
    }

    function appendDetailItems(reset = false) {
      if (!currentDetailCategory) return;
      if (reset) {
        detailList.innerHTML = '';
        detailRenderedCount = 0;
      }
      const files = currentDetailCategory.files || [];
      const chunk = files.slice(detailRenderedCount, detailRenderedCount + detailPageSize);
      if (chunk.length > 0) {
        detailList.insertAdjacentHTML('beforeend', chunk.map(buildDetailItem).join(''));
      }
      detailRenderedCount += chunk.length;
      const hasMore = detailRenderedCount < files.length;
      detailLoadMore.classList.toggle('active', hasMore);
      detailLoadMoreText.textContent = `已显示 ${detailRenderedCount}/${files.length}`;
      detailLoadMoreButton.textContent = hasMore ? '加载更多' : '已全部显示';
      detailLoadMoreButton.disabled = !hasMore;
    }

    function renderDetail(categoryId, pushHash = true) {
      const category = reportData.categories.find((item) => item.id === categoryId);
      if (!category) return;

      currentDetailCategory = category;
      detailTitle.textContent = category.name;
      detailSubtitle.textContent = `${category.count} 个文件 · ${category.top_types || '混合文件类型'}`;
      appendDetailItems(true);

      clusterGrid.style.display = 'none';
      emptyState.classList.remove('active');
      detailView.classList.add('active');

      if (pushHash) {
        history.pushState({ categoryId }, '', `#category=${encodeURIComponent(categoryId)}`);
      }
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    function showHome(pushHash = true) {
      detailView.classList.remove('active');
      clusterGrid.style.display = '';
      currentDetailCategory = null;
      detailRenderedCount = 0;
      detailLoadMore.classList.remove('active');
      detailLoadMoreText.textContent = '';
      updateEmptyState();
      if (pushHash) {
        history.pushState({}, '', '#');
      }
    }

    function updateEmptyState() {
      const visibleCards = [...document.querySelectorAll('.cluster-card')].filter((card) => card.style.display !== 'none');
      emptyState.classList.toggle('active', visibleCards.length === 0);
    }

    function filterClusters() {
      const keyword = searchBox.value.trim().toLowerCase();
      document.querySelectorAll('.cluster-card').forEach((card) => {
        const haystack = card.dataset.search || '';
        card.style.display = !keyword || haystack.includes(keyword) ? '' : 'none';
      });
      updateEmptyState();
    }

    document.addEventListener('click', (event) => {
      const button = event.target.closest('[data-open-category]');
      if (!button) return;
      renderDetail(button.dataset.openCategory);
    });

    backButton.addEventListener('click', () => {
      showHome();
    });

    detailLoadMoreButton.addEventListener('click', () => {
      appendDetailItems(false);
    });

    searchBox.addEventListener('input', () => {
      filterClusters();
    });

    window.addEventListener('popstate', () => {
      const hash = window.location.hash || '';
      if (hash.startsWith('#category=')) {
        renderDetail(decodeURIComponent(hash.slice('#category='.length)), false);
      } else {
        showHome(false);
      }
    });

    const initialHash = window.location.hash || '';
    if (initialHash.startsWith('#category=')) {
      renderDetail(decodeURIComponent(initialHash.slice('#category='.length)), false);
    } else {
      filterClusters();
    }
  </script>
</body>
</html>
"""
)


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


def generate_reports(records: list[dict], html_path: str = "report.html", json_path: str = "report.json") -> None:
    prepared = prepare_records(records)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for record in prepared:
        grouped[record.get("category") or "未分类"].append(record)

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
    Path(json_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

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
        categorized_files=sum(1 for record in prepared if record.get("category")),
        summarized_files=sum(1 for record in prepared if record.get("summary")),
        categories=categories,
        report_data_json=json.dumps(report_data, ensure_ascii=False),
    )
    Path(html_path).write_text(html, encoding="utf-8")
