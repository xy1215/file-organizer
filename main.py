from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import click
import yaml
from rich.console import Console

from cache import CacheDB
from classifier import LLMClient, build_file_stub, classify_files_iter, summarize_text
from report import generate_reports
from scanner import scan_files
from summarizer import UnsupportedSummaryError, extract_text


console = Console()
logging.basicConfig(
    filename="error.log",
    level=logging.ERROR,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def _ensure_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _ensure_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def load_config(config_path: str = "config.yaml") -> dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        raise click.ClickException("未找到 config.yaml，请先检查项目目录。")
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        console.print("[yellow]config.yaml 顶层结构无效，已按空配置处理。[/yellow]")
        return {}
    return loaded


def get_cache() -> CacheDB:
    return CacheDB("cache.db")


def get_batch_size(config: dict[str, Any]) -> int:
    raw = config.get("batch_size", 80)
    try:
        raw_value = int(raw or 80)
    except (TypeError, ValueError):
        console.print("[yellow]batch_size 配置无效，已使用默认值 80。[/yellow]")
        raw_value = 80
    if raw_value < 80 or raw_value > 100:
        console.print("[yellow]batch_size 超出建议范围，已自动调整到 80-100 之间。[/yellow]")
    return min(100, max(80, raw_value))


def _normalize_file_path(value: str) -> str:
    """Normalize file path for matching model output with local batch paths."""
    raw = value.strip()
    if not raw:
        return ""
    path = Path(raw).expanduser()
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        resolved = path
    return os.path.normcase(str(resolved))


def get_summary_workers(config: dict[str, Any]) -> int:
    raw = config.get("summary_workers", 4)
    try:
        value = int(raw or 4)
    except (TypeError, ValueError):
        console.print("[yellow]summary_workers 配置无效，已使用默认值 4。[/yellow]")
        value = 4
    return min(8, max(1, value))


def _select_summary_targets(
    cache: CacheDB,
    *,
    category_name: str | None = None,
    file_path: str | None = None,
    summarize_all: bool = False,
    force: bool = False,
    candidate_paths: list[str] | None = None,
) -> list[str]:
    if candidate_paths is not None:
        deduped = list(dict.fromkeys(candidate_paths))
        return cache.filter_paths_with_category(deduped)

    if file_path:
        return [str(Path(file_path).expanduser().resolve())]

    if category_name:
        records = cache.list_by_category(category_name)
        if force:
            return [record["file_path"] for record in records]
        return [
            record["file_path"]
            for record in records
            if not str(record.get("summary") or "").strip()
        ]

    if summarize_all:
        records = [record for record in cache.list_all() if record.get("category")]
        if force:
            return [record["file_path"] for record in records]
        return [
            record["file_path"]
            for record in records
            if not str(record.get("summary") or "").strip()
        ]

    return []


def _scan_and_classify(cache: CacheDB, config: dict[str, Any], force: bool = False) -> dict[str, Any]:
    console.print("[cyan]正在扫描目录，请稍候...[/cyan]")
    scan_config = _ensure_dict(config.get("scan", {}))
    scanned_files = scan_files(
        paths=_ensure_str_list(scan_config.get("paths", [])),
        exclude_patterns=_ensure_str_list(scan_config.get("exclude_patterns", [])),
    )
    if not scanned_files:
        console.print("[yellow]没有扫描到符合条件的文件。[/yellow]")
        return {
            "scanned_files": [],
            "changed_paths": [],
            "summary_targets": [],
            "classified": 0,
        }

    console.print(f"[cyan]扫描完成，发现 {len(scanned_files)} 个符合条件的文件，正在检查缓存...[/cyan]")
    existing_records = cache.index_scan_state_by_path()
    scanned_paths = {item.file_path for item in scanned_files}
    removed = cache.delete_absent_files(scanned_paths)
    if removed:
        console.print(f"[cyan]已清理 {removed} 条失效缓存记录（源文件不存在）。[/cyan]")

    unchanged_paths: set[str] = set()
    upsert_rows: list[tuple[str, int, float]] = []
    changed_paths: list[str] = []
    changed_path_set: set[str] = set()
    summary_candidates: list[str] = []
    summary_candidate_seen: set[str] = set()
    for item in scanned_files:
        record = existing_records.get(item.file_path)
        unchanged = (
            not force
            and record is not None
            and record.file_size == item.size
            and record.modified_time == item.modified_time
            and record.has_category
        )
        if unchanged:
            unchanged_paths.add(item.file_path)
        else:
            changed_paths.append(item.file_path)
            changed_path_set.add(item.file_path)
        if force or record is None or not record.has_summary or item.file_path in changed_path_set:
            if item.file_path not in summary_candidate_seen:
                summary_candidate_seen.add(item.file_path)
                summary_candidates.append(item.file_path)
        upsert_rows.append((item.file_path, item.size, item.modified_time))

    cache.upsert_files_bulk(upsert_rows)
    if changed_paths:
        cache.clear_summaries_bulk(changed_paths)

    if force:
        pending = [build_file_stub(item.file_path) for item in scanned_files]
    else:
        pending = [
            build_file_stub(item.file_path)
            for item in scanned_files
            if item.file_path not in unchanged_paths
        ]

    classified = 0
    if not pending:
        console.print(f"[green]扫描完成，共 {len(scanned_files)} 个文件，未发现需要重新分类的文件。[/green]")
    else:
        try:
            client = LLMClient(config)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc

        batch_size = get_batch_size(config)
        console.print(f"[cyan]缓存检查完成，开始分类，共 {len(pending)} 个文件待处理。[/cyan]")

        failed_batches = 0
        for done, total, batch, batch_results, batch_error in classify_files_iter(
            client, pending, batch_size=batch_size
        ):
            batch_path_map: dict[str, str] = {}
            batch_id_map: dict[str, str] = {}
            for item in batch:
                batch_file_path = str(item.get("file_path") or "").strip()
                normalized = _normalize_file_path(batch_file_path)
                if normalized:
                    batch_path_map.setdefault(normalized, batch_file_path)
                file_id = str(item.get("file_id") or "").strip()
                if file_id:
                    batch_id_map.setdefault(file_id, batch_file_path)
            update_rows: list[tuple[str, str, str | None]] = []
            covered_paths: set[str] = set()

            if batch_error:
                failed_batches += 1
                console.print(
                    f"[yellow]警告：批次分类失败，已跳过该批次（{done}/{total}）：{batch_error}[/yellow]"
                )

            for item in batch_results:
                file_id = str(item.get("file_id") or "").strip()
                file_path = str(item.get("file_path") or "").strip()
                category = str(item.get("category") or "").strip()
                matched_path = batch_id_map.get(file_id) if file_id else None
                if not matched_path:
                    normalized = _normalize_file_path(file_path)
                    matched_path = batch_path_map.get(normalized)
                if not category or not matched_path:
                    continue
                brief = str(item.get("brief") or "").strip() or None
                if matched_path in covered_paths:
                    continue
                covered_paths.add(matched_path)
                update_rows.append((matched_path, category, brief))

            classified += cache.update_categories_bulk(update_rows)
            missing = len(set(batch_path_map.values()) - covered_paths)
            if missing:
                console.print(f"[yellow]当前批次有 {missing} 个文件未返回分类结果，将在后续扫描重试。[/yellow]")
            console.print(f"进度：{done}/{total} - 已分类 {classified} 个文件")
        if failed_batches:
            console.print(
                f"[yellow]分类阶段有 {failed_batches} 个批次失败，其他批次已继续处理。可稍后执行 sync/scan 重试。[/yellow]"
            )

    summary_targets = _select_summary_targets(cache, candidate_paths=summary_candidates)
    return {
        "scanned_files": scanned_files,
        "changed_paths": changed_paths,
        "summary_targets": summary_targets,
        "classified": classified,
    }


def _summarize_file(config: dict[str, Any], file_path: str, client_local: threading.local) -> tuple[bool, str]:
    path = Path(file_path)
    if not path.exists():
        return False, f"文件不存在：{file_path}"
    try:
        extracted = extract_text(file_path)
        if not extracted.strip():
            return False, f"无法提取有效文本：{file_path}"
        client = getattr(client_local, "client", None)
        if client is None:
            client = LLMClient(config)
            client_local.client = client
        summary = summarize_text(client, file_path, extracted)
        return True, summary
    except UnsupportedSummaryError as exc:
        return False, str(exc)
    except Exception as exc:
        logging.exception("摘要生成失败: %s", file_path)
        return False, f"摘要失败：{exc}"


def _run_summary_jobs(cache: CacheDB, config: dict[str, Any], targets: list[str]) -> tuple[int, int]:
    if not targets:
        console.print("[yellow]没有找到需要生成摘要的文件。[/yellow]")
        return 0, 0

    workers = min(get_summary_workers(config), len(targets))
    console.print(
        f"[cyan]已找到 {len(targets)} 个目标文件，开始生成摘要（并发 {workers}）...[/cyan]"
    )
    success = 0
    completed = 0
    pending_updates: list[tuple[str, str]] = []
    flush_size = 20
    client_local = threading.local()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(_summarize_file, config, target, client_local): target
            for target in targets
        }
        for future in as_completed(future_map):
            target = future_map[future]
            completed += 1
            try:
                ok, message = future.result()
            except Exception as exc:
                logging.exception("摘要任务线程异常: %s", target)
                ok, message = False, f"摘要失败：{exc}"
            console.print(f"[cyan]进度：{completed}/{len(targets)} - 已完成 {Path(target).name}[/cyan]")
            if ok:
                success += 1
                pending_updates.append((target, message))
                if len(pending_updates) >= flush_size:
                    cache.update_summaries_bulk(pending_updates)
                    pending_updates.clear()
            else:
                logging.error("摘要失败: %s | %s", target, message)
            console.print(message)
    if pending_updates:
        cache.update_summaries_bulk(pending_updates)
    return success, len(targets)


