# Embeddingi na GPU i zdalne API

Dokument dla administratora. Opisuje trzy funkcje wprowadzone w wersji 0.2.x:

1. obliczenia lokalnego modelu embeddingów na karcie graficznej (DirectML albo CUDA);
2. batchowe osadzanie fragmentów wielu dokumentów naraz podczas indeksowania;
3. zdalnego dostawcę embeddingów z uwierzytelnieniem kluczem API.

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
wariant CPU.

DirectML (`gpu-dml`) jest zalecany na Windows 11: działa na kartach AMD, Intel
i NVIDIA i potrzebuje wyłącznie zwykłego sterownika graficznego (DirectX 12).
CUDA (`gpu-cuda`) działa tylko na kartach NVIDIA i poza sterownikiem wymaga
bibliotek CUDA oraz cuDNN w wersjach zgodnych z wydaniem onnxruntime.
Uwaga na wersje: linia onnxruntime-directml kończy się obecnie na 1.24.4
i nie idzie równo z linią CPU (1.28.0); interfejs używany przez aplikację jest
zgodny w obu wersjach.

Stan środowiska pokazuje `finddocs model device` (pozycja
`dostepne_w_srodowisku`) oraz ekran Diagnostyka.

### Kwantyzacja a GPU

Wariant INT8 modelu jest zoptymalizowany pod procesor. Na karcie graficznej
działa wolniej od pełnego FP32 i może dawać wektory minimalnie różne od
liczonych na CPU. Pomiar na stacji deweloperskiej (MMLW base, batch 32,
64 fragmenty):

| Wariant | CPU | GPU (DirectML) |
| --- | --- | --- |
| INT8 | 375 fragm./s | 181 fragm./s |
| FP32 | 172 fragm./s | 615 fragm./s |

Wektory FP32 z CPU i z GPU są identyczne (podobieństwo kosinusowe 1.0), więc
zmiana samego urządzenia nie wymaga przebudowy indeksu. Zalecenie: na GPU
wyłącz wariant INT8 (`quantized: false`); ta zmiana unieważnia część wektorową
indeksu, jak każda zmiana wariantu modelu, więc wykonaj ją razem z planową
przebudową.

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

Wartość `auto` wybiera DirectML, potem CUDA, na końcu CPU. Przy przejściu na
GPU warto podnieść `--batch` (fragmenty w jednym przebiegu modelu) z domyślnych
8 do 64 lub więcej: małe paczki nie wykorzystują przepustowości karty.

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
* Polityka sieciowa dopuszcza wyłącznie host z podanego adresu i wyłącznie
  HTTPS. Żaden inny host nie przejdzie, nawet po włączeniu kategorii.
* Klucz API trafia do Menedżera poświadczeń Windows (albo DPAPI), nigdy do
  pliku konfiguracyjnego ani logów.
* Treść fragmentów i zapytań nie jest logowana. W logu pojawiają się tylko
  liczby tekstów, kody odpowiedzi i czasy.

### Kontrakty

| Kontrakt | Żądanie | Zastosowanie |
| --- | --- | --- |
| `finddocs` | `POST {adres}/embeddings` z `{"input": [...], "kind": "query"/"passage", "model": "..."}` | wewnętrzny kontrakt z zespołem klastra GPU |
| `openai` | `POST {adres}/embeddings` z `{"model": "...", "input": [...], "encoding_format": "float"}` | serwery zgodne z OpenAI: vLLM, TEI, bramki API |

Obie odpowiedzi mają postać `{"data": [{"embedding": [...]}, ...]}`. Dla
kontraktu `openai` adres powinien zawierać segment wersji, np.
`https://embeddingi.example.com/v1`.

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
