from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

import click
import yaml
from rich.console import Console

from app_paths import app_path
from numpy_compat import ensure_numpy_legacy_aliases
ensure_numpy_legacy_aliases()

from cache import CacheDB
from classifier import LLMClient, build_file_stub, classify_files_iter, summarize_text
from common import OperationCancelled, ensure_dict, ensure_str_list
from report import generate_reports
from scanner import scan_files
from summarizer import UnsupportedSummaryError, extract_text


console = Console()
ERROR_LOG_PATH = app_path("error.log")
logging.basicConfig(
    filename=str(ERROR_LOG_PATH),
    level=logging.ERROR,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8",
)


LogCallback = Callable[[str], None]
ProgressCallback = Callable[[str, int, int, str], None]
CancelChecker = Callable[[], bool]


@dataclass
class RuntimeHooks:
    log: LogCallback | None = None
    progress: ProgressCallback | None = None
    is_cancelled: CancelChecker | None = None


def _log(message: str, hooks: RuntimeHooks | None = None) -> None:
    if hooks and hooks.log:
        hooks.log(message)
        return
    console.print(message)


def _progress(
    phase: str,
    current: int,
    total: int,
    detail: str,
    hooks: RuntimeHooks | None = None,
) -> None:
    if hooks and hooks.progress:
        hooks.progress(phase, current, total, detail)


def _raise_if_cancelled(hooks: RuntimeHooks | None = None) -> None:
    if hooks and hooks.is_cancelled and hooks.is_cancelled():
        raise OperationCancelled()


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(config_path) if config_path is not None else app_path("config.yaml")
    if not path.exists():
        _log("[yellow]未找到 config.yaml，已按默认配置继续。[/yellow]")
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
    except OSError as exc:
        raise click.ClickException(f"无法读取 config.yaml：{exc}") from exc
    except yaml.YAMLError as exc:
        raise click.ClickException(f"config.yaml 格式错误，请先修正 YAML 语法：{exc}") from exc
    if not isinstance(loaded, dict):
        _log("[yellow]config.yaml 顶层结构无效，已按空配置处理。[/yellow]")
        return {}
    return loaded


def get_cache() -> CacheDB:
    return CacheDB(app_path("cache.db"))


def get_batch_size(config: dict[str, Any]) -> int:
    raw = config.get("batch_size", 30)
    try:
        raw_value = int(raw or 30)
    except (TypeError, ValueError):
        _log("[yellow]batch_size 配置无效，已使用默认值 30。[/yellow]")
        raw_value = 30
    if raw_value < 10 or raw_value > 100:
        _log("[yellow]batch_size 超出建议范围，已自动调整到 10-100 之间。[/yellow]")
    return min(100, max(10, raw_value))


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


def _normalize_file_id(value: str) -> str:
    return value.strip().lower()


def get_summary_workers(config: dict[str, Any]) -> int:
    raw = config.get("summary_workers", 4)
    try:
        value = int(raw or 4)
    except (TypeError, ValueError):
        _log("[yellow]summary_workers 配置无效，已使用默认值 4。[/yellow]")
        value = 4
    return min(8, max(1, value))


def get_classification_workers(config: dict[str, Any]) -> int:
    raw = config.get("classification_workers", 2)
    try:
        value = int(raw or 2)
    except (TypeError, ValueError):
        _log("[yellow]classification_workers 配置无效，已使用默认值 2。[/yellow]")
        value = 2
    return min(4, max(1, value))


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
        if force:
            return cache.filter_paths_with_category(deduped)
        return cache.filter_summary_candidate_paths(deduped)

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
            and str(record.get("summary_status") or "").strip() not in {"needs_ocr", "needs_conversion", "no_text", "unsupported_type"}
        ]

    if summarize_all:
        records = [record for record in cache.list_all() if record.get("category")]
        if force:
            return [record["file_path"] for record in records]
        return [
            record["file_path"]
            for record in records
            if not str(record.get("summary") or "").strip()
            and str(record.get("summary_status") or "").strip() not in {"needs_ocr", "needs_conversion", "no_text", "unsupported_type"}
        ]

    return []


