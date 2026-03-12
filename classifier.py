from __future__ import annotations

import json
import os
import time
from pathlib import Path
from collections.abc import Iterator
from typing import Any

import anthropic
from openai import OpenAI


DEFAULT_CATEGORIES = [
    "工作/报告与方案",
    "工作/演示文稿",
    "工作/表格与数据",
    "工作/合同与协议",
    "财务/发票与收据",
    "财务/税务申报",
    "财务/银行与账单",
    "学习/课程资料",
    "学习/论文与研究",
    "学习/笔记与作业",
    "学习/申请与文书",
    "媒体/照片",
    "媒体/截图",
    "媒体/音乐",
    "媒体/视频",
    "开发/源代码",
    "开发/配置文件",
    "开发/技术文档",
    "通讯/聊天记录",
    "通讯/邮件",
    "系统/安装程序",
    "系统/驱动与更新",
    "系统/备份与镜像",
    "个人/证件与证书",
    "个人/简历",
    "个人/电子书",
    "其他",
]


class LLMClient:
    def __init__(self, config: dict[str, Any]) -> None:
        llm_config = config.get("llm", {})
        self.provider = (llm_config.get("provider") or "openai").lower()
        self.api_key = self._resolve_api_key(llm_config)
        self.model = llm_config.get("model") or "gpt-4o-mini"
        self.summary_model = llm_config.get("summary_model") or self.model
        self.base_url = llm_config.get("base_url") or None
        if not self.api_key:
            raise ValueError("未配置 API Key，请在 config.yaml 或环境变量 LLM_API_KEY 中设置。")

        if self.provider == "openai":
            kwargs: dict[str, Any] = {"api_key": self.api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self.openai_client = OpenAI(**kwargs)
            self.anthropic_client = None
        elif self.provider == "anthropic":
            self.anthropic_client = anthropic.Anthropic(api_key=self.api_key)
            self.openai_client = None
        else:
            raise ValueError(f"不支持的 LLM provider: {self.provider}")

    def _resolve_api_key(self, llm_config: dict[str, Any]) -> str:
        configured_key = str(llm_config.get("api_key") or "").strip()
        if configured_key:
            return configured_key

        fallback_env_vars = ["LLM_API_KEY"]
        if self.provider == "openai":
            fallback_env_vars.append("OPENAI_API_KEY")
        elif self.provider == "anthropic":
            fallback_env_vars.append("ANTHROPIC_API_KEY")

        for env_name in fallback_env_vars:
            value = os.getenv(env_name, "").strip()
            if value:
                return value
        return ""

    def _retry(self, func):
        delays = [0, 1, 2, 4]
        last_error: Exception | None = None
        for index, delay in enumerate(delays, start=1):
            try:
                return func()
            except Exception as exc:
                last_error = exc
                if index == len(delays):
                    break
                if delay > 0:
                    time.sleep(delay)
        assert last_error is not None
        raise last_error

    def _extract_text_content(self, response_text: str) -> dict[str, Any]:
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            start = response_text.find("{")
            end = response_text.rfind("}")
            if start >= 0 and end > start:
                return json.loads(response_text[start : end + 1])
            raise

    def complete_json(self, prompt: str, model: str | None = None) -> dict[str, Any]:
        model_name = model or self.model

        def _call() -> dict[str, Any]:
            if self.provider == "openai":
                response = self.openai_client.responses.create(
                    model=model_name,
                    input=prompt,
                    text={"format": {"type": "json_object"}},
                )
                text = response.output_text
            else:
                response = self.anthropic_client.messages.create(
                    model=model_name,
                    max_tokens=4000,
                    temperature=0,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = "".join(
                    block.text for block in response.content if getattr(block, "type", "") == "text"
                )
            return self._extract_text_content(text)

        return self._retry(_call)


def chunk_list(items: list[Any], size: int) -> Iterator[list[Any]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def build_classification_prompt(batch: list[dict[str, Any]]) -> str:
    files_json = json.dumps(batch, ensure_ascii=False, indent=2)
    categories_json = json.dumps(DEFAULT_CATEGORIES, ensure_ascii=False)
    return f"""
你是一个本地文件整理助手。请根据文件名和所在路径，对文件进行分类，并给出简短描述。

要求：
1. 优先使用这些分类：{categories_json}
2. 分类采用"大类/子类"格式。如果文件明显不适合已有分类，可以创建新的中文分类，但必须遵循"大类/子类"格式。
3. 只根据文件名和路径推断，不要虚构文件内容。
4. confidence 取值范围 0 到 1。
5. brief 为一句话描述（不超过 20 个汉字），根据文件名和路径推测文件可能的内容或用途。
6. 输出必须是 JSON，格式如下：
{{
  "classifications": [
    {{
      "file_path": "完整路径",
      "category": "大类/子类",
      "confidence": 0.9,
      "brief": "简短描述"
    }}
  ]
}}

文件列表：
{files_json}
""".strip()


def classify_files(client: LLMClient, files: list[dict[str, Any]], batch_size: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for _, _, _, batch_results, _ in classify_files_iter(client, files, batch_size=batch_size):
        results.extend(batch_results)
    return results


def classify_files_iter(
    client: LLMClient, files: list[dict[str, Any]], batch_size: int
) -> Iterator[tuple[int, int, list[dict[str, Any]], list[dict[str, Any]], str | None]]:
    """Yield (completed_count, total_count, batch, batch_results, error_message) after each batch."""
    total = len(files)
    done = 0
    for batch in chunk_list(files, batch_size):
        error_message: str | None = None
        batch_results: list[dict[str, Any]] = []
        try:
            prompt = build_classification_prompt(batch)
            payload = client.complete_json(prompt, model=client.model)
            raw_results = payload.get("classifications", [])
            if isinstance(raw_results, list):
                batch_results = [item for item in raw_results if isinstance(item, dict)]
        except Exception as exc:
            error_message = str(exc) or exc.__class__.__name__
        done += len(batch)
        yield done, total, batch, batch_results, error_message


def build_summary_prompt(file_path: str, extracted_text: str) -> str:
    truncated = extracted_text[:6000]
    return f"""
你是一个文档摘要助手。请根据提供的文件路径和文本内容，输出 JSON。

要求：
1. summary 为一句话概述，不超过 50 个汉字。
2. key_points 为 3 到 5 条中文要点，每条简洁明确。
3. doc_type 只能从以下值中选择：合同、报告、表格、笔记、其他。
4. 如果文本信息不足，也要尽量给出保守判断。
5. 输出必须是 JSON，格式如下：
{{
  "summary": "一句话概述",
  "key_points": ["要点1", "要点2", "要点3"],
  "doc_type": "报告"
}}

文件路径：
{file_path}

文本内容：
{truncated}
""".strip()


def format_summary(payload: dict[str, Any]) -> str:
    summary = str(payload.get("summary", "")).strip()
    key_points = payload.get("key_points", [])
    doc_type = str(payload.get("doc_type", "其他")).strip() or "其他"
    lines = [f"概述：{summary}", f"类型：{doc_type}"]
    if isinstance(key_points, list):
        for point in key_points[:5]:
            lines.append(f"- {str(point).strip()}")
    return "\n".join(lines).strip()


def summarize_text(client: LLMClient, file_path: str, extracted_text: str) -> str:
    prompt = build_summary_prompt(file_path, extracted_text)
    payload = client.complete_json(prompt, model=client.summary_model)
    return format_summary(payload)


def build_file_stub(path: str) -> dict[str, Any]:
    file_path = Path(path)
    return {
        "file_path": str(file_path),
        "file_name": file_path.name,
        "parent_path": str(file_path.parent),
    }
