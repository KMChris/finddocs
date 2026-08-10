# Uruchomienie z kodu źródłowego

FindDocs nie ma instalatora ani pliku wykonywalnego. Aplikację uruchamia się
wprost z kodu źródłowego, interpreterem Pythona ze środowiska wirtualnego
przygotowanego obok kodu. Ten rozdział opisuje przygotowanie środowiska,
pierwsze uruchomienie, konfigurację oraz podłączenie modelu embeddingów.

## Wymagania

* Windows 11 oraz Python od 3.11 do 3.14 w wydaniu 64-bitowym.
* Aktualny pip.
* Katalog z kodem: kopia repozytorium (`git clone` albo rozpakowane archiwum).

Uprawnienia administratora nie są potrzebne. Wszystko, łącznie ze środowiskiem
wirtualnym, mieści się w profilu użytkownika.

## Przygotowanie środowiska

W katalogu z kodem:

```bat
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pip install -r requirements-ocr.txt
```

Zależności dzielą się na cztery pliki:

| Plik | Zawartość |
| --- | --- |
| `requirements.txt` | wszystko, czego wymaga sama aplikacja |
| `requirements-ocr.txt` | silnik RapidOCR na ONNX Runtime, bez instalatora systemowego |
| `requirements-export.txt` | torch, transformers, onnx i onnxscript: konwersja modeli Hugging Face do ONNX |
| `requirements-dev.txt` | testy, kontrola typów i linting |

Bez `requirements-ocr.txt` działa wszystko poza odczytem skanów. EasyOCR jest
alternatywnym silnikiem i instaluje się go osobno (`pip install "easyocr>=1.7.2"`),
bo przy ustawieniu `ocr.engine` na `auto` ma pierwszeństwo przed RapidOCR.
Tesseract, jeżeli jest preferowany, instaluje się według rozdziału [OCR](ocr.md).

Wszystkie zależności na Pythonach od 3.11 do 3.14 instalują się z gotowych kół,
bez kompilacji ze źródeł. Dokładne wersje całego drzewa zależności, razem
z zależnościami pośrednimi, zapisuje `requirements-lock.txt`.

## Uruchamianie

Wszystko uruchamia skrypt `run.py`, wykonany interpreterem ze środowiska:

```bat
.venv\Scripts\python run.py
```

Bez argumentów startuje interfejs graficzny. Pierwszy argument wybiera tryb
pracy:

| Polecenie | Działanie |
| --- | --- |
| `run.py` | interfejs graficzny |
| `run.py gui --data-dir D:\Dane` | interfejs graficzny z opcjami |
| `run.py --help` | lista poleceń administracyjnych |
| `run.py index` | polecenia administracyjne |

Skrót w menu Start albo na pulpicie tworzy się ręcznie: cel to
`<katalog>\.venv\Scripts\pythonw.exe`, argument to `<katalog>\run.py`,
katalog roboczy to katalog z kodem. Wersja `pythonw.exe` nie otwiera okna
konsoli. Ikona jest w `src\finddocs\resources\finddocs.ico`.

W dalszych przykładach `python` oznacza interpreter ze środowiska wirtualnego,
czyli `.venv\Scripts\python`.

## Pierwsze uruchomienie

Dane, indeks i konfiguracja trafiają do `%LOCALAPPDATA%\FindDocs`, a plik
konfiguracyjny to `%LOCALAPPDATA%\FindDocs\config\settings.json`. Inne
położenie katalogu danych ustawia się zmienną środowiskową `FINDDOCS_HOME`
(działa dla GUI i CLI) albo parametrem `--data-dir`.

Najprostsza ścieżka w GUI: na ekranie **Źródła i konfiguracja** dodaj katalog
lokalny (albo wygeneruj zbiór demonstracyjny), przejdź na ekran **Indeksowanie**,
naciśnij **Skanuj źródła**, po czym wyszukuj na ekranie **Wyszukiwanie**.

To samo z wiersza poleceń:

```bat
python run.py init
python run.py sources add-local C:\Dokumenty --label "Dokumenty działu"
python run.py index
python run.py search "procedura przelewów"
```

## Konfiguracja

Plik `settings.json` edytuje się przy zamkniętej aplikacji. Najczęściej używane
sekcje:

* `sources`: lista źródeł dokumentów; wygodniej zarządzać nią przez GUI albo
  `run.py sources`,
* `ocr.engine`: `auto`, `tesseract`, `rapidocr`, `easyocr` albo `none`,
* `ocr.languages`: języki rozpoznawania, domyślnie `["pol"]`,
* `embedding`: ustawienia modelu embeddingów, opisane niżej,
* `indexing`, `chunking`, `search`: opisane w
  [instrukcji administratora](instrukcja-administratora.md).

## Wyszukiwanie semantyczne: instalacja modelu

Zaraz po przygotowaniu środowiska działa wyszukiwanie dokładne. Tryby
semantyczny i hybrydowy wymagają lokalnego modelu embeddingów w formacie ONNX.
Model instaluje jedno polecenie:

```bat
.venv\Scripts\python -m pip install -r requirements-export.txt
python run.py model import --use
```

Polecenie pobiera domyślny polski model `sdadas/mmlw-retrieval-roberta-base`
z Hugging Face, konwertuje go do ONNX z kwantyzacją INT8, sprawdza poprawność
próbnym przebiegiem i zapisuje w `%LOCALAPPDATA%\FindDocs\models`. Opcja
`--use` od razu przełącza konfigurację na zainstalowany model.

