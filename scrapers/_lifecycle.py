"""Shared scraper-process lifecycle: die when the parent (terminal) goes away.

Why this exists
---------------
A scraper launched manually as `python3 scraper.py` is supposed to be a
foreground child of the shell. When the user closes the terminal:

  1. The shell sends SIGHUP to its foreground process group.
  2. Python's default SIGHUP handler is SIG_DFL → process terminates.

In practice we have observed scrapers surviving terminal close and looping at
100% CPU for hours (e.g. PID 11886 on 2026-05-04: `scrapers/epus/scraper.py`
spinning in CPython at 99% CPU after the user closed iTerm). Two things can
defeat the SIGHUP path:

  - A library quietly installs `signal.signal(SIGHUP, SIG_IGN)`.
  - The process is mid-CPU-loop with no Python opcode boundary check, so
    even if SIGHUP fires, signal delivery is delayed indefinitely.
  - The shell didn't propagate SIGHUP (huponexit off, job control glitch).

`install()` defends in two layers:

  1. Reinstalls SIG_DFL for SIGHUP and SIGTERM so terminal-close actually
     terminates us if a library masked the handler.
  2. Spawns a daemon thread that polls `os.getppid()`. When the parent dies
     (or gets reaped by launchd → ppid becomes 1), the thread calls
     `os._exit()` immediately. This bypasses any wedged C call because the
     watchdog runs in a separate OS thread and `os._exit` is the kernel-level
     exit syscall.

Call `install()` as the very first thing in any scraper entrypoint.
"""
import os
import signal
import sys
import threading
import time

_DEFAULT_POLL_SECONDS = 2.0


def install(poll_seconds: float = _DEFAULT_POLL_SECONDS) -> None:
    # Reset terminal-close signals to default-terminate behavior.
    # Skip SIGINT — Python's default of raising KeyboardInterrupt is what
    # callers expect for Ctrl-C cleanup paths.
    for sig in (signal.SIGHUP, signal.SIGTERM):
        try:
            signal.signal(sig, signal.SIG_DFL)
        except (ValueError, OSError):
            pass

    initial_ppid = os.getppid()
    if initial_ppid <= 1:
        # Already detached (e.g. nohup, launchd, daemonized). Nothing to watch.
        return

    def _watchdog() -> None:
        while True:
            time.sleep(poll_seconds)
            ppid = os.getppid()
            if ppid == 1 or ppid != initial_ppid:
                sys.stderr.write(
                    "[lifecycle] parent process gone "
                    f"(initial_ppid={initial_ppid}, now ppid={ppid}); exiting.\n"
                )
                try:
                    sys.stderr.flush()
                except Exception:
                    pass
                os._exit(143)  # 128 + SIGTERM

    threading.Thread(
        target=_watchdog, name="parent-death-watchdog", daemon=True
    ).start()
