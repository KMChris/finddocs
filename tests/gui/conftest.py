"""Wspolne fixture testow interfejsu graficznego.

Testy dzialaja bez widocznego okna. Zmienna ``QT_QPA_PLATFORM`` jest ustawiana
przy imporcie tego pliku, czyli zanim pytest-qt utworzy ``QApplication``.

Indeks jest otwierany bez modelu embeddingow: klucz modelu wskazuje na katalog,
ktorego nie ma, wiec ``IndexService`` zglasza brak dostawcy i dziala w trybie
tylko dokladnym. Dzieki temu zaden test interfejsu nie laduje modelu ONNX.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QWidget

from finddocs.app_paths import AppPaths
from finddocs.config import LocalDirSourceSettings, SourceConfig
from finddocs.gui.context import AppContext
from finddocs.gui.main_window import MainWindow
from finddocs.gui.theme import LIGHT, Palette
from finddocs.gui.widgets.result_card import EmptyState, ResultCard
from finddocs.jobs.indexing_job import IndexingJob, JobOptions
from finddocs.types import JobKind, JobState, SourceKind

os.environ["QT_QPA_PLATFORM"] = "offscreen"

#: Klucz modelu, ktorego nie ma na dysku. Wymusza tryb tylko dokladny.
MISSING_MODEL_KEY = "model-testowy-ktorego-nie-ma"

#: Domyslny czas oczekiwania na zadanie wykonywane w tle (milisekundy).
TASK_TIMEOUT_MS = 15_000

#: Zawartosc korpusu testowego. Kluczem jest nazwa pliku.
CORPUS_FILES: dict[str, str] = {
    "procedura-01.txt": (
        "Procedura przelewow krajowych, wersja pierwsza.\n"
        "Numer rachunku 00 1234 5678 9012 3456 7890 1234.\n"
    ),
    "procedura-02.txt": "Procedura przelewow krajowych, wersja druga.\nDokument testowy.\n",
    "procedura-03.txt": "Procedura przelewow krajowych, wersja trzecia.\nDokument testowy.\n",
    "procedura-04.txt": "Procedura przelewow krajowych, wersja czwarta.\nDokument testowy.\n",
    "notatka.md": "Notatka o procedurze przelewow krajowych z dnia 24.07.2015.\n",
    "harmonogram.txt": "Harmonogram szkolen na drugi kwartal. Sala numer 12.\n",
    # Plik pusty daje dokument o statusie EMPTY, czyli niewyszukiwalny.
    # Uzywaja go testy raportu pokrycia i tabeli plikow pominietych.
    "pusty.txt": "",
}

#: Ile dokumentow korpusu zawiera slowo "przelewow".
CORPUS_TRANSFER_DOCUMENTS = 5

#: Ile dokumentow korpusu ma rozszerzenie .md.
CORPUS_MARKDOWN_DOCUMENTS = 1

#: Nazwa pliku, ktorego nie da sie wyszukac.
NON_SEARCHABLE_NAME = "pusty.txt"


# --- pomocnicze -----------------------------------------------------------------


def wait_for_tasks(timeout_ms: int = TASK_TIMEOUT_MS) -> None:
    """Czeka na zakonczenie zadan z puli watkow i dostarcza zalegle zdarzenia."""
    pool = QThreadPool.globalInstance()
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if QApplication.instance() is not None:
            QApplication.processEvents()
        if pool.activeThreadCount() == 0:
            break
        time.sleep(0.01)
    pool.waitForDone(timeout_ms)
    if QApplication.instance() is not None:
        QApplication.processEvents()


def local_source(root: Path, source_id: str = "zrodlo-testowe") -> SourceConfig:
    """Konfiguracja zrodla wskazujacego na katalog z korpusem."""
    return SourceConfig(
        source_id=source_id,
        kind=SourceKind.LOCAL_DIR,
        label="Katalog testowy",
        local=LocalDirSourceSettings(root_path=str(root)),
    )


def run_indexing(context: AppContext) -> None:
    """Indeksuje skonfigurowane zrodla synchronicznie, bez watku roboczego."""
    job = IndexingJob(
        context.config,
        context.require_index(),
        options=JobOptions(kind=JobKind.RESCAN),
        paths=context.paths,
    )
    snapshot = job.run()
    assert snapshot.state is JobState.COMPLETED, snapshot.message


def _result_widgets(view: QWidget) -> list[QWidget]:
    """Kontrolki wstawione aktualnie do listy wynikow.

    Karty usuniete przez ``deleteLater`` sa nadal dziecmi widoku, dopoki petla
    zdarzen ich nie posprzata. Czytamy wiec uklad, a nie liste dzieci.
    """
    layout = view._results_layout
    items = [layout.itemAt(position) for position in range(layout.count())]
    return [item.widget() for item in items if item is not None and item.widget() is not None]


# --- fixture --------------------------------------------------------------------


@pytest.fixture
def corpus_stats() -> dict[str, int]:
    """Liczby dokumentow w korpusie testowym uzywane w asercjach."""
    return {
        "przelewow": CORPUS_TRANSFER_DOCUMENTS,
        "markdown": CORPUS_MARKDOWN_DOCUMENTS,
        "niewyszukiwalne": 1,
    }


@pytest.fixture
def gui_palette() -> Palette:
    """Stala paleta jasna, zeby wynik testu nie zalezal od motywu systemu."""
    return LIGHT


@pytest.fixture(autouse=True)
def message_boxes(monkeypatch: pytest.MonkeyPatch) -> list[QMessageBox]:
    """Przechwytuje okna komunikatow, zeby modal nie zatrzymal testu.

    Zwraca liste okien w kolejnosci pojawiania sie. ``exec`` nie klika zadnego
    przycisku, wiec ``ask_yes_no`` odpowiada przeczaco.
    """
    seen: list[QMessageBox] = []

    def fake_exec(box: QMessageBox) -> int:
        seen.append(box)
        return int(QMessageBox.StandardButton.Ok)

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    return seen


@pytest.fixture(autouse=True)
def _drain_thread_pool(qtbot: object) -> Iterator[None]:
    """Po tescie czeka na zadania w tle, zanim pytest-qt usunie kontrolki."""
    yield
    wait_for_tasks()


@pytest.fixture
def gui_context(tmp_home: AppPaths) -> Iterator[AppContext]:
    """AppContext z katalogiem danych w tmp_path i otwartym indeksem bez modelu."""
    context = AppContext()
    context.config.embedding.model_key = MISSING_MODEL_KEY
    context.config.embedding.model_path = str(tmp_home.models_dir / "brak-modelu")
    context.open()
    try:
        yield context
    finally:
        wait_for_tasks()
        context.close()


@pytest.fixture
def gui_corpus(tmp_path: Path) -> Path:
    """Katalog z kilkoma malymi dokumentami tekstowymi."""
    root = tmp_path / "korpus"
    root.mkdir(parents=True, exist_ok=True)
    for name, content in CORPUS_FILES.items():
        (root / name).write_text(content, encoding="utf-8")
    return root


@pytest.fixture
def gui_context_with_source(gui_context: AppContext, gui_corpus: Path) -> AppContext:
    """Kontekst ze zrodlem lokalnym, ale jeszcze bez zaindeksowanych dokumentow."""
    gui_context.config.sources.append(local_source(gui_corpus))
    return gui_context


@pytest.fixture
def indexed_gui_context(gui_context_with_source: AppContext) -> AppContext:
    """Kontekst z malym zaindeksowanym korpusem."""
    run_indexing(gui_context_with_source)
    return gui_context_with_source


@pytest.fixture
def main_window(qtbot: object, gui_context: AppContext, gui_palette: Palette) -> MainWindow:
    """Okno glowne zbudowane na pustej konfiguracji."""
    window = MainWindow(gui_context, gui_palette)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    return window


@pytest.fixture
def result_cards() -> Callable[[QWidget], list[ResultCard]]:
    """Funkcja zwracajaca karty wynikow widoczne aktualnie w liscie."""

    def collect(view: QWidget) -> list[ResultCard]:
        return [w for w in _result_widgets(view) if isinstance(w, ResultCard)]

    return collect


@pytest.fixture
def empty_state_text() -> Callable[[QWidget], str]:
    """Funkcja zwracajaca tresc komunikatu zastepczego albo pusty napis."""

    def read(view: QWidget) -> str:
        for widget in _result_widgets(view):
            if isinstance(widget, EmptyState):
                label = widget.findChild(QLabel)
                return label.text() if label is not None else ""
        return ""

    return read
