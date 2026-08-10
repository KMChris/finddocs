# System wizualny interfejsu

Dokument opisuje reguły, według których zbudowany jest interfejs FindDocs, oraz
powody, dla których wyglądają tak, a nie inaczej. Jest przeznaczony dla osoby,
która będzie ten interfejs rozwijać.

Punktem odniesienia jest Fluent, czyli język wizualny Windows 11: warstwowe tła,
zaokrąglone rogi, cienkie obramowania, jeden kolor akcentu.

## Zasada nadrzędna

Ekran wyszukiwania jest jedynym ekranem, na którym użytkownik spędza czas.
Wszystko nad listą wyników to koszt: im niżej zaczyna się pierwszy wynik, tym
mniej wyników widać bez przewijania. Dlatego elementy sterujące albo niosą
informację potrzebną przy każdym zapytaniu, albo pojawiają się warunkowo.

Konsekwencje tej zasady widoczne w kodzie:

* liczba wyników jest w wierszu tytułu ekranu, a nie w osobnym wierszu;
* wiersz stron pojawia się dopiero wtedy, gdy stron jest więcej niż jedna;
* panel filtrów jest zwinięty, a to, że jednak działa, sygnalizuje liczba
  na przycisku **Filtry**;
* uwagi wyszukiwarki idą do banera, a nie do szarego tekstu, który czytelnik
  pomija. Te uwagi mówią o kompletności wyników, więc muszą być widoczne.

## Tokeny

Wszystkie wartości są w `src/finddocs/gui/theme.py`. Widoki nie wpisują liczb
z palca, tylko biorą je stamtąd. Dzięki temu zmiana rytmu całego interfejsu to
zmiana jednej stałej, a nie przegląd pięciu plików.

### Odstępy

| Stała | Wartość | Typowe zastosowanie |
| --- | --- | --- |
| `SPACE_XS` | 4 px | odstęp podpisu od pola |
| `SPACE_SM` | 8 px | odstęp między przyciskami w wierszu |
| `SPACE_MD` | 12 px | odstęp między blokami ekranu |
| `SPACE_LG` | 16 px | wnętrze karty |
| `SPACE_XL` | 24 px | margines boczny ekranu |

`PAGE_MARGINS` to marginesy ekranu, wspólne dla wszystkich widoków. Ustawia je
`widgets.page.page_layout`, więc żaden widok nie definiuje własnych.

### Typografia

| Stała | Wartość | Zastosowanie |
| --- | --- | --- |
| `FONT_SIZE_SMALL` | 9 pt | plakietki, podpisy, podpowiedzi |
| `FONT_SIZE` | 10 pt | tekst podstawowy |
| `FONT_SIZE_TITLE` | 12 pt | nazwa dokumentu, tytuł sekcji |
| `FONT_SIZE_QUERY` | 13 pt | pole zapytania |
| `FONT_SIZE_BRAND` | 15 pt | nazwa aplikacji |
| `FONT_SIZE_PAGE` | 17 pt | tytuł ekranu |

Skala jest zamknięta: test `test_stopnie_pisma_pochodza_ze_skali_typografii`
sprawdza, że w arkuszu stylów nie ma stopnia pisma spoza tej tabeli.

Hierarchia karty wyniku opiera się wyłącznie na tej skali: nazwa dokumentu
12 pt w kolorze akcentu, ścieżka i plakietki 9 pt, treść fragmentu 10 pt.
Fragment jest jedyną rzeczą, którą czytelnik naprawdę czyta, więc nic obok
niego nie może być większe.

### Kształt i kolor

`RADIUS_SMALL` 6 px (wstawki), `RADIUS` 8 px (pola, przyciski),
`RADIUS_LARGE` 12 px (karty), `RADIUS_PILL` (plakietki, kropka stanu).

Kolory są w `Palette`, osobno dla motywu jasnego i ciemnego. Wartości zależne
od wariantu, których nie ma w palecie (tło wstawki, suwak, obramowanie przy
najechaniu), liczy `build_stylesheet`, bo są potrzebne tylko arkuszowi stylów.

Role kolorów niosących znaczenie są słownikami: `BADGE_COLORS` (plakietki),
`BANNER_COLORS` (banery), `DOT_COLORS` (kropka stanu). Każda rola musi istnieć
w obu wariantach, pilnują tego testy motywu.

## Kontrolki wspólne

Katalog `src/finddocs/gui/widgets`. Widok, który potrzebuje czegoś, co ma już
inny widok, bierze to stąd zamiast pisać drugi raz.

