"""Testy okien komunikatow i polskich tekstow interfejsu."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from PySide6.QtWidgets import QMessageBox

from finddocs.gui import dialogs, i18n
from finddocs.types import DocumentStatus, JobState, MatchKind, SearchMode


def _button_texts(box: QMessageBox) -> list[str]:
    return [button.text() for button in box.buttons()]


# --- okna komunikatow -----------------------------------------------------------


@pytest.mark.gui
@pytest.mark.parametrize(
    ("show", "title", "icon"),
    [
        (dialogs.show_info, i18n.INFO_TITLE, QMessageBox.Icon.Information),
        (dialogs.show_warning, i18n.WARNING_TITLE, QMessageBox.Icon.Warning),
        (dialogs.show_error, i18n.ERROR_TITLE, QMessageBox.Icon.Critical),
    ],
)
def test_message_dialogs_use_polish_buttons(
    qtbot: object,
    message_boxes: list[QMessageBox],
    show: Callable[..., None],
    title: str,
    icon: QMessageBox.Icon,
) -> None:
    """Komunikat ma polski tytul, wlasciwa ikone i jeden przycisk OK."""
    show(None, "Tresc komunikatu")

    assert len(message_boxes) == 1
    box = message_boxes[0]
    assert box.windowTitle() == title
    assert box.icon() is icon
    assert box.text() == "Tresc komunikatu"
    assert _button_texts(box) == [i18n.BUTTON_OK]


@pytest.mark.gui
def test_error_with_code_shows_code(qtbot: object, message_boxes: list[QMessageBox]) -> None:
    """Blad z kodem podaje kod w tresci, zeby uzytkownik mogl go zglosic."""
    dialogs.show_error_with_code(None, "FD-3002", "Nie udalo sie odczytac pliku.")

    assert len(message_boxes) == 1
    assert "Nie udalo sie odczytac pliku." in message_boxes[0].text()
    assert "Kod bledu: FD-3002" in message_boxes[0].text()


@pytest.mark.gui
def test_question_dialog_has_polish_answers(
    qtbot: object, message_boxes: list[QMessageBox]
) -> None:
    """Pytanie ma przyciski Tak i Nie, a domyslna odpowiedzia jest Nie."""
    answer = dialogs.ask_yes_no(None, "Czy kontynuowac?")

    assert answer is False
    box = message_boxes[0]
    assert box.windowTitle() == i18n.CONFIRM_TITLE
    assert _button_texts(box) == ["Tak", "Nie"]
    assert box.defaultButton().text() == "Nie"


@pytest.mark.gui
def test_question_dialog_returns_true_after_yes(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, message_boxes: list[QMessageBox]
) -> None:
    """Klikniecie przycisku Tak daje odpowiedz twierdzaca."""

    def accept(box: QMessageBox) -> int:
        message_boxes.append(box)
        for button in box.buttons():
            if button.text() == "Tak":
                button.click()
        return int(QMessageBox.StandardButton.Yes)

    monkeypatch.setattr(QMessageBox, "exec", accept)

    assert dialogs.ask_yes_no(None, "Czy kontynuowac?", "Pytanie") is True
    assert message_boxes[0].windowTitle() == "Pytanie"


# --- formaty polskie ------------------------------------------------------------


@pytest.mark.gui
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "0 B"),
        (512, "512 B"),
        (1023, "1023 B"),
        (1024, "1,0 kB"),
        (1536, "1,5 kB"),
        (1024**2, "1,0 MB"),
        (int(2.5 * 1024**3), "2,5 GB"),
        (1024**4, "1,0 TB"),
        (1024**5, "1024,0 TB"),
    ],
)
def test_format_bytes(value: int, expected: str) -> None:
    """Rozmiar ma przecinek dziesietny i jednostke po spacji."""
    assert i18n.format_bytes(value) == expected
    assert "." not in i18n.format_bytes(value)


@pytest.mark.gui
@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "0 s"),
        (-12, "0 s"),
        (9.7, "9 s"),
        (59, "59 s"),
        (60, "1 min 0 s"),
        (90, "1 min 30 s"),
        (3600, "1 godz. 0 min"),
        (3725, "1 godz. 2 min"),
    ],
)
def test_format_duration(seconds: float, expected: str) -> None:
    """Czas trwania jest podawany po polsku, bez ujemnych wartosci."""
    assert i18n.format_duration(seconds) == expected


@pytest.mark.gui
@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (0, "0 dokumentow"),
        (1, "1 dokument"),
        (2, "2 dokumenty"),
        (4, "4 dokumenty"),
        (5, "5 dokumentow"),
        (11, "11 dokumentow"),
        (12, "12 dokumentow"),
        (13, "13 dokumentow"),
        (14, "14 dokumentow"),
        (21, "21 dokumentow"),
        (22, "22 dokumenty"),
        (25, "25 dokumentow"),
        (102, "102 dokumenty"),
        (112, "112 dokumentow"),
    ],
)
def test_documents_count(count: int, expected: str) -> None:
    """Odmiana rzeczownika po liczbie zgodna z regulami polskimi."""
    assert i18n.documents_count(count) == expected
    assert i18n.format_count(count, "dokument", "dokumenty", "dokumentow") == expected


@pytest.mark.gui
def test_files_count_uses_its_own_forms() -> None:
    """Liczba plikow uzywa form: plik, pliki, plikow."""
    assert i18n.files_count(1) == "1 plik"
    assert i18n.files_count(3) == "3 pliki"
    assert i18n.files_count(8) == "8 plikow"


# --- kompletnosc slownikow ------------------------------------------------------


@pytest.mark.gui
@pytest.mark.parametrize(
    ("labels", "enum_type"),
    [
        (i18n.MODE_LABELS, SearchMode),
        (i18n.MODE_HINTS, SearchMode),
        (i18n.MATCH_LABELS, MatchKind),
        (i18n.STATUS_LABELS, DocumentStatus),
        (i18n.JOB_STATE_LABELS, JobState),
    ],
)
def test_label_dictionaries_cover_full_enums(labels: dict[object, str], enum_type: type) -> None:
    """Kazda wartosc enumu ma swoj polski opis i zaden opis nie jest pusty."""
    assert set(labels) == set(enum_type)
    assert all(text.strip() for text in labels.values())
