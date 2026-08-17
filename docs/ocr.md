# OCR: rozpoznawanie tekstu ze skanów

OCR jest kosztowny, więc uruchamiamy go tylko wtedy, gdy dokument naprawdę nie
ma użytecznej warstwy tekstowej. Decyzję podejmuje moduł
[`ocr/detector.py`](../src/finddocs/ocr/detector.py) dla każdej strony osobno.

## Kiedy OCR się uruchamia

Strona trafia do OCR, gdy zachodzi którykolwiek z warunków:

| Warunek | Domyślny próg | Ustawienie |
| --- | --- | --- |
| za mało znaków na stronie | poniżej 90 | `ocr.min_chars_per_page` |
| za mało liter wśród znaków | poniżej 45 procent | `ocr.min_alpha_ratio` |
| tekst wygląda na uszkodzony | heurystyka | brak |
| plik jest obrazem rastrowym | zawsze | brak |

Pierwszy próg wyłapuje skany bez warstwy tekstowej. Drugi wyłapuje pliki,
w których warstwa tekstowa istnieje, ale składa się głównie ze śmieci
(typowe dla starych skanerów zapisujących pojedyncze znaki pozycjonowania).

Dokument mieszany, na przykład PDF z dziesięcioma stronami tekstu i dwiema
wklejonymi fotografiami, przechodzi OCR tylko dla tych dwóch stron. Jego
`text_origin` to wtedy `mixed`.

OCR można wyłączyć całkowicie: `ocr.enabled = false`. Skany zostaną wtedy
zaindeksowane jako dokumenty puste i pojawią się w raporcie pokrycia.

## Silniki

Aplikacja nie jest związana z jednym silnikiem. Interfejs jest w
[`ocr/base.py`](../src/finddocs/ocr/base.py), a wybór odbywa się przez
`ocr.engine`.

| Silnik | Wartość `engine` | Instalacja | Polski | Uwagi |
| --- | --- | --- | --- | --- |
| Tesseract | `tesseract` | osobny instalator plus pakiet `pol` | tak, model `pol` | najlepsza jakość dla druku, licencja Apache-2.0 |
| EasyOCR | `easyocr` | `pip install "easyocr>=1.7.2"` | tak | wymaga pobrania modeli, wolniejszy |
| RapidOCR | `rapidocr` | `pip install -r requirements-ocr.txt` | model łaciński | działa na ONNX Runtime, bez instalatora systemowego |
| Serwer zdalny | `remote_api` | kontener po stronie serwera | tak, PP-OCRv6 | liczy na GPU, wysyła obrazy stron poza komputer |

Silnik zdalny opisuje osobny dokument:
[OCR na GPU przez zdalne API](ocr-gpu-api.md). Wymaga świadomego włączenia
i nigdy nie jest wybierany przez `auto`.

Plik `requirements-ocr.txt` instaluje pakiet `rapidocr`, następcę wycofanego
`rapidocr-onnxruntime` (tamten kończy się na wersji 1.4.4 i wymaga Pythona
poniżej 3.13). Oba pochodzą z projektu RapidAI, mają modele wbudowane w pakiet
i nie pobierają niczego z sieci. Adapter aplikacji obsługuje oba warianty, więc
starsze środowisko z poprzednim pakietem nadal działa.

`ocr.engine = "auto"` wybiera pierwszy dostępny w kolejności Tesseract,
EasyOCR, RapidOCR. Serwera zdalnego na tej liście nie ma celowo: wysyłka obrazu
poza komputer wymaga jawnego wyboru. Sprawdzenie, co jest widoczne na danym
komputerze:

```bash
python run.py doctor
```

### Instalacja Tesseract

Tesseract nie jest zależnością aplikacji, bo ma własny instalator systemowy
i własny zestaw modeli językowych.

1. Pobierz instalator dla Windows (wydania UB Mannheim).
2. W trakcie instalacji zaznacz język **Polish**.
3. Jeżeli Tesseract nie trafił do zmiennej `PATH`, wskaż plik wykonywalny
   w konfiguracji: `ocr.tesseract_path`.

Aplikacja szuka Tesseract kolejno w `ocr.tesseract_path`, w `PATH`
i w standardowych lokalizacjach instalacji.

Bez Tesseract i bez pozostałych silników OCR jest wyłączony, a aplikacja
mówi o tym na ekranie **Diagnostyka**, zamiast po cichu pomijać skany.

## Renderowanie stron

| Parametr | Wartość domyślna | Znaczenie |
| --- | --- | --- |
| `ocr.render_dpi` | 220 | rozdzielczość renderowania strony PDF |
| `ocr.max_pages_per_document` | 1000 | limit stron poddawanych OCR (w GUI: ekran Źródła i konfiguracja, Opcje indeksowania) |
| `ocr.max_image_pixels` | 40 000 000 | ochrona pamięci przed obrazem-bombą |
| `ocr.page_timeout_seconds` | 120 | limit czasu na jedną stronę |
| `ocr.auto_rotate` | `true` | wykrywanie i korekta orientacji |

