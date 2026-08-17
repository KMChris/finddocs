# Raport bezpieczeństwa

Dokument opisuje model zagrożeń, zastosowane kontrole i to, co pozostaje
odpowiedzialnością organizacji. Dotyczy wersji 0.1.0.

## Zakres

FindDocs jest aplikacją desktopową działającą w profilu jednego użytkownika,
na jego uprawnieniach. Nie ma usługi systemowej, serwera, portów nasłuchujących
ani współdzielonego magazynu.

Poza zakresem: bezpieczeństwo samego SharePointa, bezpieczeństwo stacji
roboczej, szyfrowanie dysku, kontrola dostępu do konta Windows.

## Aktywa

| Aktywo | Gdzie leży | Wrażliwość |
| --- | --- | --- |
| treść dokumentów | tabela `chunks` w `index\finddocs.db` | jak dokumenty źródłowe |
| metadane dokumentów | tabela `documents` | jak wyżej |
| wektory fragmentów | `index\vectors.faiss` | pośrednia, wektory nie odtwarzają tekstu wprost |
| token odświeżania Microsoft | menedżer poświadczeń Windows albo DPAPI | wysoka |
| konfiguracja źródeł | `config\config.json` | niska, bez sekretów |
| logi | `logs\finddocs.log` | niska, po redakcji |

**Indeks zawiera treść dokumentów w postaci jawnej.** To najważniejsze zdanie
tego raportu. Katalog `%LOCALAPPDATA%\FindDocs` podlega tej samej klauzuli
poufności co dokumenty źródłowe.

## Model zagrożeń i kontrole

### Wyciek treści dokumentów poza komputer

**Kontrola: polityka ruchu wychodzącego.** Domyślnie żadna kategoria ruchu nie
jest włączona (`NetworkPolicy.offline()`). Dozwolone są wyłącznie:

| Kategoria | Hosty | Kiedy włączana |
| --- | --- | --- |
| `microsoft_graph` | `graph.microsoft.com`, `login.microsoftonline.com`, `*.sharepoint.com` | po dodaniu źródła SharePoint |
| `model_download` | `huggingface.co`, `cdn-lfs.huggingface.co`, `*.hf.co` | po jawnej zgodzie w konfiguracji |
| `internal_api` | lista pusta | tylko po podaniu adresu w konfiguracji |
| `vector_db` | lista pusta | tylko po wybraniu magazynu pgvector i podaniu serwera |
| `ocr_api` | lista pusta | tylko po wybraniu silnika `remote_api` i podaniu adresu |

Dla serwerów zdalnych wyłącznie HTTPS. Adres spoza listy kończy się błędem
`FD-1005`, także gdy podał go serwer w odpowiedzi.

Jedyny wyjątek od HTTPS dotyczy tego samego komputera (`localhost`, `127.0.0.1`,
`::1`) i wymaga jawnego włączenia opcji `allow_plain_http_localhost`. Służy
lokalnym serwerom modeli, które nie wystawiają TLS. Taki ruch nie opuszcza
maszyny, więc nie zwiększa powierzchni wycieku; opcja jest domyślnie wyłączona,
a jej stan widać na ekranie **Diagnostyka**. Na hosty zdalne nie ma wpływu.

**Kontrola: brak telemetrii.** Aplikacja nie wysyła żadnych zdarzeń o użyciu.
Nie ma kodu, który by to robił, i nie ma zależności, która by to robiła za nas.
Dodatkowo warstwa startowa ustawia `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`
i `DO_NOT_TRACK=1`.

**Kontrola: przejrzystość.** Lista dozwolonych adresów jest widoczna na ekranie
**Diagnostyka**, więc użytkownik może ją sprawdzić bez czytania kodu.

**Weryfikacja:** testy `tests/unit/test_security.py` sprawdzają, że polityka
domyślna odrzuca wszystko, że HTTP jest odrzucany oraz że host spoza listy nie
przechodzi. Konektor SharePoint pyta politykę przed każdym żądaniem.

### Wyciek treści przez logi

**Kontrola: redakcja jako warstwa.** Każde zdarzenie przechodzi przez procesor
redakcji (`security/redaction.py`), który:

* usuwa wartości kluczy z listy wrażliwych (`access_token`, `refresh_token`,
  `authorization`, `password`, `secret`, `api_key`, `cookie`, `query`,
  `embedding`, `vector` i podobne);
* dla kluczy z treścią (`text`, `body`, `snippet`, `chunk_text`) zapisuje samą
  długość zamiast wartości;
* maskuje wzorce w wolnym tekście: `Bearer <token>`, struktury JWT,
  pary `klucz=wartość` dla nazw wrażliwych;
