# Diagnostyka

## Od czego zacząć

```bash
finddocs doctor
```

Polecenie wypisuje wersje bibliotek, dostępność FTS5, listę parserów wraz
z powodem niedostępności, stan silników OCR, obecność modelu embeddingów,
stan indeksu, wolne miejsce i politykę sieciową. To samo widać na ekranie
**Diagnostyka** w interfejsie.

Drugi krok to ostatnie wpisy o poziomie `error` w logu.

## Logi

Plik: `%LOCALAPPDATA%\FindDocs\logs\finddocs.log`.

Format to JSON, po jednym zdarzeniu w wierszu:

```json
{"event": "gui.starting", "level": "info", "logger": "finddocs.gui.app",
 "timestamp": "2026-07-31T18:43:15.039811", "app_version": "0.1.0"}
```

Rotacja po `max_log_size_mb` (domyślnie 20 MB), zachowywanych jest
`keep_log_files` plików (domyślnie 5).

Poziom ustawia `diagnostics.log_level`. Na czas diagnozy warto ustawić `DEBUG`
i wrócić potem do `INFO`.

### Czego w logu nie ma

Świadomie i trwale:

* treści dokumentów i fragmentów;
* zapytań użytkownika, chyba że jawnie włączono `diagnostics.log_queries`;
* tokenów, haseł, nagłówków `Authorization`;
* danych uwierzytelniających i sekretów.

Za usuwanie tych danych odpowiada warstwa redakcji
[`security/redaction.py`](../src/finddocs/security/redaction.py), przez którą
przechodzi każde zdarzenie, także takie, które ktoś zaloguje przez pomyłkę.

W logu nie ma też telemetrii: aplikacja nie wysyła nigdzie żadnych zdarzeń.

### Typowe zdarzenia

| Zdarzenie | Znaczenie |
| --- | --- |
| `gui.starting` | start interfejsu |
| `migration.apply` | zastosowano migrację schematu |
| `provider.loaded` | wczytano model embeddingów |
| `index.provider_unavailable` | brak modelu, tryb semantyczny wyłączony |
| `index.vector_incompatible` | indeks wektorowy niezgodny z konfiguracją |
| `job.started`, `job.finished` | zadanie indeksowania |
| `document.failed` | dokument, którego nie udało się odczytać |
| `auth.interactive_started` | rozpoczęto logowanie do Microsoft |
| `credentials.store_selected` | wybrany magazyn poświadczeń |
| `gui.task_crashed` | nieoczekiwany wyjątek w zadaniu w tle |

## Kody błędów

Każdy wyjątek aplikacji ma stały kod i komunikat po polsku. Kod widać
w oknie błędu, w logu, w tabeli `error_log` i w raporcie pokrycia.

### FD-1xxx: konfiguracja i środowisko

| Kod | Znaczenie | Co zrobić |
| --- | --- | --- |
| `FD-1001` | błąd konfiguracji | sprawdź `config\config.json`, w razie potrzeby usuń go i skonfiguruj od nowa |
| `FD-1002` | za mało miejsca na dysku | zwolnij miejsce albo zmniejsz `min_free_disk_bytes` |
| `FD-1003` | problem z przestrzenią tymczasową | sprawdź prawa do `%LOCALAPPDATA%\FindDocs\temp` |
| `FD-1004` | brak wymaganego składnika | `finddocs doctor` pokaże, czego brakuje |
| `FD-1005` | połączenie odrzucone przez politykę sieciową | adres spoza listy dozwolonych, patrz ekran **Diagnostyka** |

### FD-2xxx: źródła dokumentów

| Kod | Znaczenie | Co zrobić |
| --- | --- | --- |
| `FD-2000` | ogólny błąd konektora | szczegóły w logu |
| `FD-2001` | źródło niedostępne | sprawdź ścieżkę albo adres witryny i połączenie sieciowe |
| `FD-2002` | błąd uwierzytelnienia | zaloguj się ponownie, sprawdź uprawnienia w Entra ID |
| `FD-2003` | błąd przejściowy | aplikacja sama ponawia, nic nie trzeba robić |
| `FD-2004` | ograniczenie przepustowości serwera | aplikacja czeka i ponawia, ewentualnie zmniejsz `page_size` |
| `FD-2005` | nie udało się pobrać pliku | dokument w raporcie ze statusem `download_failed` |

