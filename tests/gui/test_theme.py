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


#: Glify uzywane przez widoki; brak pliku oznaczalby pusta ikone w GUI.
GLYPH_NAMES = (
    "search",
    "stop",
    "folder",
    "copy",
    "refresh",
    "database",
    "chart",
    "pulse",
    "play",
    "pause",
    "cross",
    "plus",
    "trash",
    "export",
    "filter",
    "chevron-left",
    "chevron-right",
)

#: Glify z wariantem na tle akcentu (przyciski Primary i PrimaryIcon).
ACCENT_GLYPH_NAMES = ("search", "stop", "play", "refresh")


def test_glify_svg_istnieja_we_wszystkich_klasach() -> None:
    for variant in ("light", "dark"):
        for name in GLYPH_NAMES:
            for infix in ("", "-muted"):
                path = theme.ICON_DIR / f"{name}{infix}-{variant}.svg"
                assert path.exists(), f"brakuje glifu {path}"
        for name in ACCENT_GLYPH_NAMES:
            path = theme.ICON_DIR / f"{name}-accent-{variant}.svg"
            assert path.exists(), f"brakuje glifu {path}"


def test_theme_icon_ma_wariant_zwykly_i_wylaczony(qapp: QApplication) -> None:
    """Ikona musi sie renderowac takze w stanie wylaczonym przycisku."""
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QIcon

    for palette in (theme.LIGHT, theme.DARK):
        for icon in (theme.theme_icon("play", palette), theme.accent_icon("play", palette)):
            assert not icon.isNull()
            assert not icon.pixmap(QSize(16, 16), QIcon.Mode.Normal).isNull()
            assert not icon.pixmap(QSize(16, 16), QIcon.Mode.Disabled).isNull()


def test_role_plakietek_sa_w_arkuszu_stylow_obu_palet() -> None:
    for palette in (theme.LIGHT, theme.DARK):
        css = theme.build_stylesheet(palette)
        roles = theme.BADGE_COLORS[palette.variant]
        assert set(theme.BADGE_COLORS["light"]) == set(theme.BADGE_COLORS["dark"])
        for role, (background, foreground) in roles.items():
            assert f'QLabel#Badge[badgeRole="{role}"]' in css
            assert background in css
            assert foreground in css


def test_paleta_qt_jest_spojna_z_motywem() -> None:
    for palette in (theme.LIGHT, theme.DARK):
        qt_palette = theme.build_qt_palette(palette)
        assert qt_palette.color(QPalette.ColorRole.Window).name() == palette.background
        assert qt_palette.color(QPalette.ColorRole.Base).name() == palette.surface
        assert qt_palette.color(QPalette.ColorRole.Text).name() == palette.text
        assert qt_palette.color(QPalette.ColorRole.Highlight).name() == palette.accent
