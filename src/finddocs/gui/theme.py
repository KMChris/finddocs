"""Wyglad aplikacji zgodny z Windows 11.

Motyw opiera sie na palecie Fluent: jasne tlo warstwowe, zaokraglone rogi,
subtelne obramowania i akcent systemowy. Wersja ciemna jest wybierana
automatycznie, gdy system zglasza ciemny motyw.

Trzy zasady, ktore latwo zepsuc:

1. Uniwersalna regula ``QWidget`` NIE ustawia tla. Ustawienie tla na kazdej
   kontrolce sprawia, ze etykiety maluja pod tekstem prostokat w kolorze tla
   aplikacji, takze wtedy, gdy leza na bialej karcie. Tlo maja tylko okna
   najwyzszego poziomu i kontrolki, ktore naprawde je potrzebuja.
2. Przyciski przyjmuja fokus wylacznie z klawiatury (:class:`TabFocusStyle`).
   Po kliknieciu myszka nie zostaje na nich ramka zaznaczenia.
3. Kropkowana ramka fokusa jest wylaczona przez ``outline: none``. Zamiast
   niej fokus z klawiatury ma wlasny, wyrazny styl obramowania.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

# Ikony motywu sa w SVG. Sam import wystarcza, zeby PyInstaller dolaczyl
# biblioteke Qt6Svg i wtyczki SVG do pakietu; w kodzie modul nie jest uzywany.
import PySide6.QtSvg  # noqa: F401
from PySide6.QtCore import QEvent, QObject, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPalette
from PySide6.QtWidgets import QApplication, QProxyStyle, QStyle, QStyleOption, QWidget

#: Rodziny pisma w kolejnosci preferencji. Pierwsza zainstalowana wygrywa.
#:
#: ``Segoe UI Variable Text`` wyglada nowocześniej, ale Qt widzi w tej rodzinie
#: tylko dwa kroje: Regular i Bold. Stopien 600 awansuje wtedy do 700, wiec
#: tytul obok tekstu podstawowego robi skok z 400 na 700 i cala strona wyglada
#: na zlozona z dwoch roznych pism. ``Segoe UI`` ma prawdziwy krój Semibold,
#: dlatego hierarchia 400 / 600 / 700 jest rowna. Semibold z rodziny Variable
#: jest w systemie osobna rodzina, ktorej Qt nie kojarzy z podstawowa.
FONT_CANDIDATES: tuple[str, ...] = ("Segoe UI", "Inter", "Noto Sans", "DejaVu Sans")

#: Rodzina uzywana, gdy nie da sie zapytac systemu o liste zainstalowanych.
FONT_FAMILY = FONT_CANDIDATES[0]

MONO_FAMILY = "Cascadia Mono, Consolas, monospace"

#: Skala typografii w punktach. Interfejs uzywa tylko tych stopni pisma.
#: Kazdy kolejny jest wyraznie wieszy od poprzedniego, wiec hierarchia jest
#: widoczna bez pogrubien i kolorow.
FONT_SIZE_SMALL = 9
FONT_SIZE = 10
FONT_SIZE_TITLE = 12
FONT_SIZE_QUERY = 13
FONT_SIZE_BRAND = 15
FONT_SIZE_PAGE = 17

#: Skala odstepow. Uklady biora marginesy i przerwy wylacznie z tej skali,
#: dlatego pionowy rytm ekranow jest ten sam bez zmawiania sie widokow.
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24

#: Marginesy wewnetrzne ekranu: lewy, gorny, prawy, dolny.
PAGE_MARGINS = (SPACE_XL, SPACE_LG, SPACE_XL, SPACE_LG)

RADIUS_SMALL = 6
RADIUS = 8
RADIUS_LARGE = 12
#: Promien plakietki i kropki stanu: polowa wysokosci, czyli pelne zaokraglenie.
RADIUS_PILL = 10

#: Bok kwadratowego przycisku ikonowego oraz wysokosc pola zapytania.
ICON_BUTTON_SIZE = 30
QUERY_HEIGHT = 44

#: Katalog z malymi obrazkami motywu (znacznik wyboru, strzalka listy).
#: Pliki generuje ``tools/make_theme_icons.py``.
ICON_DIR = Path(__file__).resolve().parents[1] / "resources" / "theme"


@dataclass(frozen=True, slots=True)
class Palette:
    """Zestaw kolorow motywu."""

    background: str
    surface: str
    surface_alt: str
    border: str
    text: str
    text_muted: str
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_text: str
    success: str
    warning: str
    danger: str
    highlight: str
    highlight_text: str
    #: Wariant obrazkow motywu: "light" albo "dark".
    variant: str = "light"


LIGHT = Palette(
    background="#f3f3f3",
    surface="#ffffff",
    surface_alt="#fafafa",
    border="#e1e1e1",
    text="#1b1b1b",
    text_muted="#5d5d5d",
    accent="#0f6cbd",
    accent_hover="#115ea3",
    accent_pressed="#0c3b5e",
    accent_text="#ffffff",
    success="#0f7b0f",
    warning="#9d5d00",
    danger="#c42b1c",
    highlight="#fff3bf",
    highlight_text="#3d2c00",
    variant="light",
)

DARK = Palette(
    background="#202020",
    surface="#2b2b2b",
    surface_alt="#323232",
    border="#3d3d3d",
    text="#f5f5f5",
    text_muted="#b0b0b0",
    accent="#4cc2ff",
    accent_hover="#69cbff",
    accent_pressed="#3aa0d8",
    accent_text="#0b1e28",
    success="#6ccb5f",
    warning="#fce100",
    danger="#ff99a4",
    highlight="#5c4a00",
    highlight_text="#ffeaa0",
    variant="dark",
)


#: Kolory plakietek na karcie wyniku: rola -> (tlo, tekst), osobno dla palet.
#: Kolor dostaja tylko role niosace znaczenie: rodzaj dopasowania, OCR i sila
#: dopasowania. Metadane (typ pliku, data, autor) schodza do stylu domyslnego
#: plakietki, czyli neutralnej szarosci. Data w kolorze sukcesu i autor
#: w kolorze ostrzezenia sugerowaly stany, ktorych nie ma, a rzad pieciu
#: barwnych pigulek na kazdej karcie dawal szum silniejszy niz tresc fragmentu.
BADGE_COLORS: dict[str, dict[str, tuple[str, str]]] = {
    "light": {
        "match": ("#e8f1fb", "#0b5394"),
        "ocr": ("#fff3bf", "#6b5300"),
        "score-high": ("#e3f4e3", "#0f7b0f"),
        "score-mid": ("#fdf2df", "#9d5d00"),
        "score-low": ("#ececec", "#5d5d5d"),
    },
    "dark": {
        "match": ("#1d3a54", "#9ed0ff"),
        "ocr": ("#5c4a00", "#ffeaa0"),
        "score-high": ("#1e3b1e", "#95dd95"),
        "score-mid": ("#453309", "#f2d67c"),
        "score-low": ("#3a3a3a", "#b0b0b0"),
    },
}


#: Kolory banera komunikatu: rola -> (tlo, obramowanie i tekst).
#: Baner niesie jedno zdanie o stanie ekranu, wiec kolor musi byc czytelny
#: bez ikony i bez czytania tresci.
BANNER_COLORS: dict[str, dict[str, tuple[str, str]]] = {
    "light": {
        "success": ("#e6f4e6", "#0f7b0f"),
        "warning": ("#fdf3e2", "#9d5d00"),
        "info": ("#e8f1fb", "#0b5394"),
    },
    "dark": {
        "success": ("#1c3520", "#93d7a7"),
        "warning": ("#3d2f0c", "#f2d67c"),
        "info": ("#1d3145", "#9ed0ff"),
    },
}

#: Kolory kropki stanu w pasku okna: rola -> kolor wypelnienia.
DOT_COLORS: dict[str, dict[str, str]] = {
    "light": {"ok": "#0f7b0f", "warn": "#9d5d00", "off": "#8a8a8a"},
    "dark": {"ok": "#6ccb5f", "warn": "#fce100", "off": "#8a8a8a"},
}


class TabFocusStyle(QProxyStyle):
    """Styl, w ktorym przyciski przyjmuja fokus tylko z klawiatury.

    Domyslnie na Windows klikniety przycisk zatrzymuje fokus i rysuje na sobie
    ramke zaznaczenia, ktora zostaje do nastepnego kliknieciu gdzie indziej.
    Ten styl zmienia polityke fokusa przyciskow na ``TabFocus``: klikniecie
    tylko wykonuje akcje, a ramke fokusa widza wylacznie osoby poruszajace sie
    klawiszem Tab.
    """

    def styleHint(
        self,
        hint: QStyle.StyleHint,
        option: QStyleOption | None = None,
        widget: QWidget | None = None,
        returnData: Any = None,
    ) -> int:
        if hint == QStyle.StyleHint.SH_Button_FocusPolicy:
            return int(Qt.FocusPolicy.TabFocus.value)
        return super().styleHint(hint, option, widget, returnData)


#: Rodzina rozwiazana raz, przy pierwszym pytaniu. Lista zainstalowanych rodzin
#: nie zmienia sie w trakcie dzialania aplikacji.
_resolved_family: str | None = None


def font_family() -> str:
    """Pierwsza zainstalowana rodzina z ``FONT_CANDIDATES``.

    Arkusz stylow i ``QFont`` musza dostac te sama, jedna nazwe rodziny. Lista
    rozdzielona przecinkami dziala w obu miejscach, ale wtedy nie wiadomo, ktora
    rodzina naprawde jest uzywana, a od tego zalezy dostepnosc kroju Semibold.
    """
    global _resolved_family
    if _resolved_family is not None:
        return _resolved_family
    if QApplication.instance() is None:
        # Bez aplikacji Qt nie ma bazy czcionek. Zwracamy pierwszego kandydata,
        # zeby arkusz stylow dal sie zbudowac takze w tescie bez okna.
        return FONT_CANDIDATES[0]
    installed = set(QFontDatabase.families())
    _resolved_family = next(
        (family for family in FONT_CANDIDATES if family in installed), FONT_CANDIDATES[0]
    )
    return _resolved_family


def is_dark_mode(app: QApplication) -> bool:
    """Czy system albo aplikacja uzywaja ciemnego motywu."""
    color = app.palette().color(QPalette.ColorRole.Window)
    return color.lightness() < 128


def resolve_palette(app: QApplication, preference: str = "system") -> Palette:
    if preference == "dark":
        return DARK
    if preference == "light":
        return LIGHT
    return DARK if is_dark_mode(app) else LIGHT


# --- akcent systemowy --------------------------------------------------------


def _relative_luminance(color: QColor) -> float:
    """Luminancja wzgledna wedlug WCAG."""

    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * channel(color.red())
        + 0.7152 * channel(color.green())
        + 0.0722 * channel(color.blue())
    )


def contrast_ratio(first: QColor, second: QColor) -> float:
    """Wspolczynnik kontrastu WCAG dwoch kolorow."""
    a = _relative_luminance(first)
    b = _relative_luminance(second)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


#: Minimalny kontrast napisu na akcencie. Prog tekstu normalnego z WCAG AA.
MIN_ACCENT_CONTRAST = 4.5


def _adjusted_for_text(color: QColor, text: QColor) -> QColor:
    """Przesuwa jasnosc akcentu, az napis na nim osiagnie wymagany kontrast.

    Kolor tekstu na akcencie jest staly (bialy w palecie jasnej, ciemny
    w ciemnej), bo w tych kolorach sa wygenerowane glify przyciskow
    akcentowych. Dopasowujemy wiec akcent do tekstu, nie odwrotnie.
    """
    adjusted = QColor(color)
    darken_text = _relative_luminance(text) < 0.5
    for _step in range(40):
        if contrast_ratio(adjusted, text) >= MIN_ACCENT_CONTRAST:
            break
        hue = adjusted.hslHueF()
        saturation = adjusted.hslSaturationF()
        shift = 0.02 if darken_text else -0.02
        lightness = min(0.95, max(0.05, adjusted.lightnessF() + shift))
        adjusted.setHslF(hue, saturation, lightness)
    return adjusted


def palette_with_accent(palette: Palette, accent: QColor | None) -> Palette:
    """Paleta z akcentem zbudowanym z podanego koloru.

    ``None`` zostawia domyslny niebieski. Warianty najechania i wcisniecia
    ida w te same strony, co w palecie domyslnej: w jasnej akcent ciemnieje,
    w ciemnej najechanie rozjasnia, a wcisniecie przyciemnia.
    """
    if accent is None or not accent.isValid():
        return palette
    base = _adjusted_for_text(accent, QColor(palette.accent_text))
    if palette.variant == "light":
        hover = base.darker(112)
        pressed = base.darker(145)
    else:
        hover = base.lighter(112)
        pressed = base.darker(112)
    return replace(
        palette,
        accent=base.name(),
        accent_hover=hover.name(),
        accent_pressed=pressed.name(),
    )


#: Atrybuty DWM wlaczajace ciemny pasek tytulu. Nowsze kompilacje Windows
#: uzywaja wartosci 20, starsze (przed 20H1) wartosci 19.
_DWMWA_USE_IMMERSIVE_DARK_MODE = (20, 19)


def apply_title_bar_theme(window: QWidget, *, dark: bool | None = None) -> None:
    """Dopasowuje kolor paska tytulu okna do motywu aplikacji.

    Qt przelacza pasek tytulu za motywem systemu, ale nie za motywem
    wymuszonym w aplikacji: przy jasnym systemie i ciemnym motywie pasek
    zostawal bialy. Niepowodzenie wywolania jest ignorowane, pasek zostaje
    wtedy systemowy (starsze kompilacje Windows, pulpit zdalny).
    """
    if sys.platform != "win32" or not window.isWindow():
        return
    handle = int(window.winId())
    if not handle:
        return
    import ctypes

    value = ctypes.c_int(
        1 if (dark if dark is not None else _active_palette.variant == "dark") else 0
    )
    for attribute in _DWMWA_USE_IMMERSIVE_DARK_MODE:
        try:
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(handle),
                ctypes.c_uint(attribute),
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
        except OSError:
            return
        if result == 0:
            return


#: Atrybut DWM typu tla okna oraz wartosc Mica dla okna glownego.
_DWMWA_SYSTEMBACKDROP_TYPE = 38
_DWMSBT_MAINWINDOW = 2

#: Najstarsza kompilacja Windows 11 z publicznym API tla systemowego (22H2).
_MICA_MIN_BUILD = 22621


def mica_supported() -> bool:
    """Czy system obsluguje tlo Mica okna."""
    if sys.platform != "win32":
        return False
    try:
        return sys.getwindowsversion().build >= _MICA_MIN_BUILD
    except OSError:
        return False


def enable_mica(window: QWidget) -> bool:
    """Wlacza tlo Mica dla okna. Zwraca, czy sie powiodlo.

    Fallback jest twardy: kazde niepowodzenie zostawia okno w obecnym,
    nieprzezroczystym wygladzie (starsze kompilacje Windows, pulpit zdalny,
    wylaczona przezroczystosc systemu).
    """
    if not mica_supported() or not window.isWindow():
        return False
    import ctypes

    class _Margins(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_int),
            ("right", ctypes.c_int),
            ("top", ctypes.c_int),
            ("bottom", ctypes.c_int),
        ]

    handle = ctypes.c_void_p(int(window.winId()))
    value = ctypes.c_int(_DWMSBT_MAINWINDOW)
    try:
        result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            handle,
            ctypes.c_uint(_DWMWA_SYSTEMBACKDROP_TYPE),
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
        if result != 0:
            return False
        margins = _Margins(-1, -1, -1, -1)
        ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(handle, ctypes.byref(margins))
    except OSError:
        return False
    return True


def _rgba(color: str, alpha: float) -> str:
    """Kolor szesnastkowy jako rgba() z zadanym kryciem."""
    parsed = QColor(color)
    return f"rgba({parsed.red()}, {parsed.green()}, {parsed.blue()}, {alpha:.2f})"


#: Krycie powierzchni lezacych bezposrednio na tle Mica.
MICA_SURFACE_ALPHA = 0.65


def mica_window_css(palette: Palette) -> str:
    """Nadpisania stylu okna glownego z wlaczonym tlem Mica.

    Okno staje sie przezroczyste, a panel nawigacji i pasek stanu dostaja
    polprzezroczyste tla, przez ktore przebija material systemowy. Karty
    i pola pozostaja nieprzezroczyste: to na nich jest tresc.
    """
    p = palette
    return f"""
    QMainWindow {{
        background: transparent;
    }}
    #Sidebar {{
        background-color: {_rgba(p.surface_alt, MICA_SURFACE_ALPHA)};
    }}
    QStatusBar {{
        background-color: {_rgba(p.surface_alt, MICA_SURFACE_ALPHA)};
    }}
    """


class _TitleBarFilter(QObject):
    """Nadaje motyw paska tytulu kazdemu pokazywanemu oknu, takze dialogom."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() is QEvent.Type.Show and isinstance(watched, QWidget) and watched.isWindow():
            apply_title_bar_theme(watched)
        return False


