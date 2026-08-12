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
* panel filtrów jest zwinięty, a to, że jednak działa, sygnalizują chipy
  aktywnych filtrów i liczba na przycisku **Filtry**; klik chipa zdejmuje
  pojedynczy filtr. Wiersz chipów leży pod panelem, więc przy zwiniętym panelu
  wypada tuż pod paskiem trybów, a chip dołożony przy otwartym panelu odsuwa
  tylko wyniki i nie rusza samego panelu;
* baner nad listą wyników dostaje wyłącznie uwagi zależne od zapytania
  (obcięta lista, niedostępny indeks semantyczny). Stała charakterystyka trybu
  jest w podpowiedzi pod przełącznikiem trybów: ostrzeżenie pokazywane przy
  każdym wyszukiwaniu przestaje być ostrzeżeniem i uczy pomijania banera.

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
| `FONT_SIZE_TITLE` | 12 pt | nazwa dokumentu, tytuł sekcji, zakładki |
| `FONT_SIZE_QUERY` | 13 pt | pole zapytania |
| `FONT_SIZE_BRAND` | 15 pt | nazwa aplikacji |
| `FONT_SIZE_PAGE` | 17 pt | tytuł ekranu |

Skala jest zamknięta: test `test_stopnie_pisma_pochodza_ze_skali_typografii`
sprawdza, że w arkuszu stylów nie ma stopnia pisma spoza tej tabeli.

### Rodzina pisma

Interfejs używa **Segoe UI**, a nie Segoe UI Variable, mimo że Windows 11
składa swój własny interfejs rodziną Variable. Powód jest mierzalny: Qt widzi
w rodzinie `Segoe UI Variable Text` tylko dwa kroje, Regular i Bold. Stopień
600 nie ma wtedy odpowiednika i Qt awansuje go do 700, więc tytuł pisany
stopniem 600 wychodzi tak ciężki jak 700. Obok tekstu podstawowego w stopniu
400 daje to skok bez wartości pośredniej i cała strona wygląda na złożoną
z dwóch różnych pism. Semibold z rodziny Variable jest w systemie osobną
rodziną (`Segoe UI Variable Text Semibold`), której Qt nie kojarzy z podstawową.

`Segoe UI` ma prawdziwe kroje o wagach 300, 350, 400, 600, 700 i 900, więc
hierarchia 400 / 600 / 700 jest równa. Sprawdza to test
`test_rodzina_pisma_ma_kroj_semibold`; na platformie `offscreen` nie ma bazy
czcionek systemowych, więc tam jest pomijany.

Rodzinę rozwiązuje `theme.font_family()`: bierze pierwszą zainstalowaną z listy
`FONT_CANDIDATES` i podaje tę samą, jedną nazwę zarówno do `QFont`, jak i do
arkusza stylów. Lista rozdzielona przecinkami działałaby w obu miejscach, ale
wtedy nie wiadomo, która rodzina jest naprawdę używana, a od tego zależy
dostępność kroju Semibold.

Aplikacja nie ustawia `QFont.StyleStrategy`. Wymuszenie `PreferAntialias` daje
wygładzanie w odcieniach szarości, więc te same litery wyglądają cieniej niż
w oknach systemowych.

Hierarchia karty wyniku opiera się wyłącznie na tej skali: nazwa dokumentu
12 pt w kolorze akcentu, ścieżka i plakietki 9 pt, treść fragmentu 10 pt.
Fragment jest jedyną rzeczą, którą czytelnik naprawdę czyta, więc nic obok
niego nie może być większe.

Karta pokazuje od razu najwyżej dwa fragmenty, pozostałe rozwija odnośnik
na karcie. Proza jest sklejana z łamań wierszy pochodzących z ekstrakcji
(fragmenty tabel zachowują wiersze), bo te łamania potrafiły potroić wysokość
karty i w oknie mieścił się jeden wynik.

