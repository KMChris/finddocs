# Obsługiwane formaty

Typ pliku rozpoznajemy po sygnaturze zawartości, a nie po rozszerzeniu. Plik
`raport.pdf`, który w środku jest obrazem JPEG, zostanie potraktowany jak obraz.

Poziomy wsparcia:

| Poziom | Znaczenie |
| --- | --- |
| **pełny** | tekst, struktura i metadane odczytywane bez strat |
| **dobry** | tekst i metadane poprawne, część formatowania pomijana |
| **ograniczony** | tekst wymaga dodatkowego kroku (OCR) albo zewnętrznego składnika |
| **eksperymentalny** | odczyt zapasowy, możliwe braki w trudnych plikach |

## Tabela formatów

| Format | Rozszerzenia | Poziom | Biblioteka | Uwagi |
| --- | --- | --- | --- | --- |
| PDF z warstwą tekstową | `.pdf` | pełny | pypdfium2 | tekst, numery stron, metadane |
| PDF skanowany | `.pdf` | ograniczony | pypdfium2 + OCR | render strona po stronie, wynik oznaczony jako OCR |
| Word | `.docx`, `.docm` | pełny | python-docx | akapity, nagłówki, tabele, właściwości dokumentu |
| Word 97-2003 z Office | `.doc`, `.dot` | ograniczony | automatyzacja Microsoft Word | wymaga zainstalowanego Office, makra wyłączone |
| Word 97-2003 bez Office | `.doc`, `.dot` | eksperymentalny | własny czytnik OLE | tekst z tablicy fragmentów, bez układu i tabel |
| PowerPoint | `.pptx`, `.ppsx`, `.pptm`, `.ppsm` | pełny | python-pptx | slajdy z numeracją, tabele, notatki prelegenta, metadane |
| PowerPoint 97-2003 z Office | `.ppt`, `.pps`, `.pot` | ograniczony | automatyzacja Microsoft PowerPoint | wymaga zainstalowanego Office, makra wyłączone, zachowuje podział na slajdy i notatki |
| PowerPoint 97-2003 bez Office | `.ppt`, `.pps`, `.pot` | eksperymentalny | własny czytnik OLE | sam tekst slajdów i notatek, bez przypisania do slajdów |
| Excel | `.xlsx`, `.xlsm` | pełny | openpyxl | arkusze, nagłówki kolumn, daty i liczby jako tekst |
| Excel 97-2003 | `.xls` | dobry | xlrd | tylko odczyt, formuły jako wartości |
| Dane rozdzielane | `.csv`, `.tsv` | pełny | biblioteka standardowa | wykrywanie separatora `;` `,` tabulator `|` i kodowania |
| Tekst | `.txt`, `.log`, `.md`, `.json`, `.xml`, `.ini`, `.cfg`, `.yaml`, `.yml` | pełny | biblioteka standardowa | podział na akapity, wykrywanie kodowania |
| Inne pliki tekstowe | dowolne rozszerzenie | pełny | biblioteka standardowa | kod źródłowy, skrypty i konfiguracja rozpoznawane po treści, niezależnie od rozszerzenia i typu MIME |
| HTML | `.html`, `.htm`, `.xhtml` | pełny | `html.parser` | skrypty i style pomijane, nagłówki wiązane z akapitami |
| RTF | `.rtf` | dobry | własny dekoder | strony kodowe cp1250 i cp1252, obrazy pomijane |
| Wiadomość e-mail | `.eml`, `.mht`, `.mhtml` | pełny | biblioteka standardowa | nagłówki, treść tekstowa lub HTML, załączniki |
| Wiadomość Outlook | `.msg` | dobry | własny czytnik OLE | właściwości MAPI, treść zwykła, HTML albo RTF, załączniki |
| Obrazy | `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`, `.bmp`, `.gif`, `.webp` | ograniczony | Pillow + OCR | wielostronicowy TIFF obsługiwany, metadane EXIF |

## Załączniki

Załącznik wiadomości e-mail jest indeksowany jako osobny dokument powiązany
z wiadomością nadrzędną. Wyszukiwanie znajdzie zarówno wiadomość, jak i sam
załącznik, a w wyniku widać, do której wiadomości należy.