#: Filtr zainstalowany raz przez ``apply_theme``.
_title_bar_filter: _TitleBarFilter | None = None


def system_accent_color() -> QColor | None:
    """Kolor akcentu Windows z rejestru DWM albo ``None``.

    Rejestr, a nie paleta Qt: paleta aplikacji jest nadpisywana przez motyw,
    wiec po pierwszym ``apply_theme`` nie byloby jak odczytac wartosci
    systemowej. Wpis ``AccentColor`` ma uklad AABBGGRR.
    """
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM") as key:
            value, _kind = winreg.QueryValueEx(key, "AccentColor")
    except OSError:
        return None
    raw = int(value)
    color = QColor(raw & 0xFF, (raw >> 8) & 0xFF, (raw >> 16) & 0xFF)
    return color if color.isValid() else None


def _icon_url(name: str, variant: str) -> str:
    """Sciezka obrazka motywu w postaci akceptowanej przez arkusz stylow."""
    return (ICON_DIR / f"{name}-{variant}.png").as_posix()


#: Paleta ostatnio zastosowana przez ``apply_theme``. Widoki, ktore nie dostaja
#: palety w konstruktorze, biora z niej wariant ikon.
_active_palette: Palette = LIGHT


def active_palette() -> Palette:
    """Paleta ostatnio zastosowana przez ``apply_theme`` (domyslnie jasna)."""
    return _active_palette


