"""Append one CSV line per minute while the real app runs (T-22 24-hour soak).

Attach to the running GSend.exe (start it normally, then pass --pid),
or let this script launch the exe with --exe. Output: one CSV line per minute
(timestamp, pid, RSS MB, CPU percent, thread count, handle count) written to
the app's log folder — numbers only, never log text, addresses or mail content.
Stop with Ctrl+C; the CSV keeps what was collected.

Usage:
  python scripts/soak_monitor.py --pid 12345
  python scripts/soak_monitor.py --exe dist\\GSend\\GSend.exe --hours 24
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

_SAMPLE_SECONDS = 60.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="24-hour soak monitor (CSV per minute).")
    parser.add_argument("--exe", help="path to GSend.exe to launch")
    parser.add_argument("--pid", type=int, help="attach to a running process instead")
    parser.add_argument("--hours", type=float, default=24.0, help="stop after this many hours")
    parser.add_argument(
        "--out",
        default=str(config.logs_dir() / "soak_metrics.csv"),
        help="CSV destination (default: %%LOCALAPPDATA%%\\GSend\\logs\\soak_metrics.csv)",
    )
    args = parser.parse_args(argv)

    if args.pid:
        process = psutil.Process(args.pid)
    elif args.exe:
        exe = Path(args.exe)
        if not exe.exists():
            print(f"error: exe not found: {exe.name}")
            return 2
        child = subprocess.Popen([str(exe)])  # noqa: S603 - fixed, verified path
        process = psutil.Process(child.pid)
    else:
        print("error: pass --exe or --pid")
        return 2

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fresh = not out_path.exists()
    end = time.monotonic() + args.hours * 3600
    print(f"writing {out_path.name} every {_SAMPLE_SECONDS:.0f}s; Ctrl+C to stop")
    try:
        with open(out_path, "a", encoding="utf-8", buffering=1) as handle:
            if fresh:
                handle.write("timestamp,pid,rss_mb,cpu_percent,threads,handles\n")
            while time.monotonic() < end:
                try:
                    rss_mb = process.memory_info().rss / (1024 * 1024)
                    cpu = process.cpu_percent(interval=_SAMPLE_SECONDS)
                    threads = process.num_threads()
                    handles = process.num_handles()
                except psutil.Error:
                    print("error: process exited; soak monitor stops")
                    return 1
                stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                handle.write(f"{stamp},{process.pid},{rss_mb:.1f},{cpu:.1f},{threads},{handles}\n")
    except KeyboardInterrupt:
        print("stopped by user; CSV kept")
    return 0


if __name__ == "__main__":
    sys.exit(main())
