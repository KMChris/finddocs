"""Generuje ikony motywu: glify SVG oraz dwa obrazki PNG dla arkusza stylow.

Glify przyciskow i nawigacji sa zapisywane jako SVG w
``src/finddocs/resources/theme``. QIcon renderuje SVG ostro w kazdej skali,
wiec nie potrzeba wariantow ``@2x``. Wyjatkiem sa znacznik pola wyboru
i strzalka listy rozwijanej: te obrazki wstawia arkusz stylow przez
``image: url(...)``, a ta sciezka rasteryzuje obraz w rozmiarze bazowym,
wiec dla ostrosci na ekranach o podwojnej gestosci zostaja PNG z ``@2x``.

Kazdy glif jest zapisywany w kilku klasach kolorow:

* ``{nazwa}-{wariant}.svg``: kolor tekstu, na zwyklych przyciskach i w nawigacji
  (wyjatek: ``trash`` dostaje kolor ostrzegawczy, bo lezy na przycisku Danger);
* ``{nazwa}-muted-{wariant}.svg``: kolor wyciszony, dla stanu wylaczonego;
* ``{nazwa}-accent-{wariant}.svg``: kolor tekstu na tle akcentu, tylko dla
  glifow wystepujacych na przyciskach akcentowych.

Kolory odpowiadaja paletom z ``finddocs.gui.theme``. Skrypt uruchamia sie
tylko przy zmianie zestawu ikon:

    .venv/Scripts/python.exe tools/make_theme_icons.py
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "src" / "finddocs" / "resources" / "theme"

#: Kolory klas glifow wedlug wariantu palety (jasna, ciemna).
CLASS_COLORS: dict[str, tuple[str, str]] = {
    "text": ("#1b1b1b", "#f5f5f5"),
    "muted": ("#5d5d5d", "#b0b0b0"),
    "accent": ("#ffffff", "#0b1e28"),
    "danger": ("#c42b1c", "#ff99a4"),
}

Op = tuple[str, tuple[float, ...] | tuple[tuple[float, float], ...]]

#: Definicje glifow w ukladzie logicznym 16 na 16 pikseli.
#: Operacje: line (lamana), poly (zamkniety obrys), fill (wypelniony wielokat),
#: ellipse (obrys elipsy), arc (luk: prostokat, kat startu, rozpietosc w stopniach,
#: katy jak w Qt: 0 na godzinie trzeciej, dodatnie przeciwnie do wskazowek),
#: rrect (obrys prostokata zaokraglonego), frrect (wypelniony prostokat zaokraglony).
GLYPHS: dict[str, tuple[float, tuple[Op, ...]]] = {
    "search": (
        1.7,
        (
            ("ellipse", (3.0, 3.0, 8.0, 8.0)),
            ("line", ((10.2, 10.2), (13.2, 13.2))),
        ),
    ),
    "stop": (
        1.6,
        (("frrect", (4.2, 4.2, 7.6, 7.6, 1.6)),),
    ),
    "folder": (
        1.6,
        (("poly", ((2.2, 4.2), (6.4, 4.2), (7.8, 5.8), (13.8, 5.8), (13.8, 12.6), (2.2, 12.6))),),
    ),
    "copy": (
        1.6,
        (
            ("rrect", (2.8, 4.8, 8.4, 8.4, 1.6)),
            ("line", ((5.6, 2.8), (13.2, 2.8), (13.2, 10.4))),
        ),
    ),
    "refresh": (
        1.6,
        (
            ("arc", (3.4, 3.4, 9.2, 9.2, 30.0, 300.0)),
            ("fill", ((13.2, 8.2), (13.4, 11.1), (10.6, 9.5))),
        ),
    ),
    "database": (
        1.5,
        (
            ("ellipse", (3.6, 2.8, 8.8, 3.4)),
            ("line", ((3.6, 4.5), (3.6, 11.6))),
            ("line", ((12.4, 4.5), (12.4, 11.6))),
            ("arc", (3.6, 9.9, 8.8, 3.4, 180.0, 180.0)),
        ),
    ),
    "chart": (
        2.0,
        (
            ("line", ((4.4, 12.6), (4.4, 9.2))),
            ("line", ((8.0, 12.6), (8.0, 4.6))),
            ("line", ((11.6, 12.6), (11.6, 7.2))),
        ),
    ),
    "pulse": (
        1.6,
        (("line", ((2.0, 9.0), (5.0, 9.0), (6.6, 4.8), (9.2, 12.0), (10.9, 9.0), (14.0, 9.0))),),
    ),
    "play": (
        1.6,
        (("fill", ((5.4, 3.6), (5.4, 12.4), (12.6, 8.0))),),
    ),
    "pause": (
        2.2,
        (
            ("line", ((6.0, 4.2), (6.0, 11.8))),
            ("line", ((10.0, 4.2), (10.0, 11.8))),
        ),
    ),
    "cross": (
        1.7,
        (
            ("line", ((4.6, 4.6), (11.4, 11.4))),
            ("line", ((11.4, 4.6), (4.6, 11.4))),
        ),
    ),
    "plus": (
        1.7,
        (
            ("line", ((8.0, 3.6), (8.0, 12.4))),
            ("line", ((3.6, 8.0), (12.4, 8.0))),
        ),
    ),
    "trash": (
        1.5,
        (
            ("line", ((3.2, 5.2), (12.8, 5.2))),
            ("line", ((6.5, 4.9), (6.9, 3.2), (9.1, 3.2), (9.5, 4.9))),
            ("line", ((4.4, 5.6), (5.1, 13.0), (10.9, 13.0), (11.6, 5.6))),
        ),
    ),
    "export": (
        1.6,
        (
            ("line", ((3.0, 10.6), (3.0, 12.8), (13.0, 12.8), (13.0, 10.6))),
            ("line", ((8.0, 3.2), (8.0, 9.6))),
            ("line", ((5.6, 7.2), (8.0, 9.7), (10.4, 7.2))),
        ),
    ),
    "filter": (
        1.6,
        (("poly", ((2.8, 3.8), (13.2, 3.8), (9.4, 8.5), (9.4, 12.4), (6.6, 10.8), (6.6, 8.5))),),
    ),
    "chevron-left": (
        1.7,
        (("line", ((10.0, 3.9), (6.0, 8.0), (10.0, 12.1))),),
    ),
    "chevron-right": (
        1.7,
        (("line", ((6.0, 3.9), (10.0, 8.0), (6.0, 12.1))),),
    ),
}

#: Glify z dodatkowym wariantem na tle akcentu. Kazdy glif uzywany na przycisku
#: ``#Primary`` albo ``#PrimaryIcon`` musi tu byc, inaczej dostanie kolor tekstu
#: zwyklego przycisku i w trybie ciemnym bedzie jasny obok ciemnego napisu.
ACCENT_GLYPHS = ("search", "stop", "play", "refresh", "plus")

#: Glify, ktorych klasa podstawowa jest inna niz kolor tekstu.
PLAIN_CLASS_OVERRIDES = {"trash": "danger"}

GLYPH_SIZE = 16

#: Obrazki wpisane w arkusz stylow: nazwa, rozmiar, grubosc, klasa koloru, operacje.
STYLESHEET_ICONS: tuple[tuple[str, int, float, str, tuple[Op, ...]], ...] = (
    ("check", 12, 1.7, "accent", (("line", ((2.6, 6.4), (4.9, 8.7), (9.4, 3.4))),)),
    ("chevron", 16, 1.6, "muted", (("line", ((4.2, 6.4), (8.0, 10.2), (11.8, 6.4))),)),
)


def fmt(value: float) -> str:
    """Liczba w zapisie SVG, bez zbednych zer."""
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return text or "0"


def points_attr(data: tuple[tuple[float, float], ...]) -> str:
    return " ".join(f"{fmt(x)},{fmt(y)}" for x, y in data)


def arc_path(x: float, y: float, w: float, h: float, start: float, span: float) -> str:
    """Sciezka SVG luku zadanego po katach w konwencji Qt."""
    rx, ry = w / 2, h / 2
    cx, cy = x + rx, y + ry
    a1 = math.radians(start)
    a2 = math.radians(start + span)
    x1, y1 = cx + rx * math.cos(a1), cy - ry * math.sin(a1)
    x2, y2 = cx + rx * math.cos(a2), cy - ry * math.sin(a2)
    large = 1 if abs(span) > 180 else 0
    # Dodatnia rozpietosc to w Qt kierunek przeciwny do wskazowek zegara,
    # czyli sweep=0 w ukladzie SVG z osia Y w dol.
    sweep = 0 if span > 0 else 1
    return f"M {fmt(x1)} {fmt(y1)} A {fmt(rx)} {fmt(ry)} 0 {large} {sweep} {fmt(x2)} {fmt(y2)}"


def svg_element(
    kind: str, data: tuple[float, ...] | tuple[tuple[float, float], ...], color: str
) -> str:
    if kind == "line":
        return f'<polyline points="{points_attr(data)}"/>'  # type: ignore[arg-type]
    if kind == "poly":
        return f'<polygon points="{points_attr(data)}"/>'  # type: ignore[arg-type]
    if kind == "fill":
        return f'<polygon points="{points_attr(data)}" fill="{color}" stroke="none"/>'  # type: ignore[arg-type]
    if kind == "ellipse":
        x, y, w, h = data  # type: ignore[misc]
        return (
            f'<ellipse cx="{fmt(x + w / 2)}" cy="{fmt(y + h / 2)}"'
            f' rx="{fmt(w / 2)}" ry="{fmt(h / 2)}"/>'
        )
    if kind == "arc":
        x, y, w, h, start, span = data  # type: ignore[misc]
        return f'<path d="{arc_path(x, y, w, h, start, span)}"/>'
    if kind == "rrect":
        x, y, w, h, radius = data  # type: ignore[misc]
        return (
            f'<rect x="{fmt(x)}" y="{fmt(y)}" width="{fmt(w)}" height="{fmt(h)}"'
            f' rx="{fmt(radius)}"/>'
        )
    if kind == "frrect":
        x, y, w, h, radius = data  # type: ignore[misc]
        return (
            f'<rect x="{fmt(x)}" y="{fmt(y)}" width="{fmt(w)}" height="{fmt(h)}"'
            f' rx="{fmt(radius)}" fill="{color}" stroke="none"/>'
        )
    raise ValueError(f"Nieznana operacja rysowania: {kind}")


def svg_document(size: int, line_width: float, color: str, ops: tuple[Op, ...]) -> str:
    body = "".join(svg_element(kind, data, color) for kind, data in ops)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}"'
        f' viewBox="0 0 {size} {size}">'
        f'<g fill="none" stroke="{color}" stroke-width="{fmt(line_width)}"'
        f' stroke-linecap="round" stroke-linejoin="round">{body}</g></svg>\n'
    )


def variant_color(color_class: str, variant: str) -> str:
    light, dark = CLASS_COLORS[color_class]
    return light if variant == "light" else dark


def write_glyphs() -> int:
    count = 0
    for name, (line_width, ops) in GLYPHS.items():
        for variant in ("light", "dark"):
            plain_class = PLAIN_CLASS_OVERRIDES.get(name, "text")
            targets = [(f"{name}-{variant}", plain_class), (f"{name}-muted-{variant}", "muted")]
            if name in ACCENT_GLYPHS:
                targets.append((f"{name}-accent-{variant}", "accent"))
            for file_name, color_class in targets:
                color = variant_color(color_class, variant)
                document = svg_document(GLYPH_SIZE, line_width, color, ops)
                (OUTPUT_DIR / f"{file_name}.svg").write_text(document, encoding="utf-8")
                count += 1
    return count


def write_stylesheet_icons() -> int:
    """Rasteryzuje obrazki arkusza stylow do PNG w skali 1x i 2x."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen

    app = QGuiApplication(sys.argv[:1])
    count = 0
    for name, size, line_width, color_class, ops in STYLESHEET_ICONS:
        for variant in ("light", "dark"):
            color = variant_color(color_class, variant)
            for suffix, scale in (("", 1), ("@2x", 2)):
                image = QImage(size * scale, size * scale, QImage.Format.Format_ARGB32)
                image.fill(Qt.GlobalColor.transparent)
                painter = QPainter(image)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                pen = QPen(QColor(color))
                pen.setWidthF(line_width * scale)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(pen)
                for _kind, data in ops:
                    points = [QPointF(x * scale, y * scale) for x, y in data]  # type: ignore[misc]
                    painter.drawPolyline(points)
                painter.end()
                target = OUTPUT_DIR / f"{name}-{variant}{suffix}.png"
                if not image.save(str(target)):
                    raise RuntimeError(f"Nie udalo sie zapisac {target}")
                count += 1
    del app
    return count


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    svg_count = write_glyphs()
    png_count = write_stylesheet_icons()
    print(f"Zapisano {svg_count} plikow SVG i {png_count} plikow PNG w {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
