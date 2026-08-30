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

def _bg_purple(src: Image.Image) -> tuple[int, int, int]:
    """The icon's own purple, sampled from the rounded square's upper-left field
    (above the raven, clear of the drop shadow). Used to fill the adaptive icon's
    background so the mask-cropped corners stay purple, matching the desktop icon.
    """
    sw, sh = src.size
    r, g, b = src.getpixel((int(sw * 0.20), int(sh * 0.18)))[:3]
    return (r, g, b)


def create_adaptive_layers(size: int) -> tuple[Image.Image, Image.Image]:
    """Create foreground and background layers for the adaptive icon.

    The desktop's composed icon (raven on a purple rounded square, `icon.png`) is
    already the finished mark, so the foreground IS that icon scaled to fill the
    adaptive canvas - no re-extraction, no shrink-to-safe-zone. Its transparent
    corners fall onto a matching purple background, and the launcher's circle /
    squircle mask crops to raven-on-purple, identical to the desktop icon. The
    previous approach keyed on alpha (but icon.png's purple is opaque, so it kept
    the whole square) and then shrank it onto a WHITE field - the "tiny raven on a
    big white background" this replaces.
    """
    src = Image.open(SOURCE).convert("RGBA")
    fg = src.resize((size, size), Image.Resampling.LANCZOS)
    bg = Image.new("RGB", (size, size), _bg_purple(src))
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

        # Legacy + round launcher icons: the composed icon on the purple field
        # (foreground over background), so pre-adaptive launchers show the same
        # raven-on-purple as the desktop icon.
        composed = bg.convert("RGBA")
        composed.paste(fg, (0, 0), fg)
        composed.save(Path(mipmap_dir) / "ic_launcher.png")
        composed.save(Path(mipmap_dir) / "ic_launcher_round.png")

        print(f"Generated {density} ({size}x{size})")

    print("Done!")


if __name__ == "__main__":
    main()
