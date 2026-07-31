"""Wyglad aplikacji zgodny z Windows 11.

Motyw opiera sie na palecie Fluent: jasne tlo warstwowe, zaokraglone rogi, subtelne
obramowania i akcent systemowy. Wersja ciemna jest wybierana automatycznie, gdy
system zglasza ciemny motyw.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

FONT_FAMILY = "Segoe UI Variable Text, Segoe UI, Inter, sans-serif"
FONT_SIZE = 10
MONO_FAMILY = "Cascadia Mono, Consolas, monospace"

RADIUS = 8
RADIUS_LARGE = 12


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
)


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


def build_stylesheet(palette: Palette) -> str:
    """Arkusz stylow Qt dla calej aplikacji."""
    p = palette
    return f"""
    QWidget {{
        background-color: {p.background};
        color: {p.text};
        font-family: "{FONT_FAMILY}";
        font-size: {FONT_SIZE}pt;
    }}
    QMainWindow, QDialog {{
        background-color: {p.background};
    }}
    #Sidebar {{
        background-color: {p.surface_alt};
        border-right: 1px solid {p.border};
    }}
    #SidebarList {{
        background: transparent;
        border: none;
        padding: 8px 6px;
    }}
    #SidebarList::item {{
        padding: 10px 12px;
        border-radius: {RADIUS}px;
        margin: 2px 4px;
        color: {p.text};
    }}
    #SidebarList::item:selected {{
        background-color: {p.surface};
        color: {p.text};
        border: 1px solid {p.border};
    }}
    #SidebarList::item:hover:!selected {{
        background-color: {p.surface};
    }}
    #AppTitle {{
        font-size: 15pt;
        font-weight: 600;
        padding: 16px 16px 0 16px;
    }}
    #AppSubtitle {{
        color: {p.text_muted};
        padding: 0 16px 12px 16px;
    }}
    QLabel#PageTitle {{
        font-size: 17pt;
        font-weight: 600;
        padding-bottom: 4px;
    }}
    QLabel#SectionTitle {{
        font-size: 12pt;
        font-weight: 600;
        padding-top: 4px;
    }}
    QLabel#Muted, QLabel#Hint {{
        color: {p.text_muted};
    }}
    QFrame#Card, QGroupBox {{
        background-color: {p.surface};
        border: 1px solid {p.border};
        border-radius: {RADIUS_LARGE}px;
    }}
    QGroupBox {{
        margin-top: 14px;
        padding: 14px 12px 12px 12px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 6px;
        background-color: {p.surface};
    }}
    QLineEdit, QComboBox, QDateEdit, QSpinBox, QPlainTextEdit, QTextEdit {{
        background-color: {p.surface};
        border: 1px solid {p.border};
        border-bottom: 2px solid {p.border};
        border-radius: {RADIUS}px;
        padding: 7px 10px;
        selection-background-color: {p.accent};
        selection-color: {p.accent_text};
    }}
    QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus {{
        border-bottom: 2px solid {p.accent};
    }}
    QLineEdit#SearchBox {{
        font-size: 13pt;
        padding: 11px 14px;
    }}
    QComboBox::drop-down {{
        border: none;
        width: 22px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {p.surface};
        border: 1px solid {p.border};
        border-radius: {RADIUS}px;
        selection-background-color: {p.accent};
        selection-color: {p.accent_text};
        padding: 4px;
    }}
    QPushButton {{
        background-color: {p.surface};
        border: 1px solid {p.border};
        border-radius: {RADIUS}px;
        padding: 8px 16px;
        min-height: 18px;
    }}
    QPushButton:hover {{
        background-color: {p.surface_alt};
    }}
    QPushButton:pressed {{
        background-color: {p.border};
    }}
    QPushButton:disabled {{
        color: {p.text_muted};
        background-color: {p.surface_alt};
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
    QPushButton#Danger {{
        color: {p.danger};
    }}
    QPushButton#Link {{
        background: transparent;
        border: none;
        color: {p.accent};
        text-align: left;
        padding: 4px 2px;
    }}
    QPushButton#Link:hover {{
        text-decoration: underline;
    }}
    QPushButton#ModeButton {{
        padding: 7px 18px;
        border-radius: {RADIUS}px;
    }}
    QPushButton#ModeButton:checked {{
        background-color: {p.accent};
        color: {p.accent_text};
        border: 1px solid {p.accent};
        font-weight: 600;
    }}
    QFrame#ResultCard {{
        background-color: {p.surface};
        border: 1px solid {p.border};
        border-radius: {RADIUS_LARGE}px;
    }}
    QFrame#ResultCard:hover {{
        border: 1px solid {p.accent};
    }}
    QLabel#ResultTitle {{
        font-size: 12pt;
        font-weight: 600;
        color: {p.accent};
    }}
    QLabel#ResultPath {{
        color: {p.text_muted};
    }}
    QLabel#Badge {{
        background-color: {p.surface_alt};
        border: 1px solid {p.border};
        border-radius: 10px;
        padding: 2px 9px;
        color: {p.text_muted};
    }}
    QLabel#BadgeOcr {{
        background-color: {p.highlight};
        color: {p.highlight_text};
        border: none;
        border-radius: 10px;
        padding: 2px 9px;
    }}
    QLabel#Snippet {{
        background-color: {p.surface_alt};
        border-radius: {RADIUS}px;
        padding: 8px 10px;
    }}
    QProgressBar {{
        background-color: {p.surface_alt};
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
    }}
    QHeaderView::section {{
        background-color: {p.surface_alt};
        border: none;
        border-bottom: 1px solid {p.border};
        padding: 7px 8px;
        font-weight: 600;
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
        background: {p.border};
        border-radius: 5px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {p.text_muted};
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
        background: {p.border};
        border-radius: 5px;
        min-width: 30px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}
    QCheckBox, QRadioButton {{
        spacing: 8px;
    }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {p.text_muted};
        border-radius: 4px;
        background-color: {p.surface};
    }}
    QCheckBox::indicator:checked {{
        background-color: {p.accent};
        border: 1px solid {p.accent};
    }}
    QStatusBar {{
        background-color: {p.surface_alt};
        border-top: 1px solid {p.border};
        color: {p.text_muted};
    }}
    QToolTip {{
        background-color: {p.surface};
        color: {p.text};
        border: 1px solid {p.border};
        border-radius: {RADIUS}px;
        padding: 6px 8px;
    }}
    QTabWidget::pane {{
        border: 1px solid {p.border};
        border-radius: {RADIUS_LARGE}px;
        background-color: {p.surface};
        top: -1px;
    }}
    QTabBar::tab {{
        background: transparent;
        padding: 8px 16px;
        margin-right: 4px;
        border-radius: {RADIUS}px;
        color: {p.text_muted};
    }}
    QTabBar::tab:selected {{
        background-color: {p.surface};
        color: {p.text};
        border: 1px solid {p.border};
        font-weight: 600;
    }}
    QSplitter::handle {{
        background-color: {p.border};
    }}
    """


def apply_theme(app: QApplication, preference: str = "system") -> Palette:
    """Ustawia czcionke i arkusz stylow. Zwraca uzyta palete."""
    palette = resolve_palette(app, preference)
    font = QFont(FONT_FAMILY.split(",")[0].strip(), FONT_SIZE)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
    app.setStyleSheet(build_stylesheet(palette))
    qt_palette = app.palette()
    qt_palette.setColor(QPalette.ColorRole.Link, QColor(palette.accent))
    qt_palette.setColor(QPalette.ColorRole.Highlight, QColor(palette.accent))
    app.setPalette(qt_palette)
    app.setAttribute(Qt.ApplicationAttribute.AA_DontShowIconsInMenus, False)
    return palette


def highlight_css(palette: Palette) -> str:
    """Styl znacznika trafienia uzywany w tekscie HTML fragmentu."""
    return f"background-color: {palette.highlight}; color: {palette.highlight_text};"


__all__ = [
    "DARK",
    "FONT_FAMILY",
    "LIGHT",
    "MONO_FAMILY",
    "RADIUS",
    "RADIUS_LARGE",
    "Palette",
    "apply_theme",
    "build_stylesheet",
    "highlight_css",
    "is_dark_mode",
    "resolve_palette",
]
