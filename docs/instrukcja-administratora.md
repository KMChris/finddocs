# FindDocs: instrukcja administratora

Dokument opisuje wdrożenie, konfigurację i utrzymanie aplikacji. Obsługę
codzienną opisuje [instrukcja użytkownika](instrukcja-uzytkownika.md).

## Wymagania

| Element | Wymaganie |
| --- | --- |
| System | Windows 11 (x64), Windows 10 22H2 działa, ale nie jest testowany |
| Procesor | x86-64 z AVX2, cztery rdzenie lub więcej |
| Pamięć | 4 GB dla trybu dokładnego, 8 GB gdy używany jest model embeddingów |
| Dysk | ok. 2 GB na kod, środowisko wirtualne i model, plus miejsce na indeks |
| Python | 3.11 do 3.14, wydanie 64-bitowe |
| Uprawnienia | zwykły użytkownik, wszystko mieści się w jego profilu |
| GPU | niepotrzebne, aplikacja nigdy go nie używa |

Rozmiar indeksu to z grubsza 30 do 60 procent rozmiaru dokumentów tekstowych.
Skany zajmują mniej, bo indeksowany jest wynik OCR, a nie obraz.

## Wdrożenie

Aplikacja nie ma instalatora ani pliku wykonywalnego. Wdrożenie to skopiowanie
katalogu z kodem i przygotowanie obok niego środowiska wirtualnego. Pełny opis:
[uruchomienie z kodu źródłowego](uruchomienie-ze-zrodel.md).

### Stanowisko pojedyncze

```bat
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pip install -r requirements-ocr.txt
.venv\Scripts\python run.py
```

Katalog z kodem może leżeć w profilu użytkownika albo w katalogu tylko
do odczytu, wspólnym dla stanowiska. W drugim przypadku środowisko wirtualne
tworzy się osobno, w miejscu zapisywalnym dla użytkownika, a `run.py`
uruchamia się z pełnej ścieżki.

### Skrót w menu Start

Instalatora nie ma, więc skrót zakłada się ręcznie albo skryptem wdrożeniowym:

| Pole skrótu | Wartość |
| --- | --- |
| Element docelowy | `<katalog>\.venv\Scripts\pythonw.exe "<katalog>\run.py"` |
| Rozpocznij w | `<katalog>` |
| Ikona | `<katalog>\src\finddocs\resources\finddocs.ico` |

`pythonw.exe` nie otwiera okna konsoli. Skrót kopiuje się do
`%APPDATA%\Microsoft\Windows\Start Menu\Programs`.

### Wdrożenie masowe

Pakiet dla Intune albo Configuration Managera wykonuje trzy kroki: kopiuje
katalog z kodem, tworzy środowisko wirtualne poleceniami z sekcji wyżej
i zakłada skrót. Wykrywanie wersji: `python run.py --version`.

Warunkiem wstępnym jest Python od 3.11 do 3.14 na stanowisku. Gdy go nie ma,
instaluje go administrator, osobnym pakietem.

### Usunięcie

Skasuj katalog z kodem razem ze środowiskiem `.venv` i skrót w menu Start.
Katalog danych `%LOCALAPPDATA%\FindDocs` zostaje nietknięty: kasuje się go
osobno, gdy indeks nie jest już potrzebny.

### Stanowisko bez dostępu do sieci

Aplikacja w trakcie pracy nie pobiera niczego sama. Sieci potrzebuje tylko
przygotowanie środowiska, więc na stanowisku odciętym od internetu zależności
instaluje się z lokalnego katalogu z kołami:

```bat
.venv\Scripts\python -m pip install --no-index --find-links D:\kola -r requirements.txt
```

Model embeddingów można wtedy:

