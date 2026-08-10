"""Testy motywu: polityka fokusa przyciskow, tla etykiet i obrazki motywu."""

from __future__ import annotations

import pytest
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
ACCENT_GLYPH_NAMES = ("search", "stop", "play", "refresh", "plus")


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


def test_akcent_systemowy_zachowuje_kontrast_napisu() -> None:
    """Typowe akcenty Windows po korekcie daja czytelny napis na przycisku."""
    from PySide6.QtGui import QColor

    for base in ("#0078d4", "#ffb900", "#e81123", "#00cc6a", "#8e8cd8"):
        for palette in (theme.LIGHT, theme.DARK):
            derived = theme.palette_with_accent(palette, QColor(base))
            ratio = theme.contrast_ratio(QColor(derived.accent), QColor(derived.accent_text))
            assert ratio >= theme.MIN_ACCENT_CONTRAST, (base, palette.variant, ratio)
            # Role poza akcentem zostaja bez zmian.
            assert derived.background == palette.background
            assert derived.accent_text == palette.accent_text


def test_brak_akcentu_systemowego_zostawia_palete_domyslna() -> None:
    assert theme.palette_with_accent(theme.LIGHT, None) is theme.LIGHT


def test_wylaczony_przycisk_danger_traci_czerwien() -> None:
    """Identyfikator wygrywa z pseudoklasa, wiec regula :disabled musi byc jawna."""
    for palette in (theme.LIGHT, theme.DARK):
        css = theme.build_stylesheet(palette)
        assert "QPushButton#Danger:disabled" in css
        block = css.split("QPushButton#Danger:disabled", 1)[1].split("}", 1)[0]
        assert palette.text_muted in block


def test_wylaczony_przycisk_ma_oslabione_obramowanie() -> None:
    """Na bialej karcie roznica tla nie istnieje, stan niesie obramowanie."""
    for palette in (theme.LIGHT, theme.DARK):
        css = theme.build_stylesheet(palette)
        block = css.split("QPushButton:disabled", 1)[1].split("}", 1)[0]
        assert "border: 1px solid" in block


def test_podswietlenie_list_rozwijanych_i_tabel_ma_kontrast() -> None:
    """Ostylowany ::item nie dziedziczy selection-background-color z widoku.

    Bez jawnych stanow tekst podswietlonej pozycji przyjmuje kolor tekstu
    zaznaczenia na tle powierzchni, czyli bialy na bialym w jasnym motywie.
    """
    for palette in (theme.LIGHT, theme.DARK):
        css = theme.build_stylesheet(palette)
        combo = css.split("QComboBox QAbstractItemView::item:hover", 1)[1].split("}", 1)[0]
        assert f"background-color: {palette.accent}" in combo
        assert f"color: {palette.accent_text}" in combo
        table = css.split("QTableWidget::item:selected", 1)[1].split("}", 1)[0]
        assert f"background-color: {palette.accent}" in table
        assert f"color: {palette.accent_text}" in table


def test_segmenty_maja_reguly_dla_kazdego_polozenia() -> None:
    """Bez regul polozenia segmenty mialyby ostre rogi i podwojna krawedz."""
    for palette in (theme.LIGHT, theme.DARK):
        css = theme.build_stylesheet(palette)
        for position in ("first", "middle", "last", "only"):
            assert f'QPushButton#Segment[segmentPos="{position}"]' in css
        # Segment wybrany musi miec wlasne tlo i tekst o kontrascie akcentu.
        checked = css.split("QPushButton#Segment:checked {", 1)[1].split("}", 1)[0]
        assert f"background-color: {palette.accent}" in checked
        assert f"color: {palette.accent_text}" in checked


def test_role_banera_sa_w_arkuszu_stylow_obu_palet() -> None:
    for palette in (theme.LIGHT, theme.DARK):
        css = theme.build_stylesheet(palette)
        assert set(theme.BANNER_COLORS["light"]) == set(theme.BANNER_COLORS["dark"])
        for role, (background, foreground) in theme.BANNER_COLORS[palette.variant].items():
            assert f'QFrame#Banner[bannerRole="{role}"]' in css
            assert background in css
            assert foreground in css


def test_stopnie_pisma_pochodza_ze_skali_typografii() -> None:
    """Rozmiary w arkuszu maja isc ze skali, a nie z liczb wpisanych na miejscu."""
    css = theme.build_stylesheet(theme.LIGHT)
    assert f"font-size: {theme.FONT_SIZE_SMALL}pt" in css
    assert f"font-size: {theme.FONT_SIZE_TITLE}pt" in css
    assert f"font-size: {theme.FONT_SIZE_PAGE}pt" in css
    assert f"font-size: {theme.FONT_SIZE_QUERY}pt" in css
    scale = {
        theme.FONT_SIZE_SMALL,
        theme.FONT_SIZE,
        theme.FONT_SIZE_TITLE,
        theme.FONT_SIZE_QUERY,
        theme.FONT_SIZE_BRAND,
        theme.FONT_SIZE_PAGE,
    }
    used = {int(part.split("pt", 1)[0]) for part in css.split("font-size: ")[1:]}
    assert used <= scale, f"stopnie spoza skali typografii: {sorted(used - scale)}"


