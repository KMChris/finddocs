# OCR na GPU przez zdalne API

Dokument dla administratora. Opisuje silnik OCR, który oddaje rozpoznawanie
tekstu serwerowi z kartą graficzną zamiast liczyć je na procesorze tego
komputera.

OCR jest najdroższym etapem indeksowania. Silniki lokalne (Tesseract, EasyOCR,
RapidOCR) pracują na CPU i przy dużym zbiorze skanów potrafią wydłużyć pierwsze
indeksowanie o godziny. Serwer z modelem PP-OCRv6_medium na GPU liczy tę samą
pracę szybciej i poprawnie rozpoznaje polskie znaki diakrytyczne (pomiar niżej).

Funkcja jest domyślnie wyłączona. Obraz strony dokumentu opuszcza komputer
dopiero po świadomym włączeniu.

## Kiedy to ma sens

| Sytuacja | Zalecenie |
| --- | --- |
| kilkaset dokumentów, sporadyczne skany | silnik lokalny wystarczy |
| duży zbiór skanów, jednorazowe indeksowanie | serwer na GPU skraca pracę |
| silnik lokalny gubi polskie znaki | PP-OCRv6 rozpoznaje je poprawnie |
| brak zgody organizacji na ruch sieciowy | tylko silnik lokalny |

## Pomiar

Stacja deweloperska (RTX 3090, kontener z `deploy/ppocr` na tym samym
komputerze), skany ze zbioru demonstracyjnego, `render_dpi = 220`, mediana
z pięciu przebiegów. Porównanie z RapidOCR, jedynym silnikiem lokalnym
zainstalowanym w tym środowisku:

| Plik | Zdalny PP-OCRv6_medium (GPU) | Lokalny RapidOCR (CPU) |
| --- | --- | --- |
| skan PNG, jedna strona | 0,167 s | 1,483 s |
| skan PDF, jedna strona | 0,402 s | 1,556 s |

Czas zdalny obejmuje kodowanie strony do PNG, przesłanie jej po pętli zwrotnej
i odpowiedź serwera. Czas PDF w obu kolumnach zawiera rasteryzację strony po
stronie aplikacji, dlatego różnica jest mniejsza niż dla gotowego obrazu.

Różnica w jakości na tym samym skanie: PP-OCRv6_medium zwraca
`POTWIERDZENIE WPŁATY GOTÓWKOWEJ`, a RapidOCR z modelami wbudowanymi
`POTWIERDZENIE WPLATY GOTÓWKOWEJ` (brak `Ł`). Pewność rozpoznania: 0,999
wobec 0,994.

Pomiary pochodzą z jednego komputera i dwóch stron. Traktuj je jako rząd
wielkości, nie jako gwarancję.

## Zasady

* Silnik zdalny nie jest wybierany automatycznie. Ustawienie `ocr.engine = "auto"`
  przegląda wyłącznie silniki lokalne.
* Włączenie wymaga kompletu: zgody (`ocr.remote_api_enabled`), adresu
  (`ocr.remote_api_url`) i wybrania silnika (`ocr.engine = "remote_api"`).
  Brak któregokolwiek elementu oznacza pracę lokalną.
* Polityka sieciowa dopuszcza dokładnie jeden host: ten z podanego adresu.
  Kategoria ruchu to `ocr_api`, widoczna na ekranie Diagnostyka.
* Poza `localhost` wymagane jest https. Zwykłe http do serwera na tym samym
  komputerze wymaga włączenia `allow_plain_http_localhost`.
* Klucz API leży w magazynie poświadczeń Windows (wpis `ocr-api-key`), nigdy
  w pliku konfiguracyjnym ani w logach.
* Gdy serwer nie odpowiada, rozpoznawanie wraca na silnik lokalny. Informacja
  o tym trafia do ostrzeżeń zadania indeksowania, a nie tylko do dziennika.
* Strony idą pojedynczo, tak samo jak przy silnikach lokalnych. Zużycie pamięci
  nie zależy od liczby stron, a **Anuluj** działa między stronami.

## Co jest wysyłane

Na serwer trafia obraz pojedynczej strony w formacie PNG, wyrenderowany przez
aplikację z rozdzielczością `ocr.render_dpi`. Nie są wysyłane: nazwa pliku,
ścieżka, metadane dokumentu ani zapytania użytkownika. Wracają rozpoznane linie
tekstu z miarą pewności i ramkami.

Aplikacja wyłącza w żądaniu wykrywanie orientacji dokumentu i prostowanie
obrazu: strona jest już wyrenderowana z pliku źródłowego, więc te etapy tylko
kosztowałyby czas. Wykrywanie obrotu linii tekstu jest sterowane ustawieniem
`ocr.auto_rotate`.

## Serwer

Repozytorium zawiera gotowy kontener: [`deploy/ppocr`](../deploy/ppocr/README.md).

```bash
docker compose -f deploy/ppocr/compose.yaml up -d --build
```

Kontener wystawia model PP-OCRv6_medium przez standardowy kontrakt serwowania
PaddleX (`POST /ocr`). Aplikacja mówi tym samym kontraktem, więc zadziała także
z serwerem PaddleOCR postawionym przez organizację w inny sposób.

Kontener nie ma uwierzytelnienia i wystawia port tylko na pętli zwrotnej. Do
pracy poza jednym komputerem postaw przed nim odwrotne proxy z TLS i kluczem API.

## Konfiguracja w interfejsie

Ekran **Źródła i konfiguracja**, zakładka **Rozpoznawanie tekstu**:

