# ADR-004: FAISS HNSW jako indeks wektorowy

**Stan:** przyjęta
**Data:** lipiec 2026

## Kontekst

Wyszukiwanie semantyczne wymaga trwałego indeksu wektorowego. Musi działać
w procesie, bez serwera, na CPU, z wektorami o 768 wymiarach i skalować się do
setek tysięcy fragmentów.

## Decyzja

`faiss.IndexIDMap2` nad `IndexHNSWFlat`, metryka `METRIC_INNER_PRODUCT`,
wektory znormalizowane L2. Identyfikatorem wektora jest `chunk_id`, więc nie ma
osobnej tablicy tłumaczącej.

Dwa pliki obok bazy: `vectors.faiss` z indeksem i `vectors.json` z metadanymi
(model, wymiar, skrót zgodności, lista nagrobków).

Zapis jest atomowy: plik tymczasowy, `fsync`, zamiana nazwy.

## Rozważane alternatywy

**Chroma.** Warstwa serwera, dużo zależności, model danych zorientowany na
kolekcje z metadanymi, których i tak trzymamy w SQLite.

**Qdrant.** Serwer albo tryb wbudowany wymagający Rusta. Nadmiarowy dla jednego
użytkownika.

**`sqlite-vec`.** Kusząca opcja: wszystko w jednym pliku. Ale to rozszerzenie
SQLite, które trzeba dostarczyć jako plik binarny na każdą platformę i wersję
Pythona. Warto wrócić, gdy dojrzeje.

**Przeszukiwanie liniowe w numpy.** Wystarcza do około 50 tysięcy wektorów.
Powyżej czas rośnie liniowo, a my chcemy działać na większych zbiorach.

**IndexFlatIP zamiast HNSW.** Wynik dokładny, ale przeszukiwanie liniowe,
czyli ten sam problem co wyżej.

## Konsekwencje

Dobre:

* koła FAISS dla Windows istnieją, licencja MIT;
* HNSW daje czas wyszukiwania rosnący logarytmicznie;
* iloczyn skalarny na wektorach jednostkowych to podobieństwo kosinusowe,
  więc nie ma dodatkowego kroku obliczeniowego;
* `IndexIDMap2` pozwala użyć `chunk_id` wprost.

Kosztowne:

* **HNSW nie obsługuje `remove_ids`.** Usunięcie dokumentu nie usuwa jego
  wektorów. Realizujemy to nagrobkami w metadanych i odfiltrowaniem przy
  wyszukiwaniu. Po wielu cyklach indeksowania trzeba uruchomić kompaktację
  (`finddocs maintenance compact`), która buduje indeks od nowa;
* wynik HNSW jest przybliżeniem. Dlatego tryb semantyczny **nigdy** nie
  deklaruje kompletności, a interfejs mówi o tym wprost;
* FAISS to zależność binarna, więc PyInstaller wymaga jawnego zebrania
  bibliotek dynamicznych.
