# Raport z testów

Stan na 31 lipca 2026, wersja aplikacji 0.1.0.

## Podsumowanie

| Miara | Wartość |
| --- | --- |
| Liczba testów | 836 |
| Wynik | 836 zaliczonych, 0 niezaliczonych, 0 pominiętych |
| Czas przebiegu | 26 s |
| Pokrycie kodu `src/finddocs` | 73 procent instrukcji |
| Kontrola stylu (`ruff check`) | bez zastrzeżeń |
| Formatowanie (`ruff format --check`) | 147 plików zgodnych |
| Kontrola typów (`mypy src`) | bez zastrzeżeń, 103 pliki |

Uruchomienie:

```bash
.venv\Scripts\python.exe -m pytest -q
```

Przebieg jest powtarzalny: kolejność testów jest losowana (`pytest-randomly`),
a suita została uruchomiona wielokrotnie z różnymi ziarnami bez różnic w wyniku.

## Środowisko

| Element | Wartość |
| --- | --- |
| System | Windows 11 Education |
| Procesor | Intel64 Family 6 Model 183, 28 wątków logicznych |
| Python | 3.11.5 w `.venv` |
| Interfejs | PySide6 w trybie `offscreen`, przez `pytest-qt` |
| Model embeddingów | obecny, więc testy semantyczne nie były pomijane |
| Silnik OCR | testowany na silniku zastępczym, bez zależności od Tesseract |

## Zakres

### Testy jednostkowe: 339

| Plik | Testy | Zakres |
| --- | --- | --- |
| `test_normalization_text.py` | 36 | składanie znaków, litera `ł`, czyszczenie tekstu, wykrywanie śmieci |
| `test_normalization_numbers.py` | 30 | kwoty, numery rachunków, NIP, REGON, PESEL, identyfikatory |
| `test_normalization_dates.py` | 26 | daty w zapisie dziennikowym, ISO i słownym, zakresy, rok dwucyfrowy |
| `test_query_parser.py` | 35 | rozdział zapytania na warstwę dosłowną i znaczeniową |
| `test_encoding.py` | 35 | rozpoznawanie kodowania, w tym oba wykryte błędy cichej detekcji |
| `test_config_and_versioning.py` | 31 | konfiguracja, skróty zgodności, atomowy zapis |
| `test_security.py` | 28 | polityka sieciowa, redakcja logów |
| `test_chunking.py` | 24 | fragmentacja tekstu i tabel, nakładanie się fragmentów |
| `test_highlight.py` | 20 | wyróżnianie trafień w oryginalnej pisowni |
| `test_ocr_service.py` | 20 | wybór silnika, strony, limity, anulowanie, pamięć podręczna |
| `test_credentials.py` | 19 | magazyny poświadczeń, brak sekretu jawnym tekstem |
| `test_aggregate.py` | 18 | grupowanie fragmentów w dokumenty, RRF |
| `test_ocr_detector.py` | 17 | decyzja o uruchomieniu OCR dla strony |

### Testy regresyjne parserów: 138

Każdy plik testowy buduje pliki wejściowe od zera, więc w repozytorium nie ma
żadnych binariów. Formaty binarne bez biblioteki zapisującej (OLE, BIFF2, MSG,
DOC, RTF skompresowany LZFu) powstają w module `tests/parsers/parser_data.py`.

| Plik | Testy | Formaty |
| --- | --- | --- |
| `test_xlsx.py` | 24 | XLSX: arkusze, daty, liczby, metadane |
| `test_pdf.py` | 22 | PDF z warstwą tekstową, wielostronicowy, skan, uszkodzony |
| `test_text_html_rtf.py` | 22 | TXT, LOG, MD, HTML, RTF, kodowania |
| `test_email.py` | 17 | EML i MSG: nagłówki, treść, HTML, RTF, załączniki |
| `test_image_and_doc.py` | 17 | PNG, JPEG, TIFF, BMP, GIF oraz DOC 97-2003 |
| `test_csv.py` | 16 | CSV i TSV: separatory, kodowania, nagłówki |
| `test_docx.py` | 10 | DOCX: nagłówki, akapity, tabele, właściwości |
| `test_xls.py` | 10 | XLS w formacie BIFF2 |

