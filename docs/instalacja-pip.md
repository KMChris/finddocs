# Instalacja z PyPI

FindDocs jest publikowany na PyPI jako pakiet [`finddocs`](https://pypi.org/project/finddocs/).
Ten rozdział opisuje instalację przez pip, pierwszą konfigurację oraz podłączenie
lokalnie pobranego modelu embeddingów. Użytkownikowi końcowemu polecamy gotowy
instalator opisany w [instrukcji użytkownika](instrukcja-uzytkownika.md);
instalacja przez pip jest przeznaczona dla administratorów i osób technicznych.

## Wymagania

* Windows 11 oraz Python od 3.11 do 3.14 w wydaniu 64-bitowym.
* Aktualny pip.

## Instalacja

Zalecane jest osobne środowisko wirtualne, żeby wersje bibliotek FindDocs
nie mieszały się z innymi programami:

```bat
py -m venv %USERPROFILE%\finddocs-env
%USERPROFILE%\finddocs-env\Scripts\python -m pip install "finddocs[ocr-rapid]"
```

Sam pakiet bez OCR instaluje się poleceniem `pip install finddocs`. Dodatki:

| Dodatek | Zawartość |
| --- | --- |
| `ocr-rapid` | silnik RapidOCR na ONNX Runtime, z modelami wbudowanymi w pakiet, bez instalatora systemowego |
| `ocr-easy` | silnik EasyOCR, cięższy i wymagający własnych modeli |
| `export` | torch, transformers, onnx i onnxscript: konwersja checkpointów Hugging Face do ONNX oraz kwantyzacja INT8 |
| `gpu-dml` | wariant DirectML pakietu onnxruntime: embeddingi na karcie graficznej AMD, Intel albo NVIDIA na Windows |
| `gpu-cuda` | wariant CUDA pakietu onnxruntime: tylko NVIDIA, wymaga bibliotek CUDA i cuDNN |
| `all` | komplet dla samodzielnego stanowiska, równoważny `finddocs[ocr-rapid,export]` |

Dodatek `all` celowo nie zawiera `ocr-easy`: przy ustawieniu `ocr.engine`
na `auto` EasyOCR ma pierwszeństwo przed RapidOCR, więc jego doinstalowanie
zmieniłoby używany silnik. Kto chce EasyOCR, instaluje `finddocs[all,ocr-easy]`.
Wszystkie dodatki na Pythonach od 3.11 do 3.14 instalują się z gotowych kół,
bez kompilacji ze źródeł.

Dodatki `gpu-dml` i `gpu-cuda` instalują wariant GPU pakietu onnxruntime obok
wariantu CPU z zależności bazowej. Oba wydania mają ten sam pakiet importowy,
a pip nie gwarantuje, które koło zapisze pliki jako ostatnie, więc po dodatku
zawsze wykonuje się drugie polecenie przywracające wariant GPU:
`pip install --force-reinstall --no-deps onnxruntime-directml` (dla CUDA:
`onnxruntime-gpu`). Stan sprawdza `finddocs model device`. Szczegóły, wersje
i zalecenia wydajności: [embeddingi na GPU i zdalne API](embeddingi-gpu-api.md).

Tesseract, jeżeli jest preferowany, instaluje się osobno według rozdziału [OCR](ocr.md).

Po instalacji w katalogu `Scripts` środowiska dostępne są dwa polecenia:

* `finddocs-gui` uruchamia aplikację okienkową,
* `finddocs` udostępnia polecenia administracyjne (`finddocs --help`).

## Pierwsze uruchomienie

Aplikację uruchamia polecenie `finddocs-gui`. Dane, indeks i konfiguracja trafiają
do `%LOCALAPPDATA%\FindDocs`, a plik konfiguracyjny to
`%LOCALAPPDATA%\FindDocs\config\settings.json`. Inne położenie katalogu danych
ustawia się zmienną środowiskową `FINDDOCS_HOME` (działa dla GUI i CLI) albo
parametrem `--data-dir` w CLI.

Najprostsza ścieżka w GUI: na ekranie **Źródła i konfiguracja** dodaj katalog
lokalny (albo wygeneruj zbiór demonstracyjny), przejdź na ekran **Indeksowanie**,
naciśnij **Skanuj źródła**, po czym wyszukuj na ekranie **Wyszukiwanie**.

To samo z wiersza poleceń:

```bat
finddocs init
finddocs sources add-local C:\Dokumenty --label "Dokumenty działu"
finddocs index
finddocs search "procedura przelewów"
```

## Konfiguracja

Plik `settings.json` edytuje się przy zamkniętej aplikacji. Najczęściej używane
sekcje:

* `sources`: lista źródeł dokumentów; wygodniej zarządzać nią przez GUI albo
  `finddocs sources`,
* `ocr.engine`: `auto`, `tesseract`, `rapidocr`, `easyocr` albo `none`,
* `ocr.languages`: języki rozpoznawania, domyślnie `["pol"]`,
* `embedding`: ustawienia modelu embeddingów, opisane niżej,
* `indexing`, `chunking`, `search`: opisane w
  [instrukcji administratora](instrukcja-administratora.md).

## Wyszukiwanie semantyczne: instalacja modelu

Po samej instalacji z pip działa wyszukiwanie dokładne. Tryby semantyczny
i hybrydowy wymagają lokalnego modelu embeddingów w formacie ONNX. Model
instaluje się jednym poleceniem CLI, bez klonowania repozytorium:

```bat
pip install "finddocs[export]"
finddocs model import --use
```

Polecenie pobiera domyślny polski model `sdadas/mmlw-retrieval-roberta-base`
z Hugging Face, konwertuje go do ONNX z kwantyzacją INT8, sprawdza poprawność
próbnym przebiegiem i zapisuje w `%LOCALAPPDATA%\FindDocs\models`. Opcja
`--use` od razu przełącza konfigurację na zainstalowany model.

Dwie uwagi:

* Pobranie wymaga jednorazowego połączenia z `huggingface.co` (oraz serwerami
  plików `*.hf.co`). CLI pyta o zgodę przed nawiązaniem połączenia; w skryptach
  zgodę wyraża opcja `--yes`. Żadne inne połączenia nie są nawiązywane.
* Dodatek `finddocs[export]` (torch, transformers, onnx, onnxscript) jest
  potrzebny tylko do konwersji checkpointów. Po imporcie można go usunąć:
  `pip uninstall -y torch transformers onnx onnxscript`. Modele publikowane
  od razu w formacie ONNX (na przykład `intfloat/multilingual-e5-small`)
  instalują się bez tego dodatku.

### Import własnego modelu

Źródłem może być katalog na dysku albo repozytorium Hugging Face:

```bat
finddocs model import D:\Modele\moj-model
finddocs model import intfloat/multilingual-e5-small
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
finddocs model import organizacja/model --query-prefix "query: " --passage-prefix "passage: "
```

Pozostałe opcje: `--name` (własna nazwa), `--pooling cls|mean` (wymuszenie
poolingu), `--no-quantize` (bez wariantu INT8), `--keep-fp32` (zachowaj pełną
precyzję obok INT8), `--force` (nadpisanie istniejącego modelu).

### Zarządzanie modelami

```bat
finddocs model list
finddocs model use <klucz>
finddocs model remove <klucz>
```

Każdy zaimportowany model pojawia się automatycznie na liście modeli w GUI
na ekranie **Źródła i konfiguracja**. `finddocs model use` przełącza aktywny
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
3. katalog `models` obok kodu, używany przy uruchamianiu z repozytorium.

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
importuje się poleceniem `finddocs model import`, które go utworzy.

### Sprawdzenie i uzupełnienie indeksu

Konfigurację weryfikuje polecenie:

```bat
finddocs doctor
```

Pola `dostawca_embeddingow` i `model_embeddingow` pokazują aktywne ustawienia.
Gdy modelu brakuje, indeksowanie i wyszukiwanie wypisują ostrzeżenie, że tryb
semantyczny jest niedostępny, a tryb dokładny działa normalnie.

Jeżeli indeks powstał przed dodaniem modelu, dokumenty nie mają jeszcze
wektorów. Uzupełnia je przebudowa części wektorowej:

```bat
finddocs maintenance rebuild --vectors-only
```

Szczegóły przebudowy opisuje [rozdział o odbudowie indeksu](odbudowa-indeksu.md).

## Aktualizacja i usunięcie

```bat
pip install --upgrade finddocs
```

Katalog `%LOCALAPPDATA%\FindDocs` nie jest ruszany przy aktualizacji ani przy
`pip uninstall finddocs`. Indeks zawiera treść dokumentów, więc przy usuwaniu
aplikacji z komputera współdzielonego usuń też ten katalog.