def run_scan(force: bool = False) -> None:
    config = load_config()
    cache = get_cache()
    try:
        result = _scan_and_classify(cache, config, force=force)
        if not result["scanned_files"]:
            return
        console.print("[cyan]正在刷新报告...[/cyan]")
        generate_reports(cache.list_all())
        classified = result["classified"]
        console.print(f"[green]扫描完成。总扫描 {len(result['scanned_files'])} 个文件，本次分类 {classified} 个文件。[/green]")
        console.print("[green]已生成 report.html 和 report.json。[/green]")
    finally:
        cache.close()


def run_summarize(
    category_name: str | None = None,
    file_path: str | None = None,
    summarize_all: bool = False,
    force: bool = False,
) -> None:
    selected = sum(bool(value) for value in [category_name, file_path, summarize_all])
    if selected != 1:
        raise click.ClickException("请在 --category、--file、--all 中且仅选择一个。")

    config = load_config()
    cache = get_cache()
    try:
        if file_path:
            record = cache.get(str(Path(file_path).expanduser().resolve()))
            if not record:
                path = Path(file_path).expanduser().resolve()
                if path.exists():
                    stat = path.stat()
                    cache.upsert_file(str(path), stat.st_size, stat.st_mtime)
        targets = _select_summary_targets(
            cache,
            category_name=category_name,
            file_path=file_path,
            summarize_all=summarize_all,
            force=force,
        )
        success, total = _run_summary_jobs(cache, config, targets)
        if not total:
            return
        console.print("[cyan]摘要生成完成，正在刷新报告...[/cyan]")
        generate_reports(cache.list_all())
        console.print(f"[green]摘要任务完成，成功 {success}/{total}。[/green]")
    finally:
        cache.close()


