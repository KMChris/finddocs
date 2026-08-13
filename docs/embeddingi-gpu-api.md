# Embeddingi na GPU i zdalne API

Dokument dla administratora. Opisuje funkcje wprowadzone w wersji 0.2.x:

1. obliczenia lokalnego modelu embeddingów na karcie graficznej (DirectML albo CUDA);
2. batchowe osadzanie fragmentów wielu dokumentów naraz podczas indeksowania;
3. zdalnego dostawcę embeddingów z uwierzytelnieniem kluczem API
   (domyślnie kontrakt zgodny z OpenAI);
4. nazwane profile dostawcy embeddingów do przełączania między konfiguracjami.

Domyślne ustawienia pozostają bez zmian: model lokalny, obliczenia na CPU,
zero ruchu wychodzącego. Każdą z opisanych funkcji trzeba włączyć świadomie.

## Obliczenia na GPU

### Zasady

* Sesja ONNX Runtime powstaje zawsze z jawnej listy providerów liczących
  lokalnie: `DmlExecutionProvider`, `CUDAExecutionProvider`,
  `CPUExecutionProvider`. Lista aktywna jest sprawdzana po utworzeniu sesji.
* `AzureExecutionProvider` (provider zdalny) pozostaje zakazany i nigdy nie
  trafia do sesji, nawet jeśli środowisko go wystawia.
* CPU pozostaje ścieżką domyślną i rezerwową. Gdy żądanego urządzenia nie ma,
  obliczenia idą na CPU, a rozjazd widać w logu, w diagnostyce i w opisie
  dostawcy (pole `urzadzenie_zadane`).
* Ten sam model daje te same wektory na CPU i GPU (różnice dotyczą ostatnich
  miejsc po przecinku), więc zmiana urządzenia nie unieważnia indeksu
  i nie wymaga przebudowy.

### Instalacja pakietu

Standardowy pakiet `onnxruntime` zawiera wyłącznie provider CPU. Sam sterownik
karty graficznej nie wystarczy: kod providera GPU jest skompilowany w wariancie
pakietu onnxruntime, a nie w sterowniku, więc bez odpowiedniego wariantu
`onnxruntime.get_available_providers()` nie zwróci urządzenia GPU.

Instalacja przez dodatek pakietu, dwoma poleceniami:

```bash
pip install "finddocs[gpu-dml]"
pip install --force-reinstall --no-deps onnxruntime-directml
```

Dla CUDA odpowiednio `finddocs[gpu-cuda]` i `onnxruntime-gpu`. Drugi krok jest
konieczny: wszystkie warianty pakietu onnxruntime mają ten sam pakiet importowy,
a pip nie gwarantuje kolejności instalacji kół współdzielących pliki. W próbie
kontrolnej po jednym poleceniu aktywny pozostał wariant CPU z zależności
bazowej; drugie polecenie przywraca wariant GPU niezależnie od kolejności.
To samo polecenie naprawia środowisko, gdy późniejsza aktualizacja przywróci
wariant CPU. Gotowe zestawy z OCR instalują presety `preset-nvidia`
i `preset-gpu`, opisane w [instalacji z PyPI](instalacja-pip.md).

Wybór wariantu:

* CUDA (`gpu-cuda`) działa tylko na kartach NVIDIA i jest najszybszym
  zmierzonym wariantem (pomiar niżej). Dodatek instaluje biblioteki CUDA
  i cuDNN jako zwykłe pakiety pip (`nvidia-*`, około 2 GB na dysku), więc
  poza aktualnym sterownikiem NVIDIA nic nie trzeba instalować ręcznie.
  ONNX Runtime nie znajduje tych bibliotek sam: aplikacja ładuje je tuż
  przed utworzeniem sesji (`preload_cuda_libraries`). Z tego samego powodu
  ręczna próba w interpreterze wymaga wywołania `onnxruntime.preload_dlls()`
  przed utworzeniem sesji.
