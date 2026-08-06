# FindDocs: instrukcja użytkownika

Aplikacja szuka dokumentów na Twoim komputerze i w bibliotekach SharePoint,
do których masz dostęp. Wszystko liczy się lokalnie: dokumenty, zapytania
i wyniki nie są nigdzie wysyłane.

## Spis treści

1. [Pierwsze uruchomienie](#pierwsze-uruchomienie)
2. [Ekran wyszukiwania](#ekran-wyszukiwania)
3. [Tryby wyszukiwania](#tryby-wyszukiwania)
4. [Jak pisać zapytania](#jak-pisać-zapytania)
5. [Filtry](#filtry)
6. [Wyniki](#wyniki)
7. [Źródła dokumentów](#źródła-dokumentów)
8. [Indeksowanie](#indeksowanie)
9. [Raport pokrycia](#raport-pokrycia)
10. [Częste pytania](#częste-pytania)

## Pierwsze uruchomienie

Po instalacji uruchom FindDocs z menu Start. Aplikacja otworzy się w oknie,
nie w przeglądarce. Nie trzeba niczego startować ręcznie.

Przy pierwszym uruchomieniu indeks jest pusty. Kolejność pracy jest zawsze taka sama:

1. **Źródła i konfiguracja**: wskaż, gdzie leżą dokumenty.
2. **Indeksowanie**: naciśnij **Start** i poczekaj.
3. **Wyszukiwanie**: wpisz zapytanie.

Jeśli chcesz najpierw zobaczyć, jak to działa, na ekranie **Źródła i konfiguracja**
naciśnij **Wygeneruj zbiór demonstracyjny**. Powstanie kilkadziesiąt fikcyjnych
dokumentów po polsku (umowy, notatki, faktury, skany, wiadomości e-mail), które
możesz od razu zaindeksować. Nie ma w nich żadnych prawdziwych danych osobowych
ani firmowych.

Komunikat o niedostępnym trybie semantycznym przy starcie oznacza, że na komputerze
nie ma modelu językowego. Wyszukiwanie dokładne działa normalnie. Model można
pobrać przyciskiem **Ustawienia...** obok listy modeli na ekranie
**Źródła i konfiguracja** (wymaga zgody na jednorazowe połączenie z Hugging Face)
albo poprosić administratora, patrz
[instrukcja administratora](instrukcja-administratora.md).

## Ekran wyszukiwania

Ekran ma trzy części:

* pole zapytania na górze, z przyciskiem **Szukaj** i wyborem trybu;
* panel filtrów po prawej stronie;
* listę wyników na środku.

Zapytanie uruchamiasz klawiszem Enter albo przyciskiem **Szukaj**. Podczas
wyszukiwania pojawia się przycisk **Anuluj**: aplikacja przerwie pracę
natychmiast, nie trzeba czekać do końca.

Skróty klawiszowe:

| Skrót | Działanie |
| --- | --- |
| `Ctrl+F` | kursor do pola zapytania |
| `Enter` | wyszukaj |
| `Esc` | anuluj trwające wyszukiwanie |
| `Ctrl+1` do `Ctrl+5` | przełącz ekran |
| `F5` | odśwież stan indeksu |

Pasek na dole okna pokazuje liczbę zaindeksowanych dokumentów i fragmentów,
rozmiar indeksu oraz to, czy tryb semantyczny jest dostępny.

## Tryby wyszukiwania

**Dokładne**. Zwraca wszystkie dokumenty, które zawierają wskazane słowa,
frazy, liczby i daty. To jedyny tryb, w którym liczba wyników jest liczbą
dokładną i w którym możesz założyć, że nic nie zostało pominięte. Używaj go,
gdy szukasz konkretnej wartości: numeru rachunku, kwoty, nazwiska, sygnatury.

**Semantyczne**. Zwraca dokumenty powiązane znaczeniowo, nawet jeśli nie
zawierają ani jednego słowa z Twojego zapytania. Wynik jest **rankingiem
przybliżonym**: aplikacja pokazuje dokumenty najbardziej podobne, ale nie
gwarantuje, że pokazała wszystkie pasujące. Aplikacja pisze o tym wprost pod
polem wyników. Używaj, gdy nie pamiętasz słów użytych w dokumencie.

**Hybrydowe** (domyślne). Łączy oba podejścia. Wartości dosłowne z zapytania
(numery, daty, kwoty, frazy w cudzysłowie) pozostają warunkiem, a reszta
zapytania działa znaczeniowo. To dobry wybór na co dzień.

> Gdy zależy Ci na kompletności, użyj trybu **Dokładnego**. Tylko on daje
> gwarancję, że wszystkie pasujące dokumenty są na liście.

## Jak pisać zapytania

Zapytanie może być zwykłym zdaniem. Aplikacja sama rozpozna w nim elementy,
które trzeba potraktować dosłownie.

**Numery rachunków.** Trzy zapisy tego samego numeru dają ten sam wynik:

```
00 1234 5678 9012 3456 7890 1234
00-1234-5678-9012-3456-7890-1234
00123456789012345678901234
```

**Daty.** Również w trzech zapisach:

```
24.07.2015
2015-07-24
24 lipca 2015
```

Możesz też podać zakres: `od 01.01.2015 do 31.12.2015`. Zakres działa jak filtr
dat, a nie jak wymóg, żeby obie daty były w jednym dokumencie.

**Kwoty.** `1 234,56`, `1234.56`, `314 zł` i `314 złotych` prowadzą do tych
samych dokumentów.

**Frazy.** Tekst w cudzysłowie musi wystąpić dokładnie w tej kolejności:

```
"procedura realizacji przelewów"
```

Działa zwykły cudzysłów `"..."` i polski `„..."`.

**Nazwy plików.** Wpisz pełną nazwę z rozszerzeniem, na przykład `umowa-2015.pdf`.

**Sygnatury i identyfikatory.** `FV/2015/07/123`, `NIP 123-456-32-18`,
`REGON 123456785` są rozpoznawane jako całość i nie rozpadają się na liczby.

**Polskie znaki.** Możesz pisać z ogonkami albo bez: `zażółć` i `zazolc` znajdą
te same dokumenty. Dotyczy to także litery `ł`.

## Filtry

Panel filtrów ogranicza wynik. Filtry można łączyć.

| Filtr | Opis |
| --- | --- |
| Lokalizacja | fragment ścieżki albo nazwa folderu |
| Typ pliku | jedno lub więcej rozszerzeń |
| Data modyfikacji | zakres od i do |
| Autor | osoba zapisana w metadanych dokumentu |
| Źródło | katalog lokalny albo konkretna biblioteka SharePoint |

Przycisk **Wyczyść filtry** przywraca stan wyjściowy. Liczba wyników nad listą
zawsze dotyczy stanu po zastosowaniu filtrów.

## Wyniki

Każdy wynik to jeden dokument, a nie pojedynczy fragment. W karcie wyniku
znajdziesz:

* nazwę pliku i jego położenie logiczne (folder albo biblioteka);
* źródło, z którego pochodzi;
* od jednego do trzech najlepiej pasujących fragmentów z wyróżnionymi trafieniami;
* rodzaj dopasowania: dosłowne, znaczeniowe albo mieszane;
* typ pliku i datę modyfikacji;
* oznaczenie **OCR**, jeżeli tekst pochodzi z rozpoznawania obrazu;
* ocenę dopasowania.

Ocena służy do porównywania wyników **w obrębie jednej listy**. Nie jest
procentem trafności i nie da się jej porównywać między różnymi zapytaniami.

Trzy przyciski na karcie:

* **Otwórz dokument**: otwiera plik w domyślnej aplikacji systemu.
* **Otwórz lokalizację**: otwiera folder z zaznaczonym plikiem. Dla dokumentów
  z SharePointa otwiera stronę biblioteki w przeglądarce.
* **Kopiuj odnośnik**: kopiuje ścieżkę albo adres do schowka.

Wyniki są stronicowane. Pod listą znajdziesz numer strony i łączną liczbę
znalezionych dokumentów. W trybie dokładnym ta liczba jest dokładna,
w pozostałych trybach opisuje wielkość rozważanego zbioru kandydatów.

## Źródła dokumentów

Ekran **Źródła i konfiguracja** pozwala dodać dwa rodzaje źródeł.

**Katalog lokalny albo dysk sieciowy.** Wskaż folder. Możesz ograniczyć
rozszerzenia plików, wykluczyć wzorce nazw (na przykład `~$*`) i ustawić
maksymalny rozmiar pliku.

**Biblioteka SharePoint.** Potrzebujesz danych od administratora: identyfikatora
dzierżawy, identyfikatora aplikacji i adresu witryny. Po zapisaniu naciśnij
**Testuj połączenie**: otworzy się okno logowania Microsoft. Zaloguj się swoim
kontem służbowym. Zobaczysz tylko te dokumenty, do których i tak masz dostęp.

Przycisk **Usuń** kasuje źródło z konfiguracji. Dokumenty tego źródła znikają
z indeksu przy następnym skanowaniu.

## Model wyszukiwania semantycznego

Na dole ekranu **Źródła i konfiguracja** znajduje się lista modeli językowych.
Wybierz model i naciśnij **Zastosuj ustawienia modelu**, żeby go aktywować.
Zmiana modelu wymaga przebudowy części semantycznej indeksu (pełne
przeindeksowanie na ekranie **Indeksowanie**); do tego czasu działa
wyszukiwanie dokładne.

Przycisk **Ustawienia...** obok listy otwiera okno, w którym można:

* **zaimportować własny model z dysku**: wskaż katalog z gotowym eksportem ONNX
  albo z checkpointem Hugging Face (konwersja wymaga dodatku `finddocs[export]`,
  opisanego w [instalacji z PyPI](instalacja-pip.md));
* **pobrać model z Hugging Face**: podaj identyfikator repozytorium, na przykład
  `sdadas/mmlw-retrieval-roberta-base`. Aplikacja poprosi o zgodę na jednorazowe
  połączenie z serwerami Hugging Face; poza tym nie nawiązuje żadnych połączeń;
* **zmienić przedrostki zapytania i treści**: część modeli (na przykład rodzina
  E5) wymaga doklejenia przedrostka do tekstu przed policzeniem wektora.
  Przedrostki są wykrywane automatycznie przy imporcie, ale można je poprawić.
  Zmiana wymaga przebudowy części semantycznej indeksu;
* **wyłączyć indeksowanie semantyczne**: aplikacja przestaje liczyć wektory
  i działa wyłącznie w trybie dokładnym. Po ponownym włączeniu wystarczy zwykłe
  skanowanie, brakujące wektory zostaną uzupełnione automatycznie.

Po zapisaniu zmian aplikacja sama otwiera indeks ponownie; nie trzeba jej
restartować. Każdy zaimportowany model pojawia się na liście obok modeli
wbudowanych.

## Indeksowanie

Ekran **Indeksowanie** pokazuje, co się dzieje:

* bieżący etap (skanowanie, pobieranie, odczyt, OCR, zapis);
* liczby: wykryte, przetworzone, pominięte, błędy, bez zmian, usunięte;
* nazwę aktualnie przetwarzanego pliku;
* pasek postępu, czas trwania i zajęte miejsce tymczasowe;
* stan połączenia ze źródłem.

Przyciski:

| Przycisk | Działanie |
| --- | --- |
| **Start** | indeksuje nowe i zmienione dokumenty |
| **Pauza** | wstrzymuje pracę, można wznowić później |
| **Wznów** | kontynuuje od miejsca zatrzymania |
| **Anuluj** | przerywa zadanie, indeks pozostaje spójny |
| **Skanuj ponownie** | pełne przeindeksowanie wszystkiego od nowa |
| **Eksportuj raport** | zapisuje raport pokrycia do pliku |
| **Pokaż błędy** | lista dokumentów, których nie udało się odczytać |
| **Pokaż pliki pominięte** | lista plików świadomie pominiętych |

Okno działa normalnie w czasie indeksowania. Możesz przejść na ekran
wyszukiwania i szukać w tym, co już jest w indeksie.

Kolejne uruchomienia są szybkie: aplikacja przetwarza tylko dokumenty, które
się zmieniły. Dokumenty usunięte ze źródła znikają z indeksu.

Jeżeli aplikacja została zamknięta w trakcie indeksowania, przy następnym starcie
zapyta, czy wznowić przerwane zadanie.

## Raport pokrycia

Ekran **Raport** odpowiada na pytanie „czego nie ma w indeksie i dlaczego”.

Raport zawiera liczby dokumentów w podziale na stan (zaindeksowane, puste,
uszkodzone, zabezpieczone hasłem, nieobsługiwany format, błąd odczytu),
liczbę dokumentów i stron z OCR, datę ostatniego skanowania, wersję indeksu
oraz nazwę modelu embeddingów.

Na dole znajduje się lista dokumentów niewyszukiwalnych wraz z powodem.
**Jeżeli ta lista nie jest pusta, aplikacja nie twierdzi, że zbiór wyników jest
kompletny.** Warto ją przejrzeć przed użyciem wyników do celów formalnych.

Raport można zapisać przyciskiem **Eksportuj** do pliku CSV (do arkusza)
albo JSON (do dalszego przetwarzania).

## Częste pytania

**Nie widzę dokumentu, o którym wiem, że istnieje.**
Sprawdź kolejno: czy jego źródło jest dodane i włączone, czy indeksowanie się
zakończyło, czy plik nie jest na liście niewyszukiwalnych w raporcie pokrycia,
czy nie zawęziły go filtry. Na koniec spróbuj w trybie **Dokładnym**.

**Wyszukiwanie semantyczne jest niedostępne.**
Na komputerze nie ma modelu językowego. Tryb dokładny działa bez modelu.
Model instaluje administrator.

**Dokument jest skanem i nic w nim nie znajduję.**
Sprawdź w raporcie, czy plik przeszedł OCR. Jeżeli OCR jest wyłączony albo brakuje
silnika, skany nie mają warstwy tekstowej. Skany bardzo słabej jakości mogą dać
tekst niepełny; taki dokument jest oznaczony jako OCR o niskiej pewności.

**Indeksowanie trwa długo.**
Pierwsze indeksowanie przetwarza wszystko, a OCR jest kosztowny. Kolejne
uruchomienia dotyczą tylko zmian. Można wstrzymać pracę przyciskiem **Pauza**
i wrócić do niej później.

**Aplikacja mówi, że indeks wymaga przebudowy.**
Zmieniła się konfiguracja wpływająca na sposób budowy indeksu (na przykład model).
Do czasu przebudowy działa wyszukiwanie dokładne. Przebudowę uruchamia
administrator, patrz [odbudowa indeksu](odbudowa-indeksu.md).

**Czy moje dokumenty gdzieś wyciekają?**
Nie. Aplikacja nie zawiera telemetrii, a cały ruch wychodzący jest domyślnie
zablokowany. Jedyne dozwolone połączenia to Microsoft Graph (gdy skonfigurujesz
SharePoint) i jednorazowe pobranie modelu. Lista dozwolonych adresów jest widoczna
na ekranie **Diagnostyka**.

**Gdzie są moje dane?**
W katalogu `%LOCALAPPDATA%\FindDocs`. Indeks zawiera treść dokumentów, więc
podlega tej samej klauzuli poufności co dokumenty źródłowe.
