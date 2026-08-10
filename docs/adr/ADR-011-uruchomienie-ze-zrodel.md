# ADR-011: Uruchomienie wyłącznie z kodu źródłowego

**Stan:** przyjęta
**Data:** sierpień 2026
**Zastępuje:** [ADR-010](ADR-010-pakowanie.md)

## Kontekst

Poprzednia decyzja zakładała, że użytkownik dostaje plik wykonywalny zbudowany
przez PyInstaller i instalowany przez Inno Setup. Wynikały z tego trzy koszty,
które okazały się dotkliwsze niż wygoda instalatora:

* pakiet ważył 409 MB w 974 plikach i wymagał osobnego procesu budowania,
  którego wynik trzeba było za każdym razem sprawdzać testem dymnym;
* plik wykonywalny bez podpisu certyfikatem organizacji wywołuje ostrzeżenie
  SmartScreen, a w środowiskach z kontrolą uruchamiania aplikacji bywa po
  prostu blokowany;
* audyt tego, co faktycznie działa na stanowisku, wymagał zaufania procesowi
  budowania. Kod źródłowy w pakiecie był skompilowany do plików `.pyc`
  i zamknięty w archiwum.

Docelowe stanowisko ma Pythona i pozwala tworzyć środowiska wirtualne
w profilu użytkownika.

## Decyzja

**Jedynym sposobem uruchomienia jest wykonanie kodu źródłowego.** W katalogu
z kodem powstaje środowisko wirtualne, zależności instaluje pip z plików
`requirements*.txt`, a aplikację startuje skrypt `run.py` z katalogu głównego.

**`run.py` jest jedynym punktem wejścia.** Dodaje katalog `src` do ścieżki
importów, wybiera tryb pracy (bez argumentów albo z `gui` uruchamia interfejs
graficzny, każdy inny argument trafia do wiersza poleceń) i zamienia brak
zależności na czytelny komunikat zamiast ściany wyjątku. Skrót w menu Start
wskazuje na `pythonw.exe` z argumentem `run.py`, więc użytkownik dalej nie
widzi konsoli.

**Pakiet nie jest instalowany w środowisku.** Nie ma kroku `pip install`
dla samego FindDocs, nie ma pliku `[project]` w `pyproject.toml` ani punktów
wejścia `console_scripts`. `pyproject.toml` trzyma wyłącznie konfigurację
narzędzi deweloperskich, a testy dostają katalog `src` przez `pythonpath`.

**Zależności są przypięte i podzielone według potrzeby**: `requirements.txt`
(aplikacja), `requirements-ocr.txt` (silnik OCR), `requirements-export.txt`
(konwersja modeli), `requirements-dev.txt` (testy i linting). Pełne drzewo
z zależnościami pośrednimi jest w `requirements-lock.txt`.

## Rozważane alternatywy

**Instalacja pakietu z PyPI (`pip install finddocs`).** Wygodna, ale to nadal
dystrybucja artefaktu: na stanowisku ląduje kod z indeksu publicznego, a nie
ten, który przeszedł przegląd w repozytorium. Do tego wymaga dostępu do PyPI,
którego środowiska odcięte od internetu nie mają.

**Instalacja edytowalna (`pip install -e .`).** Rozwiązuje ścieżkę importów,
ale wymaga backendu budowania i zostawia w środowisku metadane pakietu oraz
polecenia `finddocs` i `finddocs-gui`. Dwa sposoby uruchomienia zamiast
jednego, przy zerowym zysku wobec dodania `src` do ścieżki w `run.py`.

**Zmienna `PYTHONPATH=src` zamiast `run.py`.** Działa, ale przenosi warunek
poprawnego startu do konfiguracji powłoki albo skrótu, czyli w miejsce,
którego nikt nie testuje.

**Płaski układ katalogów (pakiet w katalogu głównym zamiast w `src`).**
Pozwoliłby na `python -m finddocs.gui` bez żadnego skryptu, ale kosztem
przeniesienia całego pakietu i utraty rozdziału między kodem a resztą
repozytorium.

## Konsekwencje

Dobre:

* nie ma procesu budowania, więc nie ma też klasy błędów, które PyInstaller
  wprowadzał sam z siebie (niezebrane podmoduły numpy, brakujące biblioteki
  binarne, ostrzeżenie SmartScreen);
* na dysku leży dokładnie ten kod, który jest w repozytorium, w formie
  czytelnej dla audytu;
* aktualizacja to `git pull` plus ewentualne doinstalowanie zależności;
* wersja aplikacji jest utrzymywana w jednym miejscu (`finddocs/version.py`),
  bo zniknęły stałe w pliku instalatora i w metadanych pakietu;
* zniknęła zależność deweloperska od PyInstallera (GPLv2) razem z jego
  drzewem zależności, więc zestawienie licencji jest krótsze.

Kosztowne:

* stanowisko musi mieć Pythona od 3.11 do 3.14. To warunek wstępny, którego
  wcześniej nie było, i w razie jego braku instalację Pythona wykonuje
  administrator;
* pierwsze przygotowanie środowiska pobiera zależności z PyPI, w tym Qt
  i biblioteki binarne. Stanowisko bez dostępu do sieci wymaga własnego
  repozytorium pakietów albo katalogu z kołami i instalacji
  z `--no-index --find-links`;
* skrót w menu Start trzeba utworzyć ręcznie albo skryptem wdrożeniowym,
  bo nie ma instalatora, który by go założył;
* nic nie chroni użytkownika przed przypadkową zmianą kodu na stanowisku.
  Katalog z kodem powinien być tylko do odczytu dla konta użytkownika.
