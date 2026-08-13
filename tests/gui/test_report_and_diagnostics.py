"""Testy ekranu raportu pokrycia i ekranu diagnostyki."""

from __future__ import annotations

import json

import pytest
from PySide6.QtWidgets import QLabel

from finddocs.gui import i18n
from finddocs.gui.context import AppContext
from finddocs.gui.diagnostics_view import DiagnosticsView
from finddocs.gui.report_view import SUMMARY_ENTRIES, ReportView, summary_values
from finddocs.types import DocumentStatus

#: Raport i diagnostyka licza sie w tle, wiec czekamy na wynik.
TIMEOUT_MS = 15_000


def _summary_labels(view: ReportView) -> list[str]:
    """Napisy widoczne w obu siatkach podsumowania raportu."""
    labels = [label.text() for label in view.summary_box.findChildren(QLabel)]
    labels += [label.text() for label in view.tech_box.findChildren(QLabel)]
    return labels


@pytest.fixture
def report_view(qtbot: object, indexed_gui_context: AppContext) -> ReportView:
    """Widok raportu dla zaindeksowanego korpusu."""
    view = ReportView(indexed_gui_context)
    qtbot.addWidget(view)  # type: ignore[attr-defined]
    return view


@pytest.fixture
def diagnostics_view(qtbot: object, gui_context: AppContext) -> DiagnosticsView:
    """Widok diagnostyki dla otwartego, pustego indeksu."""
    view = DiagnosticsView(gui_context)
    qtbot.addWidget(view)  # type: ignore[attr-defined]
    return view


# --- raport pokrycia ------------------------------------------------------------


def _wait_for_report(qtbot: object, view: ReportView) -> None:
    """Czeka na policzony raport.

    Baner kompletnosci ma tresc od poczatku (prosbe o odswiezenie), wiec sam
    niepusty napis nie oznacza, ze raport jest juz gotowy.
    """
    qtbot.waitUntil(lambda: view._report is not None, timeout=TIMEOUT_MS)  # type: ignore[attr-defined]


@pytest.mark.gui
def test_report_shows_summary_after_refresh(qtbot: object, report_view: ReportView) -> None:
    """Odswiezenie wypelnia podsumowanie i informacje o kompletnosci zbioru."""
    report_view.refresh()

    _wait_for_report(qtbot, report_view)
    labels = _summary_labels(report_view)
    assert "Wykryte pliki" in labels
    assert "Zaindeksowane" in labels
    assert "Rozmiar indeksu" in labels
    assert "Wersja aplikacji" in labels
    # Siatka podsumowania trzyma wartosci pod kluczami, wiec test nie musi
    # zgadywac, w ktorym miejscu ukladu lezy dana liczba. Liczby pokrycia
    # i metadane techniczne leza w osobnych kartach.
    assert int(report_view.summary.value("discovered")) > 0
    assert report_view.tech_summary.value("app_version")


@pytest.mark.gui
def test_klucze_podsumowania_zgadzaja_sie_z_siatka(qtbot: object, report_view: ReportView) -> None:
    """Klucz siatki bez wartosci zostalby na napisie ,,brak'' i nikt by nie zauwazyl."""
    report_view.refresh()
    _wait_for_report(qtbot, report_view)

    values = summary_values(report_view._report)

    assert set(values) == {key for key, _ in SUMMARY_ENTRIES}


@pytest.mark.gui
def test_report_reports_incomplete_set(
    qtbot: object, report_view: ReportView, corpus_stats: dict[str, int]
) -> None:
    """Gdy sa dokumenty niewyszukiwalne, komunikat mowi wprost o niekompletnosci."""
    report_view.refresh()

    _wait_for_report(qtbot, report_view)
    expected = i18n.REPORT_INCOMPLETE.format(
        count=i18n.documents_count(corpus_stats["niewyszukiwalne"])
    )
    assert report_view.completeness.text() == expected
    assert report_view.completeness.property("bannerRole") == "warning"
    assert i18n.REPORT_COMPLETE not in report_view.completeness.text()

    assert report_view.table.rowCount() == corpus_stats["niewyszukiwalne"]
    assert report_view.table.item(0, 0).text() == "pusty.txt"
    # Komorka tabeli zaczyna sie wielka litera. Kolumna z komunikatem nigdy nie
    # jest pusta: bez komunikatu parsera wchodzi tam wyjasnienie statusu.
    assert report_view.table.item(0, 2).text() == i18n.status_label(DocumentStatus.EMPTY)
    assert report_view.table.item(0, 4).text()


@pytest.mark.gui
def test_wartosci_techniczne_ida_zwyklym_stopniem(report_view: ReportView) -> None:
    """Identyfikator modelu pisany stopniem liczb przytlaczal sekcje."""
    for label in report_view.tech_summary.labels.values():
        assert label.objectName() == "StatText"
    for label in report_view.summary.labels.values():
        assert label.objectName() == "StatValue"


@pytest.mark.gui
def test_report_on_empty_index(qtbot: object, gui_context: AppContext) -> None:
    """Pusty indeks nie jest opisywany jako kompletny zbior."""
    view = ReportView(gui_context)
    qtbot.addWidget(view)  # type: ignore[attr-defined]

    view.refresh()

    _wait_for_report(qtbot, view)
    assert view.completeness.text() == i18n.REPORT_EMPTY
    assert view.completeness.property("bannerRole") == "info"
    assert view.table.rowCount() == 0


