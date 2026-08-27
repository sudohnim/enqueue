"""Generate Android adaptive icons from the raven mark.

The adaptive icon consists of two layers:
- Foreground: the raven mark (with transparency, masked to 66% safe zone)
- Background: solid light canvas color

The source is desktop/icons/icon.png which is the full composed icon (raven on purple).
We need to extract the raven mark and create adaptive icon layers.

Android adaptive icon specs:
- Foreground must be 108x108 dp within a 108x108 dp canvas (66% safe zone = 71.28 dp)
- Background is solid color 108x108 dp
- mdpi: 48x48 px, hdpi: 72x72 px, xhdpi: 96x96 px, xxhdpi: 144x144 px, xxxhdpi: 192x192 px
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).parent
SOURCE = HERE / "icon.png"  # The composed icon (raven on purple)

# Android adaptive icon sizes
SIZES = {
    "mdpi": 48,
    "hdpi": 72,
    "xhdpi": 96,
    "xxhdpi": 144,
    "xxxhdpi": 192,
}

# Light canvas color from DESIGN.md
LIGHT_CANVAS = "#ffffff"


def create_adaptive_layers(size: int) -> tuple[Image.Image, Image.Image]:
    """Create foreground and background layers for adaptive icon at given size.

    Returns (foreground, background) where:
    - foreground: RGBA image (full size), raven centered in 66% safe zone
    - background: solid color image
    """
    # Source icon (composed: raven on purple with transparency)
    src = Image.open(SOURCE).convert("RGBA")

    # Extract raven using alpha channel: opaque = raven, transparent = background
    src_array = np.array(src)
    if src_array.ndim != 3 or src_array.shape[2] != 4:
        raise ValueError(f"Source icon must be RGBA, got shape {src_array.shape}")
    alpha_mask = src_array[:, :, 3]

    # Find bounding box of the raven (opaque pixels)
    rows = np.any(alpha_mask > 0, axis=1)
    cols = np.any(alpha_mask > 0, axis=0)
    if not np.any(rows):
        raise ValueError("No opaque pixels found in source icon")
    rmin, rmax = np.where(rows)[0][[0, -1]]
    cmin, cmax = np.where(cols)[0][[0, -1]]
    # Add minimal padding to keep anti-aliased edges
    h, w = src_array.shape[:2]
    pad = max(h, w) // 50
    rmin = max(0, rmin - pad)
    rmax = min(h, rmax + pad)
    cmin = max(0, cmin - pad)
    cmax = min(w, cmax + pad)
    raven_cropped = Image.fromarray(src_array[rmin:rmax, cmin:cmax])

    # Android adaptive icon safe zone is 66% (spec).
    # Size raven to ~62% of icon to fit comfortably within 66% safe zone
    # after launcher applies its mask (circle/rounded-square).
    raven_target_size = int(size * 0.62)
    raven_scaled = raven_cropped.resize(
        (raven_target_size, raven_target_size), Image.Resampling.LANCZOS
    )

    # Create full-size foreground layer (launcher will mask this)
    fg = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    inset = (size - raven_target_size) // 2
    fg.paste(raven_scaled, (inset, inset), raven_scaled)

    # Background: solid light canvas color
    bg = Image.new("RGB", (size, size), LIGHT_CANVAS)

    return fg, bg


def main() -> None:
    RES_DIR = Path(__file__).parent.parent / "gen" / "android" / "app" / "src" / "main" / "res"

    for density, size in SIZES.items():
        mipmap_dir = Path(RES_DIR) / f"mipmap-{density}"
        mipmap_dir.mkdir(parents=True, exist_ok=True)

        fg, bg = create_adaptive_layers(size)

        # Save foreground
        fg.save(Path(mipmap_dir) / "ic_launcher_foreground.png")

        # Save background
        bg.save(Path(mipmap_dir) / "ic_launcher_background.png")

        # Also create the legacy ic_launcher.png (composed for legacy support)
        legacy = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        bg_rgba = Image.new("RGBA", (size, size), LIGHT_CANVAS + "ff")
        legacy.paste(bg_rgba, (0, 0))
        legacy.paste(fg, (0, 0), fg)
        legacy.save(Path(mipmap_dir) / "ic_launcher.png")

        # Round icon (same as foreground for now)
        fg.save(Path(mipmap_dir) / "ic_launcher_round.png")

        print(f"Generated {density} ({size}x{size})")

    print("Done!")


if __name__ == "__main__":
    main()
