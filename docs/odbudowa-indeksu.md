# Odbudowa i konserwacja indeksu

Dokument opisuje kopie zapasowe, przywracanie, kompaktację i przebudowę.
Wszystkie operacje działają na katalogu `%LOCALAPPDATA%\FindDocs\index`.

## Kiedy indeks trzeba przebudować

| Zmiana | Zakres przebudowy |
| --- | --- |
| inny model embeddingów (`model_key`) | tylko wektory |
| przełączenie `quantized` albo `max_sequence_length` | tylko wektory |
| wzbogacenie o nazwę pliku i ścieżkę (`enrich_context`) | tylko wektory |
| nowa wersja normalizacji tekstu | całość |
| nowa wersja reguł fragmentacji | całość |
| zmiana ustawień fragmentacji w konfiguracji | całość |
| uszkodzenie pliku bazy | całość, po nieudanym przywróceniu kopii |

Aplikacja sama wykrywa niezgodność. Przy starcie porównuje skróty
`index_compat_hash` i `vector_compat_hash` zapisane w indeksie z wartościami
wyliczonymi z bieżącej konfiguracji. Rozbieżność kończy się komunikatem
**Indeks wymaga przebudowy** i kodem `FD-5001`.

Do czasu przebudowy **wyszukiwanie dokładne działa normalnie**. Aplikacja nie
używa niezgodnej części indeksu i nie udaje, że wyniki są kompletne.

## Kopia zapasowa

```bash
finddocs maintenance backup
```

Kopia trafia do `%LOCALAPPDATA%\FindDocs\backup\index-RRRRMMDD-GGMMSS`.
Przed skopiowaniem plików aplikacja domyka bazę, żeby dziennik WAL był
zapisany, i sprawdza, czy jest dość wolnego miejsca. Przy jego braku kończy
pracę kodem `FD-1002` zamiast tworzyć niepełną kopię.

Lista kopii:

```bash
finddocs maintenance list-backups
```

Kopie nie są usuwane automatycznie. Stare katalogi kasuje się ręcznie.

**Wykonaj kopię przed każdą operacją z tego dokumentu.** Kopia indeksu
zawiera treść dokumentów, więc przechowuj ją tam, gdzie same dokumenty.

## Przywracanie kopii

```bash
finddocs maintenance restore --name index-20260731-183000
```

Bieżący indeks nie jest kasowany: trafia do
`backup\przed-przywroceniem-RRRRMMDD-GGMMSS`. Gdyby przywrócona kopia okazała
się gorsza, można wrócić do stanu sprzed operacji.

Aplikacja musi być zamknięta w trakcie przywracania.

## Kompaktacja

```bash
finddocs maintenance compact
```

Co robi:

* buduje indeks wektorowy od nowa, pomijając nagrobki po usuniętych fragmentach;
* wykonuje `VACUUM` i `PRAGMA optimize` na bazie SQLite;
* porządkuje pamięć podręczną OCR.

Kompaktacja jest potrzebna, bo FAISS HNSW nie obsługuje usuwania wektorów.
Skasowany dokument zostawia po sobie nagrobek: wektor fizycznie zostaje
w pliku, ale jest pomijany przy wyszukiwaniu. Po wielu cyklach indeksowania
nagrobki zajmują miejsce i spowalniają wyszukiwanie.

Kiedy uruchamiać: raz w miesiącu albo gdy `finddocs maintenance check` pokaże
dużą liczbę nagrobków w stosunku do liczby wektorów.

Operacja wymaga miejsca na tymczasową kopię indeksu wektorowego.

## Przebudowa

Przebudowa nie kasuje indeksu. Oznacza dokumenty do ponownego przetworzenia,
a właściwą pracę wykonuje zwykłe indeksowanie:

```bash
finddocs maintenance backup
finddocs maintenance rebuild
finddocs index
```

Tylko część semantyczna:

