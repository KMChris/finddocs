"""Testy warstwy pracy w tle interfejsu.

Interfejs nigdy nie liczy niczego w watku glownym. Testy pilnuja dwoch rzeczy:
wynik wraca do watku glownego, a obiekt zadania zyje dopoki tego wyniku nie odda.
Bez tego drugiego warunku pula usuwa zadanie zaraz po ``run``, a zdarzenie
czekajace w kolejce wskazuje na zwolniona pamiec i proces konczy sie naruszeniem
ochrony pamieci zamiast wyjatkiem.
"""

from __future__ import annotations

import gc
import threading
from collections.abc import Callable

import pytest

from finddocs.errors import ExtractionError, SearchCancelledError
from finddocs.gui.workers import (
    CallableTask,
    CancellationFlag,
    ProgressBridge,
    SearchTask,
    active_task_count,
    thread_pool,
)
from finddocs.types import (
    JobKind,
    JobState,
    ProgressSnapshot,
    QueryAnalysis,
    SearchMode,
    SearchRequest,
    SearchResponse,
)

pytestmark = pytest.mark.gui


def test_callable_task_zwraca_wynik(qtbot: object, drain_tasks: Callable[[], None]) -> None:
    """Wynik funkcji trafia do sygnalu finished."""
    wyniki: list[object] = []
    task = CallableTask(lambda: {"wartosc": 42}, label="test")
    task.signals.finished.connect(wyniki.append)

    thread_pool().start(task)
    drain_tasks()

    assert wyniki == [{"wartosc": 42}]


def test_callable_task_pracuje_poza_watkiem_glownym(
    qtbot: object, drain_tasks: Callable[[], None]
) -> None:
    """Funkcja wykonuje sie w puli, a nie w watku rysujacym interfejs."""
    watek_pracy: list[int] = []
    watek_glowny = threading.get_ident()
    watek_odbioru: list[int] = []

    def praca() -> str:
        watek_pracy.append(threading.get_ident())
        return "gotowe"

    task = CallableTask(praca, label="watki")
    task.signals.finished.connect(lambda _: watek_odbioru.append(threading.get_ident()))

    thread_pool().start(task)
    drain_tasks()

    assert watek_pracy and watek_pracy[0] != watek_glowny
    assert watek_odbioru == [watek_glowny]


def test_callable_task_zglasza_blad_z_kodem(qtbot: object, drain_tasks: Callable[[], None]) -> None:
    """Wyjatek aplikacji wraca jako kod i komunikat po polsku."""
    bledy: list[tuple[str, str]] = []
    task = CallableTask(lambda: (_ for _ in ()).throw(ExtractionError("Blad testowy.")))
    task.signals.failed.connect(lambda code, message: bledy.append((code, message)))

    thread_pool().start(task)
    drain_tasks()

    assert len(bledy) == 1
    assert bledy[0][0].startswith("FD-")
    assert bledy[0][1]


