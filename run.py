"""Uruchamia FindDocs bezposrednio z kodu zrodlowego.

Aplikacja nie ma instalatora, pliku wykonywalnego ani pakietu na PyPI.
Uruchamia sie ja tym skryptem, interpreterem ze srodowiska, w ktorym
zainstalowano zaleznosci z pliku ``requirements.txt``:

    python run.py                      interfejs graficzny
    python run.py gui --data-dir D     interfejs graficzny z opcjami
    python run.py index                polecenia administracyjne
    python run.py --help               lista polecen administracyjnych

Skrypt dodaje katalog ``src`` do sciezki importow, wiec pakiet ``finddocs``
dziala bez instalowania go w srodowisku.
"""

from __future__ import annotations

import contextlib
import os
import sys
import traceback
from collections.abc import Callable
from pathlib import Path

MINIMUM_PYTHON = (3, 11)
SOURCE_DIR = Path(__file__).resolve().parent / "src"

INSTALL_HINT = (
    "Zainstaluj zależności w środowisku wirtualnym:\n"
    "    py -3.11 -m venv .venv\n"
    "    .venv\\Scripts\\python.exe -m pip install -r requirements.txt\n"
    "a potem uruchom aplikację tym samym interpreterem:\n"
    "    .venv\\Scripts\\python.exe run.py"
)


def _report(message: str) -> None:
    """Pokazuje komunikat takze wtedy, gdy proces nie ma konsoli.

    Skrot uruchamiany przez ``pythonw.exe`` nie ma strumienia bledow, wiec
    komunikat wypisany na wyjscie zginalby bez sladu.
    """
    if sys.stderr is not None:
        # Konsola Windows domyslnie nie uzywa UTF-8, a komunikat ma polskie
        # znaki. Bez tego kroku wypisanie bledu moglo by sie samo wywrocic.
        reconfigure = getattr(sys.stderr, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(OSError, ValueError):
                reconfigure(encoding="utf-8", errors="replace")
        print(message, file=sys.stderr)
        return
    import ctypes

    with contextlib.suppress(Exception):
        ctypes.windll.user32.MessageBoxW(None, message, "FindDocs", 0x10)


def _report_failure(exc: BaseException) -> None:
    """Zapisuje slad wyjatku i mowi uzytkownikowi, gdzie go szukac.

    Uruchomienie przez ``pythonw.exe`` nie zostawia nic na ekranie, wiec bez
    tego pliku blad startu bylby niemozliwy do zdiagnozowania.
    """
    home = os.environ.get("FINDDOCS_HOME")
    if home:
        katalog = Path(home) / "logs"
    else:
        katalog = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "FindDocs" / "logs"
    cel = katalog / "blad-uruchomienia.txt"
    try:
        katalog.mkdir(parents=True, exist_ok=True)
        cel.write_text("".join(traceback.format_exception(exc)), encoding="utf-8")
    except OSError:
        cel = Path("blad-uruchomienia.txt")
    _report(
        "Nie udało się uruchomić aplikacji FindDocs.\n\n"
        f"{type(exc).__name__}: {exc}\n\n"
        f"Szczegóły zapisano w pliku:\n{cel}"
    )


def _entry_point(command: str) -> Callable[[list[str]], int]:
    """Zwraca funkcje glowna interfejsu graficznego albo wiersza polecen."""
    if command == "gui":
        from finddocs.gui.app import main as run_gui

        return run_gui
    from finddocs.cli import main as run_cli

    return run_cli


def main(argv: list[str]) -> int:
    if sys.version_info < MINIMUM_PYTHON:
        wymagany = ".".join(str(part) for part in MINIMUM_PYTHON)
        _report(
            f"FindDocs wymaga Pythona {wymagany} lub nowszego, a ten interpreter "
            f"to {sys.version.split()[0]}:\n{sys.executable}"
        )
        return 1
    if not SOURCE_DIR.is_dir():
        _report(f"Nie znaleziono katalogu z kodem aplikacji: {SOURCE_DIR}")
        return 1
    sys.path.insert(0, str(SOURCE_DIR))

    command = argv[0] if argv else "gui"
    arguments = argv[1:] if command == "gui" else argv
    try:
        entry = _entry_point(command)
    except ImportError as exc:
        brakujacy = exc.name or "nieznany"
        _report(f"Brakuje pakietu „{brakujacy}”, wymaganego do uruchomienia.\n\n{INSTALL_HINT}")
        return 1
    try:
        return entry(arguments)
    except Exception as exc:
        _report_failure(exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