def _scan_and_prepare(
    cache: CacheDB,
    config: dict[str, Any],
    force: bool = False,
    hooks: RuntimeHooks | None = None,
) -> dict[str, Any] | None:
    """Scan filesystem and diff against cache. Returns None if no files found."""
    _raise_if_cancelled(hooks)
    _log("[cyan]正在扫描目录，请稍候...[/cyan]", hooks)
    _progress("scan", 0, 0, "正在扫描目录...", hooks)
    scan_config = ensure_dict(config.get("scan", {}))
    default_paths_config = ensure_dict(scan_config.get("default_paths", {}))
    scanned_files = scan_files(
        paths=ensure_str_list(scan_config.get("paths", [])),
        exclude_patterns=ensure_str_list(scan_config.get("exclude_patterns", [])),
        default_path_flags={
            "desktop": bool(default_paths_config.get("desktop", True)),
            "documents": bool(default_paths_config.get("documents", True)),
            "downloads": bool(default_paths_config.get("downloads", True)),
        },
    )
    if not scanned_files:
        _log("[yellow]没有扫描到符合条件的文件。[/yellow]", hooks)
        return None

    _raise_if_cancelled(hooks)
    _log(f"[cyan]扫描完成，发现 {len(scanned_files)} 个符合条件的文件，正在检查缓存...[/cyan]", hooks)
    _progress("scan", len(scanned_files), len(scanned_files), "扫描完成，正在检查缓存...", hooks)
    existing_records = cache.index_scan_state_by_path()
    scanned_paths = {item.file_path for item in scanned_files}
    removed = cache.delete_absent_files(scanned_paths)
    if removed:
        _log(f"[cyan]已清理 {removed} 条失效缓存记录（源文件不存在）。[/cyan]", hooks)

    unchanged_paths: set[str] = set()
    upsert_rows: list[tuple[str, int, float]] = []
    changed_paths: list[str] = []
    changed_path_set: set[str] = set()
    summary_candidates: list[str] = []
    summary_candidate_seen: set[str] = set()
    for item in scanned_files:
        _raise_if_cancelled(hooks)
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

    pending_path_set = {item["file_path"] for item in pending}
    return {
        "scanned_files": scanned_files,
        "changed_paths": changed_paths,
        "pending": pending,
        "summary_candidates": summary_candidates,
        "summary_candidate_set": summary_candidate_seen,
        "pending_path_set": pending_path_set,
    }


def _process_classify_batch_results(
    batch: list[dict[str, Any]],
    batch_results: list[dict[str, Any]],
) -> tuple[list[tuple[str, str, str | None]], set[str], int]:
    """Process classification batch results. Returns (update_rows, covered_paths, missing_count)."""
    batch_path_map: dict[str, str] = {}
    batch_id_map: dict[str, str] = {}
    for item in batch:
        batch_file_path = str(item.get("file_path") or "").strip()
        normalized = _normalize_file_path(batch_file_path)
        if normalized:
            batch_path_map.setdefault(normalized, batch_file_path)
        file_id = _normalize_file_id(str(item.get("file_id") or ""))
        if file_id:
            batch_id_map.setdefault(file_id, batch_file_path)

    update_rows: list[tuple[str, str, str | None]] = []
    covered_paths: set[str] = set()
    for item in batch_results:
        file_id = _normalize_file_id(str(item.get("file_id") or ""))
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

    missing = len(set(batch_id_map.values()) - covered_paths)
    return update_rows, covered_paths, missing


