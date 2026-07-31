# ADR-002: SQLite FTS5 jako indeks pełnotekstowy

**Stan:** przyjęta
**Data:** lipiec 2026

## Kontekst

Potrzebujemy wyszukiwania pełnotekstowego, które daje **kompletny** zbiór
wyników i dokładną ich liczbę, bez ukrytego limitu. Musi działać w procesie
aplikacji, bez serwera i bez Javy. Musi obsłużyć zbiory rzędu dziesiątek
tysięcy dokumentów.

Osobno potrzebujemy magazynu metadanych dokumentów z transakcjami: aktualizacja
dokumentu ma być atomowa.

## Decyzja

SQLite w trybie WAL jako magazyn metadanych i fragmentów, oraz FTS5 w wariancie
**external content** jako indeks pełnotekstowy.

```sql
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    folded, norm,
    content='chunks', content_rowid='chunk_id',
    tokenize="unicode61 remove_diacritics 2 categories 'L* N* Co'"
)
```

Synchronizację zapewniają trzy wyzwalacze na tabeli `chunks`.

## Rozważane alternatywy

**Elasticsearch, OpenSearch, Solr.** Osobny serwer, Java, konfiguracja. Odpada
z powodu ADR-001.

**Whoosh.** Czysty Python, brak serwera, ale wolny na większych zbiorach
i projekt praktycznie nierozwijany.

**Tantivy przez `tantivy-py`.** Szybki i dobrze utrzymywany, ale byłby drugim
magazynem obok SQLite, który i tak jest nam potrzebny na metadane. Dwa magazyny
to dwa miejsca, w których transakcja może się rozjechać.

## Konsekwencje

Dobre:

* metadane i indeks w jednym pliku, więc kopia zapasowa jest trywialna;
* transakcyjność za darmo: usunięcie starych fragmentów i wstawienie nowych
  dzieje się w jednej transakcji;
* tryb external content nie duplikuje tekstu;
* WAL pozwala czytać w trakcie zapisu, więc wyszukiwanie działa podczas
  indeksowania.

Kosztowne:

* FTS5 musi być obecny w kompilacji SQLite. Aplikacja sprawdza to przy starcie
  i zgłasza `FD-5001`, gdy go brak;
* `bm25()` nie działa razem z `GROUP BY` ani z funkcjami okna, a zwykłe
  podzapytanie zostaje spłaszczone przez optymalizator. Zapytania muszą używać
  `WITH ... AS MATERIALIZED`. To pułapka, w którą wpadliśmy raz i którą
  opisujemy w [architekturze](../architektura.md);
* jeden plik oznacza jednego pisarza. Nie da się indeksować z dwóch procesów.
