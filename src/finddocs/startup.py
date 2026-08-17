"""Przygotowanie procesu przed startem aplikacji.

Aplikacja uruchamia sie prosto z kodu zrodlowego, wiec nie ma warstwy
instalatora, ktora ustawilaby zmienne srodowiskowe przed uruchomieniem
interpretera. Robi to ten modul, wolany z obu punktow wejscia: z interfejsu
graficznego i z wiersza polecen.
"""

from __future__ import annotations

import os

#: Zmienne wylaczajace pobieranie w tle i telemetrie bibliotek zewnetrznych.
#: Polityka sieciowa aplikacji dopuszcza tylko ruch wywolany przez uzytkownika,
#: a te biblioteki potrafia siegnac do sieci przy samym imporcie.
OFFLINE_DEFAULTS: dict[str, str] = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "DO_NOT_TRACK": "1",
}


def prepare_environment() -> None:
    """Ustawia domyslne zmienne srodowiskowe polityki sieciowej.

    Uzywa ``setdefault``, wiec swiadome ustawienie zmiennej w powloce ma
    pierwszenstwo. Pobieranie modelu embeddingow nie korzysta z tych bibliotek,
    tylko z wlasnego klienta HTTP, wiec zmienne go nie blokuja.
    """
    for name, value in OFFLINE_DEFAULTS.items():
        os.environ.setdefault(name, value)


__all__ = ["OFFLINE_DEFAULTS", "prepare_environment"]