def test_karta_wyniku_odroznia_fokus_od_najechania() -> None:
    """Fokus z klawiatury musi byc wyrazniejszy niz najechanie myszka."""
    for palette in (theme.LIGHT, theme.DARK):
        css = theme.build_stylesheet(palette)
        focus = css.split("QFrame#ResultCard:focus {", 1)[1].split("}", 1)[0]
        assert f"border: 2px solid {palette.accent}" in focus


def test_rodzina_pisma_ma_kroj_semibold(qapp: QApplication) -> None:
    """Bez prawdziwego kroju 600 Qt awansuje go do 700 i hierarchia robi skok.

    ``Segoe UI Variable Text`` ma w bazie czcionek tylko Regular i Bold, wiec
    tytul pisany stopniem 600 wychodzi tak samo ciezki jak 700, a obok tekstu
    podstawowego wyglada to jak dwa rozne pisma na jednym ekranie.

    Testy interfejsu dzialaja na platformie ``offscreen``, ktora nie ma bazy
    czcionek systemowych. Wtedy nie ma czego sprawdzac i test jest pomijany;
    sens ma dopiero na maszynie z zainstalowanymi czcionkami.
    """
    from PySide6.QtGui import QFont, QFontDatabase

    family = theme.font_family()
    assert family in theme.FONT_CANDIDATES

    if family not in QFontDatabase.families():
        pytest.skip("platforma bez bazy czcionek systemowych")

    weights = {QFontDatabase.weight(family, style) for style in QFontDatabase.styles(family)}
    between = {
        weight for weight in weights if int(QFont.Weight.Normal) < weight < int(QFont.Weight.Bold)
    }
    assert between, f"rodzina {family} nie ma kroju miedzy Regular i Bold: {sorted(weights)}"


def test_arkusz_stylow_podaje_jedna_rodzine_pisma() -> None:
    """Lista rozdzielona przecinkami nie mowi, ktora rodzina jest uzywana."""
    css = theme.build_stylesheet(theme.LIGHT)
    declaration = css.split("font-family:", 1)[1].split(";", 1)[0].strip()

    assert "," not in declaration
    assert declaration.strip('"') in theme.FONT_CANDIDATES


def test_zakladki_sa_podkresleniem_a_nie_pudelkiem() -> None:
    """Zakladka w ramce wyglada jak przycisk, czyli jak akcja, a nia nie jest."""
    for palette in (theme.LIGHT, theme.DARK):
        css = theme.build_stylesheet(palette)
        selected = css.split("QTabBar::tab:selected {", 1)[1].split("}", 1)[0]
        assert f"border-bottom: 2px solid {palette.accent}" in selected
        assert "background" not in selected
        pane = css.split("QTabWidget::pane {", 1)[1].split("}", 1)[0]
        assert "border: none" in pane


def test_pozycja_nawigacji_nie_ma_obramowania() -> None:
    """Krawedz przycieta zaokragleniem wygladala jak zakrzywiony pasek.

    Wskaznik zaznaczenia rysuje delegat, wiec arkusz stylow nie moze wracac do
    obramowania: dostalibysmy oba wskazniki naraz.
    """
    for palette in (theme.LIGHT, theme.DARK):
        css = theme.build_stylesheet(palette)
        item = css.split("#SidebarList::item {", 1)[1].split("}", 1)[0]
        assert "border: none" in item
        selected = css.split("#SidebarList::item:selected {", 1)[1].split("}", 1)[0]
        assert "border" not in selected
        assert palette.accent not in selected


def test_muted_icon_renderuje_sie_w_obu_paletach(qapp: QApplication) -> None:
    from PySide6.QtCore import QSize

    for palette in (theme.LIGHT, theme.DARK):
        icon = theme.muted_icon("search", palette)
        assert not icon.isNull()
        assert not icon.pixmap(QSize(40, 40)).isNull()


def test_paleta_qt_jest_spojna_z_motywem() -> None:
    for palette in (theme.LIGHT, theme.DARK):
        qt_palette = theme.build_qt_palette(palette)
        assert qt_palette.color(QPalette.ColorRole.Window).name() == palette.background
        assert qt_palette.color(QPalette.ColorRole.Base).name() == palette.surface
        assert qt_palette.color(QPalette.ColorRole.Text).name() == palette.text
        assert qt_palette.color(QPalette.ColorRole.Highlight).name() == palette.accent
