"""Split the flat eyeball image into a frame and a movable iris pupil.

O.3 shipped the eyeball as one flat image and the follow as a whole-eye
slide on a canvas disc, which visibly moved a shading patch of the bird
rather than the eye. This version produces two clean alpha assets:

- eye-frame.png: the full 1024x1024 eyeball with the purple iris region
  replaced by the local sclera white. The bird, the eye outline, the
  lashes, and the ground stay in this layer and never move.
- eye-pupil.png: ONLY the purple iris, extracted onto a small transparent
  canvas. This is the only thing that moves in the DOM.

The DOM stacks the clipped pupil under the frame, positioned exactly over
the iris socket, and translates only the pupil. The frame stays still, so
what the cursor pulls is the eye's glance, not the bird.

The iris bbox and the colour gate below are measured from the current
1024x1024 eyeball.png (replaced 2026-08-09): the purple eye sits at
x in [511, 581], y in [367, 436], centre ~(546, 401), iris centre
#60079f, sclera ~#fcfdfc (re-sampled 50px ring around the iris: neutral
white with a hair cool tint, (252, 253, 252)).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter

HERE = Path(__file__).parent
STATIC = HERE.parent.parent / "src" / "enqueue" / "static"

SOURCE = STATIC / "eyeball.png"
FRAME = STATIC / "eye-frame.png"
PUPIL = STATIC / "eye-pupil.png"
# Purple eye bbox in source pixels.
IRIS_X0, IRIS_X1 = 511, 581
IRIS_Y0, IRIS_Y1 = 367, 436
# Sclera white sampled just outside the iris (do NOT include the purple fringe).
# Re-sampled a 50px ring around the iris bbox (15687 white pixels): average is
# neutral white with a hair cool tint - (252, 253, 252), not the old (253,254,246)
# which included a purple pixel. Q.1 re-bleaches the near-white canvas to fully
# transparent first, so the iris hole fill is transparent too and the lavender
# gradient wash on .homehead shows through the frame's surround.
SCLERA = (0, 0, 0, 0)
# How far the pupil may travel in source pixels. The eye renders at
# ~104 CSS px from a 1024 px source (scale ~0.10), so 32 px is ~3-4 CSS px
# of lean - a real iris shift without spilling the lid.
SLIDE = 32


def bleach_background(img: Image.Image) -> Image.Image:
    """Repaint the pink-tinted near-white canvas to fully transparent.

    The eyeball's background is #fcf7fe (RGB 252-253, 247-248, 253-254) - a
    pink-tinted white that reads as a faint halo against the #ffffff page
    canvas (P.3), and as a white box against the .homehead lavender gradient
    wash (Q.1). The colour gate captures that near-white (r>248, g>244,
    b>250, b>=r) and rejects the dark lash ink, the purple iris, and the
    green ground. A 3px MinFilter erosion shrinks the mask so the soft
    anti-aliased fringe around the lash ink is NOT bleached - without it the
    bird's outline would go hard-edged. Returns the background mask (L).
    """
    r, g, b, _a = img.split()
    r_hi = r.point(_gate_gt(248))
    g_hi = g.point(_gate_gt(244))
    b_hi = b.point(_gate_gt(250))
    # b >= r  <=>  NOT (r - b > 0)
    b_ge_r = ImageChops.subtract(r, b).point(_gate_gt(0)).point(lambda v: 255 - v)
    mask = ImageChops.multiply(r_hi, ImageChops.multiply(g_hi, ImageChops.multiply(b_hi, b_ge_r)))
    # Erode by 3px so the anti-aliased fringe around lash ink survives.
    return mask.filter(ImageFilter.MinFilter(size=3))


def _gate_gt(threshold: int) -> Callable[[int], int]:
    """A point transform that maps channel values above a threshold to 255."""

    def _apply(v: int) -> int:
        return 255 if v > threshold else 0

    return _apply


def _gate_lt(threshold: int) -> Callable[[int], int]:
    """A point transform that maps channel values below a threshold to 255."""

    def _apply(v: int) -> int:
        return 255 if v < threshold else 0

    return _apply


def purple_mask(img: Image.Image) -> Image.Image:
    """Binary L mask of the iris purple, over the whole source image.

    Colour gate: b > 110 and b > r + 30 and g < 130. The iris centre is
    (96, 7, 159); this captures the purple body and rejects the white
    sclera, the green ground, and the dark lash ink.
    """
    r, g, b, _alpha = img.split()
    b_hi = b.point(_gate_gt(110))
    # b > r + 30  <=>  max(b - r, 0) > 30
    b_gt_r = ImageChops.subtract(b, r).point(_gate_gt(30))
    g_lo = g.point(_gate_lt(130))
    mask = ImageChops.multiply(b_hi, ImageChops.multiply(b_gt_r, g_lo))
    # Feather by 2px so the frame hole has no hard seam and the pupil edge
    # grades into the lash line instead of cutting it.
    return mask.filter(ImageFilter.GaussianBlur(2))


def main() -> None:
    img = Image.open(SOURCE).convert("RGBA")
    # P.3/Q.1: bleach the off-white canvas to fully transparent so the
    # composite eye reads flush against the page and lets the .homehead
    # lavender gradient wash show through. The source is overwritten so the
    # delivered eyeball.png and the generated assets stay consistent.
    bg = bleach_background(img)
    transparent = Image.new("RGBA", img.size, (0, 0, 0, 0))
    img = Image.composite(transparent, img, bg)
    img.save(SOURCE)
    w, h = img.size
    mask = purple_mask(img)

    # Frame: the full eyeball with the iris hole filled with sclera white,
    # feathered into the lash edge. Everything else is untouched.
    frame = img.copy()
    sclera = Image.new("RGBA", img.size, SCLERA)
    frame = Image.composite(sclera, frame, mask)
    FRAME.parent.mkdir(parents=True, exist_ok=True)
    frame.save(FRAME)

    # Pupil: only the purple iris, on a transparent canvas 2x SLIDE larger
    # than the crop so the DOM can centre it and still travel in every
    # direction. The same feathered mask keeps only the purple pixels.
    crop = img.crop((IRIS_X0, IRIS_Y0, IRIS_X1, IRIS_Y1))
    pw = IRIS_X1 - IRIS_X0 + 2 * SLIDE
    ph = IRIS_Y1 - IRIS_Y0 + 2 * SLIDE
    pupil = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    pupil.paste(crop, (SLIDE, SLIDE))
    mask_crop = mask.crop((IRIS_X0, IRIS_Y0, IRIS_X1, IRIS_Y1))
    mask_full = Image.new("L", (pw, ph), 0)
    mask_full.paste(mask_crop, (SLIDE, SLIDE))
    pr, pg, pb, _pa = pupil.split()
    pupil = Image.merge("RGBA", (pr, pg, pb, mask_full))
    pupil.save(PUPIL)

    # The old single-layer asset is gone; the DOM moves to the pupil in O.3b.
    stale = STATIC / "eye-iris.png"
    if stale.exists():
        stale.unlink()

    offset = (IRIS_X0 - SLIDE, IRIS_Y0 - SLIDE)
    print(
        f"wrote {FRAME.name} ({w}x{h}), {PUPIL.name} ({pw}x{ph}), "
        f"pupil offset within frame {offset}"
    )


if __name__ == "__main__":
    main()
