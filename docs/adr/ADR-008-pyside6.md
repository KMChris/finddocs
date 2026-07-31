# ADR-008: PySide6 jako biblioteka interfejsu

**Stan:** przyjęta
**Data:** lipiec 2026

## Kontekst

Interfejs ma wyglądać nowocześnie na Windows 11, być w języku polskim,
obsługiwać skalowanie DPI i nigdy nie blokować się podczas indeksowania ani
wyszukiwania. Nie może to być interfejs w przeglądarce (ADR-001).

Licencja musi pozwalać na wdrożenie korporacyjne bez zakupu.

## Decyzja

PySide6, czyli oficjalne wiązania Qt dla Pythona, na licencji LGPL-3.0.

Zasada: **wątek główny tylko rysuje**. Wyszukiwanie idzie do puli wątków
(`QThreadPool`), indeksowanie do osobnego wątku (`JobRunner`). Wyniki wracają
sygnałami Qt dostarczanymi w kolejce do wątku głównego.

Wygląd: własny arkusz stylów w duchu Fluent, palety jasna i ciemna,
przełączane zgodnie z ustawieniem systemu.

## Rozważane alternatywy

**PyQt6.** Technicznie równoważny, ale licencja GPL albo komercyjna. GPL
w produkcie wdrażanym w organizacji to problem, którego nie musimy mieć.

**Tkinter.** W bibliotece standardowej, ale wygląd odbiega od Windows 11,
a obsługa skalowania DPI jest słaba.

**wxPython.** Natywne kontrolki, ale mniejsza społeczność i gorsze wsparcie
dla Windows 11.

**Interfejs webowy w oknie (pywebview, Electron).** Sprowadza się do
przeglądarki w przebraniu, z dodatkową warstwą i większym pakietem.

## Konsekwencje

Dobre:

* wygląd zgodny z Windows 11 bez pisania własnych kontrolek;
* dobre wsparcie DPI i motywów systemowych;
* `pytest-qt` pozwala testować przepływy interfejsu bez widocznego okna;
* LGPL pozwala na wdrożenie bez zakupu licencji, o ile biblioteka pozostaje
  wymienialna (a przy pakowaniu PyInstaller w trybie onedir tak jest).

Kosztowne:

* Qt to duża zależność: około 200 MB w spakowanej aplikacji;
* LGPL wymaga dołączenia tekstu licencji i informacji o możliwości wymiany
  biblioteki. Robi to [dokument o licencjach](../licencje.md);
* praca w tle wymaga uwagi. Obiekt zadania musi być trzymany przy życiu, dopóki
  nie dostarczy wyniku: pula usuwa `QRunnable` zaraz po `run`, a zdarzenie
  czekające w kolejce wskazywałoby wtedy na zwolnioną pamięć i proces kończyłby
  się naruszeniem ochrony pamięci zamiast wyjątkiem. Rozwiązuje to rejestr
  aktywnych zadań w `gui/workers.py`, pilnowany testem.
