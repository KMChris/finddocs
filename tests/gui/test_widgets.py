"""Testy kontrolek wspolnych dla ekranow.

Kontrolki z ``gui/widgets`` sa uzywane na kilku ekranach naraz, wiec ich
zachowanie sprawdzamy raz, tutaj, a nie po kawalku w testach kazdego ekranu.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from finddocs.gui import theme
from finddocs.gui.widgets.page import Banner, PageHeader, StatusDot
from finddocs.gui.widgets.segmented import SEGMENT_PADDING, SegmentedControl
from finddocs.gui.widgets.stat_grid import StatGrid

LABELS = ("Hybrydowe", "Dokładne", "Semantyczne")


# --- segmentowany wybor ---------------------------------------------------------


@pytest.mark.gui
def test_segmenty_dostaja_polozenie_dla_arkusza_stylow(qtbot: object) -> None:
    """Skrajne segmenty maja zaokraglone rogi, wiec musza sie roznic wlasciwoscia."""
    control = SegmentedControl(LABELS)
    qtbot.addWidget(control)  # type: ignore[attr-defined]

    positions = [button.property("segmentPos") for button in control.buttons()]

    assert positions == ["first", "middle", "last"]


@pytest.mark.gui
def test_pojedynczy_segment_jest_zaokraglony_z_obu_stron(qtbot: object) -> None:
    control = SegmentedControl(("Jedyny",))
    qtbot.addWidget(control)  # type: ignore[attr-defined]

    assert [button.property("segmentPos") for button in control.buttons()] == ["only"]


@pytest.mark.gui
def test_segmenty_maja_wspolna_szerokosc_liczona_pismem_pogrubionym(qtbot: object) -> None:
    """Wybrany segment jest pogrubiony, wiec szerokosc musi uwzgledniac pogrubienie."""
    control = SegmentedControl(LABELS)
    qtbot.addWidget(control)  # type: ignore[attr-defined]

    widths = {button.minimumWidth() for button in control.buttons()}

    assert len(widths) == 1
    widest = max(control.fontMetrics().horizontalAdvance(label) for label in LABELS)
    assert widths.pop() >= widest + SEGMENT_PADDING - 1


@pytest.mark.gui
def test_wybor_segmentu_jest_wykluczajacy_i_zglasza_zmiane(qtbot: object) -> None:
    control = SegmentedControl(LABELS, checked=0)
    qtbot.addWidget(control)  # type: ignore[attr-defined]
    seen: list[int] = []
    control.changed.connect(seen.append)

    control.buttons()[2].click()

    assert seen == [2]
    assert control.checked_index() == 2
    assert [button.isChecked() for button in control.buttons()] == [False, False, True]


@pytest.mark.gui
def test_zmiana_wyboru_z_kodu_nie_zglasza_sygnalu(qtbot: object) -> None:
    """Sygnal opisuje decyzje uzytkownika, nie kazde ustawienie stanu."""
    control = SegmentedControl(LABELS)
    qtbot.addWidget(control)  # type: ignore[attr-defined]
    seen: list[int] = []
    control.changed.connect(seen.append)

    control.set_checked_index(1)

    assert control.checked_index() == 1
    assert seen == []


@pytest.mark.gui
def test_podpowiedzi_trafiaja_na_segmenty(qtbot: object) -> None:
    control = SegmentedControl(LABELS, hints=("a", "b", "c"))
    qtbot.addWidget(control)  # type: ignore[attr-defined]

    assert [button.toolTip() for button in control.buttons()] == ["a", "b", "c"]


# --- siatka liczb ---------------------------------------------------------------


@pytest.mark.gui
def test_siatka_liczb_podmienia_wartosci_po_kluczu(qtbot: object) -> None:
    grid = StatGrid((("discovered", "Wykryte"), ("processed", "Przetworzone")), columns=2)
    qtbot.addWidget(grid)  # type: ignore[attr-defined]

    grid.set_values({"discovered": 12, "processed": "7"})

    assert grid.value("discovered") == "12"
    assert grid.value("processed") == "7"


@pytest.mark.gui
def test_siatka_liczb_pomija_nieznane_klucze(qtbot: object) -> None:
    """Zrodlo wartosci moze byc bogatsze niz siatka; nadmiar nie moze wysypac widoku."""
    grid = StatGrid((("a", "A"),))
    qtbot.addWidget(grid)  # type: ignore[attr-defined]

    grid.set_values({"a": 1, "nie-ma-takiego": 2})

    assert grid.value("a") == "1"
    assert grid.value("nie-ma-takiego") == ""


@pytest.mark.gui
def test_siatka_liczb_uklada_pary_w_kolumnach(qtbot: object) -> None:
    """Podpis lezy nad wartoscia, a kolejne rzedy rozdziela pusty wiersz."""
    entries = tuple((str(number), f"Podpis {number}") for number in range(5))
    grid = StatGrid(entries, columns=4)
    qtbot.addWidget(grid)  # type: ignore[attr-defined]
    layout = grid.layout()

    assert layout is not None
    # Piec par w czterech kolumnach to dwa rzedy: wiersze 0 i 1 oraz 3 i 4.
    assert layout.rowCount() == 5
    assert layout.itemAtPosition(0, 0).widget().text() == "Podpis 0"
    assert layout.itemAtPosition(3, 0).widget().text() == "Podpis 4"


# --- baner ----------------------------------------------------------------------


@pytest.mark.gui
def test_baner_bez_tresci_jest_ukryty(qtbot: object) -> None:
    banner = Banner()
    qtbot.addWidget(banner)  # type: ignore[attr-defined]

    assert banner.isHidden()
    assert banner.text() == ""


@pytest.mark.gui
def test_baner_pokazuje_i_ukrywa_komunikat(qtbot: object) -> None:
    banner = Banner()
    qtbot.addWidget(banner)  # type: ignore[attr-defined]

    banner.show_message("Zbiór nie jest kompletny.", "warning")

    assert not banner.isHidden()
    assert banner.text() == "Zbiór nie jest kompletny."
    assert banner.property("bannerRole") == "warning"

    banner.show_message("")

    assert banner.isHidden()
    assert banner.text() == ""


@pytest.mark.gui
def test_nieznana_rola_banera_schodzi_do_informacyjnej(qtbot: object) -> None:
    """Rola spoza palety nie moze zostawic banera bez tla i bez obramowania."""
    banner = Banner()
    qtbot.addWidget(banner)  # type: ignore[attr-defined]

    banner.show_message("Tresc", "kolor-ktorego-nie-ma")

    assert banner.property("bannerRole") == "info"


# --- kropka stanu ---------------------------------------------------------------


@pytest.mark.gui
@pytest.mark.parametrize(
    ("role", "expected"),
    [("ok", "ok"), ("warn", "warn"), ("off", "off"), ("czerwona", "off")],
)
def test_kropka_stanu_przyjmuje_tylko_znane_role(qtbot: object, role: str, expected: str) -> None:
    dot = StatusDot()
    qtbot.addWidget(dot)  # type: ignore[attr-defined]

    dot.set_role(role)

    assert dot.property("dotRole") == expected


@pytest.mark.gui
def test_kazda_rola_kropki_ma_kolor_w_obu_paletach() -> None:
    for palette in (theme.LIGHT, theme.DARK):
        css = theme.build_stylesheet(palette)
        for role, color in theme.DOT_COLORS[palette.variant].items():
            assert f'QLabel#StatusDot[dotRole="{role}"]' in css
            assert color in css


# --- naglowek ekranu ------------------------------------------------------------


@pytest.mark.gui
def test_naglowek_pokazuje_informacje_tylko_gdy_jest_tresc(qtbot: object) -> None:
    header = PageHeader("Wyszukiwanie")
    qtbot.addWidget(header)  # type: ignore[attr-defined]

    assert header.meta_label.isHidden()

    header.set_meta("Znaleziono 5 dokumentów")
    assert not header.meta_label.isHidden()
    assert header.meta_label.text() == "Znaleziono 5 dokumentów"

    header.set_meta("")
    assert header.meta_label.isHidden()


@pytest.mark.gui
def test_naglowek_uzywa_stylu_tytulu_ekranu(qtbot: object, qapp: QApplication) -> None:
    header = PageHeader("Diagnostyka")
    qtbot.addWidget(header)  # type: ignore[attr-defined]

    titles = [
        label.text() for label in header.findChildren(QLabel) if label.objectName() == "PageTitle"
    ]

    assert titles == ["Diagnostyka"]
