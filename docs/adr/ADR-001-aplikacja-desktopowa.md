# ADR-001: Aplikacja desktopowa bez serwera

**Stan:** przyjęta
**Data:** lipiec 2026

## Kontekst

Wymagania mówią wprost: użytkownik końcowy nie dotyka terminala, nie uruchamia
serwera i nie wpisuje adresu w przeglądarce. Aplikacja ma się uruchamiać
z menu Start i działać bez połączenia z siecią poza SharePointem. Dokumenty,
zapytania i indeks nie mogą opuszczać komputera.

## Decyzja

Jeden proces desktopowy na Windows 11. Cały stan aplikacji leży w katalogu
`%LOCALAPPDATA%\FindDocs`. Nie ma usługi systemowej, serwera HTTP, brokera
zadań ani bazy zewnętrznej.

Indeks jest prywatny dla użytkownika i zbudowany na jego uprawnieniach.

## Rozważane alternatywy

**Serwer lokalny z interfejsem w przeglądarce.** Wygodny w budowie, ale łamie
wymaganie wprost: użytkownik musiałby startować proces i znać adres. Do tego
port nasłuchujący na localhost to powierzchnia ataku, której nie musimy mieć.

**Usługa systemowa indeksująca w tle.** Wymaga uprawnień administratora przy
instalacji i komplikuje model uprawnień: usługa działa na innym koncie niż
użytkownik, więc token SharePoint przestaje pasować.

**Instalacja centralna ze wspólnym indeksem.** Wymagałaby serwera, własnego
modelu uprawnień i replikacji uprawnień SharePoint po stronie aplikacji.
To osobny produkt, nie ta aplikacja.

## Konsekwencje

Dobre:

* instalacja bez uprawnień administratora, w profilu użytkownika;
* brak portów nasłuchujących i brak powierzchni sieciowej;
* uprawnienia rozwiązane w najprostszy możliwy sposób: użytkownik widzi to,
  do czego i tak ma dostęp;
* kopia zapasowa to skopiowanie katalogu.

Kosztowne:

* każdy użytkownik buduje własny indeks, więc ta sama biblioteka SharePoint
  jest indeksowana wielokrotnie w organizacji;
* indeksowanie zajmuje zasoby stacji roboczej;
* brak centralnego monitorowania.

Pierwszy koszt jest realny przy dużych zbiorach. Rozwiązaniem byłby wariant
z indeksem współdzielonym, ale wymaga on serwera i własnego modelu uprawnień,
czyli innego produktu. Świadomie tego nie robimy.