* DirectML (`gpu-dml`) działa na kartach AMD, Intel i NVIDIA i potrzebuje
  wyłącznie zwykłego sterownika graficznego (DirectX 12). To właściwy wariant
  dla kart innych niż NVIDIA; na karcie NVIDIA jest wyraźnie wolniejszy
  od CUDA.

Uwaga na wersje: linia onnxruntime-directml kończy się obecnie na 1.24.4
i nie idzie równo z linią CPU (1.28.0); interfejs używany przez aplikację jest
zgodny w obu wersjach. Gdy biblioteki providera GPU nie dają się załadować,
sesja powstaje na CPU: aplikacja wykrywa to po utworzeniu sesji, zapisuje
ostrzeżenie w logu i pokazuje faktyczne urządzenie w diagnostyce.

Stan środowiska pokazuje `finddocs model device` (pozycja
`dostepne_w_srodowisku`) oraz ekran Diagnostyka.

### Kwantyzacja, urządzenie i rozmiar paczki

Wariant INT8 modelu jest zoptymalizowany pod procesor. Na karcie graficznej
działa wolniej od pełnego FP32 i daje wektory minimalnie różne od liczonych
na CPU. Pomiar na stacji deweloperskiej z kartą NVIDIA GeForce RTX 3090
(MMLW base, batch 32, identyczne fragmenty po 300-700 znaków na każdym
urządzeniu; DirectML mierzony na tej samej karcie co CUDA):

| Wariant | CPU | GPU (DirectML) | GPU (CUDA) |
| --- | --- | --- | --- |
| INT8 | 98 fragm./s | 197 fragm./s | 91 fragm./s |
| FP32 | 52 fragm./s | 405 fragm./s | 727 fragm./s |

Wnioski z pomiaru:

* Na karcie NVIDIA najszybszy jest CUDA z modelem FP32: 727 fragm./s wobec
  52 na CPU, czyli 14 razy szybciej. DirectML na tej samej karcie osiąga 405.
* Wariant INT8 na CUDA jest wolniejszy nawet od CPU, a na DirectML dwa razy
  wolniejszy od FP32. Kwantyzacja pozostaje optymalizacją wyłącznie dla
  procesora.
* Karta graficzna potrzebuje dużych paczek (`batch_size`). CUDA FP32: 618
  fragm./s przy batch 8, 774 przy 64, 791 przy 128. DirectML FP32: 170 przy 8,
  367 przy 64, 383 przy 128. Zalecenie: na GPU ustaw batch 64; wartość 128
  dodaje już tylko 2-5%.
* Na CPU domyślny batch 8 pozostaje optymalny. Fragmenty w paczce są
  dopełniane do najdłuższego, więc duże paczki mieszają długości i INT8
  zwalnia: 104 fragm./s przy batch 8, 93 przy 128.

Wektory FP32 z CPU, DirectML i CUDA są identyczne (podobieństwo kosinusowe
1.000000 na wspólnej próbce), więc zmiana samego urządzenia nie wymaga
przebudowy indeksu. Wektory INT8 różnią się między urządzeniami (najniższe
zmierzone podobieństwo 0.9950), co jest dodatkowym powodem, żeby na karcie
graficznej używać FP32. Zalecenie: na GPU wyłącz wariant INT8
(`quantized: false`); ta zmiana unieważnia część wektorową indeksu, jak każda
zmiana wariantu modelu, więc wykonaj ją razem z planową przebudową.

### Włączenie

W GUI: **Źródła i konfiguracja, zakładka Wyszukiwanie semantyczne, karta
Obliczenia embeddingów** (dostawca: Model lokalny). Karta pokazuje
urządzenia wykryte w bieżącym środowisku.

Z wiersza poleceń:

```bash
finddocs model device            # podgląd i dostępność
finddocs model device dml --batch 64
finddocs model device auto
finddocs model device cpu
```

Wartość `auto` wybiera CUDA, potem DirectML, na końcu CPU. Przy przejściu na
GPU podnieś `--batch` (fragmenty w jednym przebiegu modelu) z domyślnych 8
do 64: małe paczki nie wykorzystują przepustowości karty, a wartości powyżej
64 dodają już tylko kilka procent (pomiar wyżej).

