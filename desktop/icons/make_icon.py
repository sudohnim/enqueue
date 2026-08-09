"""Compose the app icon from the supplied logo art.

Minh supplied logo.png (a 1024x1024 JPEG mis-named .png, master converted to
assets/logo.png): the full icon already composed - the mark (a black ring with
a white interior and a black centre dot) on a vivid purple tile that fills the
canvas. Nothing needs removing or re-tiling: this script masks the tile into
Apple's rounded square and emits the cuts the bundle needs.

macOS supplies no mask for an app icon, so the rounded square is part of the
artwork. The proportions are Apple's: on a 1024 grid the tile is 824 wide,
centred, with a corner radius of 185 - the same constants every previous icon
used.

Everything is composed at 4x and downsampled, which keeps the rounded corners
crisp.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent
# The master lives in assets/ as a true PNG (the root copy is a JPEG with a
# .png extension; this script reads the converted master).
SOURCE = HERE.parent.parent / "assets" / "logo.png"

S = 4  # supersample
SIZE = 1024

TILE = 824
RADIUS = 185
INSET = (SIZE - TILE) / 2


def compose(size: int = SIZE) -> Image.Image:
    w = size * S
    img = Image.new("RGBA", (w, w), (0, 0, 0, 0))
    k = w / SIZE

    # The source tile is pasted across the whole canvas, masked by the rounded
    # square that IS the icon's silhouette; no separate stroke is added.
    src = Image.open(SOURCE).convert("RGBA")
    src = src.resize((w, w), Image.Resampling.LANCZOS)
    mask = Image.new("L", (w, w), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle(
        [INSET * k, INSET * k, (SIZE - INSET) * k, (SIZE - INSET) * k],
        radius=RADIUS * k,
        fill=255,
    )
    img.paste(src, (0, 0), mask)

    return img.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    draw = compose(SIZE)
    draw.save(HERE / "icon.png")

    # Tauri wants these three by name for Windows and Linux; macOS takes the .icns.
    for name, size in (("32x32.png", 32), ("128x128.png", 128), ("128x128@2x.png", 256)):
        compose(size).save(HERE / name)

    iconset = HERE / "icon.iconset"
    iconset.mkdir(exist_ok=True)
    for size in (16, 32, 128, 256, 512):
        compose(size).save(iconset / f"icon_{size}x{size}.png")
        compose(size * 2).save(iconset / f"icon_{size}x{size}@2x.png")

    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(HERE / "icon.icns")],
        check=True,
    )
    # Scaffolding for iconutil, not an output. Leaving it behind puts twenty
    # near-identical PNGs in the tree that nothing reads and everything diffs.
    for stale in iconset.iterdir():
        stale.unlink()
    iconset.rmdir()
    print("wrote icon.png, icon.icns, and the sized PNGs", file=sys.stderr)


if __name__ == "__main__":
    main()