def test_callable_task_zglasza_nieoczekiwany_wyjatek(
    qtbot: object, drain_tasks: Callable[[], None]
) -> None:
    """Wyjatek spoza hierarchii aplikacji tez nie przewraca interfejsu."""
    bledy: list[tuple[str, str]] = []
    task = CallableTask(lambda: 1 // 0)
    task.signals.failed.connect(lambda code, message: bledy.append((code, message)))

    thread_pool().start(task)
    drain_tasks()

    assert len(bledy) == 1
    assert "ZeroDivisionError" in bledy[0][1]


def test_zadanie_zyje_do_czasu_dostarczenia_wyniku(
    qtbot: object, drain_tasks: Callable[[], None]
) -> None:
    """Rejestr zadan trzyma obiekt przy zyciu mimo braku referencji z zewnatrz."""
    wyniki: list[object] = []
    przed = active_task_count()

    task = CallableTask(lambda: "wynik")
    task.signals.finished.connect(wyniki.append)
    thread_pool().start(task)
    del task
    gc.collect()

    drain_tasks()

    assert wyniki == ["wynik"]
    assert active_task_count() == przed


def test_rejestr_zwalnia_zadanie_po_bledzie(qtbot: object, drain_tasks: Callable[[], None]) -> None:
    """Zadanie zakonczone bledem tez znika z rejestru."""
    przed = active_task_count()
    task = CallableTask(lambda: 1 // 0)
    task.signals.failed.connect(lambda _code, _message: None)

    thread_pool().start(task)
    drain_tasks()

    assert active_task_count() == przed


def _odpowiedz(request: SearchRequest) -> SearchResponse:
    """Pusta, ale poprawna odpowiedz wyszukiwarki."""
    return SearchResponse(
        hits=[],
        total_documents=0,
        total_is_exact=True,
        mode=request.mode,
        took_ms=1,
        query_analysis=QueryAnalysis(
            raw_query=request.query,
            normalized_query=request.query,
            semantic_text=request.query,
        ),
    )


def _pusta_odpowiedz(request: SearchRequest, _token: CancellationFlag) -> SearchResponse:
    return _odpowiedz(request)


def test_search_task_zwraca_odpowiedz(qtbot: object, drain_tasks: Callable[[], None]) -> None:
    """Wyszukiwanie w tle oddaje gotowa odpowiedz do interfejsu."""
    odpowiedzi: list[SearchResponse] = []
    request = SearchRequest(query="przelew", mode=SearchMode.EXACT)
    task = SearchTask(_pusta_odpowiedz, request)
    task.signals.finished.connect(odpowiedzi.append)

    thread_pool().start(task)
    drain_tasks()

    assert len(odpowiedzi) == 1
    assert odpowiedzi[0].query_analysis.raw_query == "przelew"
    assert odpowiedzi[0].mode is SearchMode.EXACT


def test_search_task_zglasza_anulowanie(qtbot: object, drain_tasks: Callable[[], None]) -> None:
    """Anulowane wyszukiwanie konczy sie sygnalem cancelled, nie bledem."""
    anulowane: list[bool] = []

    def przerwane(_request: SearchRequest, token: CancellationFlag) -> SearchResponse:
        token.cancel()
        token.raise_if_cancelled()
        raise AssertionError("nieosiagalne")

    task = SearchTask(przerwane, SearchRequest(query="x", mode=SearchMode.EXACT))
    task.signals.cancelled.connect(lambda: anulowane.append(True))

    thread_pool().start(task)
    drain_tasks()

    assert anulowane == [True]


def test_search_task_anulowanie_po_zakonczeniu_pracy(
    qtbot: object, drain_tasks: Callable[[], None]
) -> None:
    """Wynik odrzucamy, gdy uzytkownik anulowal wyszukiwanie w trakcie liczenia."""
    zdarzenia: list[str] = []

    def powolne(request: SearchRequest, token: CancellationFlag) -> SearchResponse:
        token.cancel()
        return _odpowiedz(request)

    task = SearchTask(powolne, SearchRequest(query="x", mode=SearchMode.EXACT))
    task.signals.finished.connect(lambda _: zdarzenia.append("finished"))
    task.signals.cancelled.connect(lambda: zdarzenia.append("cancelled"))

    thread_pool().start(task)
    drain_tasks()

    assert zdarzenia == ["cancelled"]


def test_token_anulowania_podnosi_wyjatek() -> None:
    """Token zglasza wyjatek dopiero po anulowaniu."""
    token = CancellationFlag()

    token.raise_if_cancelled()
    token.cancel()

    assert token.is_cancelled() is True
    with pytest.raises(SearchCancelledError):
        token.raise_if_cancelled()


def test_most_postepu_przenosi_migawke_do_watku_glownego(
    qtbot: object, drain_tasks: Callable[[], None]
) -> None:
    """ProgressBridge dostarcza migawki postepu do watku interfejsu."""
    bridge = ProgressBridge()
    odebrane: list[ProgressSnapshot] = []
    watek_glowny = threading.get_ident()
    watki_odbioru: list[int] = []

    def zapisz(snapshot: object) -> None:
        assert isinstance(snapshot, ProgressSnapshot)
        odebrane.append(snapshot)
        watki_odbioru.append(threading.get_ident())

    bridge.progress.connect(zapisz)
    snapshot = ProgressSnapshot(
        job_id="1",
        kind=JobKind.FULL_INDEX,
        state=JobState.RUNNING,
        stage="skanowanie",
        stage_label="Skanowanie zrodel",
        discovered=3,
        processed=1,
    )

    watek = threading.Thread(target=lambda: bridge.publish(snapshot), name="publikacja")
    watek.start()
    watek.join(5.0)
    drain_tasks()

    assert len(odebrane) == 1
    assert odebrane[0].stage == "skanowanie"
    assert watki_odbioru == [watek_glowny]


def test_pula_watkow_ma_co_najmniej_cztery_watki() -> None:
    """Pula musi obsluzyc wyszukiwanie i odswiezanie diagnostyki jednoczesnie."""
    assert thread_pool().maxThreadCount() >= 4