### FD-3xxx: odczyt dokumentów

| Kod | Znaczenie | Co zrobić |
| --- | --- | --- |
| `FD-3000` | ogólny błąd odczytu | patrz nazwa parsera w logu |
| `FD-3001` | format nieobsługiwany | patrz [formaty](formaty.md) |
| `FD-3002` | plik uszkodzony | otwórz plik ręcznie, żeby potwierdzić |
| `FD-3003` | dokument zabezpieczony hasłem | aplikacja nie łamie haseł, dokument pozostaje niewyszukiwalny |
| `FD-3004` | dokument nie zawiera tekstu | dla skanów sprawdź, czy OCR jest włączony |
| `FD-3005` | przekroczono limit czasu odczytu | podnieś `extraction_timeout_seconds` |

### FD-4xxx: OCR

| Kod | Znaczenie | Co zrobić |
| --- | --- | --- |
| `FD-4000` | błąd rozpoznawania | patrz [OCR](ocr.md) |
| `FD-4001` | brak silnika OCR | zainstaluj Tesseract z językiem polskim |
| `FD-4002` | rozpoznawanie anulowane | działanie użytkownika, nie błąd |

### FD-5xxx: indeks

| Kod | Znaczenie | Co zrobić |
| --- | --- | --- |
| `FD-5000` | ogólny błąd indeksu | `finddocs maintenance check` |
| `FD-5001` | indeks niezgodny z konfiguracją | przebudowa, patrz [odbudowa indeksu](odbudowa-indeksu.md) |
| `FD-5002` | indeks uszkodzony | przywróć kopię albo odbuduj |
| `FD-5003` | błąd migracji schematu | przywróć kopię, zgłoś problem z logiem |

### FD-6xxx: model embeddingów

| Kod | Znaczenie | Co zrobić |
| --- | --- | --- |
| `FD-6000` | ogólny błąd dostawcy | szczegóły w logu |
| `FD-6001` | brak modelu | tryb dokładny działa, model instaluje administrator |
| `FD-6002` | suma kontrolna modelu się nie zgadza | pobierz model ponownie |

### FD-7xxx, FD-8xxx, FD-9xxx

| Kod | Znaczenie | Co zrobić |
| --- | --- | --- |
| `FD-7000` | błąd wyszukiwania | szczegóły w logu |
| `FD-7001` | błąd składni zapytania | sprawdź, czy cudzysłowy są domknięte |
| `FD-7002` | wyszukiwanie anulowane | działanie użytkownika, nie błąd |
| `FD-8000` | błąd zadania indeksowania | patrz zakładkę **Błędy** na ekranie **Indeksowanie** |
| `FD-8001` | zadanie anulowane | działanie użytkownika, nie błąd |
| `FD-9001` | magazyn poświadczeń niedostępny | logowanie do SharePoint trzeba powtarzać po restarcie |

## Sprawdzanie spójności indeksu

```bash
finddocs maintenance check
```

Sprawdza `PRAGMA integrity_check`, fragmenty bez dokumentu, zgodność liczników,
zgodność liczby wektorów, liczbę nagrobków i skróty zgodności w `index_meta`.
Wynik trafia też na ekran **Diagnostyka**, zakładka **Spójność**.

Wynik niezdrowy nie zawsze oznacza katastrofę. Duża liczba nagrobków to sygnał,
że warto uruchomić kompaktację, a nie że indeks jest zepsuty.

## Raport pokrycia

```bash
finddocs report --json-out raport.json --csv-out raport.csv
```

Raport odpowiada na pytanie „czego nie ma w indeksie i dlaczego”. Zawiera liczby
dokumentów w podziale na statusy, liczbę dokumentów i stron z OCR, listę
dokumentów niewyszukiwalnych z powodem, datę ostatniego skanowania, wersję
indeksu i nazwę modelu.