Przy tytule leży glif rodziny pliku (tekst, tabela, obraz, poczta) w kolorze
wyciszonym. Rodzaj dokumentu widać przed przeczytaniem nazwy, a lista zyskuje
kotwicę wzrokową. Mapowanie rozszerzeń: `FILE_GLYPH_FAMILIES` w karcie wyniku,
glify generuje `tools/make_theme_icons.py`.

### Kształt i kolor

`RADIUS_SMALL` 6 px (wstawki), `RADIUS` 8 px (pola, przyciski),
`RADIUS_LARGE` 12 px (karty), `RADIUS_PILL` (plakietki, kropka stanu).

Kolory są w `Palette`, osobno dla motywu jasnego i ciemnego. Wartości zależne
od wariantu, których nie ma w palecie (tło wstawki, suwak, obramowanie przy
najechaniu), liczy `build_stylesheet`, bo są potrzebne tylko arkuszowi stylów.

Role kolorów niosących znaczenie są słownikami: `BADGE_COLORS` (plakietki),
`BANNER_COLORS` (banery), `DOT_COLORS` (kropka stanu). Każda rola musi istnieć
w obu wariantach, pilnują tego testy motywu.

Plakietki metadanych na karcie wyniku (typ pliku, data, autor) celowo nie mają
ról w `BADGE_COLORS` i schodzą do stylu domyślnego, czyli neutralnej szarości.
Kolor mają tylko role niosące znaczenie: rodzaj dopasowania (widoczny wyłącznie
w trybie hybrydowym, bo tylko tam różni się między wynikami), OCR i siła
dopasowania. Data w kolorze sukcesu sugerowała stan, którego nie ma.

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
| `NavDelegate` | pigułka zaznaczenia w panelu nawigacji |
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
  bo wybrany segment jest pogrubiony i inaczej ucinałby pierwszą literę;
* `NavDelegate` rysuje pigułkę, bo arkusz stylów nie umie narysować prostokąta
  wewnątrz pozycji listy. Pozostały wygląd pozycji nadal pochodzi z arkusza.

## Dwa wskaźniki wyboru

Interfejs ma dwa miejsca, w których widać wybraną pozycję, i każde ma inny
wzorzec, bo odpowiada na inne pytanie.

**Panel nawigacji: pigułka.** Zaznaczona pozycja ma neutralne, zaokrąglone tło,
a przy jej lewej krawędzi leży pigułka w kolorze akcentu (3 na 16 pikseli, w pełni
zaokrąglona). Wcześniej zaznaczenie rysowała lewa krawędź obramowania, ale rogi
pozycji są zaokrąglone, więc ta krawędź była przycinana łukiem i wyglądała jak
zakrzywiony pasek, a nie jak wskaźnik. Kolor niesie wyłącznie pigułka, tło jest
neutralne w obu wariantach palety.

**Zakładki: podkreślenie.** Zakładka jest samym napisem z podkreśleniem wybranej
pozycji, bez linii toru pod całym paskiem: tor kończył się przed polem filtra
i wyglądał jak urwana ramka. Zakładka w pudełku z obramowaniem wygląda jak
przycisk, czyli tak samo jak akcje nad nią, a przecież nie jest akcją: nie robi
nic poza zmianą widoku. Panel zakładek nie ma ramki, bo tabele w środku mają
własne obramowanie.

Ekrany z polem „Filtruj wiersze" obok zakładek używają `widgets/tabs.py`
(`TabPanel`): osobny `QTabBar` w wierszu układu nad `QStackedWidget`.
`QTabWidget.setCornerWidget` przycinał pole z prawej strony, także poza trybem
dokumentowym, bo geometria rogu w stylu arkuszowym nie zgadza się z szerokością
kontrolki.

## Dostępność

