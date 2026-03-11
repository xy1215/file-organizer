from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import click
import yaml
from rich.console import Console

from cache import CacheDB
from classifier import LLMClient, build_file_stub, classify_files, summarize_text
from report import generate_reports
from scanner import scan_files
from summarizer import UnsupportedSummaryError, extract_text


console = Console()
logging.basicConfig(
    filename="error.log",
    level=logging.ERROR,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def load_config(config_path: str = "config.yaml") -> dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        raise click.ClickException("未找到 config.yaml，请先检查项目目录。")
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def get_cache() -> CacheDB:
    return CacheDB("cache.db")


def get_batch_size(config: dict[str, Any]) -> int:
    raw_value = int(config.get("batch_size", 80) or 80)
    if raw_value < 80 or raw_value > 100:
        console.print("[yellow]batch_size 超出建议范围，已自动调整到 80-100 之间。[/yellow]")
    return min(100, max(80, raw_value))


@click.group()
def cli() -> None:
    """本地文件管理分类与摘要工具"""


@cli.command()
@click.option("--force", is_flag=True, help="强制重新处理所有文件")
def scan(force: bool) -> None:
    """扫描并分类文件"""
    config = load_config()
    cache = get_cache()
    try:
        scanned_files = scan_files(
            paths=config.get("scan", {}).get("paths", []),
            exclude_patterns=config.get("scan", {}).get("exclude_patterns", []),
        )
        if not scanned_files:
            console.print("[yellow]没有扫描到符合条件的文件。[/yellow]")
            return

        pending: list[dict[str, Any]] = []
        for item in scanned_files:
            unchanged = cache.is_unchanged(item.file_path, item.size, item.modified_time)
            if force or not unchanged:
                pending.append(build_file_stub(item.file_path))
            cache.upsert_file(
                file_path=item.file_path,
                file_size=item.size,
                modified_time=item.modified_time,
            )

        if force:
            pending = [build_file_stub(item.file_path) for item in scanned_files]

        if not pending:
            console.print(f"[green]扫描完成，共 {len(scanned_files)} 个文件，未发现需要重新分类的文件。[/green]")
            generate_reports(cache.list_all())
            console.print("[green]已刷新 report.html 和 report.json。[/green]")
            return

        try:
            client = LLMClient(config)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        batch_size = get_batch_size(config)
        console.print(f"[cyan]开始分类，共 {len(pending)} 个文件待处理。[/cyan]")
        results = classify_files(client, pending, batch_size=batch_size)

        classified = 0
        for index, item in enumerate(results, start=1):
            file_path = item.get("file_path")
            category = item.get("category")
            if not file_path or not category:
                continue
            cache.update_category(str(file_path), str(category))
            classified += 1
            console.print(f"进度：{index}/{len(results)} - {Path(str(file_path)).name} -> {category}")

        generate_reports(cache.list_all())
        console.print(
            f"[green]扫描完成。总扫描 {len(scanned_files)} 个文件，本次分类 {classified} 个文件。[/green]"
        )
        console.print("[green]已生成 report.html 和 report.json。[/green]")
    finally:
        cache.close()


def _summarize_file(cache: CacheDB, client: LLMClient, file_path: str) -> tuple[bool, str]:
    record = cache.get(file_path)
    path = Path(file_path)
    if not path.exists():
        return False, f"文件不存在：{file_path}"
    if not record:
        stat = path.stat()
        cache.upsert_file(str(path), stat.st_size, stat.st_mtime)
    try:
        extracted = extract_text(file_path)
        if not extracted.strip():
            return False, f"无法提取有效文本：{file_path}"
        summary = summarize_text(client, file_path, extracted)
        cache.update_summary(file_path, summary)
        return True, summary
    except UnsupportedSummaryError as exc:
        return False, str(exc)
    except Exception as exc:
        logging.exception("摘要生成失败: %s", file_path)
        return False, f"摘要失败：{exc}"


@cli.command()
@click.option("--category", "category_name", type=str, help="为指定分类生成摘要")
@click.option("--file", "file_path", type=str, help="为单个文件生成摘要")
@click.option("--all", "summarize_all", is_flag=True, help="为所有已分类文件生成摘要")
def summarize(category_name: str | None, file_path: str | None, summarize_all: bool) -> None:
    """生成摘要"""
    selected = sum(bool(value) for value in [category_name, file_path, summarize_all])
    if selected != 1:
        raise click.ClickException("请在 --category、--file、--all 中且仅选择一个。")

    config = load_config()
    cache = get_cache()
    try:
        try:
            client = LLMClient(config)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        targets: list[str] = []
        if file_path:
            targets = [str(Path(file_path).expanduser().resolve())]
        elif category_name:
            targets = [record["file_path"] for record in cache.list_by_category(category_name)]
        elif summarize_all:
            targets = [record["file_path"] for record in cache.list_all() if record.get("category")]

        if not targets:
            console.print("[yellow]没有找到需要生成摘要的文件。[/yellow]")
            return

        success = 0
        for index, target in enumerate(targets, start=1):
            console.print(f"[cyan]进度：{index}/{len(targets)} - 正在处理 {Path(target).name}[/cyan]")
            ok, message = _summarize_file(cache, client, target)
            if ok:
                success += 1
            else:
                logging.error("摘要失败: %s | %s", target, message)
            console.print(message)

        generate_reports(cache.list_all())
        console.print(f"[green]摘要任务完成，成功 {success}/{len(targets)}。[/green]")
    finally:
        cache.close()


@cli.command()
def report() -> None:
    """生成或刷新报告"""
    cache = get_cache()
    try:
        generate_reports(cache.list_all())
        console.print("[green]报告已生成：report.html, report.json[/green]")
    finally:
        cache.close()


@cli.command()
def stats() -> None:
    """查看缓存统计"""
    cache = get_cache()
    try:
        stats_data = cache.stats()
        console.print(f"缓存文件总数：{stats_data['total_files']}")
        console.print(f"已分类文件数：{stats_data['categorized_files']}")
        console.print(f"已有摘要文件数：{stats_data['summarized_files']}")
        console.print("分类统计：")
        for item in stats_data["categories"]:
            console.print(f"- {item['category']}: {item['count']}")
    finally:
        cache.close()


@cli.command()
def gui() -> None:
    """启动图形界面"""
    from gui import run_gui

    raise SystemExit(run_gui())


if __name__ == "__main__":
    cli()