| Kontrolka | Rola |
| --- | --- |
| `page_layout` | marginesy i odstęp ekranu |
| `PageHeader` | tytuł ekranu oraz krótka informacja przy prawej krawędzi |
| `Banner` | jedno zdanie o stanie ekranu, w roli `success`, `warning`, `info` |
| `StatusDot` | stan składnika wyrażony kolorem, w roli `ok`, `warn`, `off` |
| `SegmentedControl` | wybór jednej opcji z kilku, złączony w jedną kontrolkę |
| `StatGrid` | siatka par podpis/wartość |
| `ResultCard`, `EmptyState` | karta wyniku i komunikat zastępczy |

Uwagi implementacyjne:

* role są wyrażone właściwościami dynamicznymi (`bannerRole`, `dotRole`,
  `segmentPos`, `badgeRole`), a kolory dobiera arkusz stylów. Po zmianie
  właściwości trzeba wywołać `widgets.page.repolish`, inaczej Qt nie policzy
  stylu ponownie;
* rola spoza listy schodzi do wartości domyślnej. Literówka daje wtedy element
  o neutralnym wyglądzie, a nie element bez tła i bez obramowania;
* `StatGrid` ma stałą strukturę i podmienia same wartości. Odświeżenie raportu
  nie tworzy kontrolek od nowa;
* `SegmentedControl` liczy wspólną szerokość segmentów pismem pogrubionym,
  bo wybrany segment jest pogrubiony i inaczej ucinałby pierwszą literę.

## Reguły, które łatwo złamać

1. **Napis na przycisku ma być krótki, zdanie idzie do podpowiedzi.** Wiersz
   sześciu przycisków z peryfrazami nie mieści się w oknie o najmniejszym
   dozwolonym rozmiarze (980 px minus panel nawigacji), a Qt wtedy przycina
   tekst bez ostrzeżenia.
2. **Jedna operacja to jeden przycisk.** Dawne **Start** i **Skanuj ponownie**
   zlecały to samo zadanie, więc obok siebie sugerowały dwie różne operacje.
   Dziś jest jeden przycisk **Skanuj źródła**.
3. **Akcja wymagająca zaznaczenia jest nieaktywna bez zaznaczenia.** Okno
   z pouczeniem „wybierz źródło z listy” to informacja podana za późno.
4. **Zero to wartość licznika, nie stan.** „Połączenie: 0” nic nie znaczy.
   Wartości, które nie są licznikami, mają w stanie spoczynku `brak`.
5. **Stan pusty zajmuje całą wolną wysokość i jest wyśrodkowany.** Komunikat
   przyklejony do górnej krawędzi dużego pustego prostokąta wygląda na błąd
   renderowania.
6. **Element bez treści jest ukryty, a nie pusty.** Baner, wiersz stron
   i podpowiedź postępu nie zajmują miejsca, gdy nie mają nic do powiedzenia.
7. **Uniwersalna reguła `QWidget` nie ustawia tła.** Etykiety malowałyby wtedy
   prostokąt w kolorze tła aplikacji także wtedy, gdy leżą na białej karcie.
8. **Fokus z klawiatury musi być wyraźniejszy niż najechanie myszką.** Karta
   wyniku dostaje przy fokusie obramowanie dwupikselowe w kolorze akcentu,
   przy najechaniu tylko szarą krawędź.

## Klawiatura

Każda akcja wykonywana często ma skrót, a skrót jest widoczny w podpowiedzi
kontrolki, do której należy. Skróty ekranu wyszukiwania rejestruje `SearchView`,
skróty okna rejestruje `MainWindow`. Pełna lista jest w
[instrukcji użytkownika](instrukcja-uzytkownika.md).

Karta wyniku przyjmuje fokus (`Tab` przechodzi między wynikami), a `Enter`
otwiera dokument. Przyciski przyjmują fokus wyłącznie z klawiatury
(`theme.TabFocusStyle`), więc kliknięcie myszką nie zostawia na nich ramki.

## Sprawdzanie wyglądu

Testy pilnują struktury, nie wyglądu. Zmiany wizualne ogląda się na zrzutach
okna renderowanych bez interakcji: buduje się `MainWindow` na tymczasowym
katalogu danych, wywołuje `grab()` na każdym ekranie i porównuje obrazy przed
zmianą i po niej. Warto to zrobić w obu motywach, bo kontrast plakietek i banerów
liczy się osobno dla każdego wariantu palety.