* skraca adresy URL do postaci bez parametrów zapytania.

**Kontrola: zapytania użytkownika domyślnie nie są zapisywane.**
`diagnostics.log_queries` jest wyłączone. Włączenie wymaga świadomej zmiany
konfiguracji i jest opisane jako tryb diagnostyczny.

**Ograniczenie:** redakcja jest ostatnią linią obrony, a nie jedyną. Kod jest
napisany tak, żeby wrażliwych danych do logu nie przekazywać. Redakcja łapie
pomyłki.

**Weryfikacja:** testy redakcji obejmują wszystkie wymienione wzorce.

### Kradzież tokenu dostępu do SharePointa

**Kontrola: token nigdy nie leży jawnym tekstem.** Kolejność magazynów:

1. Menedżer poświadczeń Windows (przez `keyring`);
2. DPAPI (`CryptProtectData`) z zaszyfrowanym plikiem w katalogu danych;
3. pamięć procesu, gdy dwa poprzednie zawiodą.

Wariant trzeci nie jest trwały i aplikacja wpisuje to do logu
(`credentials.non_persistent_store`).

**Kontrola: token związany z kontem Windows.** DPAPI szyfruje na koncie
użytkownika, więc skopiowanie katalogu danych na inny komputer nie przenosi
dostępu.

**Kontrola: brak sekretu klienta.** Rejestracja w Entra ID jest typu public
client z PKCE. Aplikacja nie ma i nie potrzebuje sekretu, więc nie ma czego
wykraść z pliku konfiguracyjnego.

**Weryfikacja:** test sprawdza, że plik magazynu DPAPI nie zawiera sekretu
w postaci czytelnej.

### Podniesienie uprawnień przez aplikację

**Kontrola: uprawnienia delegowane, nie aplikacyjne.** `Files.Read.All`
i `Sites.Read.All` w wariancie delegowanym oznaczają, że aplikacja widzi
dokładnie to, co zalogowany użytkownik. Nie ma dostępu do całej dzierżawy
i nie może obejść uprawnień SharePoint.

**Kontrola: tylko odczyt.** Aplikacja nie zapisuje, nie kasuje i nie modyfikuje
niczego w SharePoint.

**Kontrola: instalacja bez administratora.** Aplikacja instaluje się w profilu
użytkownika i nie zmienia ustawień systemu.

### Złośliwy dokument

Dokumenty pochodzą ze źródeł, do których użytkownik ma dostęp, ale zawartość
pliku jest zawsze danymi wejściowymi z zewnątrz.

| Zagrożenie | Kontrola |
| --- | --- |
| bomba dekompresyjna (ZIP, obraz) | limit `max_image_pixels` (40 mln), limit rozmiaru pliku, archiwa nie są rozpakowywane |
| plik zapętlający parser | limit czasu odczytu `extraction_timeout_seconds`, limit czasu strony OCR |
| dokument z makrami | makra nigdy nie są uruchamiane; automatyzacja Office wyłącza je jawnie |
| wyjście poza katalog przez nazwę załącznika | `_safe_filename` zamienia separatory ścieżek i znaki niedozwolone, pusta nazwa staje się `zalacznik` |
| plik podszywający się pod inny format | typ rozpoznawany po sygnaturze zawartości, nie po rozszerzeniu |
| bardzo głębokie zagnieżdżenie wiadomości | ograniczona głębokość, limit 30 załączników i 100 MB na wiadomość |
| zewnętrzne encje XML | parsery nie rozwijają encji zewnętrznych |

**Kontrola: izolacja błędów.** Uszkodzony dokument nie przerywa zadania.
Błąd jest zapisywany przy dokumencie i w tabeli `error_log`, a przetwarzanie
idzie dalej. Sprawdzają to testy w `tests/integration/test_pipeline.py`.

**Weryfikacja:** testy parserów zawierają celowo uszkodzone pliki, plik
podszywający się pod PDF, dokument zabezpieczony hasłem i pliki losowych bajtów.

### Wstrzyknięcie SQL

**Kontrola: zapytania parametryzowane.** Wartości nigdy nie są wklejane do
tekstu zapytania. Wyjątkiem są nazwy kolumn i kierunek sortowania, budowane
z zamkniętej listy wartości w kodzie, a nie z danych wejściowych.

**Kontrola: składnia FTS5.** Tekst zapytania użytkownika jest przetwarzany na
tokeny, a nie przekazywany wprost do `MATCH`. Cudzysłowy i operatory z zapytania
nie mogą zmienić struktury wyrażenia.

### Uszkodzenie albo utrata indeksu

