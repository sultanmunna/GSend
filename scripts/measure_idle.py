"""Measure startup time and idle RSS/CPU of the running app (docs/BUILD.md).

Dev-only helper (psutil, DECISIONS D-22). Launches the built exe or attaches to
a running PID, measures the time from process start to the app's "starting" log
line, then samples RSS and CPU until the duration elapses. Every output line
carries timestamps and numbers only — never log text, addresses, mail content
or tokens.

Usage:
  python scripts/measure_idle.py --exe dist\\GSend\\GSend.exe --minutes 10
  python scripts/measure_idle.py --pid 12345 --minutes 10
  python scripts/measure_idle.py --dist dist\\GSend          (folder size only)

Quit the running GSend instance first: a second launch would exit on
the single-instance mutex and nothing would be measured.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import psutil

from gsend import config

_START_MARKER = " starting"  # the log line the app writes at startup
_POLL_SECONDS = 0.25
_SAMPLE_SECONDS = 30.0


def _log_file() -> Path:
    return config.log_file_path()


def _wait_for_start_marker(deadline_seconds: float) -> float | None:
    """Seconds until the "starting" line appears in the log, or None on timeout.

    Reads the log tail but only compares against the marker substring; the
    content of lines is never printed or stored.
    """
    deadline = time.monotonic() + deadline_seconds
    path = _log_file()
    offset = 0
    if path.exists():
        offset = path.stat().st_size  # ignore lines from previous runs
    while time.monotonic() < deadline:
        try:
            if path.exists() and path.stat().st_size > offset:
                with open(path, encoding="utf-8", errors="replace") as handle:
                    handle.seek(offset)
                    new_text = handle.read()
                    offset = path.stat().st_size
                if _START_MARKER in new_text:
                    return time.monotonic()
        except OSError:
            pass
        time.sleep(_POLL_SECONDS)
    return None


def _dist_size_mb(path: Path) -> float:
    total = sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
    return total / (1024 * 1024)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure startup and idle RSS/CPU.")
    parser.add_argument("--exe", help="path to GSend.exe to launch")
    parser.add_argument("--pid", type=int, help="attach to a running process instead")
    parser.add_argument("--minutes", type=float, default=10.0, help="sample duration")
    parser.add_argument("--dist", help="optional dist folder to measure (size only)")
    args = parser.parse_args(argv)

    if args.dist:
        print(f"dist_size_mb={_dist_size_mb(Path(args.dist)):.1f}")
        if not (args.exe or args.pid):
            return 0

    if args.pid:
        process = psutil.Process(args.pid)
        start_time = None  # unknown for an attached process
    elif args.exe:
        exe = Path(args.exe)
        if not exe.exists():
            print(f"error: exe not found: {exe.name}")
            return 2
        started = time.monotonic()
        child = subprocess.Popen([str(exe)])  # noqa: S603 - fixed, verified path
        process = psutil.Process(child.pid)
        marker = _wait_for_start_marker(deadline_seconds=30.0)
        start_time = None if marker is None else marker - started
    else:
        print("error: pass --exe or --pid")
        return 2

    print("timestamp,pid,rss_mb,cpu_percent")
    first_rss = None
    samples = 0
    cpu_sum = 0.0
    end = time.monotonic() + args.minutes * 60
    while time.monotonic() < end:
        try:
            rss_mb = process.memory_info().rss / (1024 * 1024)
            cpu = process.cpu_percent(interval=_SAMPLE_SECONDS)
        except psutil.Error:
            print("error: process exited before the measurement finished")
            return 1
        if first_rss is None:
            first_rss = rss_mb
        samples += 1
        cpu_sum += cpu
        stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        print(f"{stamp},{process.pid},{rss_mb:.1f},{cpu:.1f}")

    if samples:
        print(f"RESULT startup_seconds={'n/a' if start_time is None else f'{start_time:.1f}'}")
        print(f"RESULT idle_rss_mb={rss_mb:.1f}")
        print(f"RESULT cpu_percent_avg={cpu_sum / samples:.2f}")
    if args.exe and process.is_running():
        process.terminate()  # we spawned it; clean up so no tray icon lingers
        try:
            process.wait(timeout=10)
        except psutil.TimeoutExpired:
            process.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
