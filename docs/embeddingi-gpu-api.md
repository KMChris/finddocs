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

Standardowy pakiet `onnxruntime` zawiera wyłącznie provider CPU. Obliczenia na
GPU wymagają zamiany pakietu w tym samym środowisku Pythona:

```bash
pip uninstall onnxruntime
pip install onnxruntime-directml
```

DirectML działa na kartach AMD, Intel i NVIDIA na Windows 11 i nie wymaga
dodatkowych sterowników. Wariant CUDA (`onnxruntime-gpu`) działa tylko na
kartach NVIDIA i wymaga zgodnych wersji CUDA oraz cuDNN.

### Włączenie

W GUI: **Źródła i konfiguracja, Ustawienia modelu, Obliczenia modelu
lokalnego**. Okno pokazuje urządzenia wykryte w bieżącym środowisku.

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

W GUI: **Ustawienia modelu, Zdalne API embeddingów**. Z wiersza poleceń:

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
