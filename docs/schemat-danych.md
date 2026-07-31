# Schemat danych

Indeks to jeden plik SQLite `index\finddocs.db` w trybie WAL oraz dwa pliki
indeksu wektorowego obok niego. Definicja schematu:
[`src/finddocs/indexing/schema.py`](../src/finddocs/indexing/schema.py).

Aktualna wersja schematu: **1**.

## Ustawienia bazy

| Pragma | Wartość | Powód |
| --- | --- | --- |
| `journal_mode` | `WAL` | odczyt nie blokuje zapisu, indeksowanie nie zatrzymuje wyszukiwania |
| `synchronous` | `NORMAL` | kompromis między szybkością a odpornością przy WAL |
| `foreign_keys` | `ON` | kasowanie dokumentu usuwa jego fragmenty |
| `busy_timeout` | 10 s | wyszukiwanie w trakcie zapisu czeka, zamiast zgłaszać błąd |

## Tabele

### `index_meta`

Para klucz i wartość. Tu mieszka wszystko, co decyduje o zgodności indeksu.

| Klucz | Znaczenie |
| --- | --- |
| `schema_version` | wersja schematu bazy |
| `app_version` | wersja aplikacji, która utworzyła indeks |
| `created_at` | data utworzenia indeksu |
| `index_compat_hash` | skrót konfiguracji wpływającej na część pełnotekstową |
| `vector_compat_hash` | skrót konfiguracji wpływającej na część wektorową |
| `model_key` | nazwa modelu embeddingów |
| `model_version` | wersja modelu |
| `embedding_dim` | wymiar wektora |
| `normalization_version` | wersja reguł normalizacji tekstu |
| `chunking_version` | wersja reguł fragmentacji |
| `vector_store_version` | wersja formatu magazynu wektorów |
| `last_scan_at` | data ostatniego skanowania |
| `last_full_index_at` | data ostatniego pełnego przeindeksowania |
| `last_scan_id` | numer ostatniego skanowania |

Przy każdym starcie aplikacja porównuje `index_compat_hash` i `vector_compat_hash`
z wartościami wyliczonymi z bieżącej konfiguracji. Rozbieżność oznacza indeks
niezgodny: aplikacja mówi o tym wprost i nie udaje, że wyniki są kompletne.

### `sources`

Jedno źródło dokumentów.

| Kolumna | Opis |
| --- | --- |
| `source_id` | identyfikator nadany przy dodaniu |
| `kind` | `local_dir` albo `sharepoint` |
| `label` | nazwa widoczna w interfejsie |
| `location` | ścieżka albo adres witryny |
| `enabled` | czy źródło jest brane pod uwagę przy skanowaniu |
| `last_scan_at`, `last_full_index_at` | daty |
| `last_scan_id` | numer ostatniego skanowania tego źródła |
| `delta_token` | znacznik zmian przyrostowych, gdy źródło je udostępnia |

### `documents`

Jeden wiersz na dokument. Załącznik wiadomości e-mail jest osobnym dokumentem
wskazującym rodzica przez `attachment_of`.

Grupy kolumn:

**Tożsamość i położenie.** `doc_id`, `source_id`, `external_id` (unikalne
w obrębie źródła), `name`, `logical_path`, `extension`, `mime_type`, `size`,
`web_url`, `parent_url`, `local_path`, `library`.

**Kolumny złożone.** `name_folded` i `path_folded` przechowują nazwę i ścieżkę
po złożeniu znaków, żeby filtr lokalizacji działał bez względu na ogonki
i wielkość liter.

**Czas.** `created_at`, `modified_at`, `indexed_at`.

**Stan.** `status` przyjmuje wartości:

| Status | Znaczenie | Wyszukiwalny |
| --- | --- | --- |
| `pending` | wykryty, jeszcze nieprzetworzony | nie |
| `indexed` | zaindeksowany w całości | tak |
| `partial` | tekst zaindeksowany, brak wektorów | tak, tryb dokładny |
| `empty` | plik nie zawiera tekstu | nie |
| `unsupported` | format nieobsługiwany | nie |
| `corrupted` | plik uszkodzony | nie |
| `password_protected` | zabezpieczony hasłem | nie |
| `download_failed` | nie udało się pobrać ze źródła | nie |
| `error` | błąd odczytu | nie |
| `skipped` | pominięty świadomie (filtr, rozmiar) | nie |
| `deleted` | zniknął ze źródła | nie |

