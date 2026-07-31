# Integracja z SharePoint przez Microsoft Graph

> **Stan weryfikacji.** Konektor jest w pełni zaimplementowany i pokryty testami
> jednostkowymi oraz integracyjnymi na zamockowanych odpowiedziach Microsoft
> Graph. **Połączenie z prawdziwą dzierżawą nie zostało zweryfikowane**
> w środowisku, w którym powstała ta wersja: nie było tam danych dostępowych.
> Testy na mockach nie zastępują testu u klienta. Przed wdrożeniem produkcyjnym
> wykonaj procedurę z sekcji [Test wdrożeniowy](#test-wdrożeniowy).

## Co aplikacja robi z Graphem

| Operacja | Zasób Graph | Po co |
| --- | --- | --- |
| odczyt witryny | `GET /sites/{host}:{sciezka}` | zamiana adresu witryny na `site_id` |
| lista bibliotek | `GET /sites/{site-id}/drives` | wybór biblioteki dokumentów |
| lista elementów | `GET /drives/{drive-id}/root/children` | przechodzenie po folderach |
| zmiany przyrostowe | `GET /drives/{drive-id}/root/delta` | wykrywanie zmian bez pełnego skanu |
| pobranie pliku | `GET /drives/{drive-id}/items/{id}/content` | odczyt treści dokumentu |

Aplikacja tylko czyta. Nie zapisuje, nie kasuje i nie modyfikuje niczego
w SharePoint.

## Rejestracja aplikacji w Entra ID

Rejestrację wykonuje administrator dzierżawy jeden raz. Ta sama rejestracja
obsługuje wszystkich użytkowników w organizacji.

### 1. Nowa rejestracja

Centrum administracyjne Microsoft Entra, **Rejestracje aplikacji**,
**Nowa rejestracja**.

| Pole | Wartość |
| --- | --- |
| Nazwa | `FindDocs` |
| Obsługiwane typy kont | Tylko konta w tym katalogu organizacyjnym |
| Identyfikator URI przekierowania | typ **Klient publiczny/natywny**, wartość `http://localhost` |

Po zapisaniu przepisz **Identyfikator aplikacji (klienta)** i **Identyfikator
katalogu (dzierżawy)**. Obie wartości podaje się w konfiguracji źródła.

### 2. Klient publiczny

Zakładka **Uwierzytelnianie**, sekcja **Ustawienia zaawansowane**:

* **Zezwalaj na przepływy klienta publicznego**: **Tak**.

To ustawienie jest wymagane. FindDocs jest aplikacją desktopową i nie ma gdzie
bezpiecznie przechować sekretu klienta, więc **żaden sekret nie jest tworzony
ani używany**. Uwierzytelnianie opiera się na przepływie authorization code
z PKCE, obsługiwanym przez bibliotekę MSAL.

### 3. Uprawnienia

Zakładka **Uprawnienia interfejsu API**, **Dodaj uprawnienie**,
**Microsoft Graph**, **Uprawnienia delegowane**:

| Uprawnienie | Typ | Po co |
| --- | --- | --- |
| `Files.Read.All` | delegowane | odczyt plików, do których użytkownik ma dostęp |
| `Sites.Read.All` | delegowane | odczyt struktury witryn i bibliotek |
| `User.Read` | delegowane | dodawane domyślnie, potrzebne do logowania |
| `offline_access` | delegowane | odświeżanie tokenu bez ponownego logowania |

**Uprawnienia delegowane, nie aplikacyjne.** Aplikacja działa w imieniu
zalogowanego użytkownika i widzi wyłącznie to, co on. Nie ma dostępu do całej
dzierżawy i nie może obejść uprawnień SharePoint.

Uprawnienia `Files.Read.All` i `Sites.Read.All` wymagają zgody administratora.
Naciśnij **Udziel zgody administratora dla \<organizacja\>**. Bez tego kroku
użytkownicy zobaczą przy pierwszym logowaniu komunikat o konieczności zgody.

### 4. Ograniczenie zasięgu (opcjonalnie)

`Sites.Read.All` daje odczyt wszystkich witryn, do których użytkownik i tak ma
dostęp. Jeżeli chcesz zawęzić to do wybranych witryn, użyj
**Sites.Selected** wraz z uprawnieniami aplikacyjnymi nadanymi na poziomie
konkretnej witryny. Wymaga to zmiany zakresu w konfiguracji źródła
(pole `scopes`) i przetestowania, bo ta ścieżka nie została sprawdzona
w tej wersji.

## Konfiguracja źródła

### Z poziomu interfejsu

Ekran **Źródła i konfiguracja**, przycisk **Dodaj SharePoint**. Wypełnij:

| Pole | Przykład |
| --- | --- |
| Identyfikator dzierżawy | `00000000-1111-2222-3333-444444444444` |
| Identyfikator aplikacji | `55555555-6666-7777-8888-999999999999` |
| Adres witryny | `https://contoso.sharepoint.com/sites/Finanse` |
| Biblioteka | `Dokumenty` |
| Folder startowy | puste oznacza korzeń biblioteki |
| Sposób logowania | okno przeglądarki albo kod urządzenia |

Naciśnij **Testuj połączenie**. Otworzy się okno logowania Microsoft.
Po zalogowaniu aplikacja wypisze nazwę witryny i liczbę widocznych elementów.

### Z wiersza poleceń

```bash
finddocs sources add-sharepoint --id finanse --label "Finanse" \
    --site https://contoso.sharepoint.com/sites/Finanse \
    --library "Dokumenty" \
    --tenant 00000000-1111-2222-3333-444444444444 \
    --client-id 55555555-6666-7777-8888-999999999999 \
    --auth-flow interactive

finddocs sources test finanse
```

### Sposoby logowania

**Okno przeglądarki** (`interactive`). Domyślny. MSAL otwiera systemową
przeglądarkę i nasłuchuje na `http://localhost` na losowym porcie. Wymaga
dostępu do przeglądarki na tym samym komputerze.

**Kod urządzenia** (`device_code`). Aplikacja wypisuje kod i adres
`https://microsoft.com/devicelogin`. Kod wpisuje się na dowolnym urządzeniu.
Przydatne na stacjach bez przeglądarki albo w sesji zdalnej.

## Przechowywanie tokenu

Token odświeżania trafia do magazynu w kolejności:

1. Menedżer poświadczeń Windows (biblioteka `keyring`);
2. DPAPI powiązane z kontem użytkownika;
3. pamięć procesu, gdy dwa poprzednie zawiodą.

W trzecim przypadku token ginie po zamknięciu aplikacji i logowanie trzeba
powtórzyć. Aplikacja informuje o tym w logu (`credentials.store_selected`).

Token jest związany z kontem Windows użytkownika. Skopiowanie katalogu danych
na inny komputer nie przenosi dostępu.

Token nigdy nie trafia do logu ani do raportów. Odpowiada za to warstwa
redakcji, która usuwa nagłówki `Authorization`, ciągi `Bearer` i struktury
wyglądające na JWT.

## Ruch sieciowy

Dodanie źródła SharePoint włącza kategorię `microsoft_graph` w polityce
sieciowej. Dozwolone hosty:

```
graph.microsoft.com
*.graph.microsoft.com
login.microsoftonline.com
*.login.microsoftonline.com
login.microsoft.com
*.sharepoint.com
```

Wyłącznie HTTPS. Każde inne połączenie kończy się błędem `FD-1005`, także
wtedy, gdy adres podał serwer w odpowiedzi. Lista jest wpisana w kod
i widoczna na ekranie **Diagnostyka**.

Serwer proxy: ustaw `HTTPS_PROXY` i `NO_PROXY` w zmiennych środowiskowych
użytkownika. Biblioteka `httpx` je respektuje.

## Ograniczanie przepustowości

Graph odpowiada kodem 429 albo 503 z nagłówkiem `Retry-After`, gdy uzna, że
klient pyta za często. Konektor:

* czeka dokładnie tyle, ile mówi `Retry-After`, ograniczając to rozsądnym maksimum;
* przy braku nagłówka stosuje opóźnienie wykładnicze z podstawą 2 sekundy;
* ponawia próbę do `max_retries` razy (domyślnie 5);
* pokazuje w interfejsie stan **oczekiwanie na serwer**, zamiast wyglądać na
  zawieszony.

Ograniczenie przepustowości nie jest błędem i nie przerywa zadania.

## Wykrywanie zmian

Konektor używa `change_key` zbudowanego w kolejności: `eTag` elementu, skrót
treści, para data modyfikacji i rozmiar. Dokument z niezmienionym kluczem jest
pomijany.

Jeżeli biblioteka udostępnia `delta`, kolejne skanowania pobierają tylko zmiany.
Znacznik `deltaToken` jest zapisywany w kolumnie `sources.delta_token`.
Unieważnienie znacznika przez serwer powoduje automatyczne przejście na pełne
skanowanie.

## Test wdrożeniowy

Przed udostępnieniem aplikacji użytkownikom wykonaj na jednej bibliotece:

1. `finddocs sources add-sharepoint ...` z danymi rejestracji.
2. `finddocs sources test <id>`: sprawdza logowanie i odczyt witryny.
3. `finddocs index --source <id>`: pierwsze indeksowanie.
4. `finddocs report`: sprawdź, czy liczba dokumentów zgadza się z zawartością
   biblioteki i czy lista niewyszukiwalnych zawiera tylko oczekiwane pozycje.
5. Zmień jeden dokument w SharePoint, uruchom `finddocs index --source <id>`
   ponownie i sprawdź, że przetworzony został tylko ten jeden.
6. Usuń jeden dokument, uruchom skanowanie i sprawdź, że zniknął z indeksu.
7. Sprawdź w logu, że nie ma w nim tokenów ani treści dokumentów.

Dopiero wynik tej procedury pozwala powiedzieć, że integracja działa
w konkretnej dzierżawie.

## Rozwiązywanie problemów

| Objaw | Kod | Przyczyna i działanie |
| --- | --- | --- |
| Okno logowania nie zamyka się | `FD-2002` | zablokowane przekierowanie na `http://localhost`, sprawdź typ platformy w rejestracji |
| „Wymagana zgoda administratora” | `FD-2002` | brak zgody na `Files.Read.All` albo `Sites.Read.All` |
| „Nie znaleziono witryny” | `FD-2001` | zły adres witryny, sprawdź, czy zawiera `/sites/<nazwa>` |
| Widoczna część dokumentów | brak | to poprawne: użytkownik widzi tylko to, do czego ma uprawnienia w SharePoint |
| Częste przerwy w indeksowaniu | `FD-2004` | ograniczanie przepustowości, zmniejsz `page_size` albo uruchom poza godzinami szczytu |
| Połączenie odrzucone przez politykę | `FD-1005` | adres spoza listy dozwolonych, sprawdź ekran **Diagnostyka** |
| Logowanie za każdym razem | `FD-9001` | magazyn poświadczeń niedostępny, sprawdź w logu `credentials.store_selected` |

Przy każdym zgłoszeniu zacznij od `finddocs doctor` i od ostatnich wpisów
`error` w `logs\finddocs.log`.