def _compose_icon(normal_name: str, name: str, variant: str) -> QIcon:
    """Ikona z wariantem wyciszonym dla stanu wylaczonego przycisku."""
    icon = QIcon(str(ICON_DIR / f"{normal_name}-{variant}.svg"))
    icon.addFile(str(ICON_DIR / f"{name}-muted-{variant}.svg"), QSize(), QIcon.Mode.Disabled)
    return icon


def theme_icon(name: str, palette: Palette | None = None) -> QIcon:
    """Ikona motywu w kolorze tekstu, dopasowana do aktywnej palety."""
    variant = (palette or _active_palette).variant
    return _compose_icon(name, name, variant)


def accent_icon(name: str, palette: Palette | None = None) -> QIcon:
    """Ikona na przycisk akcentowy: jasny glif, wyciszony gdy przycisk wylaczony."""
    variant = (palette or _active_palette).variant
    return _compose_icon(f"{name}-accent", name, variant)


def muted_icon(name: str, palette: Palette | None = None) -> QIcon:
    """Ikona ozdobna w kolorze wyciszonym, do stanow pustych."""
    variant = (palette or _active_palette).variant
    return QIcon(str(ICON_DIR / f"{name}-muted-{variant}.svg"))


def build_stylesheet(palette: Palette) -> str:
    """Arkusz stylow Qt dla calej aplikacji."""
    p = palette
    check = _icon_url("check", p.variant)
    chevron = _icon_url("chevron", p.variant)
    light = p.variant == "light"
    # Wypelnienie kontrolek (przyciski, pola formularzy): w jasnym motywie
    # biala powierzchnia, w ciemnym odcien wyraznie jasniejszy od kart.
    # Kontrolka w kolorze karty zlewala sie z nia i zostawala sama ramka,
    # a stan wylaczony (surface_alt) byl jasniejszy od wlaczonego.
    if light:
        control_bg = p.surface
        control_hover = p.surface_alt
        control_pressed = p.border
    else:
        surface = QColor(p.surface)
        control_bg = surface.lighter(128).name()
        control_hover = surface.lighter(150).name()
        control_pressed = surface.lighter(112).name()
    # Tlo najechania na przycisk ikonowy lezacy na bialej karcie musi byc
    # ciemniejsze niz karta, a w trybie ciemnym jasniejsze.
    icon_hover = p.background if light else control_bg
    # Wstawka z fragmentem tekstu lezy na karcie, czyli na najjasniejszej
    # powierzchnii motywu. W jasnej palecie ``surface_alt`` byloby na niej
    # niewidoczne, dlatego bierzemy tlo aplikacji.
    inset = p.background if light else p.surface_alt
    # Suwak i obramowanie najechania podajemy z przezroczystoscia, zeby dzialaly
    # nad kazda powierzchnia i nie wymagaly osobnych kolorow w palecie.
    scroll = "rgba(0, 0, 0, 0.24)" if light else "rgba(255, 255, 255, 0.28)"
    scroll_hover = "rgba(0, 0, 0, 0.40)" if light else "rgba(255, 255, 255, 0.45)"
    card_hover = "rgba(0, 0, 0, 0.18)" if light else "rgba(255, 255, 255, 0.24)"
    # Przycisk wylaczony lezy najczesciej na bialej karcie, gdzie roznica tla
    # surface/surface_alt jest niewidoczna. Stan wylaczony musi wiec oslabiac
    # takze obramowanie, nie tylko kolor napisu.
    disabled_border = "#ececec" if light else "#343434"
    # Tla pozycji nawigacji sa neutralne, a kolor zaznaczenia niesie pigulka
    # akcentu. Dwa poziomy przezroczystosci wystarcza, zeby najechanie rozniilo
    # sie od zaznaczenia w obu wariantach palety.
    nav_hover = "rgba(0, 0, 0, 0.04)" if light else "rgba(255, 255, 255, 0.05)"
    nav_selected = "rgba(0, 0, 0, 0.07)" if light else "rgba(255, 255, 255, 0.09)"
    badge_rules = "\n".join(
        f'QLabel#Badge[badgeRole="{role}"] {{'
        f" background-color: {bg}; color: {fg}; border-color: transparent; }}"
        for role, (bg, fg) in BADGE_COLORS[p.variant].items()
    )
    banner_rules = "\n".join(
        f'QFrame#Banner[bannerRole="{role}"] {{'
        f" background-color: {bg}; border: 1px solid {fg}; }}"
        f'\nQFrame#Banner[bannerRole="{role}"] QLabel {{ color: {fg}; }}'
        for role, (bg, fg) in BANNER_COLORS[p.variant].items()
    )
    dot_rules = "\n".join(
        f'QLabel#StatusDot[dotRole="{role}"] {{ background-color: {color}; }}'
        for role, color in DOT_COLORS[p.variant].items()
    )
    return f"""
    QWidget {{
        color: {p.text};
        font-family: "{font_family()}";
        font-size: {FONT_SIZE}pt;
        font-weight: 400;
    }}
    QMainWindow, QDialog {{
        background-color: {p.background};
    }}
    QLabel, QCheckBox, QRadioButton {{
        background: transparent;
    }}
    #Sidebar {{
        background-color: {p.surface_alt};
        border-right: 1px solid {p.border};
    }}
    #SidebarList {{
        background: transparent;
        border: none;
        padding: {SPACE_SM}px {SPACE_XS + 2}px;
        outline: none;
    }}
    /* Pozycja nawigacji: samo tlo i zaokraglenie. Wskaznik zaznaczenia rysuje
       delegat z ``widgets/nav.py``, bo obramowanie przyciete zaokragleniem
       wygladalo jak zakrzywiony pasek. Lewy odstep robi miejsce na pigulke. */
    #SidebarList::item {{
        padding: 10px 12px 10px 24px;
        border-radius: {RADIUS}px;
        margin: 2px 6px;
        color: {p.text};
        border: none;
    }}
    #SidebarList::item:selected {{
        background-color: {nav_selected};
        color: {p.text};
    }}
    #SidebarList::item:hover:!selected {{
        background-color: {nav_hover};
    }}
    #AppTitle {{
        font-size: {FONT_SIZE_BRAND}pt;
        font-weight: 600;
    }}
    #AppSubtitle {{
        color: {p.text_muted};
        font-size: {FONT_SIZE_SMALL}pt;
    }}
    QLabel#PageTitle {{
        font-size: {FONT_SIZE_PAGE}pt;
        font-weight: 600;
    }}
    QLabel#PageMeta {{
        color: {p.text_muted};
    }}
    QLabel#SectionTitle {{
        font-size: {FONT_SIZE_TITLE}pt;
        font-weight: 600;
        padding-top: {SPACE_XS + 2}px;
    }}
    QLabel#Muted, QLabel#Hint {{
        color: {p.text_muted};
    }}
    QLabel#Hint {{
        font-size: {FONT_SIZE_SMALL}pt;
    }}
    QLabel#StatCaption {{
        color: {p.text_muted};
        font-size: {FONT_SIZE_SMALL}pt;
    }}
    QLabel#StatValue {{
        font-size: {FONT_SIZE_BRAND}pt;
        font-weight: 600;
    }}
    QLabel#StatValue[valueRole="danger"] {{
        color: {p.danger};
    }}
    QFrame#Divider {{
        background-color: {p.border};
        border: none;
    }}
    QFrame#Card, QGroupBox {{
        background-color: {p.surface};
        border: 1px solid {p.border};
        border-radius: {RADIUS_LARGE}px;
    }}
    QGroupBox {{
        margin-top: 26px;
        padding: {RADIUS_SMALL}px;
        font-size: {FONT_SIZE_TITLE}pt;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 2px;
        top: 2px;
        padding: 0;
        background: transparent;
    }}
    QLineEdit, QComboBox, QDateEdit, QSpinBox, QPlainTextEdit, QTextEdit {{
        background-color: {control_bg};
        border: 1px solid {p.border};
        border-bottom: 2px solid {p.border};
        border-radius: {RADIUS}px;
        padding: 7px 10px;
        selection-background-color: {p.accent};
        selection-color: {p.accent_text};
    }}
    QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus,
    QPlainTextEdit:focus, QTextEdit:focus {{
        border-bottom: 2px solid {p.accent};
    }}
    QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled, QSpinBox:disabled {{
        color: {p.text_muted};
        background-color: {p.surface_alt};
    }}
    /* Pole oznaczone jako brakujace w walidacji formularza. Wlasciwosc ustawia
       formularz, a edycja pola ja zdejmuje. */
    QLineEdit[fieldInvalid="true"], QComboBox[fieldInvalid="true"] {{
        border: 1px solid {p.danger};
        border-bottom: 2px solid {p.danger};
    }}
    QLabel#FormError {{
        color: {p.danger};
    }}
    QLineEdit#SearchBox {{
        font-size: {FONT_SIZE_QUERY}pt;
        padding: 11px 14px;
    }}
    QComboBox::drop-down, QDateEdit::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: center right;
        border: none;
        width: 26px;
    }}
    QComboBox::down-arrow, QDateEdit::down-arrow {{
        image: url("{chevron}");
        width: 16px;
        height: 16px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {p.surface};
        border: 1px solid {p.border};
        border-radius: {RADIUS}px;
        selection-background-color: {p.accent};
        selection-color: {p.accent_text};
        padding: 4px;
        outline: none;
    }}
    QComboBox QAbstractItemView::item {{
        padding: 6px 8px;
        border-radius: {RADIUS - 2}px;
    }}
    QComboBox QAbstractItemView::item:hover,
    QComboBox QAbstractItemView::item:selected {{
        background-color: {p.accent};
        color: {p.accent_text};
    }}
    QPushButton {{
        background-color: {control_bg};
        border: 1px solid {p.border};
        border-radius: {RADIUS}px;
        padding: 8px 16px;
        min-height: 18px;
        outline: none;
    }}
    QPushButton:hover {{
        background-color: {control_hover};
    }}
    QPushButton:pressed {{
        background-color: {control_pressed};
    }}
    QPushButton:focus {{
        border: 1px solid {p.accent};
    }}
    QPushButton:disabled {{
        color: {p.text_muted};
        background-color: {p.surface_alt};
        border: 1px solid {disabled_border};
    }}
    QPushButton#Primary {{
        background-color: {p.accent};
        color: {p.accent_text};
        border: 1px solid {p.accent};
        font-weight: 600;
    }}
    QPushButton#Primary:hover {{
        background-color: {p.accent_hover};
    }}
    QPushButton#Primary:pressed {{
        background-color: {p.accent_pressed};
    }}
    QPushButton#Primary:focus {{
        border: 1px solid {p.text};
    }}
    QPushButton#Primary:disabled {{
        color: {p.text_muted};
        background-color: {p.surface_alt};
        border: 1px solid {disabled_border};
    }}
    QPushButton#Danger {{
        color: {p.danger};
    }}
    /* Selektor z identyfikatorem wygrywa specyficznoscia z sama pseudoklasa,
       wiec bez tej reguly wylaczony przycisk Danger zostalby czerwony
       i wygladal na klikalny. */
    QPushButton#Danger:disabled {{
        color: {p.text_muted};
    }}
    QPushButton#Link {{
        background: transparent;
        border: none;
        color: {p.accent};
        text-align: left;
        padding: 4px 2px;
    }}
    QPushButton#Link:hover, QPushButton#Link:focus {{
        text-decoration: underline;
    }}
    /* Chip aktywnego filtra: pigulka z krzyzykiem, klikniecie zdejmuje filtr. */
    QPushButton#FilterChip {{
        background-color: {p.surface_alt};
        border: 1px solid {p.border};
        border-radius: {RADIUS_PILL}px;
        padding: 2px 10px;
        font-size: {FONT_SIZE_SMALL}pt;
        color: {p.text};
        min-height: 0;
    }}
    QPushButton#FilterChip:hover {{
        border-color: {p.accent};
        background-color: {p.surface_alt};
    }}
    QPushButton#Segment {{
        padding: 7px 18px;
        border-radius: 0;
    }}
    QPushButton#Segment[segmentPos="first"], QPushButton#Segment[segmentPos="only"] {{
        border-top-left-radius: {RADIUS}px;
        border-bottom-left-radius: {RADIUS}px;
    }}
    QPushButton#Segment[segmentPos="last"], QPushButton#Segment[segmentPos="only"] {{
        border-top-right-radius: {RADIUS}px;
        border-bottom-right-radius: {RADIUS}px;
    }}
    /* Sasiadujace segmenty leza bez przerwy, wiec tylko pierwszy z nich rysuje
       lewa krawedz. Inaczej granica miedzy segmentami mialaby dwa piksele. */
    QPushButton#Segment[segmentPos="middle"], QPushButton#Segment[segmentPos="last"] {{
        border-left: none;
    }}
    QPushButton#Segment:checked {{
        background-color: {p.accent};
        color: {p.accent_text};
        border: 1px solid {p.accent};
        font-weight: 600;
    }}
    QPushButton#Segment:checked:hover {{
        background-color: {p.accent_hover};
        border: 1px solid {p.accent_hover};
    }}
    QPushButton#Segment:checked:focus {{
        border: 1px solid {p.text};
    }}
    QPushButton#IconButton {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: {RADIUS - 2}px;
        padding: 0;
        min-height: 0;
    }}
    QPushButton#IconButton:hover {{
        background-color: {icon_hover};
    }}
    QPushButton#IconButton:pressed {{
        background-color: {p.border};
    }}
    QPushButton#IconButton:focus {{
        border: 1px solid {p.accent};
    }}
    QPushButton#PrimaryIcon {{
        background-color: {p.accent};
        border: 1px solid {p.accent};
        border-radius: {RADIUS}px;
        padding: 0;
    }}
    QPushButton#PrimaryIcon:hover {{
        background-color: {p.accent_hover};
    }}
    QPushButton#PrimaryIcon:pressed {{
        background-color: {p.accent_pressed};
    }}
    QPushButton#PrimaryIcon:focus {{
        border: 1px solid {p.text};
    }}
    QPushButton#PrimaryIcon:disabled {{
        background-color: {p.surface_alt};
        border: 1px solid {disabled_border};
    }}
    QFrame#ResultCard {{
        background-color: {p.surface};
        border: 1px solid {p.border};
        border-radius: {RADIUS_LARGE}px;
    }}
    QFrame#ResultCard:hover {{
        border: 1px solid {card_hover};
    }}
    /* Karta przyjmuje fokus z klawiatury, wiec musi go pokazac wyrazniej niz
       najechanie myszka: dwa piksele akcentu zamiast szarej krawedzi. */
    QFrame#ResultCard:focus {{
        border: 2px solid {p.accent};
    }}
    QLabel#ResultTitle {{
        font-size: {FONT_SIZE_TITLE}pt;
        font-weight: 600;
        color: {p.accent};
    }}
    QLabel#ResultPath {{
        color: {p.text_muted};
        font-size: {FONT_SIZE_SMALL}pt;
    }}
    QLabel#Badge {{
        background-color: {p.surface_alt};
        border: 1px solid {p.border};
        border-radius: {RADIUS_PILL}px;
        padding: 2px 9px;
        font-size: {FONT_SIZE_SMALL}pt;
        color: {p.text_muted};
    }}
    {badge_rules}
    QLabel#StatusDot {{
        border-radius: 5px;
        min-width: 10px;
        max-width: 10px;
        min-height: 10px;
        max-height: 10px;
    }}
    {dot_rules}
    QFrame#Banner {{
        border-radius: {RADIUS}px;
    }}
    {banner_rules}
    QLabel#Snippet {{
        background-color: {inset};
        border-radius: {RADIUS_SMALL}px;
        border-left: 2px solid {p.border};
        padding: {SPACE_SM}px 10px;
    }}
    QProgressBar {{
        background-color: {inset};
        border: 1px solid {p.border};
        border-radius: {RADIUS}px;
        height: 20px;
        text-align: center;
    }}
    QProgressBar::chunk {{
        background-color: {p.accent};
        border-radius: {RADIUS - 1}px;
    }}
    QTableWidget, QTableView, QTreeWidget {{
        background-color: {p.surface};
        border: 1px solid {p.border};
        border-radius: {RADIUS}px;
        gridline-color: {p.border};
        selection-background-color: {p.accent};
        selection-color: {p.accent_text};
        outline: none;
    }}
    QTableWidget::item, QTableView::item {{
        padding: 4px 6px;
    }}
    QTableWidget::item:selected, QTableView::item:selected {{
        background-color: {p.accent};
        color: {p.accent_text};
    }}
    QHeaderView::section {{
        background-color: {p.surface_alt};
        border: none;
        border-bottom: 1px solid {p.border};
        padding: 8px 10px;
        font-weight: 600;
    }}
    QTableCornerButton::section {{
        background-color: {p.surface_alt};
        border: none;
    }}
    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 12px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {scroll};
        border-radius: 5px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {scroll_hover};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 12px;
        margin: 2px;
    }}
    QScrollBar::handle:horizontal {{
        background: {scroll};
        border-radius: 5px;
        min-width: 30px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {scroll_hover};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}
    QCheckBox, QRadioButton {{
        spacing: 8px;
    }}
    QCheckBox:disabled, QRadioButton:disabled {{
        color: {p.text_muted};
    }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {p.text_muted};
        background-color: {control_bg};
    }}
    QCheckBox::indicator {{
        border-radius: 4px;
    }}
    QRadioButton::indicator {{
        border-radius: 8px;
    }}
    QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
        border-color: {p.accent};
    }}
    QCheckBox::indicator:checked {{
        background-color: {p.accent};
        border-color: {p.accent};
        image: url("{check}");
    }}
    QCheckBox::indicator:checked:hover {{
        background-color: {p.accent_hover};
        border-color: {p.accent_hover};
    }}
    QRadioButton::indicator:checked {{
        background-color: {control_bg};
        border: 5px solid {p.accent};
    }}
    QMenu {{
        background-color: {p.surface};
        border: 1px solid {p.border};
        padding: 4px;
    }}
    QMenu::item {{
        padding: 6px 24px 6px 12px;
        border-radius: {RADIUS - 2}px;
        background: transparent;
    }}
    QMenu::item:selected {{
        background-color: {p.accent};
        color: {p.accent_text};
    }}
    QMenu::separator {{
        height: 1px;
        background: {p.border};
        margin: 4px 8px;
    }}
    QStatusBar {{
        background-color: {p.surface_alt};
        border-top: 1px solid {p.border};
        color: {p.text_muted};
    }}
    QStatusBar::item {{
        border: none;
    }}
    QStatusBar QLabel {{
        background: transparent;
        color: {p.text_muted};
        padding: 0 {RADIUS_SMALL}px;
    }}
    QStatusBar QLabel#StatusDot {{
        padding: 0;
    }}
    QToolTip {{
        background-color: {p.surface};
        color: {p.text};
        border: 1px solid {p.border};
        border-radius: {RADIUS}px;
        padding: 6px 8px;
    }}
    /* Zakladki w ukladzie pivot: sam napis z podkresleniem wybranej pozycji.
       Zakladka w pudelku z obramowaniem wyglada jak przycisk, wiec wyglada tak
       samo jak akcje nad nia, a przeciez nie jest akcja, tylko wyborem widoku.
       Cienka linia pod calym paskiem jest torem, po ktorym biegnie podkreslenie. */
    QTabWidget::pane {{
        border: none;
        background: transparent;
        margin-top: {SPACE_MD}px;
    }}
    QTabBar {{
        background: transparent;
        outline: none;
        border-bottom: 1px solid {p.border};
    }}
    QTabBar::tab {{
        background: transparent;
        border: none;
        border-bottom: 2px solid transparent;
        padding: {SPACE_SM}px 2px;
        margin-right: {SPACE_XL}px;
        font-size: {FONT_SIZE_TITLE}pt;
        color: {p.text_muted};
    }}
    QTabBar::tab:hover:!selected {{
        color: {p.text};
        border-bottom: 2px solid {card_hover};
    }}
    QTabBar::tab:selected {{
        color: {p.text};
        border-bottom: 2px solid {p.accent};
        font-weight: 600;
    }}
    QTabBar::tab:disabled {{
        color: {p.text_muted};
    }}
    QSplitter::handle {{
        background-color: {p.border};
    }}
    """