Wyszukiwalne są wyłącznie `indexed` i `partial`. Wszystkie pozostałe statusy
trafiają na listę dokumentów niewyszukiwalnych w raporcie pokrycia.

**Wykrywanie zmian.** `change_key` (etag, skrót treści albo para data i rozmiar),
`content_sha256`, `etag`, `seen_scan_id`. Dokument, którego `change_key` się nie
zmienił, jest pomijany przy kolejnym skanowaniu. Dotyczy to również dokumentów
zakończonych błędem: nieczytelny plik nie jest próbowany w kółko.

**Pochodzenie tekstu.** `used_ocr`, `ocr_pages`, `ocr_confidence`, `text_origin`
(`native`, `ocr`, `mixed`), `parser_name`, `support_level`, `page_count`.

**Diagnostyka.** `error_code`, `error_message`, `attempt_count`, `last_attempt_at`.

**Wersjonowanie.** `normalization_version`, `chunking_version`, `model_key`,
`fts_indexed`, `vector_indexed`, `chunk_count`.

### `chunks`

Fragment dokumentu, jednostka indeksowania i prezentacji.

| Kolumna | Opis |
| --- | --- |
| `chunk_id` | klucz główny, jednocześnie `rowid` w indeksie FTS |
| `doc_id` | dokument nadrzędny, kasowanie kaskadowe |
| `ordinal` | numer fragmentu w dokumencie |
| `text` | tekst w oryginalnej pisowni, używany do wyświetlania |
| `folded` | tekst po złożeniu znaków, kolumna indeksowana |
| `norm` | tokeny znormalizowane (daty, kwoty, numery), kolumna indeksowana |
| `origin` | `native` albo `ocr` |
| `ocr_confidence` | pewność OCR dla tego fragmentu |
| `page`, `sheet`, `row_start`, `row_end` | umiejscowienie w dokumencie |
| `heading` | nagłówek, pod którym fragment wystąpił |
| `section_kind` | `text`, `table`, `email_header`, `attachment_note` |
| `char_start`, `char_end` | zakres w tekście dokumentu |
| `has_vector` | czy fragment ma wektor w indeksie wektorowym |

Rozdzielenie `text`, `folded` i `norm` jest celowe. Wyszukujemy po `folded`
i `norm`, a pokazujemy `text`, więc użytkownik widzi dokument tak, jak został
napisany, a jednocześnie znajduje go pisząc bez ogonków.

### `chunks_fts`

Wirtualna tabela FTS5 w trybie **external content**:

```sql
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    folded,
    norm,
    content='chunks',
    content_rowid='chunk_id',
    tokenize="unicode61 remove_diacritics 2 categories 'L* N* Co'"
)
```

Tryb external content nie duplikuje tekstu: indeks przechowuje tylko strukturę
wyszukiwania, a treść czyta z tabeli `chunks`. Synchronizację zapewniają trzy
wyzwalacze: `chunks_ai`, `chunks_ad` i `chunks_au`.

Tokenizator `remove_diacritics 2` nie składa polskiego `ł`, bo Unicode traktuje
je jako osobną literę, a nie literę ze znakiem diakrytycznym. Dlatego składanie
znaków robi aplikacja, a nie SQLite, i dlatego istnieje kolumna `folded`.

Kolumna `norm` zawiera tokeny czysto alfanumeryczne, bo tokenizator FTS5 dzieli
tekst na znakach interpunkcyjnych:

| Wzorzec | Przykład | Token |
| --- | --- | --- |
| data dzienna | 24.07.2015 | `dat20150724` |
| miesiąc | lipiec 2015 | `mon201507` |
| rok | 2015 | `yea2015` |
| ciąg cyfr | 384675 | `num384675` |
| numer rachunku | 00 1234 ... 1234 | `acc00123456789012345678901234` |
| kwota | 1 234,56 | `kwo123456` |
| identyfikator | FV/2015/07/123 | `idf fv2015 07123` |
| NIP, REGON, PESEL | 123-456-32-18 | `nip1234563218` |

Dzięki temu trzy zapisy tego samego numeru rachunku dają jeden token, a więc
i jeden zbiór wyników.

### `jobs`

Zadania indeksowania. `state` przyjmuje `pending`, `running`, `paused`,
`completed`, `failed`, `cancelled`, `interrupted`. Kolumna `progress`
przechowuje migawkę liczników w formacie JSON, dzięki czemu po restarcie
aplikacji widać, na czym zadanie stanęło.