@pytest.mark.gui
def test_report_export_without_data_asks_for_refresh(
    qtbot: object, gui_context: AppContext, message_boxes: list[object]
) -> None:
    """Eksport przed odswiezeniem konczy sie podpowiedzia, a nie zapisem pliku."""
    view = ReportView(gui_context)
    qtbot.addWidget(view)  # type: ignore[attr-defined]

    # Przyciski eksportu sa wylaczone, dopoki nie ma czego eksportowac.
    assert not view.export_json_button.isEnabled()
    assert not view.export_csv_button.isEnabled()

    view.export("csv")

    assert len(message_boxes) == 1
    assert list(gui_context.paths.reports_dir.iterdir()) == []


@pytest.mark.gui
def test_report_refresh_if_stale_liczy_raport_przy_wejsciu(
    qtbot: object, report_view: ReportView
) -> None:
    """Wejscie na ekran uruchamia liczenie, bez klikania Odswiez."""
    assert report_view._report is None

    report_view.refresh_if_stale()

    _wait_for_report(qtbot, report_view)
    assert report_view.stamp_label.text().startswith("Stan z")


@pytest.mark.gui
def test_report_refresh_if_stale_nie_liczy_drugi_raz(
    qtbot: object, report_view: ReportView
) -> None:
    """Powtorne wejscie bez zmiany indeksu nie zleca kolejnego przebiegu."""
    report_view.refresh_if_stale()
    _wait_for_report(qtbot, report_view)
    first = report_view._report

    report_view.refresh_if_stale()

    assert report_view._report is first

    report_view.mark_stale()
    report_view.refresh_if_stale()
    qtbot.waitUntil(  # type: ignore[attr-defined]
        lambda: report_view._report is not first, timeout=TIMEOUT_MS
    )


@pytest.mark.gui
def test_filtr_tabeli_zaweza_wiersze(qtbot: object, report_view: ReportView) -> None:
    """Wpisanie tekstu w polu filtra ukrywa wiersze bez dopasowania."""
    report_view.refresh()
    _wait_for_report(qtbot, report_view)
    total = report_view.table.rowCount()
    assert total > 0

    report_view.table_filter.setText("pusty")

    visible = [
        row for row in range(report_view.table.rowCount()) if not report_view.table.isRowHidden(row)
    ]
    assert 0 < len(visible) < total or total == 1

    report_view.table_filter.setText("")

    assert all(
        not report_view.table.isRowHidden(row) for row in range(report_view.table.rowCount())
    )


def test_wartosci_diagnostyki_sa_czytelne() -> None:
    """True/False, None i bajty nie moga trafiac do tabeli w surowej postaci."""
    from finddocs.gui.diagnostics_view import _flatten

    rows = dict(
        _flatten(
            {
                "fts5_dostepne": True,
                "sciezka": None,
                "pamiec_calkowita_bajty": 2048,
                "sqlite": {"wersja_sqlite": "3.42"},
            }
        )
    )
    assert rows["fts5 dostepne"] == "tak"
    assert rows["sciezka"] == "brak"
    assert rows["pamiec calkowita bajty"] == "2,0 kB"
    assert rows["sqlite / wersja sqlite"] == "3.42"


# --- diagnostyka ----------------------------------------------------------------


@pytest.mark.gui
def test_diagnostics_refresh_fills_tables(qtbot: object, diagnostics_view: DiagnosticsView) -> None:
    """Odswiezenie wypelnia tabele srodowiska, komponentow i indeksu."""
    diagnostics_view.refresh()

    qtbot.waitUntil(  # type: ignore[attr-defined]
        lambda: (
            diagnostics_view.environment_table.rowCount() > 0
            and diagnostics_view.components_table.rowCount() > 0
        ),
        timeout=TIMEOUT_MS,
    )
    assert diagnostics_view.index_table.rowCount() > 0
    # Przycieta kolumna nie pokaze pelnej tresci, wiec komorka ma podpowiedz.
    first = diagnostics_view.environment_table.item(0, 1)
    assert first is not None
    assert first.toolTip() == first.text()

    parameters = {
        diagnostics_view.components_table.item(row, 0).text()
        for row in range(diagnostics_view.components_table.rowCount())
    }
    # Klucze sa humanizowane: podkreslenia zamieniaja sie w spacje.
    assert any(name.startswith("parsery") for name in parameters)
    assert "model embeddingow" in parameters
    assert not any("_" in name for name in parameters)


@pytest.mark.gui
def test_query_logging_switch_updates_config(
    diagnostics_view: DiagnosticsView, gui_context: AppContext
) -> None:
    """Przelacznik zapisywania zapytan zmienia konfiguracje i zapisuje ja na dysk."""
    assert not gui_context.config.diagnostics.log_queries
    assert not diagnostics_view.log_queries.isChecked()

    diagnostics_view.log_queries.setChecked(True)

    assert gui_context.config.diagnostics.log_queries
    saved = json.loads(gui_context.paths.config_file.read_text(encoding="utf-8"))
    assert saved["diagnostics"]["log_queries"] is True

    diagnostics_view.log_queries.setChecked(False)

    assert not gui_context.config.diagnostics.log_queries
    saved = json.loads(gui_context.paths.config_file.read_text(encoding="utf-8"))
    assert saved["diagnostics"]["log_queries"] is False


@pytest.mark.gui
def test_compact_vectors_without_store_informs(
    diagnostics_view: DiagnosticsView, message_boxes: list[object]
) -> None:
    """Bez indeksu wektorowego kompaktowanie konczy sie banerem, nie oknem."""
    diagnostics_view.compact_vectors()

    assert message_boxes == []
    assert not diagnostics_view.banner.isHidden()
    assert "wektorowy" in diagnostics_view.banner.text()
