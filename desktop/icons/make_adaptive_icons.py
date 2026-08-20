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

from PIL import Image, ImageDraw
import numpy as np

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
    - foreground: RGBA image with transparency, content centered in safe zone
    - background: solid color image
    """
    # Source icon (composed: raven on purple)
    src = Image.open(SOURCE).convert("RGBA")

    # Resize source to target size
    src = src.resize((size, size), Image.Resampling.LANCZOS)

    # Create foreground with transparent background
    fg = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # The safe zone is 66% of the icon size
    safe_zone = int(size * 0.66)
    inset = (size - safe_zone) // 2

    # The raven in the source icon is small and centered. We need to extract it
    # and scale it up to fill the safe zone. First, find the non-purple content.
    src_array = np.array(src)
    
    # Find non-white/purple pixels (the raven mark)
    # Purple background is roughly #6B46C1 (107, 70, 193) - look for non-background pixels
    # We'll create an alpha mask based on color difference from the purple background
    purple_r, purple_g, purple_b = 107, 70, 193
    diff = np.abs(src_array[:, :, 0] - purple_r) + np.abs(src_array[:, :, 1] - purple_g) + np.abs(src_array[:, :, 2] - purple_b)
    # Threshold: pixels significantly different from purple are the raven
    alpha_mask = (diff > 60).astype(np.uint8) * 255
    
    # Find bounding box of the raven
    rows = np.any(alpha_mask, axis=1)
    cols = np.any(alpha_mask, axis=0)
    if np.any(rows):
        rmin, rmax = np.where(rows)[0][[0, -1]]
        cmin, cmax = np.where(cols)[0][[0, -1]]
        # Add some padding
        h, w = src_array.shape[:2]
        pad = max(h, w) // 20
        rmin = max(0, rmin - pad)
        rmax = min(h, rmax + pad)
        cmin = max(0, cmin - pad)
        cmax = min(w, cmax + pad)
        # Crop to the raven
        src = Image.fromarray(src_array[rmin:rmax, cmin:cmax])
    else:
        # Fallback: use center crop
        src = src.crop((size//4, size//4, 3*size//4, 3*size//4))

    # Now scale the cropped raven to fill the safe zone
    src = src.resize((safe_zone, safe_zone), Image.Resampling.LANCZOS)

    # Create a circular mask for the foreground content (safe zone size)
    mask = Image.new("L", (safe_zone, safe_zone), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse([0, 0, safe_zone, safe_zone], fill=255)

    # Apply the mask to the resized raven
    fg_safe = Image.new("RGBA", (safe_zone, safe_zone), (0, 0, 0, 0))
    fg_safe.paste(src, (0, 0), mask)

    # Now place the masked safe zone content into the full-size foreground
    fg = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    fg.paste(fg_safe, (inset, inset))

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
