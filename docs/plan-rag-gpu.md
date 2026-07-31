# Plan rozwoju: akceleracja GPU i generowanie odpowiedzi

Dokument opisuje, jak rozszerzyć FindDocs o akcelerację sprzętową oraz
o generowanie odpowiedzi na podstawie znalezionych dokumentów. Żadna z tych
rzeczy nie jest częścią wersji 0.1.0 i **żadnej nie należy uruchamiać bez
świadomej decyzji organizacji**.

Aplikacja jest przygotowana na oba kierunki: warstwa dostawców embeddingów
i polityka sieciowa mają na to miejsce. Nie oznacza to, że są gotowe.

## Etap 1: akceleracja GPU dla embeddingów

### Po co

Embeddingi na CPU przetwarzają około 351 fragmentów na sekundę w wariancie
INT8 (pomiar z [raportu PoC](raport-poc.md)). Przy zbiorze stu tysięcy
fragmentów daje to około pięciu minut samego liczenia wektorów. To akceptowalne.
GPU miałoby sens dopiero przy zbiorach o rząd wielkości większych albo przy
modelu w wariancie `large`.

**Wniosek: to nie jest pilne.** Wąskim gardłem indeksowania jest OCR,
nie embeddingi.

### Jak

Warstwa dostawców (`providers/base.py`) już to umożliwia. Wystarczy nowa
implementacja `EmbeddingProvider` z inną listą providerów ONNX Runtime:

| Wariant | Provider ONNX Runtime | Uwagi |
| --- | --- | --- |
| DirectML | `DmlExecutionProvider` | działa na kartach AMD, Intel i NVIDIA, dobre wsparcie Windows |
| CUDA | `CUDAExecutionProvider` | tylko NVIDIA, wymaga CUDA i cuDNN o zgodnych wersjach |
| OpenVINO | `OpenVINOExecutionProvider` | akceleracja na układach graficznych Intel i na NPU |

DirectML jest pierwszym kandydatem: nie wymaga sterowników spoza standardowej
instalacji Windows i działa na kartach różnych producentów.

### Warunki, które trzeba spełnić

1. **Wybór providera musi być jawny i weryfikowany.** Obecna zasada mówi:
   sesja ONNX Runtime powstaje z jawną listą, sprawdzaną po utworzeniu.
   Ta zasada zostaje. GPU nie może się włączać samo.
2. **CPU pozostaje ścieżką domyślną.** Aplikacja musi działać bez GPU
   i schodzić do CPU, gdy akceleracja zawiedzie, z komunikatem, a nie po cichu.
3. **`AzureExecutionProvider` pozostaje zakazany.** To provider zdalny.
4. **Wektory z GPU i z CPU muszą być zgodne.** Wyniki mogą się różnić
   numerycznie na ostatnich miejscach po przecinku. Trzeba zmierzyć, czy różnica
   wpływa na ranking, i jeśli tak, potraktować zmianę providera jak zmianę
   modelu, czyli podnieść skrót zgodności i wymusić przebudowę.
5. **Rozmiar instalatora.** Pakiet `onnxruntime-directml` jest większy niż
   wersja CPU. Prawdopodobnie potrzebny byłby osobny wariant instalatora zamiast
   dokładania wszystkiego do jednego.

### Nakład

Około tygodnia pracy: implementacja dostawcy, testy zgodności wektorów, pomiary,
wariant pakowania. Plus czas na weryfikację na sprzęcie docelowym.

## Etap 2: akceleracja OCR

Bardziej opłacalna niż etap 1, bo OCR jest najdroższym elementem indeksowania.

Możliwości:

| Kierunek | Zysk | Koszt |
| --- | --- | --- |
| równoległe rozpoznawanie stron | proporcjonalny do liczby rdzeni | trzeba pilnować limitu pamięci |
| RapidOCR na GPU przez ONNX Runtime | duży dla dużych zbiorów skanów | zależności GPU, jakość niższa niż Tesseract |
| wstępna selekcja stron | pomija strony bez tekstu | ryzyko pominięcia treści |

**Zalecenie:** zacząć od zrównoleglenia stron w obrębie dokumentu. Nie wymaga
nowych zależności, a przy dokumencie stustronicowym daje zysk wprost
proporcjonalny do liczby rdzeni. Trzeba tylko utrzymać limit pamięci: obecnie
w pamięci jest jedna strona naraz, a przy równoległości byłoby ich tyle,
ile wątków.

## Etap 3: generowanie odpowiedzi (RAG)

### Stan wyjściowy

Wersja 0.1.0 **świadomie nie zawiera** żadnego modelu językowego generującego
tekst. Aplikacja jest wyszukiwarką: zwraca dokumenty i fragmenty, które w nich
faktycznie występują. Jest to wymaganie, nie ograniczenie techniczne.

Jednocześnie połowa pracy potrzebnej do RAG jest już zrobiona: fragmentacja
z zachowaniem kontekstu, embeddingi, wyszukiwanie hybrydowe i grupowanie
wyników to dokładnie warstwa pobierania (retrieval).

### Czego brakuje

