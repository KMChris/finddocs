# Raport z prac rozpoznawczych

Dokument zbiera wybory technologiczne poparte pomiarami i wyjaśnia, dlaczego
odrzucone rozwiązania zostały odrzucone. Liczby pochodzą z uruchomień na
maszynie opisanej niżej, a nie z dokumentacji producentów. Tam, gdzie wartość
pochodzi z zewnętrznego źródła, jest to wyraźnie napisane.

## Środowisko pomiarowe

| Element | Wartość |
| --- | --- |
| System | Windows 11 Education, jądro raportowane jako Windows 10 |
| Procesor | Intel64 Family 6 Model 183 (Raptor Lake), 28 wątków logicznych |
| Python | 3.11.5, środowisko `.venv` |
| ONNX Runtime | wyłącznie `CPUExecutionProvider` |
| Data pomiarów | 31 lipca 2026 |

Pomiary powtarzalne skryptem
[`tools/benchmark_model.py`](../tools/benchmark_model.py).

## Model embeddingów

### Rozważani kandydaci

| Model | Licencja | Wymiar | Rozmiar FP32 | Język polski | Ocena |
| --- | --- | --- | --- | --- | --- |
| `sdadas/mmlw-retrieval-roberta-base` | Apache-2.0 | 768 | ok. 473 MB | trenowany na polskim, zadanie wyszukiwania | **wybrany** |
| `sdadas/mmlw-retrieval-roberta-large` | Apache-2.0 | 1024 | ok. 1,4 GB | jak wyżej, wyższa jakość | odrzucony: rozmiar i czas na CPU |
| `intfloat/multilingual-e5-base` | MIT | 768 | ok. 1,1 GB | wielojęzyczny, polski jako jeden z wielu | odrzucony: gorszy na polskim niż model dedykowany |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Apache-2.0 | 384 | ok. 470 MB | wielojęzyczny, mały | odrzucony: wyraźnie słabszy na parafrazach po polsku |
| `Voicelab/sbert-base-cased-pl` | CC BY 4.0 | 768 | ok. 500 MB | polski, ale zadanie podobieństwa zdań | odrzucony: nieprzeznaczony do wyszukiwania |

Kryteria: licencja dopuszczająca użycie komercyjne, rozmiar możliwy do
trzymania na stanowisku, jakość na języku polskim, czas na CPU, zużycie
pamięci i wymiar wektora (wpływa na rozmiar indeksu).

`mmlw-retrieval-roberta-base` wygrywa, bo jest jedynym kandydatem, który
jednocześnie jest trenowany na polskim, przeznaczony do wyszukiwania (a nie do
podobieństwa zdań), ma licencję Apache-2.0 i mieści się w rozsądnym rozmiarze
po kwantyzacji.

**Zastrzeżenie.** Pomiary jakości wykonano tylko dla wybranego modelu.
Porównanie pozostałych kandydatów opiera się na ich kartach modeli i na
publikowanych wynikach dla języka polskiego, a nie na własnych uruchomieniach.
Nie twierdzimy, że przeprowadziliśmy pełny konkurs modeli.

### Pomiary wybranego modelu

Ten sam model w dwóch wariantach wag, ten sam zbiór, te same zapytania.

| Miara | INT8 (wybrany) | FP32 |
| --- | --- | --- |
| Rozmiar pliku wag | 119,0 MB | 472,8 MB |
| Czas wczytania sesji | 0,30 s | 0,52 s |
| Pamięć procesu po wczytaniu | 308 MB | 925 MB |
| Pamięć procesu po pracy | 325 MB | 937 MB |
| Przepustowość indeksowania | 351 fragmentów na sekundę | 162 fragmentów na sekundę |
| Czas embeddingu zapytania, mediana | 3,7 ms | 7,0 ms |
| Czas embeddingu zapytania, p95 | 4,2 ms | 7,5 ms |
| recall@5 | 1,000 | 1,000 |
| MRR | 0,938 | 1,000 |
| nDCG@5 | 0,954 | 1,000 |

Zbiór pomiarowy: 12 krótkich dokumentów biurowych po polsku, 8 zapytań
w formie parafrazy (zapytanie nie ma wspólnych słów z dokumentem, który ma
znaleźć).

