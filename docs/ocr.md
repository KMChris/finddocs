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
| EasyOCR | `easyocr` | `pip install finddocs[ocr-easy]` | tak | wymaga pobrania modeli, wolniejszy |
| RapidOCR | `rapidocr` | `pip install finddocs[ocr-rapid]` | model łaciński | działa na ONNX Runtime, bez instalatora systemowego |

Dodatek `ocr-rapid` instaluje pakiet zależny od wersji Pythona: do 3.12 jest to
`rapidocr-onnxruntime` 1.4.4 (nowszych wydań nie ma, a to wymaga Pythona
poniżej 3.13), od 3.13 następca o nazwie `rapidocr`. Oba pochodzą z projektu
RapidAI, mają modele wbudowane w pakiet i nie pobierają niczego z sieci.
Adapter aplikacji obsługuje oba warianty automatycznie.

`ocr.engine = "auto"` wybiera pierwszy dostępny w kolejności Tesseract,
EasyOCR, RapidOCR. Sprawdzenie, co jest widoczne na danym komputerze:

```bash
finddocs doctor
```

### Instalacja Tesseract

Tesseract nie jest dołączony do instalatora, bo ma własny instalator systemowy
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
| `ocr.max_pages_per_document` | 60 | limit stron poddawanych OCR |
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

Pamięć podręczną czyści `finddocs maintenance compact`.

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

## Rozwiązywanie problemów

**Skany nie są w ogóle rozpoznawane.** `finddocs doctor` pokaże, czy jakikolwiek
silnik jest dostępny. Kod `FD-4001` oznacza brak silnika.

**Rozpoznany tekst jest bez polskich znaków.** Brakuje modelu językowego `pol`.
Zainstaluj Tesseract z zaznaczonym językiem polskim.

**Rozpoznanie jest bardzo wolne.** Zmniejsz `render_dpi` do 180 albo ogranicz
`max_pages_per_document`. Sprawdź też, czy pamięć podręczna działa: drugie
indeksowanie tych samych plików powinno być wielokrotnie szybsze.

**Strona przekracza limit czasu.** Kod `FD-4000` z informacją o limicie.
Zwykle dotyczy bardzo dużych obrazów. Podnieś `page_timeout_seconds` albo
zmniejsz `max_image_pixels`.
