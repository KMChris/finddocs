# Znane ograniczenia

Dokument mówi, czego aplikacja nie robi i gdzie jej wyniki wymagają ostrożności.
Jest częścią umowy z użytkownikiem: lepiej znać granicę narzędzia, niż odkryć
ją w niewłaściwym momencie.

## Zakres produktu

**To jest wyszukiwarka, nie asystent.** Aplikacja nie generuje odpowiedzi,
nie streszcza dokumentów, nie odpowiada na pytania własnymi słowami i nie
zawiera modelu językowego typu LLM. Zwraca dokumenty i fragmenty, które w nich
faktycznie występują.

**Aplikacja nie modyfikuje dokumentów.** Nie zapisuje, nie kasuje i nie zmienia
niczego w SharePoint ani w katalogach źródłowych. Czyta i indeksuje.

**Aplikacja nie zastępuje uprawnień.** Widzisz dokładnie te dokumenty, do
których i tak masz dostęp. Indeks jest lokalny i dotyczy jednego użytkownika.

## Kompletność wyników

**Tryb dokładny gwarantuje kompletność, pozostałe nie.** Tylko wyszukiwanie
dokładne zwraca wszystkie dokumenty spełniające zapytanie i podaje dokładną
liczbę. Tryb semantyczny i hybrydowy zwracają ranking przybliżony: dokument
istotny może się w nim nie znaleźć. Aplikacja pisze o tym przy każdym wyniku.

**Kompletność dotyczy tylko dokumentów poprawnie zaindeksowanych.** Dokument
uszkodzony, zabezpieczony hasłem, w nieobsługiwanym formacie albo pominięty
przez filtr nie znajdzie się w wynikach. Raport pokrycia wymienia je wszystkie
i wyraźnie mówi, że zbiór nie jest kompletny.

**Indeks pokazuje stan z ostatniego skanowania.** Dokument dodany po nim będzie
widoczny dopiero po kolejnym indeksowaniu.

## Wyszukiwanie

**Brak odmiany wyrazów.** Aplikacja nie ma stemmera ani lematyzatora dla języka
polskiego. Zapytanie `Kowalski` nie znajdzie dokumentu, w którym jest tylko
`Kowalskiego`. Częściowo rekompensuje to tryb semantyczny, ale nie jest to
zamiennik. Dodanie stemmera wymagałoby podniesienia
`NORMALIZATION_VERSION` i przebudowy indeksu.

**Brak operatorów logicznych.** Nie ma `AND`, `OR`, `NOT`, nawiasów ani
wieloznaczników. Wszystkie elementy dosłowne zapytania są wymagane łącznie.
Dostępne są frazy w cudzysłowie i filtry.

**Brak wyszukiwania rozmytego.** Literówka w zapytaniu nie zostanie poprawiona.

**Ocena dopasowania nie jest miarą trafności.** Służy do porównywania wyników
w obrębie jednej listy. Nie da się jej porównywać między zapytaniami ani
traktować jak procentu.

**Zakres dat działa na dacie w treści dokumentu i na dacie modyfikacji pliku.**
Nie rozpoznaje pojęć w rodzaju „w zeszłym kwartale”.

## Formaty

**Pliki `.doc` i `.xls` bez pakietu Office są czytane w trybie zapasowym.**
Wbudowany czytnik OLE wyciąga tekst, ale nie odtwarza układu, tabel ani
formatowania. Poziom wsparcia to „eksperymentalny”. Z zainstalowanym Microsoft
Office jakość jest wyraźnie lepsza.

**Archiwa nie są rozpakowywane.** Zawartość `.zip`, `.7z` i `.rar` nie trafia
do indeksu.

**Obrazy osadzone w dokumentach nie przechodzą OCR.** Fotografia wklejona
do pliku DOCX albo RTF nie zostanie rozpoznana. Dotyczy to tylko dokumentów
nierasteryzowanych: strony PDF są renderowane w całości i tam OCR działa.

**Pliki większe niż `max_file_size_mb` (domyślnie 512 MB) są pomijane.**

**Dokumenty zabezpieczone hasłem nie są otwierane.** Aplikacja nie łamie
i nie zgaduje haseł.

## OCR

**OCR wymaga osobnej instalacji.** Tesseract nie jest dołączony do instalatora.
Bez żadnego silnika skany nie mają warstwy tekstowej i trafiają do raportu jako
niewyszukiwalne.