### Wniosek

Wybrany wariant to **INT8**. Uzasadnienie:

* czterokrotnie mniejszy plik i trzykrotnie mniejsze zużycie pamięci,
  co decyduje o tym, czy model da się trzymać na zwykłym stanowisku;
* dwukrotnie wyższa przepustowość indeksowania i dwukrotnie krótszy czas zapytania;
* koszt jakości jest mały i dotyczy jednego zapytania na osiem: dokument
  „protokół z inwentaryzacji” spada z pozycji pierwszej na drugą. recall@5
  pozostaje taki sam.

Wariant FP32 jest dostępny: wystarczy ustawić `embedding.quantized = false`
i przebudować część wektorową. Ma sens tam, gdzie pamięć nie jest ograniczeniem,
a zależy nam na ostatnich procentach jakości rankingu.

### Parametry modelu, których nie wolno pomylić

| Parametr | Wartość | Skutek pomyłki |
| --- | --- | --- |
| prefiks zapytania | `zapytanie: ` | wyraźny spadek jakości bez żadnego komunikatu |
| prefiks treści | pusty | jak wyżej |
| pooling | CLS | wektory z innej przestrzeni, ranking bez sensu |
| normalizacja | L2 | iloczyn skalarny przestaje odpowiadać kosinusowi |
| metryka | iloczyn skalarny | jak wyżej |

Wszystkie są zapisane w manifeście modelu i weryfikowane przy wczytaniu.

## Indeks pełnotekstowy

### Rozważane rozwiązania

| Rozwiązanie | Odrzucone, bo |
| --- | --- |
| Elasticsearch, OpenSearch | osobny serwer, wymaga Javy, sprzeczne z założeniem aplikacji desktopowej |
| Apache Solr | jak wyżej |
| Whoosh | czysty Python, wolny na większych zbiorach, projekt praktycznie nierozwijany |
| Tantivy przez `tantivy-py` | dobry, ale drugi magazyn obok SQLite i dodatkowa zależność binarna |
| **SQLite FTS5** | **wybrany** |

SQLite jest w bibliotece standardowej Pythona, ma FTS5 w standardowych
kompilacjach Windows, nie wymaga serwera, a metadane i indeks trzyma w jednym
pliku, więc kopia zapasowa i transakcyjność są proste.

### Pomiary na zbiorze demonstracyjnym

Zbiór: 24 pliki na dysku, po zaindeksowaniu 25 dokumentów (jeden jest
załącznikiem wiadomości), 27 fragmentów, 27 wektorów.

| Operacja | Czas |
| --- | --- |
| pierwsze indeksowanie, z OCR i embeddingami | 5,7 s |
| ponowne skanowanie bez zmian | poniżej 0,1 s |
| pełne przeindeksowanie z gotową pamięcią podręczną OCR | 1,6 s |

Różnica między 5,7 s a 1,6 s to koszt OCR dwóch skanów. Pamięć podręczna
sprowadza go do zera przy kolejnych przebiegach.

Czasy wyszukiwania:

| Zapytanie | Tryb | Wynik | Czas |
| --- | --- | --- | --- |
| `00 1234 5678 9012 3456 7890 1234` | dokładny | 18 dokumentów | 9 ms |
| `00-1234-5678-9012-3456-7890-1234` | dokładny | 18 dokumentów | 10 ms |
| `00123456789012345678901234` | dokładny | 18 dokumentów | 9 ms |
| `24.07.2015` | dokładny | 10 dokumentów | 4 ms |
| `2015-07-24` | dokładny | 10 dokumentów | 4 ms |
| `24 lipca 2015` | dokładny | 10 dokumentów | 4 ms |
| `przelewów` | dokładny | 2 dokumenty | 1 ms |
| `przelewow` | dokładny | 2 dokumenty | 1 ms |
| `księgowania` | dokładny | 2 dokumenty | 1 ms |
| `ksiegowania` | dokładny | 2 dokumenty | 1 ms |
| `procedura przelewow zagranicznych` | semantyczny | 21 kandydatów | 47 ms |
| `procedura przelewow zagranicznych` | hybrydowy | 21 kandydatów | 48 ms |

