"""Ulamek postepu zadania indeksowania.

Pasek postepu jest jedyna informacja o tym, ile pracy jeszcze zostalo, wiec
mianownik musi byc uczciwy. Dwa bledy sa tu najkosztowniejsze: pasek pelny przy
trwajacej pracy oraz pasek stojacy na koncu skali przez cale zadanie.
"""

from __future__ import annotations

import pytest

from finddocs.types import JobKind, JobState, ProgressSnapshot


def migawka(**zmiany: object) -> ProgressSnapshot:
    dane: dict[str, object] = {
        "job_id": "zadanie",
        "kind": JobKind.RESCAN,
        "state": JobState.RUNNING,
        "stage": "indeksowanie",
        "stage_label": "Indeksowanie",
    }
    dane.update(zmiany)
    return ProgressSnapshot(**dane)  # type: ignore[arg-type]


def test_bez_policzonych_plikow_nie_ma_ulamka() -> None:
    """Sama liczba wykrytych plikow nie jest mianownikiem: rosnie razem z licznikiem."""
    snapshot = migawka(discovered=40, processed=40, discovery_complete=False)

    assert snapshot.total_hint == 0
    assert snapshot.progress_fraction is None


def test_policzone_pliki_daja_ulamek_przed_koncem_wykrywania() -> None:
    snapshot = migawka(discovered=25, processed=20, skipped=5, estimated_total=100)

    assert snapshot.handled == 25
    assert snapshot.total_hint == 100
    assert snapshot.progress_fraction == pytest.approx(0.25)


def test_ulamek_przed_koncem_wykrywania_nie_dochodzi_do_pelna() -> None:
    """Pelny pasek przy trwajacej pracy bylby nieprawda."""
    snapshot = migawka(discovered=100, processed=100, estimated_total=100)

    assert snapshot.progress_fraction == pytest.approx(0.99)


def test_nieaktualna_liczba_plikow_nie_daje_ulamka_powyzej_jedynki() -> None:
    """Zrodlo moglo urosnac miedzy policzeniem a przetwarzaniem."""
    snapshot = migawka(discovered=180, processed=180, estimated_total=100)

    assert snapshot.total_hint == 180
    assert snapshot.progress_fraction == pytest.approx(0.99)


def test_po_wykryciu_wszystkiego_ulamek_dochodzi_do_jedynki() -> None:
    snapshot = migawka(
        discovered=40,
        processed=30,
        unchanged=8,
        failed=2,
        estimated_total=100,
        discovery_complete=True,
    )

    assert snapshot.total_hint == 40
    assert snapshot.progress_fraction == pytest.approx(1.0)


def test_puste_zrodlo_konczy_sie_bez_ulamka() -> None:
    snapshot = migawka(discovery_complete=True)

    assert snapshot.progress_fraction is None
