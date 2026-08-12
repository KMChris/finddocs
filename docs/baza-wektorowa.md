# Zewnętrzna baza wektorowa (pgvector)

Dokument dla administratora. Opisuje przechowywanie wektorów fragmentów
w bazie PostgreSQL z rozszerzeniem pgvector zamiast w lokalnym pliku FAISS.

Ustawienia domyślne pozostają bez zmian: wektory leżą w pliku
`vectors.faiss` w katalogu danych użytkownika, a aplikacja nie nawiązuje
żadnych połączeń. Magazyn pgvector trzeba włączyć świadomie.

## Kiedy to ma sens

* Indeks semantyczny ma być trwały niezależnie od stacji roboczej,
  na przykład przy profilach przenośnych albo maszynach wirtualnych.
* Organizacja utrzymuje serwer PostgreSQL i chce mieć wektory objęte
  standardową kopią zapasową bazy.
* Zbiór jest na tyle duży, że plik FAISS w profilu użytkownika przestaje
  być wygodny.

Magazyn pgvector nie przyspiesza liczenia embeddingów. Embeddingi nadal
liczy model lokalny (CPU albo GPU) albo zdalne API, zgodnie z konfiguracją
opisaną w dokumencie [embeddingi na GPU i zdalne API](embeddingi-gpu-api.md).

## Co trafia do bazy, a co nie

Do bazy trafiają wyłącznie:

* identyfikatory fragmentów (liczby całkowite),
* wektory liczbowe o wymiarze modelu,
* metadane zgodności indeksu (wersja formatu, nazwa modelu, wymiar,
  skrót konfiguracji).

Do bazy nie trafia nigdy: treść dokumentów, treść fragmentów, zapytania,
nazwy plików ani żadne inne metadane. Indeks pełnotekstowy, metadane
dokumentów i cała reszta indeksu pozostają w lokalnym SQLite. Z samych
wektorów nie da się odtworzyć tekstu, ale ich ranking podobieństwa zdradza
powiązania między fragmentami, więc bazę należy traktować jako zasób
wewnętrzny organizacji, a nie zasób publiczny.

## Zasady bezpieczeństwa

* Połączenia przechodzą przez politykę sieciową aplikacji w osobnej
  kategorii `vector_db`. Dozwolony jest dokładnie jeden host: ten podany
  w konfiguracji. Kategoria włącza się wyłącznie po ustawieniu
  `vector_store.backend` na `pgvector`.
* Poza `localhost` wymagany jest TLS: `sslmode` musi mieć wartość
  `require`, `verify-ca` albo `verify-full`. Wartość `disable` działa
  tylko dla połączeń lokalnych.
* Hasło użytkownika bazy nie jest zapisywane w pliku konfiguracyjnym.
  Trafia do magazynu poświadczeń (Menedżer poświadczeń Windows albo DPAPI)
  i jest odczytywane dopiero przy nawiązywaniu połączenia.
* Nazwy schematu i tabeli są walidowane ścisłym wzorcem (małe litery ASCII,
  cyfry, podkreślenia), a wszystkie wartości idą jako parametry zapytań.

## Wymagania po stronie serwera

