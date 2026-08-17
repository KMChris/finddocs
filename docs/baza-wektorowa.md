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

* PostgreSQL z zainstalowanym rozszerzeniem [pgvector](https://github.com/pgvector/pgvector).
* Konto z prawem tworzenia tabel we wskazanym schemacie. Jeżeli rozszerzenia
  nie ma, aplikacja spróbuje wykonać `CREATE EXTENSION IF NOT EXISTS vector`;
  zwykle wymaga to uprawnień administratora bazy, więc lepiej przygotować
  rozszerzenie zawczasu.
* Każdy indeks FindDocs wymaga własnej tabeli. Dwie stacje wskazujące tę samą
  tabelę nadpisywałyby swoje wektory, bo identyfikatory fragmentów są lokalne.
  Przy wielu użytkownikach na jednym serwerze należy rozdzielić tabele
  (np. `wektory_jkowalski`) albo schematy.
* pgvector w wersji **0.7.0 lub nowszej**, bo kolumna ma typ `halfvec`.
  Starsze rozszerzenie kończy się czytelnym błędem przy otwieraniu indeksu.
* Model musi tworzyć wektory o wymiarze **nie większym niż 4000**. Tyle
  przyjmuje indeks HNSW dla typu `halfvec` (dla typu `vector` granica wynosi
  2000, dlatego aplikacja go nie używa). Zmierzone na pgvector 0.8.6:
  `halfvec(4000)` przechodzi, `halfvec(4096)` kończy się błędem serwera
  `column cannot have more than 4000 dimensions for hnsw index`.
  Model o większym wymiarze wymaga albo magazynu FAISS, który nie ma tego
  ograniczenia, albo skrócenia wektora po stronie dostawcy embeddingów
  (opcja **Żądaj skrócenia wektora**, opisana w
  [embeddingi na GPU i zdalne API](embeddingi-gpu-api.md)).

Aplikacja tworzy w bazie dwie tabele: `<tabela>` z parami
(`chunk_id bigint`, `embedding halfvec(wymiar)`) oraz `<tabela>__meta`
z metadanymi zgodności, a także indeks HNSW z metryką iloczynu skalarnego
(`halfvec_ip_ops`), o parametrach zgodnych z lokalnym FAISS (m = 32,
ef_construction = 80).

### Precyzja połowiczna

Kolumna ma typ `halfvec`, czyli float16. Powody są dwa: indeks HNSW przyjmuje
wtedy do 4000 wymiarów zamiast 2000, a tabela zajmuje połowę miejsca. Wektory
są znormalizowane L2, więc zakres float16 jest dla nich z zapasem wystarczający.

Koszt jakości jest pomijalny. Pomiar na polskim zbiorze dokumentów
korporacyjnych (20 dokumentów, 10 zapytań, model Qwen3-Embedding-8B),
gdzie punktem odniesienia jest float32:

| Wariant | Zgodność top-1 | top-3 | top-5 | Maks. błąd podobieństwa |
| --- | --- | --- | --- | --- |
| float16 zamiast float32 | 100% | 100% | 100% | 0,00002 |

Maksymalny błąd pojedynczej składowej wyniósł 5,75e-05. Odczyt wektora
(`reconstruct`) zwraca wartość zaokrągloną do float16, a nie pierwotną
float32. Kompaktacja indeksu czyta i zapisuje te same wartości, więc
zaokrąglenie jest stabilne i nie narasta przy kolejnych przebiegach;
pilnuje tego test integracyjny.

Tabele zapisane wcześniejszą wersją aplikacji miały typ `vector`. Metadane
niosą teraz klucz `vector_type`, a jego brak albo inna wartość powoduje
odrzucenie indeksu z żądaniem przebudowy, zamiast czytania danych
niewłaściwym rzutowaniem.

## Instalacja sterownika

Sterownik PostgreSQL jest zależnością opcjonalną:

```bash
pip install -r requirements-pgvector.txt
```

Plik instaluje pakiet `psycopg` z wbudowaną biblioteką libpq. Bez niego
włączenie magazynu pgvector kończy się czytelnym komunikatem, a aplikacja
dalej działa w trybie dokładnym.

## Konfiguracja

W GUI: ekran Źródła i konfiguracja, zakładka `Przechowywanie`, karta
`Magazyn wektorów`. Pola połączenia pojawiają się po wybraniu magazynu
pgvector. Karta pozwala też zapisać hasło w magazynie poświadczeń
i przetestować połączenie przed zapisaniem ustawień.

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
python run.py maintenance rebuild --vectors-only
python run.py index
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
  znana z FAISS nie jest potrzebna; polecenie `python run.py maintenance compact`
  działa jako pełna resynchronizacja tabeli z lokalnym SQLite.
* `python run.py maintenance check` porównuje liczbę wektorów w bazie z liczbą
  fragmentów oznaczonych jako zwektoryzowane i zgłasza rozjazd jako
  ostrzeżenie.
* Kopia indeksu (`python run.py maintenance backup`) obejmuje wyłącznie pliki
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
