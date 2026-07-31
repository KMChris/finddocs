"""Okna komunikatow z jednolitym wygladem i polskimi przyciskami.

Statyczne metody ``QMessageBox`` maja w PySide6 kilka przeciazen o roznej liczbie
argumentow. Owijamy je tutaj raz, zeby widoki mialy jedno, jasne wywolanie,
a kontrola typow nie zglaszala falszywych bledow.
"""

from __future__ import annotations

import os
import sys

from PySide6.QtWidgets import QMessageBox, QWidget

from finddocs.gui import i18n


def dialogs_suppressed() -> bool:
    """Czy okna modalne maja byc pominiete.

    Ustawienie ``FINDDOCS_NO_DIALOG=1`` wylacza okna wymagajace klikniecia.
    Korzysta z tego test dymny zbudowanej aplikacji i uruchomienie z harmonogramu,
    gdzie nikt nie kliknie ,,OK'' i proces stalby w miejscu bez konca.
    """
    return os.environ.get("FINDDOCS_NO_DIALOG") == "1"


def _log_suppressed(title: str, text: str) -> None:
    print(f"[{title}] {text}", file=sys.stderr)


def _prepare(parent: QWidget | None, icon: QMessageBox.Icon, title: str, text: str) -> QMessageBox:
    box = QMessageBox(parent)
    box.setIcon(icon)
    box.setWindowTitle(title)
    box.setText(text)
    box.setTextInteractionFlags(box.textInteractionFlags())
    return box


def show_info(parent: QWidget | None, text: str, title: str = i18n.INFO_TITLE) -> None:
    """Komunikat informacyjny."""
    if dialogs_suppressed():
        _log_suppressed(title, text)
        return
    box = _prepare(parent, QMessageBox.Icon.Information, title, text)
    button = box.addButton(QMessageBox.StandardButton.Ok)
    button.setText(i18n.BUTTON_OK)
    box.exec()


def show_warning(parent: QWidget | None, text: str, title: str = i18n.WARNING_TITLE) -> None:
    """Ostrzezenie."""
    if dialogs_suppressed():
        _log_suppressed(title, text)
        return
    box = _prepare(parent, QMessageBox.Icon.Warning, title, text)
    button = box.addButton(QMessageBox.StandardButton.Ok)
    button.setText(i18n.BUTTON_OK)
    box.exec()


def show_error(parent: QWidget | None, text: str, title: str = i18n.ERROR_TITLE) -> None:
    """Blad."""
    if dialogs_suppressed():
        _log_suppressed(title, text)
        return
    box = _prepare(parent, QMessageBox.Icon.Critical, title, text)
    button = box.addButton(QMessageBox.StandardButton.Ok)
    button.setText(i18n.BUTTON_OK)
    box.exec()


def show_error_with_code(parent: QWidget | None, code: str, message: str) -> None:
    """Blad wraz z kodem, ktory ulatwia zgloszenie problemu."""
    show_error(parent, f"{message}\n\nKod bledu: {code}")


def ask_yes_no(parent: QWidget | None, text: str, title: str = i18n.CONFIRM_TITLE) -> bool:
    """Pytanie tak lub nie. Zwraca True, gdy uzytkownik potwierdzil."""
    if dialogs_suppressed():
        _log_suppressed(title, text)
        return False
    box = _prepare(parent, QMessageBox.Icon.Question, title, text)
    yes = box.addButton("Tak", QMessageBox.ButtonRole.YesRole)
    no = box.addButton("Nie", QMessageBox.ButtonRole.NoRole)
    box.setDefaultButton(no)
    box.exec()
    return box.clickedButton() is yes


__all__ = [
    "ask_yes_no",
    "dialogs_suppressed",
    "show_error",
    "show_error_with_code",
    "show_info",
    "show_warning",
]