Każdy format jest sprawdzany na: poprawnym pliku, pliku z polskimi znakami,
pliku pustym, pliku uszkodzonym oraz limitach.

### Testy wyszukiwania: 44

**`test_exact_recall.py`, 16 testów.** Kontrolowany korpus 66 dokumentów
zbudowany w kodzie, o znanej z góry liczbie wystąpień każdego elementu.

Sprawdzane własności:

| Własność | Wynik |
| --- | --- |
| numer rachunku w trzech zapisach | 17 z 17 dokumentów w każdym zapisie |
| data w trzech zapisach | ten sam zbiór w każdym zapisie |
| fraza w cudzysłowie | tylko dokumenty z pełną frazą, nie z luźnymi słowami |
| pisownia z ogonkami i bez | identyczny zbiór |
| stronicowanie | suma wszystkich stron równa `total_documents`, bez powtórzeń |
| brak ukrytego limitu | `all_matching_documents` zwraca ten sam zbiór co stronicowanie |
| filtry | zawężają zbiór, nie zmieniają jego kompletności |

**`test_semantic.py`, 13 testów.** Osobny korpus, zapytania będące parafrazami
bez wspólnych słów z dokumentem docelowym.

| Miara | Próg w teście | Wynik pomiaru |
| --- | --- | --- |
| recall@5 | co najmniej 0,75 | 1,000 |
| MRR | co najmniej 0,50 | 0,938 |
| nDCG@5 | co najmniej 0,55 | 0,954 |

Kontrola negatywna: te same zapytania w trybie dokładnym zwracają zero
dokumentów, więc mierzona jest rzeczywiście warstwa wektorowa.

**`test_hybrid.py`, 15 testów.** Cztery pary dokumentów różniące się wyłącznie
elementem dosłownym (numer rachunku, data, kwota, nazwa klienta). W każdej
parze dokument z elementem z zapytania jest na pierwszym miejscu.

Sprawdzane też: hybryda nie gubi żadnego dokumentu znalezionego dokładnie,
a przy braku modelu schodzi do trybu dokładnego i mówi o tym w odpowiedzi.

### Testy integracyjne: 120

| Plik | Testy | Zakres |
| --- | --- | --- |
| `test_diagnostics.py` | 26 | raport pokrycia, statystyki, eksport CSV, JSON i ZIP |
| `test_pipeline.py` | 23 | przetwarzanie dokumentu, izolacja błędów, załączniki, sprzątanie |
| `test_graph_mock.py` | 18 | konektor SharePoint na zamockowanych odpowiedziach Graph |
| `test_index_maintenance.py` | 18 | migracje, spójność, kopie, przywracanie, kompaktacja |
| `test_local_connector.py` | 17 | skanowanie katalogu, filtry, wykrywanie zmian |
| `test_disk_and_errors.py` | 10 | brak miejsca, uszkodzony plik, pauza, wznowienie, anulowanie |
| `test_indexing_flow.py` | 8 | pełny przebieg: nowy, zmieniony, usunięty dokument, wznowienie |

Scenariusze wymagane przez specyfikację i ich pokrycie:

| Scenariusz | Test |
| --- | --- |
| indeksowanie katalogu lokalnego | `test_indexing_flow.py` |
| indeksowanie SharePoint na mockach | `test_graph_mock.py` |
| ponowne skanowanie bez zmian | `test_indexing_flow.py` |
| nowy dokument | `test_indexing_flow.py` |
| zmieniony dokument | `test_indexing_flow.py` |
| usunięty dokument | `test_indexing_flow.py` |
| wznowienie po przerwaniu | `test_indexing_flow.py`, `test_disk_and_errors.py` |
| błąd parsera | `test_disk_and_errors.py`, `test_pipeline.py` |
| brak miejsca na dysku | `test_disk_and_errors.py` |
| migracja indeksu | `test_index_maintenance.py` |

### Testy interfejsu: 195

Uruchamiane przez `pytest-qt` w trybie `offscreen`, bez widocznego okna.

