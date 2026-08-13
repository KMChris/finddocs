# Serwer OCR PP-OCRv6_medium na GPU

Kontener z modelem PP-OCRv6_medium wystawionym przez PaddleX jako usługa HTTP.
FindDocs łączy się z nim po wybraniu silnika **Zdalny serwer na GPU** na ekranie
Źródła i konfiguracja, karta Rozpoznawanie tekstu.

Opis funkcji od strony aplikacji: [docs/ocr-gpu-api.md](../../docs/ocr-gpu-api.md).

## Wymagania

* Docker z obsługą GPU (Docker Desktop z WSL2 albo NVIDIA Container Toolkit).
* Karta NVIDIA i sterownik od wersji 550.54.14 (CUDA 12.6).
* Około 20 GB miejsca na obraz i 6 GB pamięci karty przy pracy.

## Uruchomienie

```bash
docker compose -f deploy/ppocr/compose.yaml up -d --build
```

Pierwsze budowanie pobiera koło `paddlepaddle-gpu` (około 2 GB) oraz wagi modeli.
Modele trafiają do obrazu, więc uruchomiony kontener nie potrzebuje sieci.

Sprawdzenie stanu:

```bash
curl http://127.0.0.1:8868/health
```

Zatrzymanie:

```bash
docker compose -f deploy/ppocr/compose.yaml down
```

## Co jest w środku

| Plik | Rola |
| --- | --- |
| `Dockerfile` | obraz: Python, paddlepaddle-gpu, paddleocr, wtyczka serwowania |
| `pipeline.yaml` | potok OCR przypięty do modeli PP-OCRv6_medium |
| `warmup.py` | pobranie wag do obrazu w trakcie budowania |
| `compose.yaml` | uruchomienie z rezerwacją karty i portem na pętli zwrotnej |

Model jest przypięty w `pipeline.yaml`, a nie brany z wartości domyślnych
pakietu. Nazwa modelu wchodzi do klucza pamięci podręcznej OCR po stronie
aplikacji, więc po jej zmianie trzeba poprawić ustawienie `ocr.remote_api_model`.

## Bezpieczeństwo

Serwer nie ma uwierzytelnienia i `compose.yaml` wystawia port wyłącznie na
`127.0.0.1`. Do pracy poza jednym komputerem postaw przed nim odwrotne proxy
z TLS i kluczem API, a w aplikacji ustaw adres proxy (`https://...`) i nagłówek
klucza. Aplikacja wymaga https dla każdego hosta poza `localhost`.

## Kontrakt HTTP

`POST /ocr`, ciało żądania:

```json
{
  "file": "<obraz strony w base64>",
  "fileType": 1,
  "useDocOrientationClassify": false,
  "useDocUnwarping": false,
  "useTextlineOrientation": true,
  "visualize": false
}
```

Odpowiedź:

```json
{
  "errorCode": 0,
  "result": {
    "ocrResults": [
      {"prunedResult": {"rec_texts": ["..."], "rec_scores": [0.99], "dt_polys": [[[0, 0]]]}}
    ]
  }
}
```

To standardowy kontrakt serwowania PaddleX, więc aplikacja zadziała także
z serwerem PaddleOCR postawionym przez organizację w inny sposób.
