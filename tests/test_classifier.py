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


class _FakeCompletions:
    def __init__(self, reject):
        self.reject = reject
        self.calls = []

    def create(self, **kwargs):
        from openai import BadRequestError
        from types import SimpleNamespace

        self.calls.append(kwargs)
        if self.reject(kwargs):
            # Built without its HTTP response so the test does not depend on the SDK's HTTP client package.
            error = BadRequestError.__new__(BadRequestError)
            Exception.__init__(error, "rejected")
            error.status_code = 400
            raise error
        message = SimpleNamespace(content='{"summary": "ok"}')
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _compat_client(reject):
    from types import SimpleNamespace
    from classifier import LLMClient

    client = LLMClient({"llm": {"api_key": "test", "base_url": "https://example.invalid/v1"}})
    completions = _FakeCompletions(reject)
    client.openai_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return client, completions


def test_compatible_endpoint_falls_back_and_remembers_level():
    client, completions = _compat_client(lambda kwargs: "response_format" in kwargs)
    assert client.complete_json("prompt") == {"summary": "ok"}
    assert len(completions.calls) == 2 and "response_format" not in completions.calls[1]
    completions.calls.clear()
    client.complete_json("prompt")
    assert len(completions.calls) == 1, "the working request shape is reused without another 400"


def test_compatible_endpoint_does_not_mask_real_bad_requests():
    from openai import BadRequestError

    client, completions = _compat_client(lambda kwargs: True)
    with pytest.raises(BadRequestError):
        client.complete_json("prompt")
    # One pass down the ladder, no retries of a permanent error.
    assert len(completions.calls) == 3
    assert client._compat_level == 0


def test_anthropic_provider_honours_base_url():
    from classifier import LLMClient

    client = LLMClient({"llm": {"provider": "anthropic", "api_key": "test", "base_url": "https://relay.example.invalid"}})
    assert str(client.anthropic_client.base_url).startswith("https://relay.example.invalid")
