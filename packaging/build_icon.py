from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

SIZES = (16, 32, 128, 256, 512)


BACKGROUND = "#123D46"
BRACKET = "#73D7C7"
FOCUS_POINT = "#FFB45C"
BRACKET_RADIUS = 40

# Two rectangles per corner make one open focus bracket. The gaps between the
# corners stay wide enough to survive a 16x16 render.
BRACKETS = (
    (208, 208, 416, 312),
    (208, 208, 312, 416),
    (608, 208, 816, 312),
    (712, 208, 816, 416),
    (208, 608, 312, 816),
    (208, 712, 416, 816),
    (712, 608, 816, 816),
    (608, 712, 816, 816),
)
DIAMOND = ((512, 388), (636, 512), (512, 636), (388, 512))


def create_icon(size: int) -> Image.Image:
    scale = size / 1024
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    def box(values: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        return tuple(round(value * scale) for value in values)

    def point(values: tuple[int, int]) -> tuple[int, int]:
        return tuple(round(value * scale) for value in values)

    draw.rounded_rectangle(box((48, 48, 976, 976)), radius=round(220 * scale), fill=BACKGROUND)
    for bounds in BRACKETS:
        draw.rounded_rectangle(box(bounds), radius=round(BRACKET_RADIUS * scale), fill=BRACKET)
    draw.polygon([point(values) for values in DIAMOND], fill=FOCUS_POINT)
    return image


def main(output_directory: Path) -> int:
    output_directory.mkdir(parents=True, exist_ok=True)
    create_icon(1024).save(output_directory / "know-your-focus.png")
    iconset = output_directory / "know-your-focus.iconset"
    iconset.mkdir(exist_ok=True)
    for size in SIZES:
        create_icon(size).save(iconset / f"icon_{size}x{size}.png")
        create_icon(size * 2).save(iconset / f"icon_{size}x{size}@2x.png")
    return 0


if __name__ == "__main__":
    destination = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("packaging/generated")
    raise SystemExit(main(destination))
