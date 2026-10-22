from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, wait
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


class IdleTimeout(TimeoutError):
    """No future finished within the idle window; ``pending`` holds the unfinished ones."""

    def __init__(self, pending: set[Future]) -> None:
        super().__init__(f"{len(pending)} 个任务长时间无进展")
        self.pending = pending


def iter_completed(
    futures: Iterable[Future],
    idle_timeout: float,
    is_cancelled: Callable[[], bool] | None = None,
    poll_interval: float = 0.5,
) -> Iterator[Future]:
    """Yield futures as they finish.

    Unlike ``as_completed(timeout=...)``, the timeout only fires when *no* future
    finishes for ``idle_timeout`` seconds, so long but steadily progressing jobs
    are never cut off. Cancellation is checked every ``poll_interval`` seconds.
    """
    pending = set(futures)
    last_progress = time.monotonic()
    while pending:
        if is_cancelled and is_cancelled():
            raise OperationCancelled()
        done, pending = wait(pending, timeout=poll_interval, return_when=FIRST_COMPLETED)
        if done:
            last_progress = time.monotonic()
            yield from done
        elif time.monotonic() - last_progress >= idle_timeout:
            raise IdleTimeout(pending)
