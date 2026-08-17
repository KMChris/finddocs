# FindDocs

Lokalna wyszukiwarka dokumentów korporacyjnych dla Windows 11.
Indeksuje dokumenty z SharePointa i z katalogów lokalnych, a następnie pozwala
je przeszukiwać dokładnie, semantycznie i hybrydowo. Wszystko dzieje się na
komputerze użytkownika: dokumenty, zapytania i embeddingi nie opuszczają maszyny.

## Co to potrafi

* **Wyszukiwanie dokładne** zwraca wszystkie dokumenty zawierające podane słowo,
  frazę, nazwisko, datę, kwotę lub numer rachunku. Bez ukrytego limitu wyników.
  Numer `00 1234 5678 9012 3456 7890 1234`, `00-1234-...` i zapis ciągły trafiają
  w te same dokumenty. Data `24.07.2015`, `2015-07-24` i `24 lipca 2015` również.
* **Wyszukiwanie semantyczne** znajduje dokumenty powiązane znaczeniowo, nawet
  jeśli nie zawierają tych samych słów. Model jest polski i działa na CPU.
* **Wyszukiwanie hybrydowe** łączy oba podejścia metodą Reciprocal Rank Fusion,
  zachowując wartości dosłowne z zapytania jako warunek obowiązkowy.
* **OCR** uruchamiany tylko wtedy, gdy dokument nie ma użytecznej warstwy tekstowej.
  Wynik jest oznaczany, żeby dało się odróżnić go od tekstu natywnego.
* **Raport pokrycia** pokazuje, czego nie udało się zaindeksować i dlaczego.
  Jeśli choć jeden dokument jest niewyszukiwalny, aplikacja nie twierdzi, że
  zbiór jest kompletny.

## Obsługiwane formaty

PDF (z warstwą tekstową i skanowany), DOCX, DOC, XLSX, XLS, CSV, TSV, TXT,
HTML, RTF, EML, MSG wraz z załącznikami, PNG, JPEG, TIFF, BMP, GIF, WEBP.