**Jeżeli lista niewyszukiwalnych nie jest pusta, raport tego nie ukrywa
i nie twierdzi, że zbiór jest kompletny.**

Eksport JSON i CSV przechodzi przez tę samą redakcję co logi, więc nie zawiera
treści dokumentów.

## Typowe problemy

### Aplikacja nie startuje

Sprawdź `%LOCALAPPDATA%\FindDocs\logs\blad-uruchomienia.txt`. Plik powstaje,
gdy błąd wystąpi zanim wstanie interfejs. Zawiera pełny ślad wyjątku.

Jeżeli pliku nie ma, a okno się nie pojawia, uruchom z wiersza poleceń:

```bash
"%LOCALAPPDATA%\Programs\FindDocs\FindDocs.exe" --self-test
```

Kod wyjścia 0 oznacza, że aplikacja wstaje i zamyka się poprawnie.

### Nie widać dokumentu, o którym wiadomo, że istnieje

Kolejno:

1. Czy jego źródło jest dodane i włączone? `finddocs sources list`.
2. Czy indeksowanie się zakończyło? Ekran **Indeksowanie**.
3. Czy dokument jest w raporcie jako niewyszukiwalny? `finddocs report`.
4. Czy nie zawężają go filtry? Naciśnij **Wyczyść filtry**.
5. Czy szukasz w trybie **Dokładnym**? Tylko on gwarantuje kompletność.

Jeżeli dokument jest w indeksie ze statusem `indexed`, a mimo to nie wychodzi
w trybie dokładnym, to jest błąd aplikacji. Zgłoś go z zapytaniem i wpisem
z raportu.

### Wyszukiwanie semantyczne niedostępne

Kod `FD-6001`. Brakuje modelu w `%LOCALAPPDATA%\FindDocs\models`. Tryb dokładny
działa bez modelu. Instalację modelu opisuje
[instrukcja administratora](instrukcja-administratora.md).

### Indeksowanie kończy się błędem miejsca na dysku

Kod `FD-1002`. Domyślnie aplikacja wymaga 2 GB wolnego miejsca. Zwolnij miejsce
albo zmniejsz `indexing.min_free_disk_bytes`. Indeks pozostaje spójny:
zadanie kończy się kontrolowanie, a nie w połowie zapisu.

### Indeksowanie jest bardzo wolne

Najczęstszą przyczyną jest OCR. Sprawdź w raporcie, ile dokumentów przez niego
przechodzi. Pamięć podręczna sprawia, że drugie indeksowanie tych samych plików
jest wielokrotnie szybsze. Zmniejszenie `ocr.render_dpi` do 180 skraca czas
kosztem jakości rozpoznania.

Drugą przyczyną bywa ograniczanie przepustowości przez Graph (kod `FD-2004`).

### Aplikacja mówi, że indeks wymaga przebudowy

Zmieniła się konfiguracja wpływająca na budowę indeksu. Do czasu przebudowy
działa wyszukiwanie dokładne. Procedura:
[odbudowa indeksu](odbudowa-indeksu.md).

### Okno zawiesza się na chwilę

Interfejs nie wykonuje pracy w wątku głównym: wyszukiwanie idzie do puli wątków,
indeksowanie do osobnego wątku. Jeżeli mimo to okno przestaje odpowiadać,
to jest błąd. Zgłoś go razem z logiem i opisem, co robiłeś.

## Zgłaszanie problemu

Dołącz:

1. wynik `finddocs doctor`;
2. ostatnie 200 wierszy `logs\finddocs.log`;
3. raport pokrycia w formacie JSON;
4. kod błędu z okna, jeżeli się pojawił;
5. opis, co robiłeś i czego się spodziewałeś.

Żaden z tych plików nie zawiera treści dokumentów ani zapytań, więc można je
przekazać dalej. Zanim to zrobisz, i tak warto je przejrzeć.
