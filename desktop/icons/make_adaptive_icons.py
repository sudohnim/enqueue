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
SOURCE = HERE / "icon.png"  # The composed icon (raven on purple), for the bg color
RAVEN_MARK = HERE.parent.parent / "src" / "enqueue" / "static" / "raven-mark.png"  # transparent raven

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


# The foreground raven is placed at this fraction of the icon canvas. Adaptive
# launchers mask the 108dp canvas down to a ~66-72% circle, so a raven scaled to
# the FULL canvas gets its head/feet clipped by that circle. The standing raven is
# taller than wide, so we scale by its height to 0.56 of the canvas: the whole bird
# lands inside the launcher circle, centered, with breathing room on every side.
RAVEN_FILL = 0.56


def create_adaptive_layers(size: int) -> tuple[Image.Image, Image.Image]:
    """Create the adaptive icon's (foreground, background).

    Foreground is the TRANSPARENT raven mark centered on a clear canvas; background
    is solid brand purple. The launcher composites them and masks to its own shape
    (circle / squircle), so every Android 8+ launcher shows raven-on-purple with no
    white ring. This needs the `mipmap-anydpi-v26/ic_launcher.xml` written by main()
    to point at these two layers - without that XML the launcher falls back to the
    legacy square PNG and wraps it in a white circle (the bug this fixes).
    """
    bg = Image.new("RGB", (size, size), _bg_purple(Image.open(SOURCE).convert("RGBA")))
    raven = Image.open(RAVEN_MARK).convert("RGBA")
    target = int(size * RAVEN_FILL)
    scale = target / max(raven.size)
    raven = raven.resize(
        (max(1, int(raven.width * scale)), max(1, int(raven.height * scale))),
        Image.Resampling.LANCZOS,
    )
    fg = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    fg.paste(raven, ((size - raven.width) // 2, (size - raven.height) // 2), raven)
    return fg, bg


_ADAPTIVE_XML = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
    '    <background android:drawable="@mipmap/ic_launcher_background" />\n'
    '    <foreground android:drawable="@mipmap/ic_launcher_foreground" />\n'
    "</adaptive-icon>\n"
)


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

    # The adaptive-icon descriptor (Android 8+). Without this, launchers ignore the
    # foreground/background layers and wrap the legacy square PNG in a white circle.
    anydpi = Path(RES_DIR) / "mipmap-anydpi-v26"
    anydpi.mkdir(parents=True, exist_ok=True)
    (anydpi / "ic_launcher.xml").write_text(_ADAPTIVE_XML, encoding="utf-8")
    (anydpi / "ic_launcher_round.xml").write_text(_ADAPTIVE_XML, encoding="utf-8")
    print("Wrote mipmap-anydpi-v26/ic_launcher.xml (+round)")

    print("Done!")


if __name__ == "__main__":
    main()