* PostgreSQL z zainstalowanym rozszerzeniem [pgvector](https://github.com/pgvector/pgvector)
  w wersji z indeksem HNSW (0.5.0 lub nowszej).
* Konto z prawem tworzenia tabel we wskazanym schemacie. Jeżeli rozszerzenia
  nie ma, aplikacja spróbuje wykonać `CREATE EXTENSION IF NOT EXISTS vector`;
  zwykle wymaga to uprawnień administratora bazy, więc lepiej przygotować
  rozszerzenie zawczasu.
* Każdy indeks FindDocs wymaga własnej tabeli. Dwie stacje wskazujące tę samą
  tabelę nadpisywałyby swoje wektory, bo identyfikatory fragmentów są lokalne.
  Przy wielu użytkownikach na jednym serwerze należy rozdzielić tabele
  (np. `wektory_jkowalski`) albo schematy.

Aplikacja tworzy w bazie dwie tabele: `<tabela>` z parami
(`chunk_id bigint`, `embedding vector(wymiar)`) oraz `<tabela>__meta`
z metadanymi zgodności, a także indeks HNSW z metryką iloczynu skalarnego
(`vector_ip_ops`), o parametrach zgodnych z lokalnym FAISS (m = 32,
ef_construction = 80).

## Instalacja sterownika

Sterownik PostgreSQL jest zależnością opcjonalną:

```bash
pip install "finddocs[pgvector]"
```

Dodatek instaluje pakiet `psycopg` z wbudowaną biblioteką libpq. Bez niego
włączenie magazynu pgvector kończy się czytelnym komunikatem, a aplikacja
dalej działa w trybie dokładnym.

## Konfiguracja

W GUI: ekran Źródła i konfiguracja, przycisk `Ustawienia...` przy modelu,
sekcja `Magazyn wektorów`. Formularz pozwala też zapisać hasło w magazynie
poświadczeń i przetestować połączenie przed zapisaniem ustawień.

Odpowiednia sekcja `settings.json`:

```json
"vector_store": {
  "backend": "pgvector",
  "pgvector_host": "baza.firma.local",
  "pgvector_port": 5432,
  "pgvector_database": "wyszukiwarka",
  "pgvector_user": "finddocs",
  "pgvector_schema": "public",
  "pgvector_table": "finddocs_vectors",
  "pgvector_sslmode": "require",
  "pgvector_connect_timeout_seconds": 10.0,
  "pgvector_statement_timeout_seconds": 60.0
}
```

`backend` przyjmuje `faiss` (domyślne) albo `pgvector`. Pola `pgvector_*`
są ignorowane przy magazynie `faiss`, więc można je przygotować zawczasu.

## Zmiana magazynu a przebudowa indeksu

Tożsamość magazynu (backend, host, port, baza, schemat, tabela) wchodzi do
skrótu zgodności części wektorowej. Przełączenie magazynu albo wskazanie
innej tabeli oznacza inny, zwykle pusty zbiór wektorów, więc aplikacja
zgłosi potrzebę przebudowy części semantycznej:

```bash
finddocs maintenance rebuild --vectors-only
finddocs index
```

Do czasu przebudowy wyszukiwanie dokładne działa bez zmian. Zmiana
użytkownika, hasła, `sslmode` ani limitów czasu nie unieważnia indeksu.

## Zachowanie przy niedostępnej bazie

Aplikacja nie przerywa pracy, gdy baza przestaje odpowiadać:

* przy starcie: wyszukiwanie semantyczne zostaje wyłączone z komunikatem
  w oknie stanu, tryb dokładny działa normalnie;
* podczas indeksowania: dokument jest zapisywany bez wektorów (status
  `zaindeksowany częściowo`), a brakujące wektory uzupełnia kolejne
  skanowanie po powrocie bazy;
* podczas wyszukiwania: tryb hybrydowy zwraca wyniki wyłącznie z części
  dokładnej i dokleja jawną informację o niedostępności bazy.

Po powrocie serwera połączenie jest nawiązywane od nowa automatycznie,
przy pierwszej kolejnej operacji.

## Konserwacja i diagnostyka

* Usunięcia wektorów wykonują się od razu (`DELETE`), więc kompaktacja
  znana z FAISS nie jest potrzebna; polecenie `finddocs maintenance compact`
  działa jako pełna resynchronizacja tabeli z lokalnym SQLite.
* `finddocs maintenance check` porównuje liczbę wektorów w bazie z liczbą
  fragmentów oznaczonych jako zwektoryzowane i zgłasza rozjazd jako
  ostrzeżenie.
* Kopia indeksu (`finddocs maintenance backup`) obejmuje wyłącznie pliki
  lokalne. Za kopię zapasową tabel w PostgreSQL odpowiada administrator bazy.
* Ekran Diagnostyka pokazuje kategorię `vector_db` w polityce połączeń
  wraz z dozwolonym hostem.

## Ograniczenia

* Wyniki wyszukiwania semantycznego zależą od parametru `hnsw.ef_search`,
  ustawianego na czas zapytania; ranking jest przybliżony tak samo jak
  w FAISS.

## Stan weryfikacji

Implementacja została sprawdzona na prawdziwym serwerze PostgreSQL 17.10
z pgvector 0.8.6 w kontenerze Docker (`pgvector/pgvector:pg17`):

* pełny cykl magazynu: tworzenie tabel i rozszerzenia, zapis, nadpisanie,
  usuwanie, odtworzenie wektora bez straty precyzji float32, wsady ponad
  500 wierszy, zapytania głębsze niż domyślny `ef_search`, metadane
  zgodności (odrzucenie innego skrótu i wymiaru);
* pełny potok z prawdziwym modelem MMLW: indeksowanie dokumentów
  z wektorami w bazie i poprawny ranking wyszukiwania semantycznego;
* TLS: `sslmode require` z sesją TLSv1.3 potwierdzoną w `pg_stat_ssl`;
* polityka sieciowa: host spoza listy zablokowany, host nielokalny działa
  wyłącznie po włączeniu kategorii `vector_db` i z TLS;
* awaria serwera w trakcie pracy: zapis zgłasza błąd `FD-5004`, dokumenty
  zostają w stanie częściowym, a po powrocie serwera połączenie odtwarza
  się automatycznie;
* konto bez uprawnień do `CREATE EXTENSION` dostaje czytelny komunikat.

Testy: `tests/integration/test_pgvector_real.py` (domyślnie pomijane;
opis uruchomienia kontenera i zmiennych środowiskowych w docstringu pliku).

Nie testowano trybów `verify-ca` i `verify-full` z firmowym urzędem
certyfikacji ani serwera produkcyjnego organizacji. Przed wdrożeniem wykonaj
próbę połączenia przyciskiem `Przetestuj połączenie` i zaindeksuj zbiór
próbny.
