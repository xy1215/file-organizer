from __future__ import annotations

import pytest

import main
from cache import CacheDB
from fakes import FakeLLMClient


NO_DEFAULT_DIRS = {"desktop": False, "documents": False, "downloads": False}


@pytest.fixture
def env(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    config = {
        "llm": {"api_key": "test"},
        "scan": {"default_paths": NO_DEFAULT_DIRS, "paths": [str(data_dir)]},
        "batch_size": 10,
    }
    monkeypatch.setattr(main, "load_config", lambda config_path=None: config)
    monkeypatch.setattr(main, "app_path", lambda *parts: app_dir.joinpath(*parts))
    monkeypatch.setattr(main, "LLMClient", FakeLLMClient)
    return {"app_dir": app_dir, "data_dir": data_dir, "config": config, "tmp": tmp_path}


def _cache(env) -> CacheDB:
    return CacheDB(env["app_dir"] / "cache.db")


def test_sync_classifies_and_summarises(env):
    for index in range(3):
        (env["data_dir"] / f"note-{index}.txt").write_text(f"第 {index} 份笔记内容", encoding="utf-8")

    main.run_sync(hooks=main.RuntimeHooks(log=lambda message: None))

    cache = _cache(env)
    try:
        rows = cache.list_all()
    finally:
        cache.close()
    assert len(rows) == 3
    assert all(row["category"] == "工作/报告与方案" for row in rows)
    assert all(row["summary_status"] == "success" and "测试摘要" in row["summary"] for row in rows)
    assert (env["app_dir"] / "report.html").exists()
    assert (env["app_dir"] / "report.json").exists()


def test_sync_is_incremental(env, monkeypatch):
    (env["data_dir"] / "a.txt").write_text("内容", encoding="utf-8")
    main.run_sync(hooks=main.RuntimeHooks(log=lambda message: None))

    calls = []

    class CountingClient(FakeLLMClient):
        def complete_json(self, prompt, model=None):
            calls.append(model)
            return super().complete_json(prompt, model)

    monkeypatch.setattr(main, "LLMClient", CountingClient)
    main.run_sync(hooks=main.RuntimeHooks(log=lambda message: None))
    assert calls == []


def test_unreachable_root_keeps_cached_results(env):
    offline_root = env["tmp"] / "offline-share"
    env["config"]["scan"]["paths"].append(str(offline_root))
    (env["data_dir"] / "present.txt").write_text("内容", encoding="utf-8")

    offline_file = str(offline_root / "合同.pdf")
    deleted_file = str(env["data_dir"] / "deleted.pdf")
    cache = _cache(env)
    try:
        for path in (offline_file, deleted_file):
            cache.upsert_file(path, 10, 1.0, category="工作/合同与协议", summary="旧摘要")
        prep = main._scan_and_prepare(cache, env["config"], hooks=main.RuntimeHooks(log=lambda message: None))
        assert prep is not None
        assert cache.get(offline_file) is not None, "records under an offline root must survive"
        assert cache.get(offline_file).summary == "旧摘要"
        assert cache.get(deleted_file) is None, "records under a reachable root whose file is gone are removed"
    finally:
        cache.close()


def test_collect_summary_results_flushes_on_cancel(env):
    from concurrent.futures import Future

    from common import OperationCancelled

    cache = _cache(env)
    try:
        paths = [str(env["data_dir"] / f"{index}.txt") for index in range(3)]
        cache.upsert_files_bulk([(path, 1, 1.0) for path in paths])
        done = Future()
        done.set_result((True, "概述：好", None))
        failed = Future()
        failed.set_result((False, "无法提取", "no_text"))
        never = Future()
        cancelled = {"value": False}

        def log(message):
            # Cancel as soon as the first result has been processed.
            if message.startswith("[cyan]进度"):
                cancelled["value"] = True

        hooks = main.RuntimeHooks(log=log, is_cancelled=lambda: cancelled["value"])
        with pytest.raises(OperationCancelled):
            main._collect_summary_results(cache, {done: paths[0], failed: paths[1], never: paths[2]}, hooks)
        # Both finished futures were drained before the cancel check; both must be persisted.
        assert cache.get(paths[0]).summary == "概述：好"
        assert cache.get(paths[1]).summary_status == "no_text"
        assert cache.get(paths[2]).summary_status is None
    finally:
        cache.close()


def test_force_rescan_keeps_summaries_of_unchanged_files(env):
    note = env["data_dir"] / "note.txt"
    note.write_text("内容", encoding="utf-8")
    edited = env["data_dir"] / "edited.txt"
    edited.write_text("旧内容", encoding="utf-8")
    main.run_sync(hooks=main.RuntimeHooks(log=lambda message: None))

    edited.write_text("新的内容更长", encoding="utf-8")
    main.run_scan(force=True, hooks=main.RuntimeHooks(log=lambda message: None))

    cache = _cache(env)
    try:
        assert cache.get(str(note.resolve())).summary, "re-classifying must not throw away a still-valid summary"
        assert cache.get(str(edited.resolve())).summary is None, "a file whose content changed needs a new summary"
        assert all(row["category"] for row in cache.list_all())
    finally:
        cache.close()


def test_force_rescan_retries_failed_summaries(env):
    doc = env["data_dir"] / "old.txt"
    doc.write_text("内容", encoding="utf-8")
    main.run_scan(hooks=main.RuntimeHooks(log=lambda message: None))
    cache = _cache(env)
    try:
        cache.update_summary_failure(str(doc.resolve()), "needs_conversion", "需要 LibreOffice")
    finally:
        cache.close()

    main.run_scan(force=True, hooks=main.RuntimeHooks(log=lambda message: None))
    main.run_sync(hooks=main.RuntimeHooks(log=lambda message: None))

    cache = _cache(env)
    try:
        record = cache.get(str(doc.resolve()))
    finally:
        cache.close()
    assert record.summary_status == "success" and record.summary


def test_offline_root_keeps_records_even_when_cached_under_another_path_form(env):
    # A mapped drive Z:\\docs is cached under its UNC form while online; when offline the root
    # cannot be resolved, so prefix matching against the root would miss these records.
    offline_root = env["tmp"] / "Z-drive"
    env["config"]["scan"]["paths"].append(str(offline_root))
    (env["data_dir"] / "present.txt").write_text("内容", encoding="utf-8")
    unc_style = str(env["tmp"] / "server" / "share" / "合同.pdf")
    cache = _cache(env)
    try:
        cache.upsert_file(unc_style, 10, 1.0, category="工作/合同与协议", summary="旧摘要")
        main._scan_and_prepare(cache, env["config"], hooks=main.RuntimeHooks(log=lambda message: None))
        assert cache.get(unc_style) is not None
    finally:
        cache.close()


def test_records_of_removed_roots_are_purged_when_all_roots_are_readable(env):
    (env["data_dir"] / "present.txt").write_text("内容", encoding="utf-8")
    stale = str(env["tmp"] / "no-longer-scanned" / "a.pdf")
    cache = _cache(env)
    try:
        cache.upsert_file(stale, 10, 1.0, category="其他")
        main._scan_and_prepare(cache, env["config"], hooks=main.RuntimeHooks(log=lambda message: None))
        assert cache.get(stale) is None
    finally:
        cache.close()
