"""Daemon-thread CPU/RAM sampler for Celery task resource accounting."""
from __future__ import annotations

import os
import threading
from collections import deque
from typing import Literal

import psutil

EmptySummary: dict = {
    "cpu_avg_pct": None,
    "cpu_peak_pct": None,
    "mem_avg_mb": None,
    "mem_peak_mb": None,
    "samples": 0,
}


class ResourceSampler:
    """Sample CPU% and RSS of a process tree at a fixed interval.

    target="pid"  → sample the given pid + all descendants (subprocess + Playwright/Chromium)
    target="self" → sample the current worker process (in-process task path)

    psutil.Process.cpu_percent(interval=None) reports CPU% measured between successive
    calls ON THE SAME Process instance — the first call always returns 0.0 (priming).
    We therefore cache Process objects per-PID across ticks; new children encountered
    mid-flight are primed once and counted on the next tick.

    stop() is idempotent — safe to call from a finally/except branch and the normal
    path simultaneously.
    """

    _RING_MAX = 1800  # ~1 hour at 2s; bounds memory on long jobs

    def __init__(
        self,
        target: Literal["pid", "self"],
        *,
        pid: int | None = None,
        interval: float = 2.0,
    ) -> None:
        if target == "pid" and pid is None:
            raise ValueError("pid required when target='pid'")
        self._target = target
        self._pid = pid
        self._interval = interval
        self._cpu_samples: deque[float] = deque(maxlen=self._RING_MAX)
        self._mem_samples: deque[float] = deque(maxlen=self._RING_MAX)
        self._procs: dict[int, psutil.Process] = {}  # pid → cached primed Process
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._stopped = False
        self._cached_summary: dict | None = None

    def start(self) -> "ResourceSampler":
        self._thread = threading.Thread(target=self._run, daemon=True, name="resource-sampler")
        self._thread.start()
        return self

    def stop(self) -> dict:
        if self._stopped:
            return self._cached_summary or EmptySummary
        self._stopped = True
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._interval * 2 + 1)
        self._cached_summary = self._summary()
        return self._cached_summary

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._sample()
            self._stop_event.wait(self._interval)
        # one final sample so very short jobs still get a reading
        self._sample()

    def _live_pids(self) -> list[int]:
        """Return current process tree as a list of PIDs."""
        try:
            if self._target == "self":
                return [os.getpid()]
            root = psutil.Process(self._pid)
            return [root.pid, *(c.pid for c in root.children(recursive=True))]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return []

    def _sample(self) -> None:
        live = set(self._live_pids())
        # drop dead processes from the cache so the dict doesn't grow unbounded
        for dead in [pid for pid in self._procs if pid not in live]:
            self._procs.pop(dead, None)

        total_cpu = 0.0
        total_rss = 0
        counted = 0
        for pid in live:
            proc = self._procs.get(pid)
            if proc is None:
                # First sighting of this PID: prime cpu_percent() and skip this tick.
                # Next tick reads a real CPU% measured between the prime call and now.
                try:
                    proc = psutil.Process(pid)
                    proc.cpu_percent(interval=None)
                    self._procs[pid] = proc
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                continue

            try:
                total_cpu += proc.cpu_percent(interval=None)
                total_rss += proc.memory_info().rss
                counted += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                self._procs.pop(pid, None)

        if counted == 0:
            return  # nothing primed yet — wait until the next tick

        self._cpu_samples.append(round(total_cpu, 2))
        self._mem_samples.append(round(total_rss / 1024 / 1024, 2))

    def _summary(self) -> dict:
        n = len(self._cpu_samples)
        if n == 0:
            return EmptySummary
        return {
            "cpu_avg_pct": round(sum(self._cpu_samples) / n, 2),
            "cpu_peak_pct": round(max(self._cpu_samples), 2),
            "mem_avg_mb": round(sum(self._mem_samples) / n, 2),
            "mem_peak_mb": round(max(self._mem_samples), 2),
            "samples": n,
        }