| Zagrożenie | Kontrola |
| --- | --- |
| przerwanie zapisu dokumentu | jedna transakcja SQLite na dokument |
| przerwanie zapisu wektorów | plik tymczasowy, `fsync`, zamiana nazwy |
| brak miejsca na dysku | próg `min_free_disk_bytes`, zadanie kończy się kodem `FD-1002` |
| przerwanie zadania | punkty kontrolne co N dokumentów, wznowienie |
| indeks niezgodny z konfiguracją | skróty `index_compat_hash` i `vector_compat_hash` sprawdzane przy starcie |
| uszkodzenie pliku bazy | `python run.py maintenance check`, kopie zapasowe |

### Kod i zależności

**Kontrola: brak sekretów w repozytorium.** Konfiguracja nie zawiera i nie może
zawierać sekretów. Nie ma zakodowanych na sztywno poświadczeń ani kluczy.

**Kontrola: zależności przypięte.** `requirements-lock.txt` zawiera dokładne
wersje. SBOM w formacie CycloneDX 1.5 jest w `sbom.cdx.json`. Wykaz powstaje
z zależności zadeklarowanych w plikach `requirements*.txt` wraz z zależnościami przechodnimi,
więc pakiet doinstalowany doraźnie do środowiska deweloperskiego nie trafia do
komponentów produktu. Generator wypisuje takie pakiety jako ostrzeżenie.

**Kontrola: licencje sprawdzone.** Wszystkie zależności mają licencję
dopuszczającą użycie komercyjne. Składniki o licencjach kłopotliwych (PyMuPDF
na AGPL, extract-msg na GPL-3.0, PyQt6 na GPL) zostały świadomie odrzucone,
co odnotowuje [dokument o licencjach](licencje.md).

**Kontrola: statyczna analiza.** `ruff` z regułami bezpieczeństwa (zestaw `S`
z bandit) i `mypy` w trybie ścisłym przechodzą bez zastrzeżeń dla całego
katalogu `src`.

## Kontrole na poziomie prywatności

| Wymaganie | Realizacja |
| --- | --- |
| brak telemetrii | brak kodu wysyłającego zdarzenia |
| brak zapytań w logach | `log_queries` domyślnie wyłączone |
| brak treści w logach | redakcja plus zasada logowania faktów, nie treści |
| brak treści w raportach | eksport przechodzi przez tę samą redakcję |
| dane tylko lokalnie | polityka ruchu wychodzącego |
| przejrzystość | ekran **Diagnostyka** pokazuje politykę i stan komponentów |

## Ryzyka pozostające po stronie organizacji

1. **Indeks nie jest szyfrowany.** Zawiera treść dokumentów. Zalecenie:
   szyfrowanie dysku (BitLocker) na stacjach roboczych.
2. **Kopie indeksu zawierają to samo.** Przechowuj je tam, gdzie dokumenty.
3. **Kod na stanowisku jest zapisywalny.** Aplikacja uruchamia się z plików
   źródłowych, więc każdy, kto ma prawo zapisu do tego katalogu, może zmienić
   jej działanie. Zalecenie: katalog z kodem tylko do odczytu dla konta
   użytkownika i kontrola integralności przy wdrożeniu.
4. **Uprawnienia w Entra ID.** `Sites.Read.All` obejmuje wszystkie witryny,
   do których użytkownik ma dostęp. Zawężenie wymaga `Sites.Selected`, co nie
   zostało przetestowane w tej wersji.
5. **Aktualizacje zależności.** Repozytorium ma włączonego Dependabota, ale
   decyzja o aktualizacji i ponownym wydaniu należy do organizacji.

## Weryfikacja

| Obszar | Sposób weryfikacji | Stan |
| --- | --- | --- |
| polityka sieciowa | testy jednostkowe | zweryfikowane |
| redakcja logów | testy jednostkowe | zweryfikowane |
| magazyn poświadczeń | testy jednostkowe, sprawdzenie pliku DPAPI | zweryfikowane |
| izolacja błędów parserów | testy integracyjne | zweryfikowane |
| bezpieczeństwo nazw plików | testy jednostkowe | zweryfikowane |
| brak sekretów w repozytorium | przegląd, `ruff` z regułami `S` | zweryfikowane |
| licencje zależności | SBOM plus przegląd | zweryfikowane |
| **połączenie z prawdziwą dzierżawą SharePoint** | **niewykonane** | **do wykonania u klienta** |
| test penetracyjny | niewykonany | poza zakresem tej wersji |
| audyt zewnętrzny | niewykonany | poza zakresem tej wersji |

Dwa ostatnie wiersze są istotne. Ten raport opisuje kontrole zaprojektowane
i przetestowane w kodzie, a nie wynik niezależnego audytu bezpieczeństwa.
