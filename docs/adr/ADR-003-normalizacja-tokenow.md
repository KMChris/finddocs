# ADR-003: Własna warstwa normalizacji i kolumna `folded`

**Stan:** przyjęta
**Data:** lipiec 2026

## Kontekst

Wymaganie: zapytanie `24.07.2015`, `2015-07-24` i `24 lipca 2015` ma znaleźć te
same dokumenty. To samo dotyczy numeru rachunku w trzech zapisach i kwot.
Osobno: pisownia z polskimi znakami i bez nich ma dawać ten sam wynik.

Tokenizator FTS5 `unicode61 remove_diacritics 2` składa znaki diakrytyczne,
ale ma dwa ograniczenia:

1. Polskie `ł` jest w Unicode osobną literą, a nie `l` ze znakiem
   diakrytycznym, więc nie zostaje złożone. `Łódź` i `Lodz` trafiałyby do
   różnych tokenów.
2. Tokenizator dzieli tekst na znakach interpunkcyjnych, więc `24.07.2015`
   rozpada się na trzy liczby, a `FV/2015/07/123` na cztery.

## Decyzja

Trzy kolumny w tabeli `chunks`, każda o innym zadaniu:

| Kolumna | Zawartość | Rola |
| --- | --- | --- |
| `text` | oryginalna pisownia | wyświetlanie użytkownikowi |
| `folded` | tekst po własnym składaniu znaków | wyszukiwanie słów |
| `norm` | tokeny znormalizowane | wyszukiwanie wartości |

Indeksowane są `folded` i `norm`. Składanie znaków robi aplikacja
(`normalization/text.py`) z własną mapą, która obejmuje `ł`, `Ł` i inne
przypadki nieobsługiwane przez NFKD.

Tokeny w `norm` są **czysto alfanumeryczne**, bez znaków interpunkcyjnych:

| Wzorzec | Token |
| --- | --- |
| data dzienna | `dat20150724` |
| miesiąc | `mon201507` |
| rok | `yea2015` |
| ciąg cyfr | `num384675` |
| numer rachunku | `acc00123456789012345678901234` |
| kwota w groszach | `kwo123456` |
| identyfikator | `idf...` |
| NIP, REGON, PESEL | `nip...`, `reg...`, `pes...` |

## Rozważane alternatywy

**Poleganie wyłącznie na `remove_diacritics 2`.** Nie działa dla `ł`, czyli dla
znaczącej części polskich słów.

**Własny tokenizator FTS5.** SQLite pozwala zarejestrować tokenizator w C.
Wymagałoby to rozszerzenia binarnego kompilowanego na każdą platformę.
Nieproporcjonalne do zysku.

**Rozwijanie zapytania na warianty zapisu.** Zamiast normalizować przy
indeksowaniu, można by przy wyszukiwaniu generować wszystkie warianty daty
i łączyć je operatorem `OR`. Działa, ale liczba wariantów rośnie, a wyszukiwanie
zwalnia. Normalizacja płaci ten koszt raz, przy indeksowaniu.

## Konsekwencje

Dobre:

* trzy zapisy numeru rachunku dają jeden token, więc jeden zbiór wyników;
* `Łódź` i `Lodz` znajdują to samo;
* użytkownik widzi dokument w oryginalnej pisowni, mimo że szukał bez ogonków;
* wyszukiwanie jest szybkie, bo cała praca dzieje się przy indeksowaniu.

Kosztowne:

* indeks jest większy o kolumnę `norm`;
* **zmiana reguł normalizacji unieważnia indeks.** Dlatego istnieje
  `NORMALIZATION_VERSION` i skrót `index_compat_hash`. Zmiana reguł bez
  podniesienia wersji sprawiłaby, że indeks byłby niespójny i nikt by o tym
  nie wiedział. To najgroźniejszy sposób zepsucia tej aplikacji.
