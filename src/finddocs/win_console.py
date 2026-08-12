"""Tlumienie okien konsoli otwieranych przez biblioteke standardowa.

``platform.win32_ver`` w Pythonie 3.11 pyta system o wersje poleceniem
``cmd /c ver`` uruchamianym w procesie potomnym. Aplikacja graficzna nie ma
wlasnej konsoli (``pythonw.exe``, wersja spakowana), wiec Windows tworzy dla
takiego procesu nowa konsole: na ulamek sekundy zapala sie czarne okno.

Wywolania nie pochodza z kodu aplikacji, tylko z bibliotek zewnetrznych:
``onnxruntime`` sprawdza system przy imporcie, ``keyring`` przy wyborze
magazynu poswiadczen. Zamiast poprawiac kazde z nich podmieniamy prywatna
funkcje ``platform._syscmd_ver`` na wersje bez procesu potomnego. Po podmianie
``platform.win32_ver`` schodzi na sciezke zapasowa wbudowana w biblioteke
standardowa i czyta wersje z ``sys.getwindowsversion()``.

Flaga ``NO_CONSOLE_WINDOW`` sluzy wlasnym wywolaniom programow konsolowych.
"""

from __future__ import annotations

import platform
import subprocess
import sys

#: Flaga ``CREATE_NO_WINDOW``: proces potomny nie dostaje wlasnego okna konsoli.
#: Poza Windows nie istnieje, wtedy zero oznacza brak dodatkowych flag.
NO_CONSOLE_WINDOW: int = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_patched = False


def _syscmd_ver_without_console(
    system: str = "",
    release: str = "",
    version: str = "",
    supported_platforms: tuple[str, ...] = ("win32", "win16", "dos"),
) -> tuple[str, str, str]:
    """Zamiennik ``platform._syscmd_ver`` oddajacy wartosci domyslne.

    Pusta wersja jest dla ``platform.win32_ver`` sygnalem, ze odpytanie systemu
    sie nie udalo. Biblioteka standardowa liczy wtedy numer z
    ``sys.getwindowsversion()``, czyli bez uruchamiania czegokolwiek.
    """
    return system, release, version


def suppress_console_windows() -> bool:
    """Wylacza okna konsoli z ``platform.win32_ver``. Zwraca True, gdy podmieniono.

    Wywolanie jest bezpieczne wielokrotnie i poza Windows nie robi nic.
    """
    global _patched
    if _patched or sys.platform != "win32":
        return False
    if not hasattr(platform, "_syscmd_ver"):  # pragma: no cover - inna wersja Pythona
        return False
    platform._syscmd_ver = _syscmd_ver_without_console
    _patched = True
    return True


__all__ = ["NO_CONSOLE_WINDOW", "suppress_console_windows"]