| Plik | Testy | Zakres |
| --- | --- | --- |
| `test_dialogs_and_i18n.py` | 43 | okna komunikatów, polskie przyciski, liczebniki, formaty |
| `test_search_view.py` | 13 | wpisanie zapytania, tryby, filtry, wyniki, stronicowanie |
| `test_workers.py` | 12 | praca w tle, dostarczanie wyników do wątku głównego |
| `test_indexing_view.py` | 10 | start, pauza, wznowienie, anulowanie, liczniki |
| `test_first_run.py` | 8 | pierwsze uruchomienie, nawigacja, pasek stanu |
| `test_report_and_diagnostics.py` | 7 | raport pokrycia i diagnostyka w interfejsie |
| `test_polish_text.py` | 102 | poprawna polszczyzna napisów w całym pakiecie |

Ostatni plik zasługuje na słowo wyjaśnienia. Wymaganie mówi, że interfejs jest
po polsku, a polszczyzna bez znaków diakrytycznych nią nie jest. Test przechodzi
po wszystkich modułach pakietu, wyciąga z nich napisy widoczne dla użytkownika
(pomijając nazwy zdarzeń logu, klucze i ścieżki) i sprawdza, czy nie zawierają
form pozbawionych ogonków. Zatrzymuje regresję przy dopisywaniu nowych
komunikatów.

## Pokrycie kodu

Pomiar: `pytest --cov=finddocs`. Łącznie **73 procent** instrukcji.

Moduły krytyczne:

| Moduł | Pokrycie |
| --- | --- |
| `normalization/text.py` | 100% |
| `ocr/detector.py` | 100% |
| `config.py` | 100% |
| `types.py` | 99% |
| `errors.py` | 99% |
| `search/aggregate.py` | 99% |
| `security/network.py` | 99% |
| `normalization/dates.py` | 98% |
| `chunking/strategy.py` | 97% |
| `normalization/numbers.py` | 95% |
| `extractors/encoding.py` | 94% |
| `search/highlight.py` | 93% |
| `jobs/control.py` | 93% |
| `search/query_parser.py` | 91% |
| `security/redaction.py` | 91% |
| `security/credentials.py` | 90% |
| `ocr/service.py` | 87% |
| `indexing/service.py` | 84% |
| `jobs/indexing_job.py` | 84% |
| `indexing/vector.py` | 83% |
| `search/service.py` | 81% |

Moduły o niższym pokryciu i powód:

| Moduł | Pokrycie | Powód |
| --- | --- | --- |
| `connectors/sharepoint/auth.py` | 17% | ścieżki wymagają prawdziwego logowania Microsoft, testowany jest interfejs, nie MSAL |
| `providers/internal_api.py` | 25% | dostawca przygotowany na przyszłość, bez działającego punktu końcowego |
| `ocr/engines/tesseract.py` | 38% | wymaga zainstalowanego Tesseract, logika aplikacji testowana na silniku zastępczym |
| `ocr/engines/easyocr_engine.py` | 39% | jak wyżej |
| `ocr/engines/rapidocr_engine.py` | 45% | jak wyżej |
| `connectors/sharepoint/connector.py` | 52% | część ścieżek zależy od odpowiedzi prawdziwej dzierżawy |
| `jobs/pipeline.py` | 66% | rzadkie kombinacje błędów, główne ścieżki i izolacja błędów pokryte |

Pokrycie modułów interfejsu jest zaniżone przez sposób pomiaru: praca w tle idzie
przez `QThreadPool`, czyli wątki tworzone po stronie Qt, których narzędzie
pomiarowe nie śledzi. Kod jest wykonywany, ale nie jest liczony.

## Weryfikacja ręczna

Poza suitą automatyczną wykonano przebieg na zbiorze demonstracyjnym:

| Krok | Wynik |
| --- | --- |
| wygenerowanie zbioru | 24 pliki w 8 katalogach |
| pierwsze indeksowanie | 24 wykryte, 20 przetworzonych, 2 pominięte, 2 błędy, 2 dokumenty z OCR, 5,7 s |
| liczba dokumentów w indeksie | 25 (jeden to załącznik wiadomości) |
| ponowne skanowanie | 24 bez zmian, 0 przetworzonych, poniżej 0,1 s |
| pełne przeindeksowanie | 1,6 s dzięki pamięci podręcznej OCR |
| raport pokrycia | 21 zaindeksowanych, 4 niewyszukiwalne, wyraźne ostrzeżenie o niekompletności |
| numer rachunku, trzy zapisy | 18 dokumentów w każdym zapisie, czasy 9 do 10 ms |
| data, trzy zapisy | 10 dokumentów w każdym zapisie, czas 4 ms |
| polskie znaki z ogonkami i bez | identyczne wyniki, także dla litery `ł` |
| tryb hybrydowy | `procedura-przelewow-2015.docx` na pierwszym miejscu tam, gdzie tryb dokładny nie znajduje nic |
| test dymny zbudowanej aplikacji | aplikacja uruchamia się i zamyka poprawnie, kod wyjścia 0 |
| pakiet bez modelu | 974 pliki, 409 MB |
| pakiet z modelem INT8 | 982 pliki, 534 MB, w logu `provider.loaded` |
| instalator Inno Setup | `FindDocs-0.1.0-instalator.exe`, 191 MB |

