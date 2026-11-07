"""Generate branding logos for the Google Auth Platform "Branding" page.

Run from the repo root:  python scripts/make_logo.py
Writes assets/logo/gsend_logo_512.png (white card) and
assets/logo/gsend_logo_512_transparent.png. Both are square, well
above Google's 120x120 minimum. Same palette and envelope geometry as the
runtime tray icon (gsend.tray), drawn supersampled for smooth edges.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "assets" / "logo"
LOGO_SIZE = 512
SS = 4  # supersampling factor: draw at 2048, downscale with Lanczos

# Same palette as gsend.tray (kept local so tray keeps its private names).
ENVELOPE_FILL = (66, 133, 244, 255)  # Google blue
ENVELOPE_LINE = (43, 93, 173, 255)  # darker blue
UNREAD_DOT = (234, 67, 53, 255)  # Google red
CARD_FILL = (255, 255, 255, 255)
CARD_BORDER = (224, 224, 224, 255)


def draw_logo(background: str) -> Image.Image:
    """Draw the logo at LOGO_SIZE*SS; `background` is "card" (white rounded) or "transparent"."""
    size = LOGO_SIZE * SS
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    if background == "card":
        margin = 16 * SS
        draw.rounded_rectangle(
            (margin, margin, size - margin, size - margin),
            radius=96 * SS,
            fill=CARD_FILL,
            outline=CARD_BORDER,
            width=3 * SS,
        )

    # Envelope proportions follow the tray icon (2:7..29:25 on a 32 grid).
    draw.rounded_rectangle(
        (56 * SS, 150 * SS, 456 * SS, 418 * SS),
        radius=28 * SS,
        fill=ENVELOPE_FILL,
        outline=ENVELOPE_LINE,
        width=10 * SS,
    )
    draw.line(
        [(68 * SS, 162 * SS), (256 * SS, 300 * SS)],
        fill=ENVELOPE_LINE,
        width=20 * SS,
    )
    draw.line(
        [(444 * SS, 162 * SS), (256 * SS, 300 * SS)],
        fill=ENVELOPE_LINE,
        width=20 * SS,
    )

    # The unread badge: the app's signature element.
    draw.ellipse(
        (317 * SS, 65 * SS, 467 * SS, 215 * SS),
        fill=UNREAD_DOT,
        outline=(255, 255, 255, 255),
        width=12 * SS,
    )
    return image.resize((LOGO_SIZE, LOGO_SIZE), Image.LANCZOS)


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    outputs = {
        "gsend_logo_512.png": "card",
        "gsend_logo_512_transparent.png": "transparent",
    }
    for name, background in outputs.items():
        path = OUTPUT_DIR / name
        draw_logo(background).save(path, format="PNG")
        print(f"Wrote {path} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