## Batchowe osadzanie wielu dokumentów

Małe dokumenty dają po kilka fragmentów. Bez batchowania każdy dokument był
osadzany osobnym wywołaniem modelu, więc paczki były wielokrotnie mniejsze od
skonfigurowanego `batch_size`. Podczas indeksowania fragmenty kolejnych
dokumentów są teraz zbierane do bufora i osadzane wspólnie, a każdy dokument
jest potem zapisywany własną transakcją, tak jak wcześniej.

Ustawienia w sekcji `indexing`:

```json
"indexing": {
  "embed_batch_documents": 8,
  "embed_batch_chunks": 128
}
```

* `embed_batch_documents` mówi, ile dokumentów może czekać na wspólne
  osadzenie. Wartość 1 wyłącza tryb batchowy i przywraca poprzednie zachowanie.
* `embed_batch_chunks` ogranicza łączną liczbę fragmentów w buforze, żeby duże
  pliki nie zawyżały zużycia pamięci.

Gwarancje spójności:

* bufor jest opróżniany przed każdym checkpointem, więc licznik postępu nigdy
  nie wyprzedza zapisów;
* anulowanie zadania porzuca bufor, a porzucone dokumenty wracają przy
  następnym skanowaniu;
* błąd dostawcy nie zatrzymuje zadania: dokumenty z bufora są zapisywane bez
  wektorów (status `partial`) i uzupełniane przy kolejnym przebiegu.

## Zdalne API embeddingów z kluczem API

### Ostrzeżenie

Włączenie zdalnego dostawcy oznacza, że treść fragmentów dokumentów będzie
wysyłana na skonfigurowany adres w celu policzenia wektorów. Zapytania
użytkownika również. Włączaj wyłącznie dla API zaakceptowanego przez
organizację, na przykład wewnętrznego klastra GPU. Specyfikacja zabrania
wysyłania dokumentów do publicznych usług chmurowych.

### Zabezpieczenia

* Dostawca jest domyślnie wyłączony. Włączenie wymaga podania adresu i jawnego
  przełączenia; sam wpis adresu niczego nie uruchamia.
* Polityka sieciowa dopuszcza wyłącznie host z podanego adresu. Żaden inny host
  nie przejdzie, nawet po włączeniu kategorii.
* Serwery zdalne wymagają HTTPS bez wyjątków. Zwykłe HTTP jest możliwe wyłącznie
  do tego samego komputera (`localhost`, `127.0.0.1`, `::1`) i wyłącznie po
  jawnym włączeniu opcji, bo taki ruch nie opuszcza maszyny. Opis niżej,
  w części o lokalnym serwerze modeli.
* Klucz API trafia do Menedżera poświadczeń Windows (albo DPAPI), nigdy do
  pliku konfiguracyjnego ani logów.
* Treść fragmentów i zapytań nie jest logowana. W logu pojawiają się tylko
  liczby tekstów, kody odpowiedzi i czasy.

### Kontrakty

Domyślnym kontraktem jest `openai`, czyli standard OpenAI `/v1/embeddings`
obsługiwany przez vLLM, TEI i typowe bramki API. Kontrakt `finddocs` to
opcjonalne rozszerzenie dla serwera, który chce sam rozróżniać rodzaj tekstu.

| Kontrakt | Żądanie | Zastosowanie |
| --- | --- | --- |
| `openai` (domyślny) | `POST {adres}/embeddings` z `{"model": "...", "input": [...], "encoding_format": "float"}` | serwery zgodne z OpenAI: vLLM, TEI, bramki API |
| `finddocs` | jak `openai`, plus pole `"kind": "query"/"passage"` | serwer, który sam stosuje przedrostki według rodzaju tekstu |

