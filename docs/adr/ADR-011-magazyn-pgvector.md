# ADR-011: Wymienny magazyn wektorów i opcjonalny pgvector

**Stan:** przyjęta
**Data:** sierpień 2026

## Kontekst

FAISS trzyma wektory w pliku w profilu użytkownika (ADR-004). To wystarcza
na pojedynczej stacji, ale nie odpowiada na trzy potrzeby zgłaszane przy
wdrożeniach: trwałość indeksu semantycznego niezależnie od maszyny, objęcie
wektorów standardową kopią zapasową bazy organizacji oraz zbiory, przy
których plik w profilu robi się nieporęczny.

Jednocześnie zasada nadrzędna się nie zmienia: domyślnie wszystko działa
lokalnie, a publiczne usługi chmurowe pozostają zabronione (spec 3.1.2).

## Decyzja

Magazyn wektorów zostaje schowany za protokołem `VectorIndex`
(`indexing/base.py`) z dwiema implementacjami:

* `VectorStore` (FAISS, plik lokalny), bez zmian, nadal domyślny;
* `PgVectorStore` (`indexing/pgvector.py`), tabela w PostgreSQL
  z rozszerzeniem pgvector i indeksem HNSW `vector_ip_ops` o parametrach
  zgodnych z FAISS.

Zasady dla wariantu pgvector:

* do bazy idą wyłącznie pary (chunk_id, wektor) i metadane zgodności;
  tekst nigdy;
* osobna kategoria polityki sieciowej `vector_db`, dozwolony dokładnie
  jeden host z konfiguracji; poza localhost wymagany TLS (sslmode co
  najmniej `require`);
* hasło w magazynie poświadczeń (keyring/DPAPI), nie w pliku konfiguracji;
* tożsamość magazynu (backend, host, port, baza, schemat, tabela) wchodzi
  do skrótu zgodności wektorów, ale tylko przy backendzie innym niż faiss,
  żeby istniejące konfiguracje nie wymagały przebudowy po aktualizacji;
* sterownik `psycopg` jest dodatkiem instalacyjnym `finddocs[pgvector]`
  importowanym dopiero po włączeniu magazynu;
* SQLite pozostaje źródłem prawdy; niedostępna baza degraduje aplikację
  do trybu dokładnego (dokumenty `partial`, jawna notatka w wynikach),
  zamiast ją zatrzymywać;
* usunięcia w pgvector są natychmiastowe, więc nagrobki i kompaktacja
  z ADR-004 tego wariantu nie dotyczą.

## Rozważane alternatywy

**Wyłącznie FAISS, bez alternatyw.** Nie odpowiada na potrzebę trwałości
i kopii zapasowych po stronie organizacji.

**Dedykowane serwery wektorowe (Qdrant, Milvus, Weaviate).** Osobna usługa
do utrzymania i osobny model uprawnień. PostgreSQL już istnieje w typowej
organizacji, ma działy utrzymania, kopie zapasowe i audyt.

**Przeniesienie całego indeksu (też FTS) do PostgreSQL.** Zmieniłoby
architekturę aplikacji desktopowej (ADR-001, ADR-002) i uzależniło
wyszukiwanie dokładne od sieci. Wektory są jedyną częścią, której ranking
jest z definicji przybliżony, więc tylko one mogą bezpiecznie mieszkać
poza maszyną.

**Synchronizacja pliku FAISS na zasób sieciowy.** Brak transakcyjności,
łatwe uszkodzenie pliku przy dwóch stacjach, brak kontroli dostępu.

## Konsekwencje

Dobre:

* organizacja może objąć wektory standardowym utrzymaniem bazy;
* warstwy wyżej widzą jeden protokół, więc wyszukiwanie, zapis
  i konserwacja nie rozróżniają magazynów;
* polityka sieciowa pozostaje zamknięta: nowa kategoria z jednym hostem.

Kosztowne:

* pojawia się zależność opcjonalna i drugi wariant zachowań do testowania;
  testy jednostkowe pokrywają magazyn na udawanym sterowniku, a zestaw
  integracyjny (`tests/integration/test_pgvector_real.py`) został wykonany
  na PostgreSQL 17.10 z pgvector 0.8.6 w Dockerze, łącznie z pełnym potokiem
  na modelu MMLW, TLS (`require`, TLSv1.3), scenariuszami awarii i braku
  uprawnień; tryby `verify-ca` i `verify-full` z firmowym urzędem
  certyfikacji wymagają próby przy wdrożeniu;
* zapytanie semantyczne w trybie pgvector wymaga działającej sieci; awaria
  bazy oznacza czasową utratę trybów semantycznych (świadomie przyjęte,
  z łagodną degradacją).
