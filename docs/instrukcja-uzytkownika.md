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
8. [Wyszukiwanie semantyczne](#wyszukiwanie-semantyczne)
9. [Przechowywanie](#przechowywanie)
10. [Indeksowanie](#indeksowanie)
11. [Raport pokrycia](#raport-pokrycia)
12. [Ustawienia](#ustawienia)
13. [Częste pytania](#częste-pytania)

## Pierwsze uruchomienie

Po instalacji uruchom FindDocs z menu Start. Aplikacja otworzy się w oknie,
nie w przeglądarce. Nie trzeba niczego startować ręcznie.

Przy pierwszym uruchomieniu indeks jest pusty. Kolejność pracy jest zawsze taka sama:

1. **Źródła i konfiguracja**: wskaż, gdzie leżą dokumenty.
2. **Indeksowanie**: naciśnij **Skanuj źródła** i poczekaj.
3. **Wyszukiwanie**: wpisz zapytanie.

Dopóki nie ma żadnego źródła, ekran wyszukiwania pokazuje powitanie z dwoma
przyciskami: **Dodaj katalog** i **Utwórz zbiór demonstracyjny**. Pierwsze kroki
robisz wprost z tego miejsca, bez szukania właściwego ekranu.

Jeśli chcesz najpierw zobaczyć, jak to działa, na tym samym ekranie
naciśnij **Utwórz zbiór demonstracyjny**. Powstanie kilkadziesiąt fikcyjnych
dokumentów po polsku (umowy, notatki, faktury, skany, wiadomości e-mail), które
możesz od razu zaindeksować. Nie ma w nich żadnych prawdziwych danych osobowych
ani firmowych.

Komunikat o niedostępnym trybie semantycznym przy starcie oznacza, że na komputerze
nie ma modelu językowego. Wyszukiwanie dokładne działa normalnie. Model można
pobrać przyciskiem **Pobierz z Hugging Face...** na karcie **Model embeddingów**
(ekran **Źródła i konfiguracja**, zakładka **Wyszukiwanie semantyczne**; pobranie
wymaga zgody na jednorazowe połączenie z Hugging Face) albo poprosić
administratora, patrz [instrukcja administratora](instrukcja-administratora.md).

## Ekran wyszukiwania

Ekran czyta się od góry:

* pole zapytania z przyciskiem lupy;
* wybór trybu, lista **Sortowanie** i przycisk **Filtry**;
* listę wyników.

Liczba znalezionych dokumentów i czas zapytania są po prawej stronie tytułu
ekranu. Jeżeli wyszukiwarka ma zastrzeżenie do kompletności wyników (na
przykład brakuje indeksu semantycznego), nad listą pojawia się pomarańczowy
pasek z wyjaśnieniem.

Zapytanie uruchamiasz klawiszem Enter albo przyciskiem lupy. W trybie
**Dokładne** wyniki liczą się też same, w trakcie pisania, po krótkiej przerwie
od ostatniego znaku (można to wyłączyć w Ustawieniach). W trakcie pracy lupa
zmienia się w kwadrat: naciśnięcie przerywa wyszukiwanie natychmiast. Pole
zapytania podpowiada ostatnie zapytania tej sesji; historia nie jest nigdzie
zapisywana.

Lista **Sortowanie** ma dwie pozycje: **Trafność** i **Najnowsze** (po dacie
modyfikacji). Jest widoczna tylko w trybie **Dokładne**, bo tryby z udziałem
modelu zwracają ranking podobieństwa i nie mają innego porządku.

Skróty klawiszowe:

| Skrót | Działanie |
| --- | --- |
| `Ctrl+F` albo `Ctrl+K` | kursor do pola zapytania |
| `Enter` | wyszukaj |
| `Esc` | przerwij wyszukiwanie, a poza nim wyczyść pole zapytania |
| `Ctrl+Shift+F` | pokaż albo ukryj panel filtrów |
| `Alt+Left`, `Alt+Right` | poprzednia i następna strona wyników |
| `Ctrl+1` do `Ctrl+4` | przełącz ekran |
| `Ctrl+5` | otwórz Ustawienia |
| `F5` | odśwież stan indeksu |

Pasek na dole okna pokazuje liczbę zaindeksowanych dokumentów i fragmentów,
rozmiar indeksu oraz to, czy tryb semantyczny jest dostępny. Kropka po lewej
stronie paska ma kolor zielony, gdy tryb semantyczny działa, pomarańczowy,
gdy brakuje modelu, i szary, gdy jest wyłączony w ustawieniach.

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

Panel filtrów rozwija przycisk **Filtry** (albo `Ctrl+Shift+F`). Filtry można łączyć.

| Filtr | Opis |
| --- | --- |
| Katalog albo lokalizacja | fragment ścieżki albo nazwa folderu |
| Typ pliku | rozszerzenie występujące w indeksie |
| Data od, Data do | zakres dat modyfikacji |
| Autor | osoba zapisana w metadanych dokumentu |
| Źródło, Biblioteka | katalog lokalny albo konkretna biblioteka SharePoint |
| Tylko dokumenty z OCR | wyłącznie teksty rozpoznane z obrazu |

Aktywne filtry są widoczne jako chipy pod panelem filtrów, także przy zwiniętym
panelu (wypadają wtedy tuż pod paskiem trybów). Ustawienie filtra przy otwartym
panelu nie przesuwa pól, bo chipy dokładają się poniżej, nad listą wyników.
Kliknięcie krzyżyka na chipie zdejmuje pojedynczy filtr i odświeża
wyniki. Liczba w nawiasie na przycisku **Filtry** mówi, ile filtrów działa.
Przycisk **Wyczyść filtry** przywraca stan wyjściowy. Liczba wyników przy tytule
ekranu zawsze dotyczy stanu po zastosowaniu filtrów.

## Wyniki

Każdy wynik to jeden dokument, a nie pojedynczy fragment. W karcie wyniku
znajdziesz:

* glif rodzaju pliku (tekst, tabela, obraz, poczta) i nazwę pliku;
* położenie dokumentu jako okruszki: biblioteka i katalogi, bez powtarzania
  nazwy pliku;
* jeden albo dwa najlepiej pasujące fragmenty z wyróżnionymi trafieniami;
  pozostałe pobrane fragmenty rozwija odnośnik **Pokaż więcej fragmentów**;
* typ pliku i datę modyfikacji;
* rodzaj dopasowania (dosłowne, znaczeniowe, mieszane), widoczny w trybie
  hybrydowym, gdzie różni się między wynikami;
* oznaczenie **OCR**, jeżeli tekst pochodzi z rozpoznawania obrazu;
* ocenę dopasowania.

Plakietki pod nazwą pliku są skrócone. Najedź na plakietkę, żeby zobaczyć,
co dokładnie oznacza: datę modyfikacji, autora, jakość OCR albo siłę dopasowania.

Ocena służy do porównywania wyników **w obrębie jednej listy**. Nie jest
procentem trafności i nie da się jej porównywać między różnymi zapytaniami.

Odnośnik **Pokaż kontekst trafienia** dokleja do pierwszego fragmentu sąsiednie
fragmenty dokumentu prosto z indeksu, bez otwierania pliku. Sąsiedzi są
wyszarzeni, a trafienie zachowuje wyróżnienie.

Dokument otwierasz na trzy sposoby: klikając jego nazwę, klikając kartę
dwukrotnie albo naciskając `Enter`, gdy karta ma zaznaczenie klawiaturowe
(klawiszem `Tab` przechodzisz między wynikami). Przy prawej krawędzi karty,
po najechaniu na nią albo po zaznaczeniu klawiaturą, pojawiają się dwa
przyciski:

* folder: otwiera katalog z zaznaczonym plikiem. Dla dokumentów z SharePointa
  otwiera stronę biblioteki w przeglądarce;
* kopia: kopiuje ścieżkę albo adres do schowka.

Wyniki są stronicowane. Wiersz z numerem strony pojawia się pod listą tylko
wtedy, gdy stron jest więcej niż jedna; strony przewijasz też skrótami
`Alt+Left` i `Alt+Right`. Łączna liczba znalezionych dokumentów jest przy
tytule ekranu. W trybie dokładnym ta liczba jest dokładna, w pozostałych
trybach opisuje wielkość rozważanego zbioru kandydatów.

## Źródła dokumentów

Ekran **Źródła i konfiguracja** ma trzy zakładki: **Źródła** (lista źródeł
dokumentów i opcje indeksowania), **Wyszukiwanie semantyczne** (model językowy
i sposób liczenia embeddingów) oraz **Przechowywanie** (katalog danych
i magazyn wektorów).

Zakładka **Źródła** pozwala dodać dwa rodzaje źródeł.

**Katalog lokalny albo dysk sieciowy.** Wskaż folder. Możesz ograniczyć
rozszerzenia plików, wykluczyć wzorce nazw (na przykład `~$*`) i ustawić
maksymalny rozmiar pliku.

**Biblioteka SharePoint.** Potrzebujesz danych od administratora: identyfikatora
dzierżawy, identyfikatora aplikacji i adresu witryny. Po zapisaniu naciśnij
**Testuj połączenie**: otworzy się okno logowania Microsoft. Zaloguj się swoim
kontem służbowym. Zobaczysz tylko te dokumenty, do których i tak masz dostęp.

Źródło włącza się i wyłącza polem wyboru w kolumnie **Aktywne**. Wyłączone
źródło nie bierze udziału w skanowaniu, a jego dokumenty zostają w indeksie.
Przyciski **Testuj połączenie** i **Usuń** działają na źródle zaznaczonym na
liście. Dopóki nic nie jest zaznaczone, są nieaktywne. **Usuń** kasuje źródło
z konfiguracji, a jego dokumenty znikają z indeksu.

Pod listą źródeł, w sekcji **Opcje indeksowania**, jest przełącznik
**Indeksuj zawartość archiwów ZIP**. Po włączeniu archiwum jest rozpakowywane,
a każdy plik w środku trafia do indeksu jako osobny dokument, tak jak załącznik
wiadomości. Zmiana zaczyna działać od następnego skanowania.

## Wyszukiwanie semantyczne

Część semantyczną konfiguruje zakładka **Wyszukiwanie semantyczne** na ekranie
**Źródła i konfiguracja**. Zakładka składa się z czterech kart. Przełączniki
pierwszej karty i przyciski karty profili działają od razu; zmiany na kartach
modelu i obliczeń zapisuje ich przycisk **Zastosuj**. Po zapisie aplikacja sama
otwiera indeks ponownie, nie trzeba jej restartować.

**Wyszukiwanie semantyczne.** Karta pokazuje aktywny model (nazwę, wymiar
wektora i licencję) i ma dwa przełączniki:

* **Włącz indeksowanie i wyszukiwanie semantyczne**: po wyłączeniu aplikacja
  przestaje liczyć wektory i działa wyłącznie w trybie dokładnym. Po ponownym
  włączeniu wystarczy zwykłe skanowanie, brakujące wektory zostaną uzupełnione
  automatycznie;
* **Wzbogacaj wektory o nazwę pliku i ścieżkę**: każdy fragment dostaje przed
  policzeniem wektora nagłówek z nazwą pliku i jego ścieżką w źródle. Dzięki
  temu zapytanie wspominające katalog albo nazwę pliku (na przykład „regulamin
  z katalogu Kadry”) znajdzie dokument, nawet gdy jego treść o nich nie
  wspomina. Nagłówek nie zmienia treści pokazywanej w wynikach ani wyszukiwania
  dokładnego. Zmiana wymaga przebudowy części semantycznej indeksu.

**Profile dostawcy embeddingów.** Profil to nazwany zestaw ustawień dostawcy:
model lokalny z urządzeniem obliczeń albo zdalne API z adresem i kontraktem.
**Aktywuj** przełącza całą konfigurację na wybrany profil, a **Zapisz bieżące
jako profil** tworzy profil z obecnych ustawień. Edycja ustawień na kartach
niżej nie zmienia zapisanych profili; znika wtedy tylko wskazanie profilu
aktywnego.

**Model embeddingów.** Karta jest widoczna, gdy dostawcą jest model lokalny.
Można tu:

* **wybrać aktywny model** z listy modeli wbudowanych i zaimportowanych oraz
  przełączyć wersję skwantyzowaną (szybszą na procesorze, z mniejszym plikiem);
* **zmienić przedrostki zapytania i treści**: część modeli (na przykład rodzina
  E5) wymaga doklejenia przedrostka do tekstu przed policzeniem wektora.
  Przedrostki są wykrywane automatycznie przy imporcie, ale można je poprawić;
* **zaimportować własny model z dysku** (przycisk **Importuj z dysku...**):
  wskaż katalog z gotowym eksportem ONNX albo z checkpointem Hugging Face
  (konwersja wymaga dodatku `finddocs[export]`, opisanego w
  [instalacji z PyPI](instalacja-pip.md));
* **pobrać model z Hugging Face** (przycisk **Pobierz z Hugging Face...**):
  podaj identyfikator repozytorium, na przykład
  `sdadas/mmlw-retrieval-roberta-base`. Aplikacja poprosi o zgodę na
  jednorazowe połączenie z serwerami Hugging Face; poza tym nie nawiązuje
  żadnych połączeń.

Parametry importu (nazwę, pooling, kwantyzację) podaje się w osobnym oknie.
Każdy zaimportowany model pojawia się na liście obok modeli wbudowanych.
Zmiana modelu, wariantu skwantyzowanego albo przedrostków wymaga przebudowy
części semantycznej indeksu (pełne przeindeksowanie na ekranie
**Indeksowanie**); do tego czasu działa wyszukiwanie dokładne.

**Obliczenia embeddingów.** Przełącznik dostawcy: **Model lokalny (ONNX)**
liczy embeddingi na tym komputerze, bez połączeń sieciowych, a **Zdalne API
organizacji** wysyła treść fragmentów do API wskazanego przez organizację.
Dla modelu lokalnego karta ustawia urządzenie obliczeń (procesor albo kartę
graficzną) i wielkość paczek. Dla zdalnego API: adres, kontrakt, nazwę modelu,
wymiar wektora oraz klucz API, przechowywany w magazynie poświadczeń, nigdy
w pliku konfiguracyjnym. Adresy zdalne muszą używać https; pole wyboru
**Zezwól na http do tego komputera** dopuszcza połączenie bez szyfrowania
wyłącznie do usługi działającej na tej samej maszynie, na przykład lokalnego
serwera modeli. Zmiana dostawcy wymaga przebudowy części semantycznej
indeksu. Szczegóły w dokumencie
[embeddingi na GPU i zdalne API](embeddingi-gpu-api.md).

## Przechowywanie

Zakładka **Przechowywanie** pokazuje katalog danych aplikacji, wolne miejsce
i rozmiar indeksu. **Zmień katalog** wskazuje nowe miejsce na dane; zmiana
zaczyna działać po ponownym uruchomieniu aplikacji. Karta **Magazyn wektorów**
przełącza między plikiem lokalnym (FAISS) a zewnętrzną bazą PostgreSQL
z rozszerzeniem pgvector. To opcja dla administratorów, opisana w dokumencie
[baza wektorowa](baza-wektorowa.md).

## Indeksowanie

W spoczynku ekran **Indeksowanie** pokazuje podsumowanie ostatniego przebiegu:
kiedy się odbył, jak się zakończył i ile dokumentów przetworzył. Karty postępu
i statystyk pojawiają się wraz z uruchomieniem zadania i pokazują:

* bieżący etap (skanowanie, pobieranie, odczyt, OCR, zapis);
* liczby: wykryte, przetworzone, pominięte, błędy, bez zmian, usunięte;
* nazwę aktualnie przetwarzanego pliku;
* pasek postępu, czas trwania i zajęte miejsce tymczasowe;
* stan połączenia ze źródłem.

Liczba błędów większa od zera jest wyróżniona kolorem błędu; kliknięcie jej
otwiera listę plików poza indeksem.

Przyciski:

| Przycisk | Działanie |
| --- | --- |
| **Skanuj źródła** | dodaje nowe pliki, aktualizuje zmienione, usuwa skasowane |
| **Pauza** i **Wznów** | jeden przycisk: wstrzymuje pracę i wraca do niej później |
| **Anuluj** | przerywa zadanie, indeks pozostaje spójny |
| **Pełne przeindeksowanie** | przetwarza wszystko od nowa, także dokumenty bez zmian |
| **Eksportuj raport** | zapisuje raport pokrycia do pliku |

Pod statystykami są dwie zakładki. Liczba w nawiasie przy nazwie mówi, ile jest
w niej pozycji, a pole **Filtruj wiersze** zawęża obie tabele do wierszy
zawierających wpisany tekst.

**Pliki poza indeksem** to stan zbioru: pliki wykryte w źródle, których nie
znajdziesz w wynikach. Każdy plik jest tu najwyżej raz, a kolumna **Powód**
mówi, co się stało (format nieobsługiwany, plik uszkodzony, brak treści,
zabezpieczony hasłem, pominięty przez ustawienia źródła). Zaznacz wiersze
i kliknij **Przetwórz ponownie**: wpisy znikną z listy, a pliki wrócą do
kolejki. Aplikacja od razu zapyta, czy uruchomić skanowanie. Plik wróci na
listę tylko wtedy, gdy znowu się nie uda.

**Dziennik błędów** to zdarzenia: wynik ostatniej próby dla każdego pliku, wraz
z etapem i kodem błędu. Wpis znika sam, gdy plik uda się przetworzyć. Przyciski
**Usuń zaznaczone** i **Wyczyść dziennik** porządkują listę; stan plików
w indeksie się przy tym nie zmienia.

Pełne przeindeksowanie zaczyna od wyczyszczenia obu list dla skanowanych źródeł,
bo liczy każdy plik od nowa. Wpisy pojawiają się dopiero wtedy, gdy błąd się
powtórzy. W trakcie zadania przyciski obu list są nieaktywne: listami zarządza
wtedy samo indeksowanie.

Okno działa normalnie w czasie indeksowania. Możesz przejść na ekran
wyszukiwania i szukać w tym, co już jest w indeksie.

Kolejne uruchomienia są szybkie: aplikacja przetwarza tylko dokumenty, które
się zmieniły. Dokumenty usunięte ze źródła znikają z indeksu.

Jeżeli aplikacja została zamknięta w trakcie indeksowania, przy następnym starcie
zapyta, czy wznowić przerwane zadanie.

## Raport pokrycia

Ekran **Raport** odpowiada na pytanie „czego nie ma w indeksie i dlaczego”.

Raport liczy się sam przy wejściu na ekran i po każdej zmianie indeksu; stempel
przy przyciskach mówi, z której godziny pochodzą liczby. Karta **Pokrycie**
zawiera liczby dokumentów w podziale na stan (zaindeksowane, puste, uszkodzone,
zabezpieczone hasłem, nieobsługiwany format, błąd odczytu) oraz liczbę
dokumentów i stron z OCR. Karta **Informacje techniczne** pokazuje datę
ostatniego skanowania, wersję indeksu i nazwę modelu embeddingów.

Odpowiedź na pytanie o kompletność jest w pasku na górze ekranu: zielony oznacza,
że wszystkie wykryte dokumenty da się wyszukać, pomarańczowy, że nie.

Na dole znajduje się lista dokumentów niewyszukiwalnych wraz z powodem; pole
**Filtruj wiersze** zawęża ją do wpisanego tekstu.
**Jeżeli ta lista nie jest pusta, aplikacja nie twierdzi, że zbiór wyników jest
kompletny.** Warto ją przejrzeć przed użyciem wyników do celów formalnych.

Raport zapisują przyciski **Eksportuj do CSV** (do arkusza) albo
**Eksportuj do JSON** (do dalszego przetwarzania).

## Ustawienia

Pozycja **Ustawienia** jest przypięta na dole panelu nawigacji (skrót `Ctrl+5`).
Ekran ma dwie zakładki: **Ogólne** i **Diagnostyka**.

Zakładka **Ogólne** zbiera ustawienia interfejsu. Zmiany działają od razu
i są zapamiętywane.

* **Motyw**: systemowy, jasny albo ciemny. Zmiana przebudowuje okno.
* **Tło Mica okna**: przezroczysty materiał systemowy pod oknem, dostępny
  na Windows 11.
* **Otwieranie dokumentów**: dokument w SharePoint (przeglądarka) albo kopia
  lokalna, gdy jest dostępna.
* **Wyników na stronę**: od 5 do 100.
* **Pokazuj plakietkę siły dopasowania**: wyłącza ocenę na kartach wyników.
* **Wyszukiwanie przyrostowe w trybie Dokładne**: wyniki w trakcie pisania.

Przycisk **O programie** pokazuje wersję aplikacji oraz katalogi danych i logów.

Zakładka **Diagnostyka** to narzędzia serwisowe: informacje o środowisku,
komponentach i indeksie (odświeżane przy każdym otwarciu), sprawdzenie
spójności indeksu, kompaktowanie indeksu wektorowego, kopia indeksu oraz
eksport pakietu diagnostycznego dla pomocy technicznej. Pakiet nie zawiera
treści dokumentów. Pole **Filtruj wiersze** zawęża tabele do wpisanego tekstu.

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
SharePoint), jednorazowe pobranie modelu oraz połączenia włączone jawnie przez
administratora: zdalne API embeddingów i zewnętrzna baza wektorów. Lista
dozwolonych adresów jest widoczna na zakładce **Diagnostyka** w Ustawieniach.

**Gdzie są moje dane?**
W katalogu `%LOCALAPPDATA%\FindDocs`. Indeks zawiera treść dokumentów, więc
podlega tej samej klauzuli poufności co dokumenty źródłowe.
