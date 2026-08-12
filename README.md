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

## Instalacja dla użytkownika

Uruchom instalator `FindDocs-0.2.4-instalator.exe`. Instalacja nie wymaga
uprawnień administratora. Po zakończeniu aplikacja jest dostępna w menu Start.
Nie trzeba uruchamiać żadnego serwera ani wpisywać adresu w przeglądarce.

Pełna instrukcja: [docs/instrukcja-uzytkownika.md](https://github.com/KMChris/finddocs/blob/main/docs/instrukcja-uzytkownika.md).

## Instalacja przez pip

Wymagany Python od 3.11 do 3.14 na Windows 11.

```bash
pip install finddocs
```

Silnik OCR jest opcjonalny i instaluje się jako dodatek:

```bash
pip install "finddocs[ocr-rapid]"
```

Dodatek `all` instaluje komplet dla samodzielnego stanowiska: silnik OCR
oraz narzędzia importu i konwersji modeli embeddingów:

```bash
pip install "finddocs[all]"
```

Po instalacji polecenie `finddocs-gui` uruchamia interfejs graficzny,
a `finddocs` daje dostęp do poleceń administracyjnych. Wyszukiwanie dokładne
działa od razu. Wyszukiwanie semantyczne i hybrydowe wymaga lokalnego modelu
embeddingów, który instaluje jedno polecenie (za jawną zgodą pobiera model
z Hugging Face i konwertuje do ONNX):

```bash
finddocs model import --use
```

Polecenie `finddocs model import` przyjmuje też katalog z własnym modelem albo
dowolne repozytorium Hugging Face. Pełny opis instalacji, konfiguracji i modeli:
[docs/instalacja-pip.md](https://github.com/KMChris/finddocs/blob/main/docs/instalacja-pip.md).

Wektory fragmentów mogą opcjonalnie trafiać do bazy PostgreSQL z rozszerzeniem
pgvector zamiast do pliku lokalnego (dodatek `finddocs[pgvector]`, włączany
świadomie w ustawieniach). Opis i zasady bezpieczeństwa:
[docs/baza-wektorowa.md](https://github.com/KMChris/finddocs/blob/main/docs/baza-wektorowa.md).

## Szybki start bez SharePointa

Aplikacja ma wbudowany zbiór demonstracyjny z fikcyjnymi polskimi dokumentami.
Na ekranie **Źródła i konfiguracja** naciśnij **Zbiór demonstracyjny**,
potem przejdź na ekran **Indeksowanie** i naciśnij **Skanuj źródła**. Po chwili
można wyszukiwać.

To samo z wiersza poleceń:

```bash
finddocs demo --register
finddocs index
finddocs search "procedura przelewów 24.07.2015"
```

## Uruchomienie developerskie

Wymagany Python od 3.11 do 3.14 na Windows 11.

```bash
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev,ocr-rapid]"
```

Model embeddingów pobiera się raz z Hugging Face i eksportuje do ONNX:

```bash
git clone https://huggingface.co/sdadas/mmlw-retrieval-roberta-base models/mmlw-retrieval-roberta-base
.venv\Scripts\python.exe -m pip install torch transformers onnx onnxscript
.venv\Scripts\python.exe tools/export_model_onnx.py models/mmlw-retrieval-roberta-base --quantize
```

Uruchomienie interfejsu:

```bash
.venv\Scripts\python.exe -m finddocs.gui
```

Uruchomienie poleceń administracyjnych:

```bash
.venv\Scripts\python.exe -m finddocs --help
```

## Kontrola jakości

```bash
.venv\Scripts\python.exe -m ruff check src tests packaging tools
.venv\Scripts\python.exe -m ruff format --check src tests packaging tools
.venv\Scripts\python.exe -m mypy src
.venv\Scripts\python.exe -m pytest -q
```

## Budowanie pakietu i instalatora

```bash
.venv\Scripts\python.exe packaging/build_app.py --with-model
.venv\Scripts\python.exe packaging/build_installer.py
```

Pierwsze polecenie tworzy katalog `packaging/output/FindDocs` z plikiem
wykonywalnym i wykonuje test dymny. Drugie buduje instalator przy pomocy
Inno Setup 6. Gdy Inno Setup nie jest zainstalowany, skrypt wypisuje instrukcję
instalacji zamiast kończyć pracę bez komunikatu.

Rozmiary wyniku: 409 MB bez modelu, 534 MB z modelem w wersji INT8,
191 MB dla samego instalatora. Przełącznik `--full-precision-model` dokłada
wagi FP32, co powiększa pakiet o około 470 MB i nie jest potrzebne do
domyślnej konfiguracji.

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
* embeddingi: ONNX Runtime na CPU, model `sdadas/mmlw-retrieval-roberta-base`
  (Apache-2.0, 768 wymiarów, pooling CLS);
* interfejs: PySide6 (LGPL).

Szczegóły i diagramy: [docs/architektura.md](https://github.com/KMChris/finddocs/blob/main/docs/architektura.md).

## Dokumentacja

| Dokument | Zawartość |
| --- | --- |
| [Instrukcja użytkownika](https://github.com/KMChris/finddocs/blob/main/docs/instrukcja-uzytkownika.md) | obsługa aplikacji |
| [Instalacja z PyPI](https://github.com/KMChris/finddocs/blob/main/docs/instalacja-pip.md) | pip, konfiguracja, lokalny model embeddingów |
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