**Jakość zależy od jakości skanu.** Dokumenty odręczne, bardzo słabej jakości
albo w nietypowych krojach pisma dają wynik niepełny. Aplikacja podaje pewność
rozpoznania, żeby dało się to ocenić.

**Limit stron.** Domyślnie 60 stron na dokument. Dłuższe skany są rozpoznawane
częściowo, z ostrzeżeniem przy dokumencie.

**Tabele w skanach tracą strukturę.** OCR zwraca tekst, nie układ kolumn.

## Wydajność i skala

**Aplikacja jest przewidziana na zbiory rzędu dziesiątek tysięcy dokumentów,
nie milionów.** SQLite FTS5 radzi sobie z takim rozmiarem bez trudu, ale nie
testowaliśmy zbiorów wielomilionowych.

**Pierwsze indeksowanie zbioru ze skanami trwa długo.** OCR jest najdroższym
elementem. Zadanie można wstrzymać i wznowić.

**Wszystko liczy się na CPU.** Jest to wybór świadomy, nie brak. Model
embeddingów w wersji INT8 zajmuje około 125 MB i przetwarza kilkadziesiąt
fragmentów na sekundę na typowym procesorze biurowym.

**Indeks zajmuje miejsce.** Z grubsza 30 do 60 procent rozmiaru dokumentów
tekstowych.

## SharePoint

**Połączenie z prawdziwą dzierżawą nie zostało zweryfikowane** w środowisku,
w którym powstała ta wersja. Konektor ma testy jednostkowe i integracyjne na
zamockowanych odpowiedziach Microsoft Graph, ale to nie zastępuje testu
u klienta. Procedurę testu wdrożeniowego opisuje
[integracja z SharePoint](integracja-sharepoint.md).

**Uprawnienia `Sites.Selected` nie zostały przetestowane.** Konfiguracja
zakłada `Files.Read.All` i `Sites.Read.All` jako uprawnienia delegowane.

**Token jest związany z kontem Windows.** Przeniesienie katalogu danych na inny
komputer wymaga ponownego zalogowania.

**Aplikacja nie obsługuje OneDrive ani Teams jako osobnych źródeł.** Biblioteki
dokumentów w witrynach zespołów są dostępne przez zwykły adres witryny.

## Interfejs

**Tylko język polski.** Nie ma przełącznika języka ani plików tłumaczeń.

**Tylko Windows.** Kod jest w większości przenośny, ale magazyn poświadczeń
(DPAPI, menedżer poświadczeń Windows), automatyzacja Office i pakowanie są
związane z Windows. Wersja dla Linux i macOS nie istnieje i nie była testowana.

**Brak dostępności dla czytników ekranu.** Interfejs nie był testowany
z technologiami asystującymi.

**Jedna instancja na użytkownika.** Dwie kopie aplikacji na tym samym katalogu
danych będą sobie przeszkadzać przy zapisie do indeksu.

## Bezpieczeństwo

**Indeks zawiera treść dokumentów w postaci jawnej.** Katalog
`%LOCALAPPDATA%\FindDocs\index` podlega tej samej klauzuli poufności co
dokumenty źródłowe. Aplikacja nie szyfruje indeksu; jeżeli tego potrzebujesz,
użyj szyfrowania dysku (BitLocker).

**Kopie indeksu zawierają to samo.** Przechowuj je tam, gdzie same dokumenty.

**Redakcja logów jest ostatnią linią obrony, a nie jedyną.** Kod jest napisany
tak, żeby wrażliwych danych do logu nie przekazywać. Warstwa redakcji łapie
pomyłki, ale nie należy na niej polegać jako na jedynym zabezpieczeniu.

## Świadomie niezaimplementowane

| Element | Powód |
| --- | --- |
| indeks współdzielony między użytkownikami | wymagałby serwera i modelu uprawnień, sprzeczne z założeniem lokalności |
| synchronizacja w czasie rzeczywistym | wymagałaby subskrypcji Graph i punktu odbioru dostępnego z internetu |
| przeglądarka dokumentów w aplikacji | dokumenty otwiera aplikacja systemowa, po co drugi czytnik |
| eksport wyników do PDF | raport pokrycia eksportuje się do CSV i JSON, to wystarcza |
| historia zapytań | zapytania nie są zapisywane, to decyzja dotycząca prywatności |
| akceleracja GPU | patrz [plan RAG i GPU](plan-rag-gpu.md) |
| generowanie odpowiedzi (RAG) | poza zakresem produktu, patrz [plan RAG i GPU](plan-rag-gpu.md) |