Dwie uwagi:

* Pobranie wymaga jednorazowego połączenia z `huggingface.co` (oraz serwerami
  plików `*.hf.co`). CLI pyta o zgodę przed nawiązaniem połączenia; w skryptach
  zgodę wyraża opcja `--yes`. Żadne inne połączenia nie są nawiązywane.
* Zawartość `requirements-export.txt` (torch, transformers, onnx, onnxscript)
  jest potrzebna tylko do konwersji checkpointów. Po imporcie można ją usunąć:
  `pip uninstall -y torch transformers onnx onnxscript`. Modele publikowane
  od razu w formacie ONNX (na przykład `intfloat/multilingual-e5-small`)
  instalują się bez tych pakietów.

### Import własnego modelu

Źródłem może być katalog na dysku albo repozytorium Hugging Face:

```bat
python run.py model import D:\Modele\moj-model
python run.py model import intfloat/multilingual-e5-small
```

Katalog może zawierać checkpoint HuggingFace (config.json z wagami; nastąpi
konwersja do ONNX) albo gotowy eksport ONNX (pliki `model.onnx` lub
`model.int8.onnx` razem z `tokenizer.json`). Obsługiwane rodziny modeli przy
konwersji: RoBERTa, XLM-RoBERTa, BERT i DistilBERT, wyłącznie z szybkim
tokenizerem (`tokenizer.json`).

Ustawienia modelu są wykrywane automatycznie: wymiar wektora z próbnego
przebiegu, tryb poolingu z konfiguracji sentence-transformers, token
wypełnienia z plików tokenizera. Dla modeli spoza wbudowanej listy przedrostki
zapytania i treści są puste; jeśli model ich wymaga (na przykład rodzina E5),
podaje się je przy imporcie:

```bat
python run.py model import organizacja/model --query-prefix "query: " --passage-prefix "passage: "
```

Pozostałe opcje: `--name` (własna nazwa), `--pooling cls|mean` (wymuszenie
poolingu), `--no-quantize` (bez wariantu INT8), `--keep-fp32` (zachowaj pełną
precyzję obok INT8), `--force` (nadpisanie istniejącego modelu).

### Zarządzanie modelami

```bat
python run.py model list
python run.py model use <klucz>
python run.py model remove <klucz>
```

Każdy zaimportowany model pojawia się automatycznie na liście modeli w GUI
na ekranie **Źródła i konfiguracja**. `run.py model use` przełącza aktywny
model i synchronizuje ustawienia (przedrostki, długość sekwencji) z jego
manifestem.

Te same operacje są dostępne w GUI: przycisk **Ustawienia...** obok listy
modeli otwiera okno z importem z dysku, pobieraniem z Hugging Face, edycją
przedrostków zapytania i treści oraz przełącznikiem indeksowania semantycznego.
Wyłączenie semantyki zatrzymuje liczenie wektorów (działa tylko tryb dokładny);
po ponownym włączeniu zwykłe skanowanie uzupełnia brakujące wektory.

### Ręczne wskazanie modelu

Model przygotowany na innej maszynie można też podłączyć bez importu.
Aplikacja szuka modelu w następującej kolejności:

1. katalog wpisany w `embedding.model_path` w `settings.json`
   (sprawdzany jest też jego podkatalog `onnx`),
2. `%LOCALAPPDATA%\FindDocs\models\<klucz>\onnx`
   (albo ten sam katalog bez podkatalogu `onnx`),
3. katalog `models` obok kodu, czyli w katalogu z repozytorium.

```json
"embedding": {
  "model_key": "mmlw-retrieval-roberta-base",
  "model_path": "D:\\Modele\\mmlw-retrieval-roberta-base\\onnx",
  "quantized": true
}
```

Ustawienie `quantized: true` (domyślne) wybiera wariant INT8, mniejszy
i szybszy na CPU. Wartość `false` wymusza `model.onnx` w pełnej precyzji.
Katalog modelu musi zawierać `manifest.json`; katalogi bez manifestu
importuje się poleceniem `run.py model import`, które go utworzy.

### Sprawdzenie i uzupełnienie indeksu

Konfigurację weryfikuje polecenie:

```bat
python run.py doctor
```

Pola `dostawca_embeddingow` i `model_embeddingow` pokazują aktywne ustawienia.
Gdy modelu brakuje, indeksowanie i wyszukiwanie wypisują ostrzeżenie, że tryb
semantyczny jest niedostępny, a tryb dokładny działa normalnie.

Jeżeli indeks powstał przed dodaniem modelu, dokumenty nie mają jeszcze
wektorów. Uzupełnia je przebudowa części wektorowej:

```bat
python run.py maintenance rebuild --vectors-only
```

Szczegóły przebudowy opisuje [rozdział o odbudowie indeksu](odbudowa-indeksu.md).

## Aktualizacja i usunięcie

Aktualizacja to pobranie nowego kodu i doinstalowanie zależności:

```bat
git pull
.venv\Scripts\python -m pip install -r requirements.txt
```

Pełną procedurę razem ze sprawdzeniem zgodności indeksu opisuje
[rozdział o aktualizacji](aktualizacja.md).

Usunięcie aplikacji to skasowanie katalogu z kodem razem ze środowiskiem
`.venv`. Katalog `%LOCALAPPDATA%\FindDocs` zostaje nietknięty, trzeba go usunąć
osobno. Indeks zawiera treść dokumentów, więc na komputerze współdzielonym
jest to krok obowiązkowy.
