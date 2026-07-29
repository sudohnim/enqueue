"""Draw the app icon.

The mark is an eye with a return arrow turning inside it: looking again at something
you already have, which is the whole product in one shape.

It is drawn here rather than stored as a flat PNG so it can be regenerated at any size
without the soft edges a resized bitmap gets, and so the colours stay tied to the light
theme's own tokens instead of drifting into whatever an image editor happened to save.

macOS supplies no mask for an app icon, so the rounded square is part of the artwork.
The proportions are Apple's: on a 1024 grid the tile is 824 wide, centred, with a
corner radius of 185.

Everything is drawn at 4x and downsampled, which is cheaper and sharper than asking a
drawing library for antialiased strokes.
"""

from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent

# Straight from museum.html's light theme. --canvas behind, --body for the mark: the
# same pairing the interface uses for text on a page, so the icon and the app it opens
# are made of one material.
CANVAS = (234, 233, 228, 255)
MARK = (67, 70, 68, 255)

S = 4  # supersample
SIZE = 1024

TILE = 824
RADIUS = 185

# Four cuts of the same mark. Apple ships distinct artwork per size for a reason: a
# stroke that reads as a hairline at 512 averages into pale grey at 32, and two
# concentric rings 80 units apart land a pixel apart once the eye is sixteen pixels
# wide. Shrinking one master is how an icon turns to mush in the Dock.
#
# So the small cuts are heavier and carry fewer parts. They are the same object seen
# from further away, which is exactly what a 32px icon is.
#
#          half_w half_h  ring  stroke  pupil  inner_ring  arrow
# The ring is always smaller than the eye's half-height. Bigger and it breaks out
# through both lids, and the arrowhead fuses into the upper one instead of turning
# inside the eye, which is the one relationship the whole mark depends on.
CUTS = {
    "large": (320, 210, 196, 30, 44, True, True),
    # Two concentric rings, an arrowhead and a pupil is four things inside an eye
    # sixty pixels wide. The inner ring is the one that carries least, so it goes
    # first: without it the arrow still turns and the pupil still reads.
    "medium": (322, 214, 176, 34, 62, False, True),
    # Eye and pupil, nothing else. Below ~48px the arrow's gap and the channel between
    # ring and pupil are both under a pixel, so they fill in and the whole iris becomes
    # one dark smudge. Side by side, the plain eye is the one that still reads.
    "small": (334, 224, 0, 58, 84, False, False),
    # At 16px every stroke has to survive being rounded to a whole pixel, so nothing
    # here is thinner than 96 units: 96/1024 * 16 is a pixel and a half. Below that the
    # antialiaser hands back grey, and grey at this size is just a smudge.
    "tiny": (350, 232, 0, 88, 104, False, False),
}


def cut_for(size: int) -> tuple:
    if size <= 20:
        return CUTS["tiny"]
    if size <= 48:
        return CUTS["small"]
    if size <= 160:
        return CUTS["medium"]
    return CUTS["large"]


def draw(size: int = SIZE) -> Image.Image:
    w = size * S
    img = Image.new("RGBA", (w, w), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    k = w / SIZE  # everything below is authored on the 1024 grid

    def px(v: float) -> float:
        return v * k

    inset = (SIZE - TILE) / 2
    d.rounded_rectangle(
        [px(inset), px(inset), px(SIZE - inset), px(SIZE - inset)],
        radius=px(RADIUS),
        fill=CANVAS,
    )

    half_w, half_h, ring, stroke, pupil, inner_ring, arrow = cut_for(size)
    cx = cy = SIZE / 2

    # ---- the eye ------------------------------------------------------------
    # The almond is two circular arcs, not an ellipse: an ellipse gives blunt ends, and
    # the point where the two curves meet is the whole character of the shape.
    #
    # For a lens of half-width a and half-height b, each arc lies on a circle of radius
    # (a^2 + b^2) / 2b whose centre sits (radius - b) away on the far side of the axis.
    r = (half_w**2 + half_h**2) / (2 * half_h)
    off = r - half_h

    # Half the angle each arc subtends at its own centre, which is not the angle the
    # lens subtends at the middle of the icon.
    corner = math.degrees(math.atan2(half_w, off))

    def arc(centre_y: float, start: float, end: float) -> None:
        d.arc(
            [px(cx - r), px(centre_y - r), px(cx + r), px(centre_y + r)],
            start=start,
            end=end,
            fill=MARK,
            width=round(px(stroke)),
        )

    arc(cy + off, 270 - corner, 270 + corner)  # upper lid
    arc(cy - off, 90 - corner, 90 + corner)  # lower lid

    # ---- the iris -----------------------------------------------------------
    if pupil:
        d.ellipse(
            [px(cx - pupil), px(cy - pupil), px(cx + pupil), px(cy + pupil)],
            fill=MARK,
        )

    if inner_ring:
        mid = ring * 0.62
        d.ellipse(
            [px(cx - mid), px(cy - mid), px(cx + mid), px(cy + mid)],
            outline=MARK,
            width=round(px(stroke)),
        )

    if ring:
        # The outer ring is the return arrow: an almost-closed circle with the gap and
        # the head at the upper right, where the eye is widest and the head has room.
        # Angles run clockwise from three o'clock because y runs down, so this is the
        # upper right. It is set by where the head lands rather than by where the arc
        # looks best: any higher and the tip punches out through the upper lid, which
        # reads as a spur growing off the eye rather than as an arrow inside it.
        head_at = 338
        gap = 44
        d.arc(
            [px(cx - ring), px(cy - ring), px(cx + ring), px(cy + ring)],
            start=head_at,
            end=head_at - gap,
            fill=MARK,
            width=round(px(stroke)),
        )

        if arrow:
            # Travelling anticlockwise, so the head arrives at the upper right pointing
            # up: the direction that reads as bringing something back round.
            t = math.radians(head_at)
            at = (cx + ring * math.cos(t), cy + ring * math.sin(t))
            direction = (math.sin(t), -math.cos(t))
            perp = (-direction[1], direction[0])

            # The head has to out-measure the stroke it terminates or it reads as a
            # kink in the ring rather than as an arrow.
            length = stroke * 2.35
            width = stroke * 1.75
            tip = (at[0] + direction[0] * length, at[1] + direction[1] * length)
            back = (
                at[0] - direction[0] * length * 0.3,
                at[1] - direction[1] * length * 0.3,
            )
            d.polygon(
                [
                    (px(tip[0]), px(tip[1])),
                    (px(back[0] + perp[0] * width), px(back[1] + perp[1] * width)),
                    (px(back[0] - perp[0] * width), px(back[1] - perp[1] * width)),
                ],
                fill=MARK,
            )

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    # Drawn at each size rather than resized from one master, or the whole point of
    # having four cuts is thrown away on the last line.
    draw(SIZE).save(HERE / "icon.png")

    # Tauri wants these three by name for Windows and Linux; macOS takes the .icns.
    for name, size in (("32x32.png", 32), ("128x128.png", 128), ("128x128@2x.png", 256)):
        draw(size).save(HERE / name)

    iconset = HERE / "icon.iconset"
    iconset.mkdir(exist_ok=True)
    for size in (16, 32, 128, 256, 512):
        draw(size).save(iconset / f"icon_{size}x{size}.png")
        draw(size * 2).save(iconset / f"icon_{size}x{size}@2x.png")

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