Trzy zapisy numeru rachunku dają identyczny zbiór 18 dokumentów. Trzy zapisy
daty dają identyczny zbiór 10 dokumentów. Zapytanie z polskimi znakami i bez
nich daje identyczny wynik, także dla litery `ł`.

Zapytanie `procedura przelewow zagranicznych` w trybie dokładnym zwraca zero
dokumentów, bo w zbiorze nie ma dokumentu z wszystkimi trzema słowami naraz.
W trybie hybrydowym na pierwszym miejscu jest `procedura-przelewow-2015.docx`.
To pokazuje, po co są oba tryby.

### Problem, który wymusił zmianę zapytań

Pierwsza wersja liczyła `bm25()` razem z `GROUP BY doc_id`. SQLite odpowiada
wtedy `unable to use function bm25 in the requested context`. Zwykłe
podzapytanie nie pomaga, bo optymalizator je spłaszcza. Rozwiązaniem jest
`WITH ... AS MATERIALIZED`, co zmusza SQLite do zmaterializowania wyniku przed
grupowaniem.

## Indeks wektorowy

| Rozwiązanie | Odrzucone, bo |
| --- | --- |
| Chroma | warstwa serwera, dużo zależności, model danych nie pasuje do naszego |
| Qdrant | serwer albo tryb wbudowany z Rustem, nadmiarowy dla jednego użytkownika |
| `sqlite-vec` | obiecujący, ale rozszerzenie trzeba dostarczyć jako plik binarny na każdą platformę |
| przeszukiwanie liniowe numpy | wystarczające do 50 tysięcy wektorów, potem czas rośnie liniowo |
| **FAISS HNSW** | **wybrany** |

FAISS ma gotowe koła dla Windows, licencję MIT, działa w procesie i skaluje
się do milionów wektorów. Wybraliśmy `IndexIDMap2` nad `IndexHNSWFlat`
z metryką iloczynu skalarnego, bo identyfikatorem wektora jest wtedy wprost
`chunk_id` i nie potrzeba osobnej tablicy tłumaczącej.

Koszt: HNSW nie obsługuje `remove_ids`. Usunięcia realizujemy nagrobkami
i okresową kompaktacją. To świadomy kompromis, opisany w
[odbudowie indeksu](odbudowa-indeksu.md).

## Odczyt PDF

| Biblioteka | Licencja | Ocena |
| --- | --- | --- |
| PyMuPDF | AGPL-3.0 albo licencja komercyjna | odrzucona: AGPL nie nadaje się do wdrożenia korporacyjnego bez zakupu licencji |
| pdfminer.six | MIT | wolna, brak renderowania stron potrzebnego do OCR |
| pypdf | BSD | brak renderowania stron |
| **pypdfium2** | BSD-3-Clause i Apache-2.0 | **wybrana**: tekst i renderowanie w jednej bibliotece, koła dla Windows |

Renderowanie stron jest wymagane, bo bez niego nie da się zrobić OCR skanów.
To wyklucza pdfminer i pypdf, a licencja wyklucza PyMuPDF.

## OCR

| Silnik | Ocena |
| --- | --- |
| **Tesseract** | domyślny: najlepsza jakość dla druku, model `pol`, licencja Apache-2.0 |
| RapidOCR | zapasowy: działa na ONNX Runtime, nie wymaga instalatora systemowego |
| EasyOCR | zapasowy: dobra jakość, ale ciągnie PyTorch, czyli setki megabajtów |
| PaddleOCR | odrzucony: bardzo duże zależności, słabe wsparcie polskiego |
| Windows OCR (WinRT) | odrzucony: wymaga pakietu językowego systemu, brak kontroli nad jakością |

Tesseract nie jest zależnością aplikacji, bo ma własny instalator systemowy
i własne modele językowe. Aplikacja wykrywa go i mówi wprost, gdy go nie ma.

## Wiadomości Outlook

| Rozwiązanie | Ocena |
| --- | --- |
| `extract-msg` | odrzucone: licencja GPL-3.0 |
| `msg-extractor` | jak wyżej |
| automatyzacja Outlook przez COM | odrzucone: wymaga zainstalowanego Outlooka |
| **własny czytnik kontenera OLE** | **wybrany** |