1. wybierz silnik **Zdalny serwer na GPU**;
2. wpisz adres serwera;
3. wpisz nazwę modelu (domyślnie `PP-OCRv6_medium`);
4. jeśli serwer wymaga klucza, wklej go i naciśnij **Zapisz klucz**;
5. naciśnij **Przetestuj połączenie**, a potem **Zastosuj**.

Test wysyła mały, sztuczny obraz przez ten sam kontrakt, którego używa
indeksowanie. Żaden dokument użytkownika nie opuszcza przy tym komputera.

Powrót na silnik lokalny zamyka kategorię ruchu `ocr_api`. Adres zostaje
zapisany, ale zgoda na wysyłkę znika razem z wyborem silnika.

## Konfiguracja z wiersza poleceń

```bash
finddocs ocr api --enable --url https://ocr.firma.local --model PP-OCRv6_medium
finddocs ocr api-key
finddocs ocr test
```

Serwer na tym samym komputerze, bez TLS:

```bash
finddocs ocr api --enable --url http://127.0.0.1:8868 --allow-http-localhost
```

Powrót na silniki lokalne:

```bash
finddocs ocr api --disable
```

Stan silników pokazuje `finddocs doctor` w sekcji **Komponenty**.

## Ustawienia

| Ustawienie | Domyślnie | Znaczenie |
| --- | --- | --- |
| `ocr.engine` | `auto` | `remote_api` włącza serwer zdalny |
| `ocr.remote_api_enabled` | `false` | zgoda na wysyłanie obrazów stron |
| `ocr.remote_api_url` | pusty | adres serwera |
| `ocr.remote_api_model` | `PP-OCRv6_medium` | nazwa modelu, wchodzi do klucza pamięci podręcznej |
| `ocr.remote_api_key_header` | pusty | pusty oznacza `Authorization: Bearer` |
| `ocr.remote_api_timeout_seconds` | 120 | limit czasu jednego żądania |
| `ocr.remote_api_max_retries` | 3 | liczba prób przy błędach przejściowych |

Kody HTTP 408, 425, 429, 500, 502, 503 i 504 są traktowane jako przejściowe:
próba jest ponawiana z rosnącym odstępem. Kod 401 albo 403 kończy się od razu
komunikatem o kluczu API.

## Pamięć podręczna

Klucz wpisu w tabeli `ocr_cache` zawiera nazwę silnika i jego wersję. Dla silnika
zdalnego wersją jest wartość `ocr.remote_api_model`. Skutek praktyczny: po
podmianie modelu na serwerze trzeba poprawić to ustawienie, inaczej aplikacja
odczyta wyniki policzone starym modelem jako własne.

Przejście z silnika lokalnego na zdalny nie unieważnia indeksu pełnotekstowego:
zmienia się tylko źródło tekstu dla nowo rozpoznawanych stron. Ponowne
rozpoznanie już zaindeksowanych skanów wymaga wyczyszczenia pamięci podręcznej
OCR (przycisk na ekranie Diagnostyka) i pełnego indeksowania.

## Rozwiązywanie problemów

**Test połączenia zwraca „nie odpowiada".** Sprawdź, czy kontener działa
(`docker ps`) i czy odpowiada na `/health`. Adres w aplikacji musi zawierać
schemat (`http://` albo `https://`).

**Kod FD-4003 z informacją o kluczu API.** Serwer odrzucił uwierzytelnienie.
Zapisz klucz ponownie (`finddocs ocr api-key`).

**Rozpoznawanie działa, ale na silniku lokalnym.** Ostrzeżenie w raporcie
indeksowania mówi, dlaczego serwer odpadł. Najczęstsze powody: kategoria
`ocr_api` wyłączona (brak zgody), adres spoza listy dozwolonych hostów albo
zwykłe http do hosta innego niż `localhost`.

**Serwer odpowiada wolno.** Przy pracy wsadowej sprawdź obciążenie karty
(`nvidia-smi`). Jedna strona A4 przy 220 dpi to kilkaset kilobajtów PNG, więc
przy wolnym łączu wąskim gardłem bywa sieć, a nie model.

## Co zostało sprawdzone

Zweryfikowane na stacji deweloperskiej z kartą RTX 3090, na kontenerze
zbudowanym z `deploy/ppocr` (PaddleOCR 3.7.0, PaddlePaddle 3.3.0, CUDA 12.6):

* rozpoznawanie skanu PNG i skanu PDF ze zbioru demonstracyjnego, z polskimi
  znakami diakrytycznymi, numerem rachunku i kwotą;
* zgodność kontraktu z prawdziwym wdrożeniem PaddleX (`POST /ocr`, `/health`);
* pamięć podręczna OCR: trafienie przy powtórzeniu i unieważnienie po zmianie
  nazwy modelu;
* blokada hosta spoza polityki sieciowej;
* powrót na silnik lokalny przy martwym serwerze, razem z ostrzeżeniem;
* konfiguracja i test połączenia z wiersza poleceń.

Zestaw testów: `tests/integration/test_remote_ocr_real.py`, domyślnie pomijany.
Uruchomienie po postawieniu kontenera:

```bash
FINDDOCS_TEST_OCR_URL=http://127.0.0.1:8868 .venv/Scripts/python.exe -m pytest tests/integration/test_remote_ocr_real.py -q
```

NIE sprawdzono: pracy przez odwrotne proxy z TLS i kluczem API, serwera
produkcyjnego organizacji ani zachowania przy wielu klientach naraz.