Obie odpowiedzi mają postać `{"data": [{"embedding": [...], "index": 0}, ...]}`;
pole `index` jest opcjonalne i pozwala zwracać wiersze w dowolnej kolejności.
Dla kontraktu `openai` adres powinien zawierać segment wersji, np.
`https://embeddingi.example.com/v1`.

Jedyna różnica między kontraktami to sposób rozróżniania zapytań od treści
przy modelach asymetrycznych (na przykład MMLW wymaga przedrostka
`zapytanie: ` wyłącznie dla zapytań):

* przy kontrakcie `openai` przedrostki dokleja aplikacja przed wysyłką;
  ustawia się je w polach przedrostków karty Obliczenia embeddingów i wchodzą
  do skrótu zgodności wektorów;
* przy kontrakcie `finddocs` żądanie niesie pole `kind`, a przedrostki stosuje
  serwer; pola przedrostków w aplikacji zwykle zostają wtedy puste, żeby nie
  doklejać ich podwójnie.

Wektory są zawsze normalizowane L2 po stronie aplikacji. Wymiar odpowiedzi jest
sprawdzany przy każdym żądaniu. Błędy przejściowe (408, 425, 429, 5xx, błędy
transportu) są ponawiane z wykładniczym odczekaniem; odmowa uwierzytelnienia
nie jest ponawiana i od razu daje czytelny komunikat.

### Konfiguracja

W GUI: **Źródła i konfiguracja, zakładka Wyszukiwanie semantyczne, karta
Obliczenia embeddingów**, dostawca **Zdalne API organizacji**. Z wiersza
poleceń:

```bash
finddocs model api --url https://embeddingi.example.com/v1 --protocol openai --model mmlw-duzy --dimension 1024
finddocs model api-key
finddocs model api --enable
```

`finddocs model api-key` pobiera klucz z ukrytego wejścia i zapisuje go
w magazynie poświadczeń (`--clear` usuwa). Nagłówek uwierzytelnienia to
domyślnie `Authorization: Bearer`; inne API wskazuje się opcją
`--key-header`, np. `--key-header api-key`.

Pola w `settings.json` (bez klucza, ten nigdy nie jest zapisywany w pliku):

```json
"embedding": {
  "provider": "internal_api",
  "internal_api_enabled": true,
  "internal_api_url": "https://embeddingi.example.com/v1",
  "internal_api_protocol": "openai",
  "internal_api_model": "mmlw-duzy",
  "internal_api_dimension": 1024,
  "internal_api_batch_size": 64,
  "internal_api_timeout_seconds": 30.0,
  "internal_api_max_retries": 3,
  "internal_api_key_header": ""
}
```

Zgoda na zwykłe HTTP do tego komputera leży poza sekcją `embedding`, bo dotyczy
polityki sieciowej całej aplikacji:

```json
"allow_plain_http_localhost": false
```

### Lokalny serwer modeli (Ollama, LM Studio, llama.cpp)

Serwer uruchomiony na tym samym komputerze zwykle nie wystawia TLS, a wymaganie
HTTPS dotyczy serwerów zdalnych. Dla adresu lokalnego trzeba więc jednorazowo
zezwolić na zwykłe HTTP:

* w GUI: karta **Obliczenia embeddingów**, dostawca **Zdalne API organizacji**,
  pole wyboru **Zezwól na http do tego komputera**;
* z wiersza poleceń: `finddocs model api --allow-http-localhost`
  (cofnięcie: `--no-allow-http-localhost`).

Zgoda obejmuje wyłącznie `localhost`, `127.0.0.1` i `::1`. Adres dowolnego
innego serwera nadal wymaga HTTPS, niezależnie od tego ustawienia. Stan opcji
widać na ekranie diagnostyki w polu `http_do_localhost` polityki sieciowej.

Przykład dla Ollamy z modelem `qwen3-embedding:8b` (kontrakt `openai`, wymiar
4096, brak klucza API):

```bash
finddocs model api --url http://127.0.0.1:11434/v1 --protocol openai --model qwen3-embedding:8b --dimension 4096 --batch 32 --allow-http-localhost --enable
```

