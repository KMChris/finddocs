"""Punkt wejscia aplikacji spakowanej przez PyInstaller.

Plik jest celowo maly. Jego zadaniem jest przygotowanie srodowiska i oddanie
sterowania do ``finddocs.gui.app.main``. Kazdy blad, ktory wystapi zanim wstanie
Qt, jest zapisywany do pliku obok katalogu danych i pokazywany uzytkownikowi.
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path


def _resource_root() -> Path:
    """Katalog z zasobami dolaczonymi do pakietu."""
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle)
    return Path(__file__).resolve().parent


def _prepare_environment() -> None:
    """Ustawia zmienne srodowiskowe potrzebne w wersji spakowanej."""
    root = _resource_root()
    models = root / "models"
    if models.is_dir():
        os.environ.setdefault("FINDDOCS_BUNDLED_MODELS", str(models))
    # Qt w wersji spakowanej znajduje wtyczki samo, ale przy nietypowych
    # instalacjach warto wskazac katalog wprost.
    plugins = root / "PySide6" / "plugins"
    if plugins.is_dir():
        os.environ.setdefault("QT_PLUGIN_PATH", str(plugins))
    # Blokujemy telemetrie bibliotek zewnetrznych na wszelki wypadek.
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("DO_NOT_TRACK", "1")


def _report_startup_failure(exc: BaseException) -> None:
    """Zapisuje szczegoly bledu startu i probuje pokazac je uzytkownikowi."""
    home = os.environ.get("FINDDOCS_HOME")
    if home:
        log_dir = Path(home) / "logs"
    else:
        local = os.environ.get("LOCALAPPDATA") or str(Path.home())
        log_dir = Path(local) / "FindDocs" / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        target = log_dir / "blad-uruchomienia.txt"
        target.write_text(
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            encoding="utf-8",
        )
    except OSError:
        target = Path("blad-uruchomienia.txt")

    message = (
        "Nie udalo sie uruchomic aplikacji FindDocs.\n\n"
        f"{type(exc).__name__}: {exc}\n\n"
        f"Szczegoly zapisano w pliku:\n{target}"
    )
    if os.environ.get("FINDDOCS_NO_DIALOG") == "1":
        # Tryb nieinteraktywny (test dymny, uruchomienie z harmonogramu):
        # okno dialogowe zablokowaloby proces, wiec tylko zapisujemy blad.
        print(message, file=sys.stderr)
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "FindDocs", 0x10)
    except Exception:
        print(message, file=sys.stderr)


def main() -> int:
    _prepare_environment()
    try:
        from finddocs.gui.app import main as run_gui
    except Exception as exc:
        _report_startup_failure(exc)
        return 1
    try:
        return run_gui(sys.argv[1:])
    except Exception as exc:
        _report_startup_failure(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
