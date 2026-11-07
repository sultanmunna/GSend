"""Generate assets/app.ico with multiple sizes, matching the runtime tray icon.

Run from the repo root:  python scripts/make_icons.py
The icon is drawn by gmail_notifier.tray.draw_icon so the exe icon, the
installer icon and the tray icon all share one source (docs/PRODUCT.md 6.1).
"""

from __future__ import annotations

from pathlib import Path

from gmail_notifier.tray import IconState, draw_icon

SIZES = [16, 24, 32, 48, 64, 128, 256]
OUTPUT = Path(__file__).resolve().parent.parent / "assets" / "app.ico"


def main() -> int:
    base = draw_icon(IconState.IDLE, 256)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    base.save(
        OUTPUT,
        format="ICO",
        sizes=[(s, s) for s in SIZES],
    )
    print(f"Wrote {OUTPUT} ({OUTPUT.stat().st_size} bytes, sizes {SIZES})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