* skopiować ręcznie do `%LOCALAPPDATA%\FindDocs\models\`, albo
* umieścić w katalogu `models` obok kodu, albo
* pobrać z poziomu aplikacji, jeśli włączysz na to zgodę w konfiguracji.

Bez modelu działa wyszukiwanie dokładne. Aplikacja mówi o tym przy starcie
i nie udaje, że tryb semantyczny jest sprawny.

## Katalog danych

Domyślnie `%LOCALAPPDATA%\FindDocs`. Można go zmienić zmienną środowiskową
`FINDDOCS_HOME` albo przełącznikiem `--data-dir`.

```
FindDocs\
  config\      konfiguracja aplikacji (settings.json)
  index\       finddocs.db (SQLite WAL) oraz pliki indeksu wektorowego
  logs\        finddocs.log z rotacją
  models\      modele embeddingów
  cache\       pamięć podręczna OCR i pobrań
  temp\        przestrzeń robocza, czyszczona po zadaniu
  reports\     wyeksportowane raporty pokrycia
  backup\      kopie indeksu
```

**Katalog `index` zawiera treść dokumentów.** Podlega tej samej klauzuli
poufności co dokumenty źródłowe. Nie umieszczaj go na dysku współdzielonym
z innymi użytkownikami.

## Konfiguracja

Plik `config\settings.json` zapisywany jest atomowo (plik tymczasowy, `fsync`,
zamiana nazwy), więc przerwanie zapisu nie uszkodzi konfiguracji. Aplikacja
odczytuje go przy starcie. Poniżej pola, które zwykle się zmienia.

### Embeddingi

```json
"embedding": {
  "provider": "local_onnx",
  "model_key": "mmlw-retrieval-roberta-base",
  "model_path": "",
  "max_sequence_length": 512,
  "batch_size": 8,
  "num_threads": 0,
  "quantized": true
}
```

`num_threads` równe zero oznacza automatyczny dobór liczby wątków ONNX Runtime.
`quantized` wybiera wariant INT8 (ok. 125 MB) zamiast pełnego FP32 (ok. 500 MB).
Zmiana `model_key`, `quantized` albo `max_sequence_length` unieważnia indeks
wektorowy i wymaga jego przebudowy.

Modele instaluje i przełącza grupa poleceń `python run.py model` (opis niżej).
`python run.py model use` ustawia `model_key` i synchronizuje pozostałe pola
z manifestem modelu, więc ręczna edycja tej sekcji zwykle nie jest potrzebna.

### OCR

```json
"ocr": {
  "enabled": true,
  "engine": "auto",
  "languages": ["pol"],
  "tesseract_path": "",
  "render_dpi": 220,
  "max_pages_per_document": 60,
  "min_chars_per_page": 90,
  "min_alpha_ratio": 0.45,
  "max_image_pixels": 40000000,
  "page_timeout_seconds": 120.0,
  "auto_rotate": true,
  "min_confidence_to_keep": 0.3
}
```

`engine: "auto"` wybiera pierwszy dostępny silnik w kolejności Tesseract,
EasyOCR, RapidOCR. Szczegóły: [OCR](ocr.md).

### Indeksowanie

```json
"indexing": {
  "checkpoint_every": 20,
  "max_temp_bytes": 4294967296,
  "min_free_disk_bytes": 2147483648,
  "max_file_size_mb": 512,
  "extraction_timeout_seconds": 300.0,
  "max_retries_per_document": 3,
  "office_com_enabled": true,
  "office_com_timeout_seconds": 90.0
}
```

`office_com_enabled` włącza odczyt plików `.doc` i `.xls` przez zainstalowany
pakiet Microsoft Office. Aplikacja sama sprawdza, czy Office jest dostępny,
nie uruchamia makr i przerywa konwersję po `office_com_timeout_seconds`.
Gdy Office nie ma, używany jest wbudowany czytnik OLE (poziom wsparcia niższy).

Poniżej `min_free_disk_bytes` wolnego miejsca zadanie kończy się stanem błędu
z czytelnym komunikatem, zamiast zostawiać uszkodzony indeks.

### Wyszukiwanie

```json
"search": {
  "default_mode": "hybrid",
  "page_size": 20,
  "max_chunks_per_document": 3,
  "rrf_k": 60,
  "exact_boost": 0.6,
  "semantic_candidates": 400,
  "fts_candidates": 2000
}
```

`rrf_k` to stała metody Reciprocal Rank Fusion. Wyższa wartość spłaszcza wpływ
pozycji na liście. `exact_boost` decyduje, jak mocno dokument z elementem
dosłownym wyprzedza dokument bez niego.

### Diagnostyka

```json
"diagnostics": {
  "log_level": "INFO",
  "log_queries": false,
  "keep_log_files": 5,
  "max_log_size_mb": 20,
  "json_logs": true
}
```

`log_queries` domyślnie wyłączone. Włączenie zapisuje treść zapytań użytkownika
do lokalnego pliku logu. Używaj tylko na czas diagnozowania problemu i wyłącz
po zakończeniu.

## Integracja z SharePoint

Pełny opis rejestracji aplikacji w Entra ID, wymaganych uprawnień i zgody
administratora: [integracja z SharePoint](integracja-sharepoint.md).

W skrócie: potrzebna jest rejestracja aplikacji typu **public client**
z przekierowaniem `http://localhost` (przepływ interaktywny) albo włączonym
przepływem device code, oraz uprawnienia delegowane `Files.Read.All`
i `Sites.Read.All`.

