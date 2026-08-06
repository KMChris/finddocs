"""Testy motywu: polityka fokusa przyciskow, tla etykiet i obrazki motywu."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QPushButton, QStyle, QStyleFactory

from finddocs.gui import theme


def test_styl_kaze_przyciskom_brac_fokus_tylko_z_klawiatury(qapp: QApplication) -> None:
    """Po kliknieciu myszka przycisk nie moze zatrzymac ramki fokusa."""
    style = theme.TabFocusStyle("windowsvista")
    hint = style.styleHint(QStyle.StyleHint.SH_Button_FocusPolicy)
    assert hint == int(Qt.FocusPolicy.TabFocus.value)


def test_zastosowanie_motywu_zmienia_polityke_fokusa_przyciskow(qapp: QApplication) -> None:
    old_sheet = qapp.styleSheet()
    old_palette = qapp.palette()
    old_style_name = qapp.style().objectName()
    theme.apply_theme(qapp, "light")
    try:
        button = QPushButton("Start")
        try:
            assert button.focusPolicy() == Qt.FocusPolicy.TabFocus
        finally:
            button.deleteLater()
    finally:
        qapp.setStyleSheet(old_sheet)
        qapp.setPalette(old_palette)
        restored = QStyleFactory.create(old_style_name) if old_style_name else None
        if restored is not None:
            qapp.setStyle(restored)


def test_uniwersalna_regula_qwidget_nie_ustawia_tla() -> None:
    """Tlo na kazdej kontrolce malowaloby prostokaty pod tekstem etykiet."""
    css = theme.build_stylesheet(theme.LIGHT)
    universal = css.split("QWidget {", 1)[1].split("}", 1)[0]
    assert "background" not in universal
    assert "QLabel, QCheckBox, QRadioButton" in css
    assert "outline: none" in css


def test_arkusz_stylow_wskazuje_istniejace_obrazki_motywu() -> None:
    for palette in (theme.LIGHT, theme.DARK):
        css = theme.build_stylesheet(palette)
        for name in ("check", "chevron"):
            path = theme.ICON_DIR / f"{name}-{palette.variant}.png"
            assert path.exists(), f"brakuje obrazka {path}"
            assert path.as_posix() in css
            assert path.with_name(f"{name}-{palette.variant}@2x.png").exists()


def test_paleta_qt_jest_spojna_z_motywem() -> None:
    for palette in (theme.LIGHT, theme.DARK):
        qt_palette = theme.build_qt_palette(palette)
        assert qt_palette.color(QPalette.ColorRole.Window).name() == palette.background
        assert qt_palette.color(QPalette.ColorRole.Base).name() == palette.surface
        assert qt_palette.color(QPalette.ColorRole.Text).name() == palette.text
        assert qt_palette.color(QPalette.ColorRole.Highlight).name() == palette.accent
