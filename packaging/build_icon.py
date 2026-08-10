from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

SIZES = (16, 32, 128, 256, 512)


def create_icon(size: int) -> Image.Image:
    scale = size / 1024
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    def box(values: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        return tuple(round(value * scale) for value in values)

    draw.rounded_rectangle(box((48, 48, 976, 976)), radius=round(220 * scale), fill="#123D46")
    draw.rounded_rectangle(box((178, 215, 846, 710)), radius=round(64 * scale), fill="#EAF7F4")
    draw.ellipse(box((354, 315, 670, 631)), fill="#2A8C82")
    draw.ellipse(box((446, 407, 578, 539)), fill="#123D46")
    draw.rounded_rectangle(box((425, 714, 599, 785)), radius=round(24 * scale), fill="#EAF7F4")
    draw.rounded_rectangle(box((320, 776, 704, 832)), radius=round(28 * scale), fill="#EAF7F4")
    draw.rounded_rectangle(box((688, 500, 858, 822)), radius=round(38 * scale), fill="#FF9C52")
    draw.ellipse(box((754, 755, 792, 793)), fill="#123D46")
    return image


def main(output_directory: Path) -> int:
    output_directory.mkdir(parents=True, exist_ok=True)
    create_icon(1024).save(output_directory / "desk-focus.png")
    iconset = output_directory / "desk-focus.iconset"
    iconset.mkdir(exist_ok=True)
    for size in SIZES:
        create_icon(size).save(iconset / f"icon_{size}x{size}.png")
        create_icon(size * 2).save(iconset / f"icon_{size}x{size}@2x.png")
    return 0


if __name__ == "__main__":
    destination = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("packaging/generated")
    raise SystemExit(main(destination))