**Połączenie z prawdziwą dzierżawą nie zostało zweryfikowane w środowisku,
w którym powstała ta wersja.** Konektor ma testy jednostkowe i integracyjne
na zamockowanych odpowiedziach Graph, ale to nie zastępuje testu u klienta.
Przed wdrożeniem wykonaj test na jednej bibliotece.

## Polityka sieciowa

Domyślnie każdy ruch wychodzący jest zablokowany. Kategorie włącza się
świadomie:

| Kategoria | Kiedy się włącza | Dozwolone hosty |
| --- | --- | --- |
| `microsoft_graph` | po dodaniu źródła SharePoint | `graph.microsoft.com`, `login.microsoftonline.com`, `*.sharepoint.com` |
| `model_download` | po ustawieniu `allow_model_download` | `huggingface.co`, `cdn-lfs.huggingface.co`, `*.hf.co` |
| `internal_api` | tylko z jawnie podanym adresem | lista pusta, wymaga konfiguracji |

Dozwolony jest wyłącznie protokół HTTPS. Lista jest wpisana w kod
(`src/finddocs/security/network.py`) i widoczna na ekranie **Diagnostyka**.
Aplikacja nie zawiera żadnej telemetrii.

Jeżeli w organizacji działa serwer proxy, ustaw zmienne `HTTPS_PROXY`
i `NO_PROXY` w profilu użytkownika. Aplikacja korzysta z biblioteki `httpx`,
która je respektuje.

## Poświadczenia

Token odświeżania Microsoft trafia do magazynu w kolejności:

1. Menedżer poświadczeń Windows (przez `keyring`);
2. DPAPI powiązane z kontem użytkownika;
3. pamięć procesu, gdy dwa poprzednie zawiodą (token ginie po zamknięciu).

W repozytorium ani w plikach konfiguracyjnych nie ma żadnych sekretów.
Logi nigdy nie zawierają tokenów, nagłówków autoryzacji ani haseł: usuwa je
warstwa redakcji (`src/finddocs/security/redaction.py`).

## Wiersz poleceń

CLI istnieje dla administracji, diagnostyki i testów. Użytkownik końcowy
nie musi go dotykać. W wersji zainstalowanej plik wykonywalny znajduje się
w katalogu instalacji.

```bash
python run.py --help
python run.py --data-dir "D:\FindDocs" --json <polecenie>
```

### Źródła

```bash
python run.py sources list
python run.py sources add-local "D:\Dokumenty" --id archiwum --label "Archiwum"
python run.py sources add-sharepoint --id finanse --label "Finanse" \
    --site https://contoso.sharepoint.com/sites/Finanse \
    --library "Dokumenty" \
    --tenant <tenant-id> --client-id <client-id> \
    --auth-flow interactive
python run.py sources test finanse
python run.py sources remove finanse
python run.py sources remove finanse --purge
```

`--purge` usuwa przy okazji dokumenty tego źródła z indeksu. Bez tego
przełącznika znikną one dopiero przy następnym skanowaniu.

### Zbiór demonstracyjny

```bash
python run.py demo --register
```

Tworzy fikcyjne dokumenty po polsku i rejestruje je jako źródło `demo`.
Zbiór nie zawiera prawdziwych danych osobowych ani firmowych.