def _run_classify_loop(
    cache: CacheDB,
    config: dict[str, Any],
    pending: list[dict[str, Any]],
    hooks: RuntimeHooks | None = None,
    on_batch_done: Callable[[list[str]], None] | None = None,
) -> int:
    """Run classification loop. Returns total classified count. Calls on_batch_done with classified paths after each batch."""
    if not pending:
        return 0

    try:
        client = LLMClient(config)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    batch_size = get_batch_size(config)
    classification_workers = min(get_classification_workers(config), max(1, (len(pending) + batch_size - 1) // batch_size))
    _log(
        f"[cyan]缓存检查完成，开始分类，共 {len(pending)} 个文件待处理（并发 {classification_workers}）。[/cyan]",
        hooks,
    )
    _progress("classify", 0, len(pending), "正在调用模型进行分类...", hooks)

    classified = 0
    failed_batches = 0
    for done, total, batch, batch_results, batch_error in classify_files_iter(
        client,
        pending,
        batch_size=batch_size,
        workers=classification_workers,
        is_cancelled=hooks.is_cancelled if hooks else None,
    ):
        _raise_if_cancelled(hooks)
        if batch_error:
            failed_batches += 1
            _log(
                f"[yellow]警告：批次分类失败，已跳过该批次（{done}/{total}）：{batch_error}[/yellow]",
                hooks,
            )

        update_rows, covered_paths, missing = _process_classify_batch_results(batch, batch_results)
        classified += cache.update_categories_bulk(update_rows)

        if on_batch_done and covered_paths:
            on_batch_done(list(covered_paths))

        if missing:
            _log(f"[yellow]当前批次有 {missing} 个文件未返回分类结果，将在后续扫描重试。[/yellow]", hooks)
        detail = f"进度：{done}/{total} - 已分类 {classified} 个文件"
        _log(detail, hooks)
        _progress("classify", done, total, detail, hooks)

    if failed_batches:
        _log(
            f"[yellow]分类阶段有 {failed_batches} 个批次失败，其他批次已继续处理。可稍后执行 sync/scan 重试。[/yellow]",
            hooks,
        )
    return classified


def _scan_and_classify(
    cache: CacheDB,
    config: dict[str, Any],
    force: bool = False,
    hooks: RuntimeHooks | None = None,
) -> dict[str, Any]:
    prep = _scan_and_prepare(cache, config, force=force, hooks=hooks)
    if prep is None:
        return {
            "scanned_files": [],
            "changed_paths": [],
            "summary_targets": [],
            "classified": 0,
        }

    scanned_files = prep["scanned_files"]
    pending = prep["pending"]

    classified = 0
    if not pending:
        _log(f"[green]扫描完成，共 {len(scanned_files)} 个文件，未发现需要重新分类的文件。[/green]", hooks)
    else:
        classified = _run_classify_loop(cache, config, pending, hooks=hooks)

    summary_targets = _select_summary_targets(cache, candidate_paths=prep["summary_candidates"])
    return {
        "scanned_files": scanned_files,
        "changed_paths": prep["changed_paths"],
        "summary_targets": summary_targets,
        "classified": classified,
    }


def _summarize_file(
    config: dict[str, Any],
    file_path: str,
    client_local: threading.local,
    hooks: RuntimeHooks | None = None,
) -> tuple[bool, str, str | None]:
    _raise_if_cancelled(hooks)
    path = Path(file_path)
    if not path.exists():
        return False, f"文件不存在：{file_path}", "missing"
    try:
        extracted = extract_text(file_path)
        if not extracted.strip():
            return False, f"无法提取有效文本：{file_path}", "no_text"
        client = getattr(client_local, "client", None)
        if client is None:
            client = LLMClient(config)
            client_local.client = client
        _raise_if_cancelled(hooks)
        summary = summarize_text(client, file_path, extracted)
        return True, summary, None
    except UnsupportedSummaryError as exc:
        return False, str(exc), exc.code
    except OperationCancelled:
        raise
    except Exception as exc:
        logging.exception("摘要生成失败: %s", file_path)
        return False, f"摘要失败：{exc}", "error"


def _run_summary_jobs(
    cache: CacheDB,
    config: dict[str, Any],
    targets: list[str],
    hooks: RuntimeHooks | None = None,
) -> tuple[int, int]:
    if not targets:
        _log("[yellow]没有找到需要生成摘要的文件。[/yellow]", hooks)
        return 0, 0

    workers = min(get_summary_workers(config), len(targets))
    _log(f"[cyan]已找到 {len(targets)} 个目标文件，开始生成摘要（并发 {workers}）...[/cyan]", hooks)
    _progress("summarize", 0, len(targets), "正在生成摘要...", hooks)
    success = 0
    completed = 0
    pending_updates: list[tuple[str, str]] = []
    pending_failures: list[tuple[str, str, str]] = []
    flush_size = 20
    client_local = threading.local()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(_summarize_file, config, target, client_local, hooks): target
            for target in targets
        }
        try:
            for future in as_completed(future_map):
                _raise_if_cancelled(hooks)
                target = future_map[future]
                completed += 1
                try:
                    ok, message, status = future.result()
                except OperationCancelled:
                    raise
                except Exception as exc:
                    logging.exception("摘要任务线程异常: %s", target)
                    ok, message, status = False, f"摘要失败：{exc}", "error"
                detail = f"进度：{completed}/{len(targets)} - 已完成 {Path(target).name}"
                _log(f"[cyan]{detail}[/cyan]", hooks)
                _progress("summarize", completed, len(targets), detail, hooks)
                if ok:
                    success += 1
                    pending_updates.append((target, message))
                    if len(pending_updates) >= flush_size:
                        cache.update_summaries_bulk(pending_updates)
                        pending_updates.clear()
                else:
                    logging.error("摘要失败: %s | %s", target, message)
                    pending_failures.append((target, status or "error", message))
                    if len(pending_failures) >= flush_size:
                        cache.update_summary_failures_bulk(pending_failures)
                        pending_failures.clear()
                _log(message, hooks)
        except OperationCancelled:
            executor.shutdown(wait=False, cancel_futures=True)
            raise
    if pending_updates:
        cache.update_summaries_bulk(pending_updates)
    if pending_failures:
        cache.update_summary_failures_bulk(pending_failures)
    return success, len(targets)


def run_scan(force: bool = False, hooks: RuntimeHooks | None = None) -> None:
    config = load_config()
    cache = get_cache()
    try:
        result = _scan_and_classify(cache, config, force=force, hooks=hooks)
        if not result["scanned_files"]:
            return
        _raise_if_cancelled(hooks)
        _log("[cyan]正在刷新报告...[/cyan]", hooks)
        _progress("report", 0, 0, "正在生成报告...", hooks)
        generate_reports(
            cache.list_all(),
            html_path=str(app_path("report.html")),
            json_path=str(app_path("report.json")),
        )
        classified = result["classified"]
        _log(f"[green]扫描完成。总扫描 {len(result['scanned_files'])} 个文件，本次分类 {classified} 个文件。[/green]", hooks)
        _log("[green]已生成 report.html 和 report.json。[/green]", hooks)
        _progress("done", 1, 1, "任务执行完成。", hooks)
    finally:
        cache.close()


def run_summarize(
    category_name: str | None = None,
    file_path: str | None = None,
    summarize_all: bool = False,
    force: bool = False,
    hooks: RuntimeHooks | None = None,
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
        success, total = _run_summary_jobs(cache, config, targets, hooks=hooks)
        if not total:
            return
        _raise_if_cancelled(hooks)
        _log("[cyan]摘要生成完成，正在刷新报告...[/cyan]", hooks)
        _progress("report", 0, 0, "正在生成报告...", hooks)
        generate_reports(
            cache.list_all(),
            html_path=str(app_path("report.html")),
            json_path=str(app_path("report.json")),
        )
        _log(f"[green]摘要任务完成，成功 {success}/{total}。[/green]", hooks)
        _progress("done", 1, 1, "任务执行完成。", hooks)
    finally:
        cache.close()


def run_sync(
    force_scan: bool = False,
    force_summary: bool = False,
    hooks: RuntimeHooks | None = None,
) -> None:
    config = load_config()
    cache = get_cache()
    try:
        prep = _scan_and_prepare(cache, config, force=force_scan, hooks=hooks)
        if prep is None:
            return

        scanned_files = prep["scanned_files"]
        pending = prep["pending"]
        summary_candidates = prep["summary_candidates"]
        summary_candidate_set = prep["summary_candidate_set"]
        pending_path_set = prep["pending_path_set"]

        # --- Pipeline: summary executor runs in background during classification ---
        summary_workers = get_summary_workers(config)
        client_local = threading.local()
        summary_futures: dict[Any, str] = {}
        summary_success = 0
        summary_completed = 0
        pending_updates: list[tuple[str, str]] = []
        pending_failures: list[tuple[str, str, str]] = []
        flush_size = 20

        summary_executor = ThreadPoolExecutor(max_workers=summary_workers)
        try:
            # Submit summary jobs for files that already have categories (unchanged files)
            immediate_candidates = [p for p in summary_candidates if p not in pending_path_set]
            if immediate_candidates:
                if force_summary:
                    immediate_targets = _select_summary_targets(cache, candidate_paths=immediate_candidates, force=True)
                else:
                    immediate_targets = _select_summary_targets(cache, candidate_paths=immediate_candidates)
                for target in immediate_targets:
                    future = summary_executor.submit(_summarize_file, config, target, client_local, hooks)
                    summary_futures[future] = target

            # Classification loop — submit summary jobs as each batch completes
            def _on_batch_classified(classified_paths: list[str]) -> None:
                batch_candidates = [p for p in classified_paths if p in summary_candidate_set]
                if not batch_candidates:
                    return
                if force_summary:
                    batch_targets = _select_summary_targets(cache, candidate_paths=batch_candidates, force=True)
                else:
                    batch_targets = _select_summary_targets(cache, candidate_paths=batch_candidates)
                for target in batch_targets:
                    future = summary_executor.submit(_summarize_file, config, target, client_local, hooks)
                    summary_futures[future] = target

            classified = 0
            if not pending:
                _log(f"[green]扫描完成，共 {len(scanned_files)} 个文件，未发现需要重新分类的文件。[/green]", hooks)
            else:
                classified = _run_classify_loop(
                    cache, config, pending, hooks=hooks,
                    on_batch_done=_on_batch_classified,
                )

            # If force_summary, also submit any remaining categorized files not yet queued
            if force_summary:
                already_submitted = set(summary_futures.values())
                all_targets = _select_summary_targets(cache, summarize_all=True, force=True)
                for target in all_targets:
                    if target not in already_submitted:
                        future = summary_executor.submit(_summarize_file, config, target, client_local, hooks)
                        summary_futures[future] = target

            # Collect summary results
            summary_total = len(summary_futures)
            if summary_futures:
                _log(f"[cyan]等待摘要完成，共 {summary_total} 个文件...[/cyan]", hooks)
                _progress("summarize", 0, summary_total, "正在生成摘要...", hooks)
                for future in as_completed(summary_futures):
                    _raise_if_cancelled(hooks)
                    target = summary_futures[future]
                    summary_completed += 1
                    try:
                        ok, message, status = future.result()
                    except OperationCancelled:
                        raise
                    except Exception as exc:
                        logging.exception("摘要任务线程异常: %s", target)
                        ok, message, status = False, f"摘要失败：{exc}", "error"
                    detail = f"进度：{summary_completed}/{summary_total} - 已完成 {Path(target).name}"
                    _log(f"[cyan]{detail}[/cyan]", hooks)
                    _progress("summarize", summary_completed, summary_total, detail, hooks)
                    if ok:
                        summary_success += 1
                        pending_updates.append((target, message))
                        if len(pending_updates) >= flush_size:
                            cache.update_summaries_bulk(pending_updates)
                            pending_updates.clear()
                    else:
                        logging.error("摘要失败: %s | %s", target, message)
                        pending_failures.append((target, status or "error", message))
                        if len(pending_failures) >= flush_size:
                            cache.update_summary_failures_bulk(pending_failures)
                            pending_failures.clear()
                    _log(message, hooks)
            elif not pending:
                _log("[yellow]没有找到需要生成摘要的文件。[/yellow]", hooks)

            if pending_updates:
                cache.update_summaries_bulk(pending_updates)
            if pending_failures:
                cache.update_summary_failures_bulk(pending_failures)

        except OperationCancelled:
            summary_executor.shutdown(wait=False, cancel_futures=True)
            raise
        finally:
            summary_executor.shutdown(wait=False)

        _raise_if_cancelled(hooks)
        _log("[cyan]正在刷新报告...[/cyan]", hooks)
        _progress("report", 0, 0, "正在生成报告...", hooks)
        generate_reports(
            cache.list_all(),
            html_path=str(app_path("report.html")),
            json_path=str(app_path("report.json")),
        )
        _log(
            f"[green]同步完成。总扫描 {len(scanned_files)} 个文件，本次分类 {classified} 个文件，摘要成功 {summary_success}/{summary_total}。[/green]",
            hooks,
        )
        _log("[green]已生成 report.html 和 report.json。[/green]", hooks)
        _progress("done", 1, 1, "任务执行完成。", hooks)
    finally:
        cache.close()


def run_report(hooks: RuntimeHooks | None = None) -> None:
    cache = get_cache()
    try:
        _raise_if_cancelled(hooks)
        _log("[cyan]正在生成报告...[/cyan]", hooks)
        _progress("report", 0, 0, "正在生成报告...", hooks)
        _raise_if_cancelled(hooks)
        generate_reports(
            cache.list_all(),
            html_path=str(app_path("report.html")),
            json_path=str(app_path("report.json")),
        )
        _log("[green]报告已生成：report.html, report.json[/green]", hooks)
        _progress("done", 1, 1, "任务执行完成。", hooks)
    finally:
        cache.close()


def run_stats(hooks: RuntimeHooks | None = None) -> None:
    cache = get_cache()
    try:
        _raise_if_cancelled(hooks)
        _log("[cyan]正在读取缓存统计...[/cyan]", hooks)
        _progress("stats", 0, 0, "正在读取缓存统计...", hooks)
        _raise_if_cancelled(hooks)
        stats_data = cache.stats()
        _log(f"缓存文件总数：{stats_data['total_files']}", hooks)
        _log(f"已分类文件数：{stats_data['categorized_files']}", hooks)
        _log(f"已有摘要文件数：{stats_data['summarized_files']}", hooks)
        _log("分类统计：", hooks)
        for item in stats_data["categories"]:
            _log(f"- {item['category']}: {item['count']}", hooks)
        _progress("done", 1, 1, "任务执行完成。", hooks)
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