Model instaluje się po stronie Ollamy poleceniem `ollama pull qwen3-embedding:8b`.
Qwen3-Embedding jest asymetryczny: treść idzie bez przedrostka, a zapytanie
z instrukcją. Pole przedrostka zapytania w GUI jest jednoliniowe, więc zamiast
zalecanego złamania wiersza przed `Query:` wpisuje się wszystko w jednej linii,
co w pomiarach dało praktycznie ten sam wynik:

```
Instruct: Given a search query, retrieve relevant passages from the document collection Query: 
```

Przedrostek kończy się spacją. Przedrostek treści zostaje pusty. Oba pola
wchodzą do skrótu zgodności wektorów, więc ich zmiana wymaga przebudowy
części semantycznej indeksu.

Wymiar 4096 to ponad pięć razy więcej niż w modelu MMLW (768), czyli 16 KB na
wektor. Przy 100 tysiącach fragmentów to około 1,6 GB samych wektorów.

### Zgodność indeksu

Przełączenie dostawcy oraz zmiana kontraktu, nazwy modelu albo wymiaru
zmieniają przestrzeń wektorów i unieważniają część semantyczną indeksu:

```bash
finddocs maintenance rebuild --vectors-only
finddocs index
```

Zmiana adresu, liczby tekstów w żądaniu, limitów czasu i liczby ponowień nie
wpływa na zgodność indeksu. Do czasu przebudowy wyszukiwanie dokładne działa
bez zmian.

### Awaria zdalnego API

Gdy API nie odpowiada przy starcie aplikacji, wyszukiwanie semantyczne jest
oznaczane jako niedostępne, a tryb dokładny działa normalnie. Gdy API zawiedzie
w trakcie indeksowania, dokumenty są zapisywane bez wektorów ze statusem
`partial` i uzupełniane przy następnym skanowaniu po przywróceniu usługi.

## Profile dostawcy embeddingów

Model lokalny i zdalne API wykluczają się: w danej chwili aktywny jest
dokładnie jeden dostawca, a gdy aktywny jest zdalny, karta modelu lokalnego
w GUI jest ukryta. Do szybkiego przełączania służą nazwane profile, czyli
migawki kompletu ustawień dostawcy: model lokalny z urządzeniem obliczeń
i wariantem, albo zdalne API z adresem, kontraktem, modelem i wymiarem.

Zasady:

* Aktywacja profilu przełącza całą konfigurację dostawcy naraz. Aktywacja
  profilu lokalnego wyłącza zdalne API i zamyka jego kategorię ruchu
  w polityce sieciowej.
* Profil zmienia się wyłącznie jawnie: przez zapisanie bieżących ustawień pod
  jego nazwą albo przez aktywację (która odświeża migawkę po synchronizacji
  z manifestem modelu). Zwykła edycja ustawień nigdy nie nadpisuje profilu;
  gdy ustawienia przestają się zgadzać z aktywnym profilem, znika samo
  wskazanie profilu aktywnego, a nowe ustawienia można zapisać jako profil.
* Przełączenie na profil o innym modelu, kontrakcie albo wymiarze unieważnia
  część semantyczną indeksu, jak każda taka zmiana; aplikacja pokazuje wtedy
  zalecenie przebudowy, a wyszukiwanie dokładne działa dalej.
* Klucz API nie jest częścią profilu: leży w magazynie poświadczeń pod jedną
  nazwą, wspólną dla całej konfiguracji zdalnego API.

W GUI: karta **Profile dostawcy embeddingów** na zakładce Wyszukiwanie
semantyczne (lista profili, Aktywuj, Zapisz bieżące jako profil, Usuń).
Z wiersza poleceń:

```bash
finddocs model profile
finddocs model profile save Klaster
finddocs model profile use Klaster
finddocs model profile remove Klaster
```

Konfiguracje zapisane przed wprowadzeniem profili dostają pierwszy profil
automatycznie, zbudowany z bieżących ustawień.
