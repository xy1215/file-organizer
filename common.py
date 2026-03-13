from __future__ import annotations

from typing import Any

import click


def ensure_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def ensure_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


class OperationCancelled(click.ClickException):
    def __init__(self) -> None:
        super().__init__("任务已取消。")