def build_qt_palette(palette: Palette) -> QPalette:
    """Paleta Qt spojna z motywem.

    Arkusz stylow nie obejmuje wszystkich kontrolek (na przyklad kalendarza
    rozwijanego z pola daty). Paleta sprawia, ze i one dostaja wlasciwe tla
    oraz kolory tekstu, takze w trybie ciemnym.
    """
    p = palette
    qt_palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: p.background,
        QPalette.ColorRole.WindowText: p.text,
        QPalette.ColorRole.Base: p.surface,
        QPalette.ColorRole.AlternateBase: p.surface_alt,
        QPalette.ColorRole.Text: p.text,
        QPalette.ColorRole.Button: p.surface,
        QPalette.ColorRole.ButtonText: p.text,
        QPalette.ColorRole.PlaceholderText: p.text_muted,
        QPalette.ColorRole.ToolTipBase: p.surface,
        QPalette.ColorRole.ToolTipText: p.text,
        QPalette.ColorRole.Highlight: p.accent,
        QPalette.ColorRole.HighlightedText: p.accent_text,
        QPalette.ColorRole.Link: p.accent,
        QPalette.ColorRole.LinkVisited: p.accent_pressed,
    }
    for role, color in roles.items():
        qt_palette.setColor(role, QColor(color))
    muted = QColor(p.text_muted)
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        qt_palette.setColor(QPalette.ColorGroup.Disabled, role, muted)
    return qt_palette