### `scan_checkpoints`

Punkt kontrolny skanowania: kursor źródła, liczniki i znacznik ukończenia
etapu wykrywania. Zapisywany co `checkpoint_every` dokumentów. Pozwala wznowić
przerwane zadanie bez powtarzania całej pracy.

### `error_log`

Historia błędów: data, źródło, dokument, etap, kod błędu, klasa wyjątku,
komunikat i informacja, czy błąd nadaje się do ponowienia. Zasila raport
pokrycia i ekran **Pokaż błędy**. Tabela nie zawiera treści dokumentów.

### `ocr_cache`

Wynik OCR zapisany pod kluczem `(content_sha256, engine, engine_version, dpi)`.
Ponowne indeksowanie tego samego pliku nie uruchamia OCR jeszcze raz. Na zbiorze
demonstracyjnym daje to różnicę rzędu ośmiokrotnej: 14,8 s przy pierwszym
przebiegu i 1,7 s przy pełnym przeindeksowaniu z gotową pamięcią podręczną.

### `scan_stats`

Statystyka jednego skanowania jednego źródła. Kolumna `complete` mówi, czy
skanowanie objęło całe źródło. Raport pokrycia nie deklaruje kompletności,
jeżeli którekolwiek skanowanie zostało przerwane.

## Indeks wektorowy

Poza bazą, w katalogu `index`:

| Plik | Zawartość |
| --- | --- |
| `vectors.faiss` | indeks FAISS `IndexIDMap2` nad `IndexHNSWFlat` |
| `vectors.json` | metadane: model, wymiar, skrót zgodności, lista nagrobków |

Wektory są znormalizowane L2, a metryką jest iloczyn skalarny, co dla wektorów
jednostkowych odpowiada podobieństwu kosinusowemu. Identyfikatorem wektora jest
`chunk_id`, więc nie ma osobnej tablicy tłumaczącej.

HNSW nie obsługuje `remove_ids`. Usunięcia zapisujemy jako nagrobki w metadanych
i odfiltrowujemy przy wyszukiwaniu. `finddocs maintenance compact` przebudowuje
indeks bez nagrobków.

Zapis jest atomowy: plik tymczasowy, `fsync`, zamiana nazwy. Przerwanie zapisu
nie zostawia uszkodzonego indeksu.

## Migracje

Każda zmiana schematu to nowa migracja w
[`src/finddocs/indexing/migrations.py`](../src/finddocs/indexing/migrations.py)
oraz podniesienie `SCHEMA_VERSION` w `schema.py`. Migracje wykonują się
automatycznie przy pierwszym otwarciu bazy przez nowszą wersję aplikacji,
w jednej transakcji, z wpisem do tabeli `schema_migrations`.

Baza nowsza niż aplikacja nie jest otwierana. Aplikacja zgłasza wtedy błąd
`FD-5001` z prośbą o aktualizację programu, zamiast ryzykować uszkodzenie danych.

## Wersje wpływające na zgodność

| Stała | Plik | Co unieważnia |
| --- | --- | --- |
| `SCHEMA_VERSION` | `indexing/schema.py` | strukturę bazy, wymaga migracji |
| `NORMALIZATION_VERSION` | `version.py` | kolumny `folded` i `norm`, wymaga przebudowy |
| `CHUNKING_VERSION` | `version.py` | podział na fragmenty, wymaga przebudowy |
| `VECTOR_STORE_VERSION` | `version.py` | format plików FAISS |
| `model_key`, `quantized`, `max_sequence_length` | konfiguracja | wektory, wymaga przebudowy części semantycznej |

Zmiana normalizacji, fragmentacji albo modelu bez podniesienia odpowiedniej
stałej sprawiłaby, że indeks byłby niespójny i nikt by o tym nie wiedział.
To najgroźniejszy sposób zepsucia tej aplikacji.

## Sprawdzanie spójności

```bash
finddocs maintenance check
```

Kontroluje: `PRAGMA integrity_check`, zgodność liczby fragmentów z licznikiem
w dokumencie, obecność fragmentów bez dokumentu, zgodność liczby wektorów
z liczbą fragmentów oznaczonych `has_vector`, obecność nagrobków oraz zgodność
skrótów w `index_meta`. Wynik trafia też na ekran **Diagnostyka**.
