# ADR-010: PyInstaller onedir i Inno Setup

**Stan:** przyjęta
**Data:** lipiec 2026

## Kontekst

Użytkownik ma zainstalować aplikację i uruchomić ją z menu Start. Bez Pythona
na komputerze, bez uprawnień administratora, bez okna konsoli. Pakiet zawiera
zależności binarne: PySide6, ONNX Runtime, FAISS, numpy, pypdfium2, Pillow.

## Decyzja

**PyInstaller w trybie onedir** buduje katalog `packaging/output/FindDocs`
z plikiem wykonywalnym. Plik specyfikacji jawnie zbiera biblioteki dynamiczne
i podmoduły zależności binarnych.

**Inno Setup 6** buduje instalator instalujący w profilu użytkownika
(`PrivilegesRequired=lowest`), z polską lokalizacją, skrótem w menu Start
i opcjonalnym skrótem na pulpicie. Deinstalator pyta, czy usunąć katalog danych.

**Test dymny** jest częścią budowania: skrypt uruchamia zbudowany plik
z `--self-test`, w trybie bez okien i bez okien modalnych, i sprawdza kod
wyjścia. Budowanie kończy się błędem, gdy test nie przejdzie.

## Rozważane alternatywy

**PyInstaller onefile.** Jeden plik wygląda lepiej, ale rozpakowuje się przy
każdym starcie do katalogu tymczasowego. Przy pakiecie zawierającym model
o rozmiarze ponad 100 MB oznacza to zauważalne opóźnienie startu i problemy
z ładowaniem bibliotek natywnych.

**Nuitka.** Kompiluje do kodu maszynowego, ale kompilacja trwa długo,
a diagnozowanie problemów jest trudniejsze.

**cx_Freeze.** Słabsze wsparcie dla numpy i ONNX Runtime.

**MSIX.** Nowoczesny format Windows, ale wymaga podpisu certyfikatem zaufanym
w organizacji albo publikacji w sklepie. Nie mamy certyfikatu.

**WiX Toolset.** Instaluje dla całej maszyny i wymaga uprawnień administratora.
Złożoność nieproporcjonalna do potrzeb.

## Konsekwencje

Dobre:

* instalacja bez uprawnień administratora;
* start bez rozpakowywania;
* aktualizacja to ponowne uruchomienie instalatora, katalog danych zostaje;
* test dymny wyłapuje błędy pakowania, zanim trafią do użytkownika.

Kosztowne:

* katalog aplikacji ma około 409 MB w 948 plikach. To cena za zależności
  binarne, a przy trybie onefile byłaby podobna, tylko ukryta;
* PyInstaller wymaga jawnej pomocy przy zależnościach binarnych. Konkretny
  przypadek: numpy 2.x nie jest zbierany w całości domyślnie, a objawia się to
  błędem `No module named 'numpy._core._exceptions'`, którego komunikat myli,
  bo wygląda na brak PySide6. Plik specyfikacji zbiera numpy jawnie;
* brak podpisu kodu oznacza ostrzeżenie SmartScreen przy pierwszym
  uruchomieniu. Rozwiązaniem jest certyfikat organizacji, poza zakresem
  tej wersji.