Dwa błędy w zbiorze demonstracyjnym są celowe: uszkodzony PDF i dokument
zabezpieczony hasłem. Sprawdzają izolację błędów.

## Błędy wykryte przez testy i naprawione

Testy pisane w tej rundzie wykryły cztery defekty na ścieżkach produkcyjnych:

1. **Ciche błędne rozpoznanie kodowania.** Krótki plik UTF-8 z polskimi znakami
   bywał rozpoznawany jako koreańska strona kodowa `cp949`, a plik iso-8859-2
   jako cp1250. Dekodowanie się udawało, więc do indeksu trafiał tekst bez sensu
   i nikt się o tym nie dowiadywał. Naprawione wspólnym modułem
   `extractors/encoding.py` z oceną jakości wyniku.
2. **Mojibake w treści HTML wiadomości MSG.** Strona kodowa wiadomości
   (domyślnie cp1252) była przyjmowana bez sprawdzenia, a dekoduje ona dowolne
   bajty, więc treść UTF-8 zamieniała się w ciąg znaków bez sensu.
3. **Brak pliku logu.** Moduły tworzą loggery przy imporcie, więc `get_logger`
   ustawiał logowanie zanim aplikacja poznała ścieżkę pliku. Późniejsze jawne
   wywołanie było ignorowane i **żaden log nie powstawał**.
4. **Naruszenie ochrony pamięci w warstwie pracy w tle.** Pula wątków usuwa
   `QRunnable` zaraz po `run`, a obiekt sygnałów nie miał referencji z poziomu
   Pythona. Zdarzenie czekające w kolejce wskazywało na zwolnioną pamięć.
   Objawiało się jako sporadyczne przerwanie procesu podczas testów interfejsu.

Osobno, poza testami, naprawiono zawieszanie się zbudowanej aplikacji: okno
modalne otwierane w konstruktorze okna głównego blokowało start w trybie
nieinteraktywnym.

## Czego nie przetestowano

| Obszar | Powód |
| --- | --- |
| **połączenie z prawdziwą dzierżawą SharePoint** | brak danych dostępowych w środowisku, w którym powstała ta wersja |
| odczyt `.doc` i `.xls` przez Microsoft Office | wymaga zainstalowanego pakietu Office |
| Tesseract, EasyOCR, RapidOCR jako silniki rzeczywiste | wymagają instalacji, testowany jest interfejs i logika aplikacji |
| zbiory rzędu setek tysięcy dokumentów | brak takiego zbioru testowego |
| dostępność dla czytników ekranu | poza zakresem tej wersji |
| test penetracyjny i audyt zewnętrzny | poza zakresem tej wersji |

Pierwszy wiersz jest najważniejszy. **Testy na zamockowanych odpowiedziach
Microsoft Graph nie są dowodem na to, że integracja działa w konkretnej
dzierżawie.** Procedurę testu wdrożeniowego opisuje
[integracja z SharePoint](integracja-sharepoint.md).

## Jak powtórzyć

```bash
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m pytest -q --cov=finddocs --cov-report=term-missing
.venv\Scripts\python.exe -m pytest -q -m "not requires_model"
.venv\Scripts\python.exe -m pytest -q tests/search
.venv\Scripts\python.exe -m ruff check src tests
.venv\Scripts\python.exe -m ruff format --check src tests
.venv\Scripts\python.exe -m mypy src
```

Znaczniki: `slow`, `gui`, `requires_model`, `requires_ocr`, `requires_office`.
Testy oznaczone `requires_model` (21 sztuk) są pomijane, gdy w katalogu
`models/` nie ma modelu embeddingów.
