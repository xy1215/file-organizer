from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from common import IdleTimeout, OperationCancelled, ensure_dict, ensure_str_list, iter_completed


def test_ensure_helpers():
    assert ensure_dict({"a": 1}) == {"a": 1}
    assert ensure_dict(None) == {}
    assert ensure_str_list([" a ", "", None, 3]) == ["a", "None", "3"]
    assert ensure_str_list("abc") == []


def test_iter_completed_does_not_time_out_while_progressing():
    # Total runtime (~0.5s) exceeds idle_timeout (0.3s), but something finishes every 0.1s.
    with ThreadPoolExecutor(max_workers=1) as executor:
        futures = [executor.submit(time.sleep, 0.1) for _ in range(5)]
        finished = list(iter_completed(futures, idle_timeout=0.3, poll_interval=0.02))
    assert len(finished) == 5


def test_iter_completed_raises_idle_timeout_with_pending():
    release = threading.Event()
    with ThreadPoolExecutor(max_workers=2) as executor:
        quick = executor.submit(lambda: "ok")
        stuck = executor.submit(release.wait)
        seen = []
        with pytest.raises(IdleTimeout) as info:
            for future in iter_completed([quick, stuck], idle_timeout=0.2, poll_interval=0.02):
                seen.append(future)
        assert seen == [quick]
        assert info.value.pending == {stuck}
        assert isinstance(info.value, TimeoutError)
        release.set()


def test_iter_completed_honours_cancellation_without_waiting_for_futures():
    release = threading.Event()
    cancelled = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as executor:
        stuck = executor.submit(release.wait)
        threading.Timer(0.1, cancelled.set).start()
        start = time.monotonic()
        with pytest.raises(OperationCancelled):
            list(iter_completed([stuck], idle_timeout=60, is_cancelled=cancelled.is_set, poll_interval=0.02))
        assert time.monotonic() - start < 2
        release.set()