Kontrolka bez własnego napisu dostaje `accessibleName`: przyciski ikonowe
biorą nazwę z podpowiedzi, pola filtrów z tekstu zastępczego, a pole
zapytania, porządek wyników i listy nawigacji mają nazwy z bloku dostępności
w `i18n.py`. Okna dialogowe służą wyłącznie błędom i pytaniom; sukcesy
operacji pokazuje baner na ekranie albo pasek stanu.

Ustawienia są przypięte na dole panelu nawigacji jako osobna lista, wzorem
nawigacji Windows 11. Wybór jest uzgadniany między listami tak, żeby zaznaczona
była zawsze dokładnie jedna pozycja (`MainWindow._on_bottom_nav_changed`).
Diagnostyka nie ma pozycji nawigacji: to narzędzie serwisowe, więc jest drugą
zakładką ekranu Ustawienia i odświeża dane sama przy każdym pokazaniu.

## Ruch i cień

Ruch jest oszczędny, wzorem Fluent: jedno przejście 150 ms na pojawienie
(baner, rozwinięcie panelu filtrów), krzywa `OutCubic`, nic nie sprężynuje.
Wszystko przez `widgets/motion.py`. Ruch wyłącza się w całości, gdy system
zgłasza ograniczenie animacji, oraz na platformie `offscreen` (determinizm
testów).

Cień występuje wyłącznie w motywie jasnym i tylko na polu zapytania oraz
kartach wyników (rozmycie 14 px, krycie około 8%). W ciemnym motywie cienia
nie ma: na ciemnym tle byłby poświatą.

W czasie wyszukiwania pustą listę wypełniają trzy statyczne zarysy kart
(`widgets/skeleton.py`): zapowiadają układ wyników bez migotania, więc
działają tak samo przy systemowym ograniczeniu animacji. Gdy na ekranie
są już wyniki, zostają do nadejścia nowych i zarysy się nie pojawiają.

Akcent pochodzi z ustawień personalizacji Windows (`system_accent_color`),
z korektą jasności do kontrastu 4,5 wobec stałego koloru napisu na akcencie
(`palette_with_accent`). Kolor napisu się nie zmienia, bo w tym kolorze są
wygenerowane glify przycisków akcentowych. Pasek tytułu okna idzie za motywem
aplikacji (`apply_title_bar_theme`), także w oknach dialogowych.

Okno główne ma tło Mica (`enable_mica`, Windows 11 22H2 wzwyż), z twardym
fallbackiem do obecnych kolorów. Przezroczyste jest okno, panel nawigacji
i pasek stanu; karty i pola pozostają nieprzezroczyste. Znane ograniczenie:
przy motywie wymuszonym przeciwnie do systemowego pasek tytułu okna z Mica
podąża za jasnością systemu. Domyślny motyw `system` nie ma tej niespójności.
Wyłącznik jest w Ustawieniach i w `ui.mica`.

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
9. **Styl roli przycisku wymaga jawnej reguły dla stanu wyłączonego.**
   Selektor z identyfikatorem (`QPushButton#Danger`) wygrywa specyficznością
   z samą pseudoklasą (`QPushButton:disabled`). Bez reguły
   `#Danger:disabled` wyłączony przycisk zostaje czerwony i wygląda na
   klikalny. Stan wyłączony osłabia napis, obramowanie i glif.
10. **Glif na przycisku akcentowym bierze się z `accent_icon`, nie z `theme_icon`.**
   Napis na przycisku `#Primary` ma kolor `accent_text`, więc ikona musi mieć ten
   sam kolor. W trybie ciemnym akcent jest jasny, a napis na nim ciemny: glif
   z `theme_icon` byłby wtedy jasny i ikona miałaby przeciwny kolor niż napis
   obok niej. Każdy glif używany na akcencie musi być w `ACCENT_GLYPHS`
   w `tools/make_theme_icons.py`. Pilnuje tego test
   `test_glify_na_przyciskach_akcentowych_maja_kolor_tekstu_na_akcencie`, który
   odczytuje kolor glifu z wyrenderowanej ikony każdego przycisku akcentowego
   w oknie głównym.

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
