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
naciśnij **Start**, po czym wyszukuj na ekranie **Wyszukiwanie**.

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

## Wyszukiwanie semantyczne: lokalnie pobrany model

Po samej instalacji z pip działa wyszukiwanie dokładne. Tryby semantyczny
i hybrydowy wymagają modelu MMLW w formacie ONNX. Pakiet nie pobiera modelu
sam z siebie: pobranie i eksport wykonuje się raz, ręcznie, a aplikacja
korzysta wyłącznie z plików lokalnych.

### Przygotowanie modelu

Potrzebne jest sklonowane repozytorium FindDocs (zawiera skrypt eksportu) oraz
środowisko z torch i transformers. Te biblioteki służą tylko do eksportu,
aplikacja ich nie potrzebuje:

```bat
git clone https://github.com/KMChris/finddocs
cd finddocs
git clone https://huggingface.co/sdadas/mmlw-retrieval-roberta-base models/mmlw-retrieval-roberta-base
py -m pip install torch transformers onnx
py tools/export_model_onnx.py models/mmlw-retrieval-roberta-base --quantize
```

Wynik eksportu trafia do `models/mmlw-retrieval-roberta-base/onnx` i zawiera:
`manifest.json` (opis modelu i sumy kontrolne), `model.onnx` (pełna precyzja),
`model.int8.onnx` (wariant skwantyzowany) oraz pliki tokenizera
(`tokenizer.json`, `tokenizer_config.json`, `special_tokens_map.json`,
`added_tokens.json`, `unigram.json`, `config.json`).

### Wskazanie modelu aplikacji

Aplikacja szuka modelu w następującej kolejności:

1. katalog wpisany w `embedding.model_path` w `settings.json`
   (sprawdzany jest też jego podkatalog `onnx`),
2. `%LOCALAPPDATA%\FindDocs\models\mmlw-retrieval-roberta-base\onnx`
   (albo ten sam katalog bez podkatalogu `onnx`),
3. katalog `models` obok kodu, używany przy uruchamianiu z repozytorium.

Najprościej skopiować wyeksportowany katalog do katalogu danych:

```bat
robocopy models\mmlw-retrieval-roberta-base\onnx %LOCALAPPDATA%\FindDocs\models\mmlw-retrieval-roberta-base\onnx /E
```

Zamiast kopiowania można wskazać dowolne położenie w `settings.json`:

```json
"embedding": {
  "model_key": "mmlw-retrieval-roberta-base",
  "model_path": "D:\\Modele\\mmlw-retrieval-roberta-base\\onnx",
  "quantized": true
}
```

Ustawienie `quantized: true` (domyślne) wybiera wariant INT8, mniejszy
i szybszy na CPU. Wartość `false` wymusza `model.onnx` w pełnej precyzji.

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