#: Nazwa stylu bazowego zapamietana przy pierwszym zastosowaniu motywu.
#: Przy kolejnych wywolaniach ``app.style()`` to juz nasz styl posredniczacy,
#: wiec nazwy nie daloby sie odtworzyc.
_base_style_key: str | None = None


def apply_theme(app: QApplication, preference: str = "system") -> Palette:
    """Ustawia styl, czcionke, arkusz stylow i palete. Zwraca uzyta palete.

    Akcent pochodzi z ustawien personalizacji Windows, wiec aplikacja wyglada
    jak czesc tego komputera. Gdy odczyt sie nie uda, zostaje domyslny
    niebieski z palety.
    """
    global _active_palette, _base_style_key, _title_bar_filter
    palette = palette_with_accent(resolve_palette(app, preference), system_accent_color())
    _active_palette = palette
    if _title_bar_filter is None:
        _title_bar_filter = _TitleBarFilter(app)
        app.installEventFilter(_title_bar_filter)
    # Okna juz widoczne (zmiana motywu w trakcie dzialania) dostaja pasek od razu.
    for widget in app.topLevelWidgets():
        if widget.isVisible():
            apply_title_bar_theme(widget, dark=palette.variant == "dark")
    if _base_style_key is None:
        _base_style_key = app.style().objectName() or "windowsvista"
    app.setStyle(TabFocusStyle(_base_style_key))
    # Bez jawnej strategii Qt renderuje pismo tak, jak reszta systemu. Wymuszenie
    # ``PreferAntialias`` daje wygladzanie w odcieniach szarosci, wiec te same
    # litery wygladaja cieniej niz w oknach systemowych.
    font = QFont(font_family(), FONT_SIZE)
    font.setWeight(QFont.Weight.Normal)
    app.setFont(font)
    app.setStyleSheet(build_stylesheet(palette))
    app.setPalette(build_qt_palette(palette))
    app.setAttribute(Qt.ApplicationAttribute.AA_DontShowIconsInMenus, False)
    return palette