def run_sync(force_scan: bool = False, force_summary: bool = False) -> None:
    config = load_config()
    cache = get_cache()
    try:
        result = _scan_and_classify(cache, config, force=force_scan)
        scanned_files = result["scanned_files"]
        if not scanned_files:
            return
        targets = result["summary_targets"]
        if force_summary:
            targets = _select_summary_targets(cache, summarize_all=True, force=True)
        success, total = _run_summary_jobs(cache, config, targets)
        console.print("[cyan]正在刷新报告...[/cyan]")
        generate_reports(cache.list_all())
        console.print(
            f"[green]同步完成。总扫描 {len(scanned_files)} 个文件，本次分类 {result['classified']} 个文件，摘要成功 {success}/{total}。[/green]"
        )
        console.print("[green]已生成 report.html 和 report.json。[/green]")
    finally:
        cache.close()


def run_report() -> None:
    cache = get_cache()
    try:
        console.print("[cyan]正在生成报告...[/cyan]")
        generate_reports(cache.list_all())
        console.print("[green]报告已生成：report.html, report.json[/green]")
    finally:
        cache.close()


def run_stats() -> None:
    cache = get_cache()
    try:
        console.print("[cyan]正在读取缓存统计...[/cyan]")
        stats_data = cache.stats()
        console.print(f"缓存文件总数：{stats_data['total_files']}")
        console.print(f"已分类文件数：{stats_data['categorized_files']}")
        console.print(f"已有摘要文件数：{stats_data['summarized_files']}")
        console.print("分类统计：")
        for item in stats_data["categories"]:
            console.print(f"- {item['category']}: {item['count']}")
    finally:
        cache.close()


@click.group()
def cli() -> None:
    """本地文件管理分类与摘要工具"""


@cli.command()
@click.option("--force", is_flag=True, help="强制重新处理所有文件")
def scan(force: bool) -> None:
    """扫描并分类文件"""
    run_scan(force=force)


@cli.command()
@click.option("--category", "category_name", type=str, help="为指定分类生成摘要")
@click.option("--file", "file_path", type=str, help="为单个文件生成摘要")
@click.option("--all", "summarize_all", is_flag=True, help="为所有已分类文件生成摘要")
@click.option("--force", is_flag=True, help="即使已有摘要也重新生成")
def summarize(category_name: str | None, file_path: str | None, summarize_all: bool, force: bool) -> None:
    """生成摘要"""
    run_summarize(category_name=category_name, file_path=file_path, summarize_all=summarize_all, force=force)


@cli.command()
@click.option("--force-scan", is_flag=True, help="强制重新分类所有文件")
@click.option("--force-summary", is_flag=True, help="强制重新生成所有摘要")
def sync(force_scan: bool, force_summary: bool) -> None:
    """增量扫描、摘要并刷新报告"""
    run_sync(force_scan=force_scan, force_summary=force_summary)


@cli.command()
def report() -> None:
    """生成或刷新报告"""
    run_report()


@cli.command()
def stats() -> None:
    """查看缓存统计"""
    run_stats()


@cli.command()
def gui() -> None:
    """启动图形界面"""
    from gui import run_gui

    raise SystemExit(run_gui())


if __name__ == "__main__":
    cli()
