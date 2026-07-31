"""Generator ikony aplikacji.

Ikona jest rysowana proceduralnie, zeby repozytorium nie musialo trzymac pliku
binarnego o niejasnym pochodzeniu i licencji. Motyw: lupa nad dokumentem.

Uzycie:

    python tools/make_icon.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

SIZES = (16, 24, 32, 48, 64, 128, 256)

BACKGROUND = (15, 108, 189, 255)
BACKGROUND_DARK = (11, 78, 138, 255)
PAPER = (255, 255, 255, 255)
PAPER_LINE = (180, 200, 220, 255)
GLASS = (255, 255, 255, 235)
GLASS_FILL = (140, 200, 255, 90)


def _rounded_background(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    radius = max(2, size // 5)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=BACKGROUND)
    draw.rounded_rectangle([0, size // 2, size - 1, size - 1], radius=radius, fill=BACKGROUND_DARK)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, outline=BACKGROUND_DARK)
    return image


def _draw_document(draw: ImageDraw.ImageDraw, size: int) -> None:
    left = size * 0.22
    top = size * 0.16
    right = size * 0.66
    bottom = size * 0.80
    fold = size * 0.13
    draw.polygon(
        [
            (left, top),
            (right - fold, top),
            (right, top + fold),
            (right, bottom),
            (left, bottom),
        ],
        fill=PAPER,
    )
    draw.polygon(
        [(right - fold, top), (right, top + fold), (right - fold, top + fold)], fill=PAPER_LINE
    )
    if size >= 32:
        line_width = max(1, size // 42)
        for index in range(3):
            y = top + size * (0.28 + index * 0.14)
            draw.line(
                [(left + size * 0.07, y), (right - size * 0.08, y)],
                fill=PAPER_LINE,
                width=line_width,
            )


def _draw_lens(draw: ImageDraw.ImageDraw, size: int) -> None:
    center = (size * 0.63, size * 0.62)
    radius = size * 0.21
    width = max(2, size // 16)
    box = [center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius]
    draw.ellipse(box, fill=GLASS_FILL, outline=GLASS, width=width)
    handle_start = (center[0] + radius * 0.72, center[1] + radius * 0.72)
    handle_end = (size * 0.88, size * 0.88)
    draw.line([handle_start, handle_end], fill=GLASS, width=width + max(1, size // 32))


def build_icon_image(size: int) -> Image.Image:
    """Rysuje pojedynczy rozmiar ikony."""
    scale = 4 if size < 64 else 2
    canvas = size * scale
    image = _rounded_background(canvas)
    draw = ImageDraw.Draw(image)
    _draw_document(draw, canvas)
    _draw_lens(draw, canvas)
    return image.resize((size, size), Image.Resampling.LANCZOS)


def write_icon(target: Path) -> Path:
    """Zapisuje plik ICO ze wszystkimi rozmiarami oraz podglad PNG."""
    target.parent.mkdir(parents=True, exist_ok=True)
    images = [build_icon_image(size) for size in SIZES]
    images[-1].save(target, format="ICO", sizes=[(s, s) for s in SIZES])
    png = target.with_suffix(".png")
    images[-1].save(png, format="PNG")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generuje ikone FindDocs")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("src/finddocs/resources/finddocs.ico"),
        help="sciezka pliku ICO",
    )
    args = parser.parse_args(argv)
    path = write_icon(args.output)
    print(f"Zapisano {path} oraz {path.with_suffix('.png')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
