# ADR-005: Model MMLW uruchamiany w ONNX Runtime na CPU

**Stan:** przyjęta
**Data:** lipiec 2026

## Kontekst

Potrzebujemy modelu embeddingów do wyszukiwania semantycznego po polsku.
Ograniczenia: działa lokalnie, tylko na CPU, licencja dopuszczająca użycie
komercyjne, rozmiar mieszczący się w instalatorze desktopowym.

Runtime aplikacji nie może zależeć od PyTorch: sam PyTorch to kilkaset
megabajtów, a przy pakowaniu jeszcze więcej.

## Decyzja

Model `sdadas/mmlw-retrieval-roberta-base` (Apache-2.0, 768 wymiarów),
wyeksportowany do ONNX i skwantyzowany do INT8. Uruchamiany w ONNX Runtime
z jawną listą providerów `("CPUExecutionProvider",)`, weryfikowaną po
utworzeniu sesji.

Eksport wykonuje się raz, skryptem
[`tools/export_model_onnx.py`](../../tools/export_model_onnx.py), w środowisku
deweloperskim z PyTorch. Runtime aplikacji zna tylko `onnxruntime`
i `tokenizers`.

Parametry zapisane w manifeście modelu i weryfikowane przy wczytaniu:

| Parametr | Wartość |
| --- | --- |
| prefiks zapytania | `zapytanie: ` |
| prefiks treści | pusty |
| pooling | CLS |
| normalizacja | L2 |
| metryka | iloczyn skalarny |

## Pomiary

Na maszynie opisanej w [raporcie PoC](../raport-poc.md):

| Miara | INT8 | FP32 |
| --- | --- | --- |
| Rozmiar wag | 119 MB | 473 MB |
| Pamięć procesu | 308 MB | 925 MB |
| Fragmenty na sekundę | 351 | 162 |
| Czas zapytania, mediana | 3,7 ms | 7,0 ms |
| recall@5 | 1,000 | 1,000 |
| MRR | 0,938 | 1,000 |

## Rozważane alternatywy

Porównanie kandydatów opisuje [raport PoC](../raport-poc.md). W skrócie:
wariant `large` odpada przez rozmiar i czas na CPU, modele wielojęzyczne przez
gorszą jakość na polskim, a modele podobieństwa zdań przez to, że nie są
przeznaczone do wyszukiwania.

## Konsekwencje

Dobre:

* runtime bez PyTorch, instalator o rząd wielkości mniejszy;
* INT8 daje dwukrotnie wyższą przepustowość i trzykrotnie mniejsze zużycie
  pamięci niż FP32, kosztem marginalnego spadku jakości rankingu;
* model jest wymienny: wystarczy inny katalog i podniesienie skrótu zgodności.

Kosztowne:

* eksport do ONNX wymaga osobnego środowiska z PyTorch. Jest to krok
  deweloperski, nie wdrożeniowy;
* ONNX Runtime domyślnie wystawia `AzureExecutionProvider`. Lista providerów
  **musi** być podana jawnie, inaczej biblioteka mogłaby próbować użyć
  zdalnego zasobu. Weryfikujemy to po utworzeniu sesji;
* pomylenie prefiksu, poolingu albo normalizacji obniża jakość bez żadnego
  komunikatu o błędzie. Dlatego parametry są w manifeście, a nie w kodzie.
