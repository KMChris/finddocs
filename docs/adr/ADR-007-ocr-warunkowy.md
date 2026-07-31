# ADR-007: OCR warunkowy z wymiennymi silnikami

**Stan:** przyjęta
**Data:** lipiec 2026

## Kontekst

Skany są częstym elementem archiwów korporacyjnych i bez OCR pozostają
niewyszukiwalne. Jednocześnie OCR jest najdroższym elementem indeksowania:
rozpoznanie strony A4 zajmuje od 1 do 3 sekund, podczas gdy odczyt strony
z warstwą tekstową to milisekundy.

Nie każdy komputer ma zainstalowany silnik OCR, a instalator nie może wymagać
uprawnień administratora.

## Decyzja

**OCR warunkowy.** Decyzja zapada dla każdej strony osobno, na podstawie tego,
co zwrócił parser:

| Warunek | Próg domyślny |
| --- | --- |
| liczba znaków na stronę | poniżej 90 |
| udział liter wśród znaków | poniżej 45 procent |
| tekst wygląda na uszkodzony | heurystyka |
| plik jest obrazem rastrowym | zawsze |

**Silniki wymienne** za protokołem `OcrEngine`. Kolejność przy `engine = "auto"`:
Tesseract, EasyOCR, RapidOCR. Aplikacja wykrywa dostępność i mówi wprost,
gdy żadnego nie ma.

**Przetwarzanie strona po stronie.** Nigdy nie trzymamy w pamięci całego
dokumentu jako obrazów.

**Pamięć podręczna** w tabeli `ocr_cache`, pod kluczem złożonym ze skrótu
SHA-256 treści, nazwy silnika, jego wersji i rozdzielczości renderowania.

**Oznaczanie wyniku** na poziomie dokumentu (`used_ocr`, `ocr_pages`,
`ocr_confidence`, `text_origin`) i fragmentu (`origin`, `ocr_confidence`).

## Rozważane alternatywy

**OCR dla wszystkiego.** Prostsze w kodzie, ale wielokrotnie droższe i gorsze
jakościowo: tekst rozpoznany z obrazu strony jest gorszy niż tekst wyciągnięty
wprost z PDF.

**Brak OCR.** Skany pozostają niewyszukiwalne, co dla archiwum korporacyjnego
jest nie do przyjęcia.

**Jeden silnik na sztywno.** Tesseract wymaga instalatora systemowego, więc na
części stacji byłby niedostępny. Warstwa protokołu kosztuje niewiele, a daje
wybór.

**Dołączenie Tesseract do instalatora.** Tesseract ma własny instalator,
własne modele językowe i licencję Apache-2.0. Dołączenie go zwiększyłoby
instalator i skomplikowało aktualizacje modeli językowych.

## Konsekwencje

Dobre:

* dokument mieszany (dziesięć stron tekstu, dwie fotografie) przechodzi OCR
  tylko dla dwóch stron;
* pamięć podręczna sprowadza koszt ponownego indeksowania do zera. Na zbiorze
  demonstracyjnym pierwsze indeksowanie zajmuje 5,7 s, a pełne przeindeksowanie
  z gotową pamięcią podręczną 1,6 s;
* zużycie pamięci nie zależy od liczby stron dokumentu;
* użytkownik widzi, że tekst pochodzi z OCR, i zna jego pewność.

Kosztowne:

* progi trzeba było dobrać eksperymentalnie i mogą wymagać korekty dla
  nietypowych zbiorów. Są w konfiguracji;
* Tesseract instaluje się osobno. Aplikacja mówi o tym na ekranie
  **Diagnostyka**, zamiast po cichu pomijać skany;
* klucz pamięci podręcznej zawiera wersję silnika, więc aktualizacja Tesseract
  unieważnia stare wpisy. Jest to zamierzone: nowa wersja daje lepszy wynik.
