from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from classifier import _display_dir, build_classification_prompt, build_file_stub, classify_files_iter
from fakes import FakeLLMClient


def test_display_dir_hides_home(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert _display_dir(str(tmp_path)) == "~"
    assert _display_dir(str(tmp_path / "Documents" / "工作")) == os.path.join("~", "Documents", "工作")
    outside = str(tmp_path.parent / "elsewhere")
    assert _display_dir(outside) == outside
    # A sibling directory sharing the home prefix is not inside home.
    sibling = str(tmp_path) + "-other"
    assert _display_dir(sibling) == sibling


def test_prompt_is_compact_and_omits_home(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    stub = build_file_stub(str(tmp_path / "Documents" / "2024年度报告.docx"))
    prompt = build_classification_prompt([stub])
    assert str(tmp_path) not in prompt
    line = next(line for line in prompt.splitlines() if line.startswith('{"file_id"'))
    assert json.loads(line) == {
        "file_id": stub["file_id"],
        "name": "2024年度报告.docx",
        "dir": os.path.join("~", "Documents"),
    }


@pytest.mark.parametrize("workers", [1, 3])
def test_classify_files_iter_covers_every_file(workers):
    files = [build_file_stub(f"/data/file-{index}.pdf") for index in range(25)]
    results = list(classify_files_iter(FakeLLMClient(), files, batch_size=10, workers=workers))
    assert [len(batch) for _, _, batch, _, _ in results] and sum(len(b) for _, _, b, _, _ in results) == 25
    assert results[-1][0] == 25 and all(total == 25 for _, total, _, _, _ in results)
    returned_ids = {item["file_id"] for _, _, _, batch_results, _ in results for item in batch_results}
    assert returned_ids == {item["file_id"] for item in files}
    assert all(error is None for *_, error in results)


def test_classify_files_iter_splits_batch_on_bad_json():
    class FlakyJson(FakeLLMClient):
        def complete_json(self, prompt, model=None):
            if prompt.count('{"file_id"') > 2:
                raise json.JSONDecodeError("bad", "", 0)
            return super().complete_json(prompt, model)

    files = [build_file_stub(f"/data/{index}.txt") for index in range(8)]
    ((done, total, batch, batch_results, error),) = list(
        classify_files_iter(FlakyJson(), files, batch_size=8, workers=1)
    )
    assert error is None
    assert len(batch_results) == 8


def test_classify_files_iter_reports_errors_per_batch():
    class Broken(FakeLLMClient):
        def complete_json(self, prompt, model=None):
            raise RuntimeError("boom")

    files = [build_file_stub(f"/data/{index}.txt") for index in range(4)]
    results = list(classify_files_iter(Broken(), files, batch_size=2, workers=2))
    assert len(results) == 2
    assert all(error == "boom" and batch_results == [] for *_, batch_results, error in results)