```bash
finddocs maintenance rebuild --vectors-only
finddocs index
```

`--vectors-only` zostawia indeks pełnotekstowy nietknięty i policzy od nowa
wyłącznie wektory. Jest to znacznie szybsze: dokumenty nie są ponownie
pobierane ani parsowane, a OCR nie rusza z miejsca.

**Wyszukiwanie dokładne działa przez cały czas przebudowy.** Stary indeks
pełnotekstowy nie jest kasowany przed zbudowaniem nowego.

W interfejsie ta sama operacja kryje się pod przyciskiem **Skanuj źródła**
na ekranie **Indeksowanie**.

## Przebudowa od zera

Gdy indeks jest uszkodzony na tyle, że nie da się go otworzyć:

1. Zamknij aplikację.
2. Wykonaj kopię katalogu `index` (nawet uszkodzonego, na wszelki wypadek).
3. Usuń pliki z katalogu `index`.
4. Uruchom aplikację. Powstanie pusty indeks z aktualnym schematem.
5. Uruchom indeksowanie.

Konfiguracja i źródła nie zostaną utracone: leżą w katalogu `config`,
a nie w indeksie.

Czas pełnego indeksowania zależy głównie od liczby skanów wymagających OCR.
Pamięć podręczna OCR jest częścią bazy, więc usunięcie indeksu kasuje ją także.
Jeżeli zależy Ci na jej zachowaniu, przywróć kopię zamiast budować od zera.

## Sprawdzanie spójności

```bash
finddocs maintenance check
```

Kontroluje:

| Kontrola | Co wykrywa |
| --- | --- |
| `PRAGMA integrity_check` | uszkodzenie pliku bazy |
| fragmenty bez dokumentu | niekompletne kasowanie |
| licznik `chunk_count` | rozjazd między dokumentem a fragmentami |
| liczba wektorów | rozjazd między FAISS a kolumną `has_vector` |
| liczba nagrobków | potrzebę kompaktacji |
| skróty w `index_meta` | niezgodność konfiguracji |

Kod wyjścia zero oznacza indeks zdrowy. Wynik widać też na ekranie
**Diagnostyka**, zakładka **Spójność**.

## Bezpieczeństwo operacji

**Aktualizacja dokumentu jest atomowa.** Usunięcie starych fragmentów
i wstawienie nowych dzieje się w jednej transakcji SQLite. Przerwanie w połowie
zostawia dokument w stanie sprzed operacji, a nie w połowie zmieniony.

**Zapis indeksu wektorowego jest atomowy.** Plik tymczasowy, `fsync`,
zamiana nazwy. Przerwanie zapisu nie zostawia uszkodzonego pliku.

**Nowy indeks nie kasuje działającego.** Dopóki na dysku jest miejsce,
przebudowa buduje nową część obok starej.

**Brak miejsca przerywa pracę kontrolowanie.** Poniżej
`indexing.min_free_disk_bytes` zadanie kończy się kodem `FD-1002`, a indeks
pozostaje spójny.

**Przestrzeń tymczasowa jest sprzątana.** Po zakończeniu zadania, także po
błędzie, katalog `temp` jest czyszczony.

## Kopie na potrzeby migracji na inny komputer

Katalog danych jest przenośny z jednym wyjątkiem: token SharePoint jest
związany z kontem Windows i nie zadziała po przeniesieniu. Wystarczy zalogować
się ponownie.

1. Zamknij aplikację na obu komputerach.
2. Skopiuj `%LOCALAPPDATA%\FindDocs\config` i `%LOCALAPPDATA%\FindDocs\index`.
3. Uruchom aplikację na nowym komputerze.
4. Dla źródeł SharePoint naciśnij **Testuj połączenie** i zaloguj się.

Ścieżki lokalne muszą być takie same albo trzeba je poprawić w konfiguracji
źródeł, inaczej dokumenty zostaną uznane za usunięte przy najbliższym
skanowaniu.