Zagnieżdżona wiadomość przekazana dalej też jest załącznikiem. Głębokość
zagnieżdżenia dokumentów podrzędnych jest ograniczona do trzech poziomów,
żeby złośliwy plik (na przykład archiwum zawierające samo siebie) nie
zapętlił indeksowania.

Domyślne limity: 30 załączników na wiadomość i 100 MB łącznie. Przekroczenie
kończy się ostrzeżeniem zapisanym przy dokumencie, nie cichym pominięciem.

## Archiwa ZIP

Domyślnie zawartość archiwów nie jest rozpakowywana, a plik `.zip` ma status
`unsupported`. Po włączeniu opcji **Indeksuj zawartość archiwów ZIP** (ekran
Źródła i konfiguracja, sekcja Opcje indeksowania; w pliku konfiguracyjnym
`indexing.index_archives`) archiwum jest przetwarzane tak jak wiadomość
z załącznikami: każdy plik w środku trafia do indeksu jako osobny dokument
podrzędny, a samo archiwum dostaje przeszukiwalny spis nazw plików.

Limity: 200 wpisów i 200 MB rozpakowanej treści na archiwum. Wpisy
zaszyfrowane, przekraczające `max_file_size_mb` oraz wpisy o podejrzanym
stosunku kompresji (ochrona przed bombą dekompresyjną) są pomijane
z ostrzeżeniem przy dokumencie. Archiwa `.7z` i `.rar` pozostają
nieobsługiwane.

## Pliki celowo pomijane

| Rodzaj | Powód |
| --- | --- |
| pliki tymczasowe Office (`~$*`) | to nie są dokumenty |
| pliki większe niż `max_file_size_mb` | ochrona pamięci, domyślnie 512 MB |
| archiwa `.zip` bez włączonej opcji indeksowania archiwów oraz `.7z`, `.rar` | zawartość nie jest rozpakowywana |
| pliki wykonywalne i binarne | nie zawierają tekstu do wyszukania |
| pliki bez uprawnień odczytu | zapisywane jako błąd, nie pomijane po cichu |

Każdy pominięty plik trafia na listę w raporcie pokrycia wraz z powodem.

## Dokumenty zabezpieczone hasłem

PDF, DOCX, XLSX, PPTX, DOC i PPT z hasłem otwarcia kończą się statusem
`password_protected` i kodem `FD-3003`. Aplikacja nie próbuje łamać ani zgadywać
haseł. Taki dokument jest widoczny w raporcie pokrycia jako niewyszukiwalny.

## Pliki uszkodzone

Plik z poprawną sygnaturą, ale niepoprawną strukturą kończy się statusem
`corrupted` i kodem `FD-3002`. Błąd jest izolowany: pozostałe dokumenty
przetwarzają się normalnie.

## Kodowanie tekstu

Kodowanie rozpoznaje wspólny moduł
[`extractors/encoding.py`](../src/finddocs/extractors/encoding.py) w kolejności:
znacznik BOM, deklaracja w pliku (`<meta charset>`), ścisłe UTF-8, ocena jakości
wyniku dla pozostałych kandydatów.

Ocena jakości jest potrzebna, bo sama detekcja statystyczna zawodzi na krótkich
polskich plikach: bajty UTF-8 zdania z polskimi znakami potrafią zostać uznane
za koreańską stronę kodową, a plik iso-8859-2 za cp1250. Oba błędy są ciche,
bo dekodowanie się udaje, tylko wynik jest bezsensowny. Ocena premiuje litery
polskiego alfabetu, a karze znaki sterujące, pisma obce i symbole typowe dla
pomylonej strony kodowej.

Obsługiwane kodowania: UTF-8 (z BOM i bez), UTF-16 i UTF-32 (LE i BE),
cp1250, iso-8859-2, cp1252, latin-1.

## Format nieobsługiwany

Plik, dla którego nie ma parsera, kończy się statusem `unsupported`
i kodem `FD-3001`. Jest wymieniony w raporcie pokrycia. Dodanie parsera opisuje
sekcja „Rozszerzanie” w [architekturze](architektura.md).

## Sprawdzenie, co jest dostępne na tym komputerze

```bash
finddocs doctor
```

Wypisuje listę parserów z informacją, czy są dostępne, a jeśli nie, to dlaczego
(na przykład brak zainstalowanego Microsoft Office dla plików `.doc`).