Czytnik obsługuje właściwości MAPI, treść w trzech wariantach (zwykły tekst,
HTML, RTF skompresowany metodą LZFu i nieskompresowany) oraz załączniki.
Testy budują pliki MSG od zera, więc regresja jest wykrywalna bez
przechowywania binariów w repozytorium.

## Interfejs

| Rozwiązanie | Ocena |
| --- | --- |
| **PySide6** | **wybrany**: LGPL-3.0, oficjalne wiązania Qt, wygląd zgodny z Windows 11 |
| PyQt6 | odrzucone: GPL albo licencja komercyjna |
| Tkinter | odrzucone: wygląd odbiegający od Windows 11, słaba obsługa DPI |
| wxPython | odrzucone: mniejsza społeczność, gorsze wsparcie Windows 11 |
| interfejs w przeglądarce (Flask, FastAPI) | odrzucone wprost przez wymagania: użytkownik nie ma wpisywać adresu ani startować serwera |

## Dystrybucja

Ocena z czasu PoC dotyczyła narzędzi pakujących: wybrano wtedy PyInstaller
w trybie onedir z instalatorem Inno Setup, odrzucając PyInstaller onefile
(rozpakowywanie przy każdym starcie), Nuitkę (długa kompilacja) i cx_Freeze
(słabsze wsparcie dla numpy i ONNX Runtime).

Ta ścieżka została później porzucona w całości. Aplikacja uruchamia się wprost
z kodu źródłowego, bez procesu budowania i bez instalatora. Powody i koszty
tej zmiany opisuje [ADR-011](adr/ADR-011-uruchomienie-ze-zrodel.md).

### Problem, który przetrwał zmianę

**Okno modalne w konstruktorze okna głównego.** Uruchomienie nieinteraktywne
przekraczało limit czasu, bo aplikacja czekała na kliknięcie w oknie, którego
nikt nie widział. Rozwiązanie: komunikaty startowe pokazywane po `show()`,
plus zmienna `FINDDOCS_NO_DIALOG=1` wyłączająca okna modalne. Sprawdza to
uruchomienie `run.py gui --self-test`.

## Rozpoznawanie kodowania

Pierwsza wersja ufała bibliotece `charset_normalizer`. Pomiar na krótkich
polskich plikach pokazał dwa ciche błędy:

* plik UTF-8 ze zdaniem zawierającym polskie znaki bywa rozpoznawany jako
  koreańska strona kodowa `cp949`;
* plik iso-8859-2 bywa rozpoznawany jako cp1250, co zamienia `ś` na `¶`,
  `ą` na `±`, a `ź` na `Œ`.

Oba przypadki są ciche, bo dekodowanie się udaje. Do indeksu trafia wtedy
tekst bez sensu i nikt się o tym nie dowiaduje.

Rozwiązanie: wspólny moduł
[`extractors/encoding.py`](../src/finddocs/extractors/encoding.py), który
ustawia kolejność decyzji (BOM, deklaracja w pliku, ścisłe UTF-8, ocena
jakości) i punktuje wynik pod kątem tego, czy wygląda na polski dokument.
Regresję pilnuje 35 testów w `tests/unit/test_encoding.py`.

## Wnioski

1. Aplikacja desktopowa bez serwera jest wykonalna: SQLite FTS5 plus FAISS
   pokrywają obie potrzeby wyszukiwania.
2. Kwantyzacja INT8 modelu jest opłacalna: czterokrotnie mniejszy plik
   i dwukrotnie szybsze działanie kosztem marginalnego spadku jakości rankingu.
3. Najdroższym elementem indeksowania jest OCR, a nie embeddingi. Pamięć
   podręczna OCR daje największy zysk czasu ze wszystkich optymalizacji.
4. Licencje ograniczają wybór bardziej niż jakość techniczna: PyMuPDF,
   extract-msg i PyQt6 odpadły wyłącznie z tego powodu.
5. Największym ryzykiem cichej awarii jest rozpoznawanie kodowania i parametry
   modelu embeddingów. Oba obszary mają teraz testy regresyjne.
