# ADR-006: Trzy tryby wyszukiwania i łączenie metodą RRF

**Stan:** przyjęta
**Data:** lipiec 2026

## Kontekst

Dwa wymagania są ze sobą w napięciu:

1. Wyszukiwanie dokładne musi zwrócić **wszystkie** pasujące dokumenty
   i dokładną ich liczbę, bez ukrytego limitu.
2. Wyszukiwanie znaczeniowe ma znaleźć dokumenty opisane innymi słowami, co
   z natury jest rankingiem przybliżonym.

Nie da się mieć obu naraz w jednym trybie. Próba udawania, że się da, kończy
się tym, że użytkownik nie wie, czy widzi komplet.

Dodatkowo: zapytanie w naturalnym języku często miesza opis znaczeniowy
z wartością dosłowną, na przykład „notatka ze spotkania zarządu 24.07.2015”.
Data nie może zniknąć w embeddingu całego zdania.

## Decyzja

Trzy osobne tryby, każdy z jasno opisaną gwarancją:

| Tryb | Gwarancja | Liczba wyników |
| --- | --- | --- |
| Dokładny | kompletny zbiór | dokładna |
| Semantyczny | ranking przybliżony | wielkość zbioru kandydatów |
| Hybrydowy | ranking przybliżony, dopasowania dosłowne wzmocnione | jak wyżej |

Analiza zapytania rozdziela warstwy. Wartości dosłowne (frazy w cudzysłowie,
daty, kwoty, numery rachunków, identyfikatory, nazwy plików) trafiają do
wyszukiwania dokładnego jako tokeny znormalizowane. Cały tekst zapytania idzie
do embeddingu. **Element rozpoznany jako dosłowny nigdy nie jest zastępowany
samym embeddingiem.**

Łączenie list metodą Reciprocal Rank Fusion:

```
score(d) = suma po listach z ( waga / (k + pozycja(d, lista)) )
```

ze stałą `k = 60`, plus premia `exact_boost` dla dokumentów zawierających
wszystkie wymagane elementy dosłowne.

Każda odpowiedź niosąca ranking przybliżony ma pole `total_is_exact = false`
oraz notatkę widoczną w interfejsie.

## Rozważane alternatywy

**Jeden tryb łączący wszystko.** Prostszy interfejs, ale nie da się wtedy
powiedzieć użytkownikowi, kiedy widzi komplet. Odrzucone przez wymaganie
kompletności.

**Ważona suma znormalizowanych ocen zamiast RRF.** Wymaga kalibracji skal:
bm25 i podobieństwo kosinusowe mają różne rozkłady, więc waga dobra dla jednego
zapytania jest zła dla innego. RRF operuje na pozycjach, więc jest odporny
na skalę.

**Przeszukiwanie tylko wektorowe z filtrem po tekście.** Filtr po pobraniu
k najbliższych gubi dokumenty, które są poza k, a zawierają szukaną wartość.
Dokładnie ten błąd chcemy wykluczyć.

## Konsekwencje

Dobre:

* użytkownik zawsze wie, czy widzi komplet;
* zapytanie „notatka ze spotkania zarządu 24.07.2015” stawia na pierwszym
  miejscu notatkę z tą datą, a nie tę z inną datą i identyczną resztą treści.
  Jest na to test;
* RRF nie wymaga kalibracji przy zmianie modelu.

Kosztowne:

* trzy ścieżki kodu do utrzymania i przetestowania;
* użytkownik musi rozumieć różnicę między trybami. Interfejs i dokumentacja
  tłumaczą ją krótko przy każdym wyniku;
* tryb hybrydowy jest wolniejszy, bo liczy obie listy.
