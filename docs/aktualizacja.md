# Procedura aktualizacji

## Zasada

Aktualizacja podmienia kod w katalogu z repozytorium i nie rusza katalogu
danych `%LOCALAPPDATA%\FindDocs`. Indeks, konfiguracja i zapisane
poświadczenia przetrwają aktualizację.

W przykładach `python` oznacza interpreter ze środowiska wirtualnego
przygotowanego obok kodu, czyli `.venv\Scripts\python`.

Migracje schematu bazy wykonują się automatycznie przy pierwszym uruchomieniu
nowej wersji, w jednej transakcji, z wpisem do tabeli `schema_migrations`.

## Przed aktualizacją

1. Sprawdź, jaka wersja jest uruchomiona: **Diagnostyka** albo
   `python run.py --version`.
2. Przeczytaj informacje o zmianach dla wersji docelowej, zwłaszcza sekcję
   o zgodności indeksu.
3. Wykonaj kopię indeksu:

```bash
python run.py maintenance backup
```

4. Zamknij aplikację i upewnij się, że żadne zadanie indeksowania nie działa
   w tle (na przykład zaplanowane w Harmonogramie zadań).

## Aktualizacja

Pobierz nowy kod i doinstaluj zależności:

```bat
git pull
.venv\Scripts\python -m pip install -r requirements.txt
```

Skrót w menu Start wskazuje na katalog z kodem, więc pozostaje bez zmian.
Gdy kod przychodzi jako archiwum, a nie przez git, rozpakuj je nad katalogiem
z poprzednią wersją. Katalog `.venv` zostaje: to środowisko, nie kod.

## Po aktualizacji

1. Uruchom aplikację. Pierwszy start może potrwać dłużej, jeżeli wykonują się
   migracje. Postęp widać w logu (`migration.apply`).
2. Sprawdź stan:

```bash
python run.py doctor
python run.py maintenance check
```

3. Jeżeli pojawi się komunikat **Indeks wymaga przebudowy**, wykonaj procedurę
   z [odbudowy indeksu](odbudowa-indeksu.md). Do czasu przebudowy działa
   wyszukiwanie dokładne.
4. Wykonaj jedno wyszukiwanie kontrolne na znanym dokumencie.

## Kiedy aktualizacja wymaga przebudowy indeksu

| Zmiana w nowej wersji | Skutek |
| --- | --- |
| poprawka parsera formatu | warto przeindeksować dokumenty tego formatu |
| zmiana reguł normalizacji | wymagana pełna przebudowa |
| zmiana reguł fragmentacji | wymagana pełna przebudowa |
| zmiana modelu embeddingów | wymagana przebudowa części wektorowej |
| zmiana schematu bazy | migracja automatyczna, przebudowa niepotrzebna |

Aplikacja sama wykrywa pierwsze cztery przypadki przez skróty zgodności
zapisane w `index_meta`. Nie polegaj na własnej pamięci: uruchom
`python run.py maintenance check` po aktualizacji.

## Wycofanie zmiany

Jeżeli nowa wersja sprawia problemy:

1. Przywróć poprzednią wersję kodu (`git checkout <tag>` albo rozpakowanie
   poprzedniego archiwum). Katalogu danych nie ruszaj.
2. Doinstaluj zależności poprzedniej wersji:
   `.venv\Scripts\python -m pip install -r requirements.txt`.
3. Przywróć kopię indeksu wykonaną przed aktualizacją:

```bash
python run.py maintenance restore --name index-20260731-183000
```

Ten krok jest konieczny, jeżeli nowa wersja podniosła wersję schematu.
**Starsza wersja nie otworzy nowszej bazy**: zgłosi błąd `FD-5001`
z prośbą o aktualizację programu, zamiast ryzykować uszkodzenie danych.

## Aktualizacja modelu embeddingów

Model jest niezależny od aplikacji. Wymiana modelu:

1. `python run.py maintenance backup`.
2. Skopiuj nowy model do `%LOCALAPPDATA%\FindDocs\models`.
3. Zmień `embedding.model_key` w konfiguracji.
4. Uruchom aplikację. Zgłosi niezgodność części wektorowej.
5. `python run.py maintenance rebuild --vectors-only` i `python run.py index`.

Wyszukiwanie dokładne działa przez cały ten czas.

## Aktualizacja Tesseract

Klucz pamięci podręcznej OCR zawiera wersję silnika, więc aktualizacja
Tesseract automatycznie unieważnia stare wpisy. Dokumenty rozpoznane starszą
wersją zostaną rozpoznane ponownie przy najbliższym pełnym przeindeksowaniu.

Jeżeli chcesz to wymusić od razu:

```bash
python run.py index --full
```

## Wdrożenie masowe

Aplikacja mieści się w profilu użytkownika i nie wymaga uprawnień
administratora, więc nadaje się do dystrybucji przez Intune albo Configuration
Manager jako pakiet dla użytkownika, nie dla urządzenia. Pakiet wdrożeniowy
kopiuje katalog z kodem, tworzy środowisko wirtualne i zakłada skrót.
Procedurę opisuje [instrukcja administratora](instrukcja-administratora.md).

Wykrywanie wersji na stanowisku: `python run.py --version` albo stała
`APP_VERSION` w pliku `src\finddocs\version.py`.

Konfigurację można rozprowadzić, umieszczając gotowy plik
`%LOCALAPPDATA%\FindDocs\config\config.json` przed pierwszym uruchomieniem.
Plik nie zawiera i nie może zawierać sekretów: dane logowania trafiają do
menedżera poświadczeń Windows dopiero po zalogowaniu użytkownika.