Zakres `render_dpi` to 120 do 400. Poniżej 150 jakość rozpoznawania druku
wyraźnie spada, powyżej 300 rośnie czas i zużycie pamięci bez wyraźnego zysku.
220 to kompromis sprawdzony na dokumentach biurowych.

Strony renderowane są **po jednej**. Nigdy nie trzymamy w pamięci całego
dokumentu jako obrazów, więc stustronicowy skan nie wywraca aplikacji.

Przekroczenie `max_pages_per_document` kończy się ostrzeżeniem przy dokumencie:
część treści nie została rozpoznana. To informacja, nie ciche obcięcie.
Wynik obcięty limitem nie trafia do pamięci podręcznej OCR, więc po podniesieniu
limitu pełne indeksowanie rozpoznaje taki dokument od nowa. Wpisy zapisane przez
starsze wydania można usunąć przyciskiem „Wyczyść pamięć OCR" na ekranie
Diagnostyka.

## Korekta orientacji

Przy `auto_rotate = true` aplikacja próbuje wykryć obrót strony (0, 90, 180
albo 270 stopni) i skorygować go przed rozpoznaniem. Skan włożony do skanera
bokiem nie zostaje przez to bezużyteczny.

## Pewność rozpoznania

Każda strona dostaje ocenę pewności w zakresie od 0 do 1, wyliczoną ze średniej
pewności słów zwróconej przez silnik. Dokument dostaje średnią ważoną z liczby
słów.

`ocr.min_confidence_to_keep` (domyślnie 0,3) odrzuca wynik tak słaby, że byłby
tylko szumem w indeksie. Odrzucona strona nie trafia do indeksu, ale zostaje
odnotowana w raporcie.

Ocena pewności widoczna jest w wyniku wyszukiwania przy dokumentach z OCR
i w raporcie pokrycia. Pozwala odróżnić skan czysty od słabo czytelnego.

## Pamięć podręczna

Wynik OCR trafia do tabeli `ocr_cache` pod kluczem złożonym ze skrótu SHA-256
treści pliku, nazwy silnika, jego wersji i rozdzielczości renderowania.

Skutek: ponowne indeksowanie tego samego pliku nie uruchamia OCR jeszcze raz.
Na zbiorze demonstracyjnym pierwsze indeksowanie zajmuje 14,8 s, a pełne
przeindeksowanie z gotową pamięcią podręczną 1,7 s.

Klucz zawiera wersję silnika, więc aktualizacja Tesseract unieważnia stare
wpisy i pozwala odzyskać poprawiony wynik.

Pamięć podręczną czyści `python run.py maintenance compact`.

## Anulowanie

OCR sprawdza żądanie anulowania przed każdą stroną. Naciśnięcie **Anuluj**
w trakcie rozpoznawania stustronicowego dokumentu działa natychmiast, a nie po
zakończeniu całego pliku.

## Oznaczanie wyników

Tekst z OCR jest w indeksie oznaczony na dwóch poziomach:

* dokument: `used_ocr`, `ocr_pages`, `ocr_confidence`, `text_origin`;
* fragment: `origin` oraz `ocr_confidence`.

W interfejsie widać etykietę **OCR** przy wyniku. Dzięki temu użytkownik wie,
że tekst został rozpoznany maszynowo i może zawierać błędy, zamiast zakładać,
że pochodzi wprost z dokumentu.

## Wydajność

Pomiary na zbiorze demonstracyjnym, procesor klasy biurowej, Tesseract z
modelem `pol`, `render_dpi = 220`:

| Operacja | Czas |
| --- | --- |
| render strony A4 z PDF | ok. 0,15 s |
| rozpoznanie strony A4 | 1 do 3 s |
| odczyt strony z pamięci podręcznej | poniżej 0,01 s |

OCR jest najdroższym elementem indeksowania. Jeżeli zbiór zawiera dużo skanów,
pierwsze indeksowanie warto uruchomić poza godzinami pracy. Zadanie da się
wstrzymać i wznowić.

Przy dużych zbiorach skanów rozpoznawanie można oddać serwerowi z kartą
graficzną. Zmierzony czas strony A4 spada wtedy z 1,5 s do 0,2 s, a polskie
znaki diakrytyczne wracają poprawnie także tam, gdzie silnik lokalny je gubi.
Opis i pomiary: [OCR na GPU przez zdalne API](ocr-gpu-api.md).

## Rozwiązywanie problemów

**Skany nie są w ogóle rozpoznawane.** `python run.py doctor` pokaże, czy jakikolwiek
silnik jest dostępny. Kod `FD-4001` oznacza brak silnika.

**Rozpoznany tekst jest bez polskich znaków.** Brakuje modelu językowego `pol`.
Zainstaluj Tesseract z zaznaczonym językiem polskim.

**Rozpoznanie jest bardzo wolne.** Zmniejsz `render_dpi` do 180 albo ogranicz
`max_pages_per_document`. Sprawdź też, czy pamięć podręczna działa: drugie
indeksowanie tych samych plików powinno być wielokrotnie szybsze.

**Strona przekracza limit czasu.** Kod `FD-4000` z informacją o limicie.
Zwykle dotyczy bardzo dużych obrazów. Podnieś `page_timeout_seconds` albo
zmniejsz `max_image_pixels`.
