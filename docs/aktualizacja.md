# Procedura aktualizacji

## Zasada

Instalator nadpisuje pliki programu w `%LOCALAPPDATA%\Programs\FindDocs`
i nie rusza katalogu danych `%LOCALAPPDATA%\FindDocs`. Indeks, konfiguracja
i zapisane poświadczenia przetrwają aktualizację.

Migracje schematu bazy wykonują się automatycznie przy pierwszym uruchomieniu
nowej wersji, w jednej transakcji, z wpisem do tabeli `schema_migrations`.

## Przed aktualizacją

1. Sprawdź, jaka wersja jest zainstalowana: **Diagnostyka** albo
   `finddocs --version`.
2. Przeczytaj informacje o zmianach dla wersji docelowej, zwłaszcza sekcję
   o zgodności indeksu.
3. Wykonaj kopię indeksu:

```bash
finddocs maintenance backup
```

4. Zamknij aplikację i upewnij się, że żadne zadanie indeksowania nie działa
   w tle (na przykład zaplanowane w Harmonogramie zadań).

## Aktualizacja

Uruchom nowy instalator. Wykryje poprzednią instalację i ją nadpisze.
Skróty w menu Start pozostaną.

Instalacja cicha dla wdrożenia masowego:

```bat
FindDocs-0.2.1-instalator.exe /VERYSILENT /NORESTART /LOG="%TEMP%\finddocs-update.log"
```

## Po aktualizacji

1. Uruchom aplikację. Pierwszy start może potrwać dłużej, jeżeli wykonują się
   migracje. Postęp widać w logu (`migration.apply`).
2. Sprawdź stan:

```bash
finddocs doctor
finddocs maintenance check
```

3. Jeżeli pojawi się komunikat **Indeks wymaga przebudowy**, wykonaj procedurę
   z [odbudowy indeksu](odbudowa-indeksu.md). Do czasu przebudowy działa
   wyszukiwanie dokładne.
4. Wykonaj jedno wyszukiwanie kontrolne na znanym dokumencie.

## Kiedy aktualizacja wymaga przebudowy indeksu

| Zmiana w nowej wersji | Skutek |
| --- | --- |
| poprawka parsera formatu | warto przeindeksować dokumenty tego formatu |
| zmiana reguł normalizacji | wymagana pełna przebudowa |
| zmiana reguł fragmentacji | wymagana pełna przebudowa |
| zmiana modelu embeddingów | wymagana przebudowa części wektorowej |
| zmiana schematu bazy | migracja automatyczna, przebudowa niepotrzebna |

Aplikacja sama wykrywa pierwsze cztery przypadki przez skróty zgodności
zapisane w `index_meta`. Nie polegaj na własnej pamięci: uruchom
`finddocs maintenance check` po aktualizacji.

## Wycofanie zmiany

Jeżeli nowa wersja sprawia problemy:

1. Odinstaluj ją, odpowiadając **Nie** na pytanie o usunięcie katalogu danych.
2. Zainstaluj poprzednią wersję.
3. Przywróć kopię indeksu wykonaną przed aktualizacją:

```bash
finddocs maintenance restore --name index-20260731-183000
```

Ten krok jest konieczny, jeżeli nowa wersja podniosła wersję schematu.
**Starsza aplikacja nie otworzy nowszej bazy**: zgłosi błąd `FD-5001`
z prośbą o aktualizację programu, zamiast ryzykować uszkodzenie danych.

## Aktualizacja modelu embeddingów

Model jest niezależny od aplikacji. Wymiana modelu:

1. `finddocs maintenance backup`.
2. Skopiuj nowy model do `%LOCALAPPDATA%\FindDocs\models`.
3. Zmień `embedding.model_key` w konfiguracji.
4. Uruchom aplikację. Zgłosi niezgodność części wektorowej.
5. `finddocs maintenance rebuild --vectors-only` i `finddocs index`.

Wyszukiwanie dokładne działa przez cały ten czas.

## Aktualizacja Tesseract

Klucz pamięci podręcznej OCR zawiera wersję silnika, więc aktualizacja
Tesseract automatycznie unieważnia stare wpisy. Dokumenty rozpoznane starszą
wersją zostaną rozpoznane ponownie przy najbliższym pełnym przeindeksowaniu.

Jeżeli chcesz to wymusić od razu:

```bash
finddocs index --full
```

## Wdrożenie masowe

Aplikacja instaluje się w profilu użytkownika i nie wymaga uprawnień
administratora, więc nadaje się do dystrybucji przez Intune albo Configuration
Manager jako pakiet dla użytkownika, nie dla urządzenia.

Wykrywanie zainstalowanej wersji: klucz rejestru
`HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\FindDocs_is1`,
wartość `DisplayVersion`.

Konfigurację można rozprowadzić, umieszczając gotowy plik
`%LOCALAPPDATA%\FindDocs\config\config.json` przed pierwszym uruchomieniem.
Plik nie zawiera i nie może zawierać sekretów: dane logowania trafiają do
menedżera poświadczeń Windows dopiero po zalogowaniu użytkownika.
