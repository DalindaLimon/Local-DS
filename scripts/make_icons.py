"""Generate the PNG app icons from the same design as app/static/icons/icon.svg (outputs are committed).

pip install pillow && python scripts/make_icons.py
"""

import math
from itertools import pairwise
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "app" / "static" / "icons"
SS = 4  # supersampling for smooth edges

# Purple -> blue diagonal gradient with a pink-violet glow in the bottom-left corner (Instagram-style).
STOPS = [(0.0, (0xB4, 0x4D, 0xFF)), (0.5, (0x6A, 0x5C, 0xFF)), (1.0, (0x1E, 0x8B, 0xFF))]
GLOW = (0xE0, 0x5C, 0xFF)


def _lerp(stops, t: float) -> tuple[int, int, int]:
    for (t0, c0), (t1, c1) in pairwise(stops):
        if t <= t1:
            f = (t - t0) / (t1 - t0)
            return tuple(round(c0[i] + (c1[i] - c0[i]) * f) for i in range(3))
    return stops[-1][1]


def background(size: int) -> Image.Image:
    """Computed at 512 px (gradients are smooth), then scaled."""
    n = 512
    pixels = []
    for y in range(n):
        for x in range(n):
            base = _lerp(STOPS, (x + y) / (2 * (n - 1)))
            # radial glow around (0.18, 0.95), radius 0.7 of the icon
            dist = math.hypot(x / n - 0.18, y / n - 0.95) / 0.7
            a = max(0.0, 1.0 - dist) * 0.75
            pixels.append(tuple(round(base[i] + (GLOW[i] - base[i]) * a) for i in range(3)))
    img = Image.new("RGB", (n, n))
    img.putdata(pixels)
    return img.resize((size, size), Image.Resampling.BICUBIC)


def draw_icon(size: int, maskable: bool = False, rounded: bool = True) -> Image.Image:
    big = size * SS
    s = big / 512
    bg = background(big)
    shape = Image.new("L", (big, big), 0)
    if rounded and not maskable:
        ImageDraw.Draw(shape).rounded_rectangle([0, 0, big - 1, big - 1], radius=int(116 * s), fill=255)
    else:
        shape.paste(255, (0, 0, big, big))
    out = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    out.paste(bg, (0, 0), shape)
    d = ImageDraw.Draw(out)
    k = 0.8 if maskable else 1.0  # keep the glyph inside the maskable safe zone
    c = big / 2

    def p(x: float, y: float) -> tuple[float, float]:
        return (c + (x - 256) * s * k, c + (y - 256) * s * k)

    d.rounded_rectangle([*p(110, 110), *p(402, 402)], radius=int(84 * s * k), outline="white", width=int(34 * s * k))
    d.polygon([p(222, 186), p(222, 326), p(330, 256)], fill="white")
    cx, cy = p(338, 174)
    r = 17 * s * k
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill="white")
    return out.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    draw_icon(192).save(OUT / "icon-192.png")
    draw_icon(512).save(OUT / "icon-512.png")
    draw_icon(512, maskable=True).save(OUT / "icon-maskable-512.png")
    draw_icon(180, rounded=False).convert("RGB").save(OUT / "apple-touch-icon.png")
    print("icons written to", OUT)


if __name__ == "__main__":
    main()