Szczegóły, poziom wsparcia i ograniczenia każdego formatu: [docs/formaty.md](https://github.com/KMChris/finddocs/blob/main/docs/formaty.md).

## Uruchomienie

FindDocs nie ma instalatora ani pliku wykonywalnego. Aplikacja uruchamia się
wprost z kodu źródłowego. Wymagany Python od 3.11 do 3.14 na Windows 11.

```bash
py -3.11 -m venv .venv
```

```bash
.venv\Scripts\python -m pip install -r requirements.txt
```

```bash
.venv\Scripts\python run.py
```

Skrypt `run.py` bez argumentów uruchamia interfejs graficzny, a z dowolnym
poleceniem daje dostęp do poleceń administracyjnych (`run.py --help`).
Skrót w menu Start wskazuje na `pythonw.exe` z argumentem `run.py`, więc
użytkownik nie widzi konsoli.

Zależności opcjonalne mają osobne pliki, instalowane w razie potrzeby:

| Plik | Zawartość |
| --- | --- |
| `requirements-ocr.txt` | silnik OCR RapidOCR, bez instalatora systemowego |
| `requirements-export.txt` | konwersja modeli Hugging Face do ONNX |
| `requirements-gpu-dml.txt` | embeddingi na dowolnej karcie graficznej (DirectML) |
| `requirements-gpu-cuda.txt` | embeddingi na karcie NVIDIA (CUDA) |
| `requirements-pgvector.txt` | magazyn wektorów w PostgreSQL z pgvector |
| `requirements-dev.txt` | testy, kontrola typów i linting |

Pliki z wariantem GPU wymagają drugiego polecenia, które przywraca wariant GPU
pakietu onnxruntime (warianty CPU i GPU współdzielą pliki, a pip nie gwarantuje
kolejności instalacji):

```bash
.venv\Scripts\python -m pip install --force-reinstall --no-deps onnxruntime-gpu
```

Pełny opis przygotowania środowiska, wydajności GPU i konfiguracji:
[docs/uruchomienie-ze-zrodel.md](https://github.com/KMChris/finddocs/blob/main/docs/uruchomienie-ze-zrodel.md)
oraz [docs/embeddingi-gpu-api.md](https://github.com/KMChris/finddocs/blob/main/docs/embeddingi-gpu-api.md).

Wyszukiwanie dokładne działa od razu. Wyszukiwanie semantyczne i hybrydowe
wymaga lokalnego modelu embeddingów, który instaluje jedno polecenie (za jawną
zgodą pobiera model z Hugging Face i konwertuje do ONNX):

```bash
.venv\Scripts\python run.py model import --use
```

Polecenie `run.py model import` przyjmuje też katalog z własnym modelem albo
dowolne repozytorium Hugging Face.

Wektory fragmentów mogą opcjonalnie trafiać do bazy PostgreSQL z rozszerzeniem
pgvector zamiast do pliku lokalnego (`requirements-pgvector.txt`, włączane
świadomie w ustawieniach). Opis i zasady bezpieczeństwa:
[docs/baza-wektorowa.md](https://github.com/KMChris/finddocs/blob/main/docs/baza-wektorowa.md).

Rozpoznawanie tekstu ze skanów działa domyślnie na procesorze. Przy dużych
zbiorach skanów można je oddać serwerowi z kartą graficzną (model
PP-OCRv6_medium, gotowy kontener w `deploy/ppocr`). Funkcja jest domyślnie
wyłączona, bo wysyła obrazy stron poza komputer. Opis:
[docs/ocr-gpu-api.md](https://github.com/KMChris/finddocs/blob/main/docs/ocr-gpu-api.md).

## Szybki start bez SharePointa

Aplikacja ma wbudowany zbiór demonstracyjny z fikcyjnymi polskimi dokumentami.
Na ekranie **Źródła i konfiguracja** naciśnij **Zbiór demonstracyjny**,
potem przejdź na ekran **Indeksowanie** i naciśnij **Skanuj źródła**. Po chwili
można wyszukiwać.

To samo z wiersza poleceń:

```bash
.venv\Scripts\python run.py demo --register
```

```bash
.venv\Scripts\python run.py index
```

```bash
.venv\Scripts\python run.py search "procedura przelewów 24.07.2015"
```

## Środowisko developerskie

```bash
py -3.11 -m venv .venv
```

```bash
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt -r requirements-ocr.txt
```

Model embeddingów pobiera się raz z Hugging Face i eksportuje do ONNX:

```bash
git clone https://huggingface.co/sdadas/mmlw-retrieval-roberta-base models/mmlw-retrieval-roberta-base
```

```bash
.venv\Scripts\python.exe -m pip install -r requirements-export.txt
```

```bash
.venv\Scripts\python.exe tools/export_model_onnx.py models/mmlw-retrieval-roberta-base --quantize
```

## Kontrola jakości

```bash
.venv\Scripts\python.exe -m ruff check src tests tools run.py
```

```bash
.venv\Scripts\python.exe -m ruff format --check src tests tools run.py
```

```bash
.venv\Scripts\python.exe -m mypy src
```

```bash
.venv\Scripts\python.exe -m pytest -q
```

## Architektura w skrócie

```
connectors  ->  extractors / ocr  ->  normalization / chunking  ->  indexing
                                                                      |
                                                     search  <--------+
                                                       |
                                                jobs  -+->  gui
```

* metadane, fragmenty i indeks pełnotekstowy: SQLite w trybie WAL z FTS5
  w wariancie external content;
* indeks wektorowy: FAISS HNSW z mapą identyfikatorów, usunięcia przez nagrobki
  i okresową kompaktację;
* embeddingi: ONNX Runtime na CPU, opcjonalnie na karcie graficznej (DirectML
  albo CUDA), model `sdadas/mmlw-retrieval-roberta-base`
  (Apache-2.0, 768 wymiarów, pooling CLS);
* interfejs: PySide6 (LGPL).

Szczegóły i diagramy: [docs/architektura.md](https://github.com/KMChris/finddocs/blob/main/docs/architektura.md).

## Dokumentacja

| Dokument | Zawartość |
| --- | --- |
| [Instrukcja użytkownika](https://github.com/KMChris/finddocs/blob/main/docs/instrukcja-uzytkownika.md) | obsługa aplikacji |
| [Uruchomienie z kodu źródłowego](https://github.com/KMChris/finddocs/blob/main/docs/uruchomienie-ze-zrodel.md) | środowisko, zależności, konfiguracja, lokalny model embeddingów |
| [Embeddingi na GPU i zdalne API](https://github.com/KMChris/finddocs/blob/main/docs/embeddingi-gpu-api.md) | DirectML i CUDA, batch, zdalny dostawca z kluczem API |
| [Instrukcja administratora](https://github.com/KMChris/finddocs/blob/main/docs/instrukcja-administratora.md) | wdrożenie, konfiguracja, CLI |
| [Integracja z SharePoint](https://github.com/KMChris/finddocs/blob/main/docs/integracja-sharepoint.md) | Microsoft Graph, Entra ID, uprawnienia |
| [Architektura](https://github.com/KMChris/finddocs/blob/main/docs/architektura.md) | warstwy, diagramy, decyzje |
| [System wizualny](https://github.com/KMChris/finddocs/blob/main/docs/ui-design.md) | tokeny, kontrolki wspólne, reguły interfejsu |
| [Schemat danych](https://github.com/KMChris/finddocs/blob/main/docs/schemat-danych.md) | tabele, kolumny, wersjonowanie |
| [Odbudowa indeksu](https://github.com/KMChris/finddocs/blob/main/docs/odbudowa-indeksu.md) | przebudowa, kopie, kompaktacja |
| [Aktualizacja](https://github.com/KMChris/finddocs/blob/main/docs/aktualizacja.md) | procedura aktualizacji |
| [Diagnostyka](https://github.com/KMChris/finddocs/blob/main/docs/diagnostyka.md) | logi, kody błędów, typowe problemy |
| [Formaty](https://github.com/KMChris/finddocs/blob/main/docs/formaty.md) | obsługiwane formaty i poziomy wsparcia |
| [OCR](https://github.com/KMChris/finddocs/blob/main/docs/ocr.md) | silniki, jakość, wydajność |
| [OCR na GPU przez zdalne API](https://github.com/KMChris/finddocs/blob/main/docs/ocr-gpu-api.md) | serwer PP-OCRv6 w kontenerze, konfiguracja, bezpieczeństwo |
| [Znane ograniczenia](https://github.com/KMChris/finddocs/blob/main/docs/ograniczenia.md) | czego aplikacja nie robi |
| [Raport bezpieczeństwa](https://github.com/KMChris/finddocs/blob/main/docs/raport-bezpieczenstwa.md) | model zagrożeń i kontrole |
| [Raport PoC](https://github.com/KMChris/finddocs/blob/main/docs/raport-poc.md) | porównanie modeli i pomiary |
| [Raport testów](https://github.com/KMChris/finddocs/blob/main/docs/raport-testow.md) | zakres i wyniki testów |
| [Licencje](https://github.com/KMChris/finddocs/blob/main/docs/licencje.md) | komponenty i licencje, SBOM w `sbom.cdx.json` |
| [Plan RAG i GPU](https://github.com/KMChris/finddocs/blob/main/docs/plan-rag-gpu.md) | przyszły rozwój |
| [ADR](https://github.com/KMChris/finddocs/tree/main/docs/adr) | decyzje architektoniczne |

## Prywatność

Aplikacja nie zawiera telemetrii. Domyślnie cały ruch wychodzący jest zablokowany.
Połączenia z Microsoft Graph włączają się dopiero po skonfigurowaniu źródła
SharePoint, a pobieranie modelu wymaga osobnej zgody. Lista dozwolonych adresów
jest wpisana w kod i widoczna na ekranie **Diagnostyka**.

Indeks zawiera treść dokumentów, więc katalog `%LOCALAPPDATA%\FindDocs` podlega
tej samej klauzuli poufności co dokumenty źródłowe.

## Licencja

Kod aplikacji: licencja MIT, patrz [LICENSE](https://github.com/KMChris/finddocs/blob/main/LICENSE).
Licencje komponentów i modeli: [docs/licencje.md](https://github.com/KMChris/finddocs/blob/main/docs/licencje.md).