### Modele embeddingów

```bash
python run.py model list
python run.py model import --use
python run.py model import D:\Modele\moj-model --name moj-model
python run.py model import intfloat/multilingual-e5-small
python run.py model use mmlw-retrieval-roberta-base
python run.py model remove moj-model
```

`import` bez argumentu pobiera domyślny model MMLW z Hugging Face; pobranie
wymaga zgody w konsoli (w skryptach `--yes`) i przechodzi przez politykę
sieciową w kategorii `model_download`. Argumentem może być katalog z gotowym
eksportem ONNX, katalog z checkpointem HuggingFace (konwersja wymaga pakietów
z `requirements-export.txt`) albo repozytorium `organizacja/nazwa`. Każdy model jest
walidowany próbnym przebiegiem przed instalacją i od razu widoczny na liście
modeli w GUI. Zmiana aktywnego modelu wymaga przebudowy części wektorowej
(`python run.py maintenance rebuild --vectors-only`, potem `python run.py index`).
Szczegóły i opcje: [uruchomienie z kodu źródłowego](uruchomienie-ze-zrodel.md).

### Indeksowanie

```bash
python run.py index
python run.py index --source archiwum
python run.py index --full
python run.py index --no-deletions
```

`--full` przetwarza wszystko od nowa, także dokumenty bez zmian.
`--no-deletions` zostawia w indeksie dokumenty, których nie ma już w źródle
(przydatne, gdy źródło jest chwilowo niedostępne).

### Wyszukiwanie

```bash
python run.py search "procedura przelewów 24.07.2015"
python run.py search "00 1234 5678 9012 3456 7890 1234" --mode exact --limit 100
python run.py search "kredyt na mieszkanie" --mode semantic
python run.py search "umowa" --ext .pdf --source archiwum
finddocs --json search "faktura" > wyniki.json
```

### Raport pokrycia

```bash
python run.py report
python run.py report --csv-out raport.csv --json-out raport.json
python run.py report --fast
```

`--fast` pomija ładowanie modelu, więc raport powstaje szybciej.

### Diagnostyka

```bash
python run.py doctor
```

Wypisuje wersje bibliotek, dostępność FTS5, listę parserów wraz z powodem
niedostępności, stan silników OCR, obecność modelu, stan indeksu i politykę
sieciową. To pierwsze polecenie przy każdym zgłoszeniu problemu.

### Konserwacja

```bash
python run.py maintenance check
python run.py maintenance backup
python run.py maintenance list-backups
python run.py maintenance restore --name kopia-2026-07-31
python run.py maintenance compact
python run.py maintenance rebuild
python run.py maintenance rebuild --vectors-only
```

Opis każdej operacji: [odbudowa indeksu](odbudowa-indeksu.md).

## Utrzymanie

**Codziennie albo co tydzień.** Zaplanuj `python run.py index` w Harmonogramie zadań
Windows, na koncie użytkownika, w kontekście jego sesji (token SharePoint jest
związany z użytkownikiem). Zadanie działa bez okien.

```bat
schtasks /Create /TN "FindDocs indeksowanie" /TR "\"%LOCALAPPDATA%\Programs\FindDocs\finddocs.exe\" index" /SC DAILY /ST 06:30
```

**Co miesiąc.** `python run.py maintenance compact` porządkuje indeks wektorowy
po usunięciach i wykonuje `VACUUM` bazy.

**Przed każdą zmianą konfiguracji wpływającej na indeks.**
`python run.py maintenance backup`.

**Monitorowanie.** Plik `logs\finddocs.log` w formacie JSON, po jednym zdarzeniu
w wierszu. Zdarzenia o poziomie `error` i `warning` warto zbierać centralnie.
Log nie zawiera treści dokumentów ani zapytań.

## Aktualizacja

Patrz [procedura aktualizacji](aktualizacja.md). Zasada ogólna: aktualizacja
podmienia kod i nie rusza katalogu danych. Migracje schematu wykonują się
przy pierwszym uruchomieniu nowej wersji.

## Rozwiązywanie problemów

Katalog problemów, kodów błędów i sposobów postępowania:
[diagnostyka](diagnostyka.md).
