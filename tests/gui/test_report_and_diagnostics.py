"""Testy ekranu raportu pokrycia i ekranu diagnostyki."""

from __future__ import annotations

import json

import pytest
from PySide6.QtWidgets import QLabel

from finddocs.gui import i18n
from finddocs.gui.context import AppContext
from finddocs.gui.diagnostics_view import DiagnosticsView
from finddocs.gui.report_view import ReportView

#: Raport i diagnostyka licza sie w tle, wiec czekamy na wynik.
TIMEOUT_MS = 15_000


def _summary_labels(view: ReportView) -> list[str]:
    """Napisy widoczne w siatce podsumowania raportu."""
    return [label.text() for label in view.summary_box.findChildren(QLabel)]


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


@pytest.mark.gui
def test_report_shows_summary_after_refresh(qtbot: object, report_view: ReportView) -> None:
    """Odswiezenie wypelnia podsumowanie i informacje o kompletnosci zbioru."""
    report_view.refresh()

    qtbot.waitUntil(lambda: bool(report_view.completeness.text()), timeout=TIMEOUT_MS)  # type: ignore[attr-defined]
    labels = _summary_labels(report_view)
    assert "Wykryte pliki" in labels
    assert "Zaindeksowane" in labels
    assert "Rozmiar indeksu" in labels
    assert "Wersja aplikacji" in labels


@pytest.mark.gui
def test_report_reports_incomplete_set(
    qtbot: object, report_view: ReportView, corpus_stats: dict[str, int]
) -> None:
    """Gdy sa dokumenty niewyszukiwalne, komunikat mowi wprost o niekompletnosci."""
    report_view.refresh()

    qtbot.waitUntil(lambda: bool(report_view.completeness.text()), timeout=TIMEOUT_MS)  # type: ignore[attr-defined]
    expected = i18n.REPORT_INCOMPLETE.format(count=corpus_stats["niewyszukiwalne"])
    assert report_view.completeness.text() == expected
    assert i18n.REPORT_COMPLETE not in report_view.completeness.text()

    assert report_view.table.rowCount() == corpus_stats["niewyszukiwalne"]
    assert report_view.table.item(0, 0).text() == "pusty.txt"
    assert report_view.table.item(0, 2).text() == "brak tresci"


@pytest.mark.gui
def test_report_on_empty_index(qtbot: object, gui_context: AppContext) -> None:
    """Pusty indeks nie jest opisywany jako kompletny zbior."""
    view = ReportView(gui_context)
    qtbot.addWidget(view)  # type: ignore[attr-defined]

    view.refresh()

    qtbot.waitUntil(lambda: bool(view.completeness.text()), timeout=TIMEOUT_MS)  # type: ignore[attr-defined]
    assert view.completeness.text() == "Indeks jest pusty."
    assert view.table.rowCount() == 0


@pytest.mark.gui
def test_report_export_without_data_asks_for_refresh(
    qtbot: object, gui_context: AppContext, message_boxes: list[object]
) -> None:
    """Eksport przed odswiezeniem konczy sie podpowiedzia, a nie zapisem pliku."""
    view = ReportView(gui_context)
    qtbot.addWidget(view)  # type: ignore[attr-defined]

    view.export("csv")

    assert len(message_boxes) == 1
    assert list(gui_context.paths.reports_dir.iterdir()) == []


# --- diagnostyka ----------------------------------------------------------------


@pytest.mark.gui
def test_diagnostics_refresh_fills_tables(qtbot: object, diagnostics_view: DiagnosticsView) -> None:
    """Odswiezenie wypelnia tabele srodowiska, komponentow i indeksu."""
    diagnostics_view.refresh()

    qtbot.waitUntil(  # type: ignore[attr-defined]
        lambda: diagnostics_view.environment_table.rowCount() > 0
        and diagnostics_view.components_table.rowCount() > 0,
        timeout=TIMEOUT_MS,
    )
    assert diagnostics_view.index_table.rowCount() > 0

    parameters = {
        diagnostics_view.components_table.item(row, 0).text()
        for row in range(diagnostics_view.components_table.rowCount())
    }
    assert any(name.startswith("parsery") for name in parameters)
    assert "model_embeddingow" in parameters


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
    """Bez indeksu wektorowego kompaktowanie konczy sie komunikatem."""
    diagnostics_view.compact_vectors()

    assert len(message_boxes) == 1