def highlight_css(palette: Palette) -> str:
    """Styl znacznika trafienia uzywany w tekscie HTML fragmentu."""
    return f"background-color: {palette.highlight}; color: {palette.highlight_text};"


__all__ = [
    "BADGE_COLORS",
    "BANNER_COLORS",
    "DARK",
    "DOT_COLORS",
    "FONT_CANDIDATES",
    "FONT_FAMILY",
    "FONT_SIZE",
    "FONT_SIZE_BRAND",
    "FONT_SIZE_PAGE",
    "FONT_SIZE_QUERY",
    "FONT_SIZE_SMALL",
    "FONT_SIZE_TITLE",
    "ICON_BUTTON_SIZE",
    "ICON_DIR",
    "LIGHT",
    "MIN_ACCENT_CONTRAST",
    "MONO_FAMILY",
    "PAGE_MARGINS",
    "QUERY_HEIGHT",
    "RADIUS",
    "RADIUS_LARGE",
    "RADIUS_PILL",
    "RADIUS_SMALL",
    "SPACE_LG",
    "SPACE_MD",
    "SPACE_SM",
    "SPACE_XL",
    "SPACE_XS",
    "Palette",
    "TabFocusStyle",
    "accent_icon",
    "active_palette",
    "apply_theme",
    "apply_title_bar_theme",
    "build_qt_palette",
    "build_stylesheet",
    "contrast_ratio",
    "enable_mica",
    "font_family",
    "highlight_css",
    "is_dark_mode",
    "mica_supported",
    "mica_window_css",
    "muted_icon",
    "palette_with_accent",
    "resolve_palette",
    "system_accent_color",
    "theme_icon",
]