1. **Model językowy działający lokalnie.** Kandydaci: Bielik (polski, licencja
   Apache-2.0), Llama 3 w wariancie instrukcyjnym, Qwen. Uruchomienie przez
   `llama.cpp` z kwantyzacją GGUF pozwala działać na CPU, ale wolno: kilka
   tokenów na sekundę na typowym procesorze biurowym. To za mało na wygodną
   pracę, więc realnie oznacza to wymaganie GPU, czyli etap 1.
2. **Warstwa układania kontekstu.** Wybór fragmentów mieszczących się w oknie
   modelu, deduplikacja, kolejność, budżet tokenów.
3. **Odsyłacze do źródeł.** Każde zdanie odpowiedzi musi wskazywać dokument
   i fragment, z którego pochodzi. Bez tego odpowiedź jest bezużyteczna
   w kontekście korporacyjnym.
4. **Obsługa braku odpowiedzi.** Model musi umieć powiedzieć „nie wiem”,
   zamiast wymyślać. To jest trudniejsze niż samo generowanie.
5. **Interfejs.** Odpowiedź obok wyników wyszukiwania, a nie zamiast nich,
   z wyraźnym oznaczeniem, że została wygenerowana.

### Ryzyka, których nie da się usunąć

**Model może zmyślić.** Nawet dobrze zbudowany RAG generuje treści, których
nie ma w dokumentach. W zastosowaniu, gdzie ktoś podejmuje decyzje na podstawie
odpowiedzi, jest to ryzyko poważne.

**Odpowiedź wygląda na pewną, nawet gdy jest błędna.** To groźniejsze niż
brak odpowiedzi. Wyszukiwarka, która nie znalazła dokumentu, mówi o tym wprost.
Model, który go nie znalazł, może napisać coś prawdopodobnego.

**Trudno zweryfikować kompletność.** Obecnie tryb dokładny gwarantuje komplet
i użytkownik to wie. Odpowiedź wygenerowana z trzech fragmentów nie daje żadnej
takiej gwarancji i trudno tę różnicę zakomunikować.

**Zużycie zasobów.** Model językowy o użytecznej jakości to kilka gigabajtów
pamięci. Na stacji roboczej konkuruje z pracą użytkownika.

### Zalecenie

RAG powinien być **osobnym, jawnie włączanym trybem**, a nie zastąpieniem
wyszukiwania. Kolejność prac:

1. wariant GPU dostawcy embeddingów (etap 1);
2. lokalny model językowy jako osobna zależność opcjonalna, nie w podstawowym
   instalatorze;
3. warstwa układania kontekstu z twardym budżetem tokenów;
4. odsyłacz do dokumentu przy każdym fragmencie użytym w odpowiedzi;
5. tryb dostępny obok wyników wyszukiwania, wyłączony domyślnie;
6. ocena jakości na zbiorze pytań i odpowiedzi przygotowanym przez organizację,
   **przed** udostępnieniem użytkownikom.

Punkt szósty jest warunkiem, nie sugestią. Bez pomiaru jakości na własnych
dokumentach nie da się powiedzieć, czy funkcja pomaga, czy szkodzi.

## Etap 4: wewnętrzne API embeddingów

Organizacja może mieć własny serwer z modelami na GPU. Wtedy nie trzeba
akceleracji na każdej stacji.

Miejsce jest przygotowane: `providers/internal_api.py` oraz kategoria ruchu
`INTERNAL_API` w polityce sieciowej z **pustą listą dozwolonych hostów**.
Uruchomienie wymaga podania adresu w konfiguracji, czyli świadomej decyzji.

Warunki:

1. Adres musi być wpisany jawnie. Kategoria nie ma domyślnych hostów.
2. Wyłącznie HTTPS, jak każdy inny ruch.
3. **Treść dokumentów opuszcza wtedy komputer.** To zmiana fundamentalnego
   założenia produktu i wymaga decyzji na poziomie organizacji, a nie
   ustawienia w pliku konfiguracyjnym bez ostrzeżenia. Interfejs musi to
   pokazać wprost.
4. Model po stronie serwera musi być tym samym modelem, którym zbudowano
   indeks, inaczej wektory nie będą porównywalne. Skrót zgodności to wykryje.

## Czego nie planujemy

| Pomysł | Powód |
| --- | --- |
| API modeli w chmurze publicznej | wykluczone przez wymagania |
| indeks współdzielony między użytkownikami | wymaga serwera i własnego modelu uprawnień, czyli innego produktu |
| chatbot jako główny interfejs | produkt jest wyszukiwarką |
| automatyczne streszczanie dokumentów | ten sam problem co RAG, bez korzyści z wyszukiwania |
| tłumaczenie maszynowe | poza zakresem |

## Podsumowanie kolejności

| Etap | Priorytet | Warunek wstępny |
| --- | --- | --- |
| zrównoleglenie OCR | wysoki, najlepszy stosunek zysku do nakładu | brak |
| GPU dla embeddingów | średni, zależny od rozmiaru zbiorów | sprzęt docelowy do pomiarów |
| wewnętrzne API embeddingów | średni, zależny od infrastruktury organizacji | serwer i decyzja o wysyłaniu treści |
| RAG | niski, wymaga wcześniejszych etapów | GPU, zbiór oceny jakości, decyzja o ryzyku |
