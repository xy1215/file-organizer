from __future__ import annotations

import json
import threading
from typing import Any


class FakeLLMClient:
    """Stands in for classifier.LLMClient: classifies everything as one category, summarises everything."""

    def __init__(self, config: dict[str, Any] | None = None, *, category: str = "工作/报告与方案") -> None:
        self.model = "fake-classify"
        self.summary_model = "fake-summary"
        self.category = category
        self.prompts: list[str] = []
        self._lock = threading.Lock()

    def complete_json(self, prompt: str, model: str | None = None) -> dict[str, Any]:
        with self._lock:
            self.prompts.append(prompt)
        if model == self.summary_model:
            return {"summary": "测试摘要", "key_points": ["要点一"], "doc_type": "报告"}
        items = [
            json.loads(line)
            for line in prompt.splitlines()
            if line.startswith('{"file_id"')
        ]
        return {
            "classifications": [
                {"file_id": item["file_id"], "category": self.category, "brief": "测试"}
                for item in items
            ]
        }
