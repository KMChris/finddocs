# ADR-009: Domyślny brak ruchu wychodzącego

**Stan:** przyjęta
**Data:** lipiec 2026

## Kontekst

Wymaganie: zero telemetrii, zero publicznych API modeli, OCR i wyszukiwarek.
Dokumenty, zapytania i embeddingi nie opuszczają komputera. Dozwolony jest
wyłącznie ruch do Microsoft Graph i Entra ID oraz jednorazowe pobranie modelu
z adresu zapisanego w manifeście.

Problem jest realny: biblioteki uczenia maszynowego chętnie pobierają modele
i wysyłają statystyki użycia, często domyślnie i bez wyraźnej informacji.

## Decyzja

Warstwa `security/network.py` z jawną polityką ruchu wychodzącego.

Trzy kategorie, każda z własną listą dozwolonych hostów:

| Kategoria | Hosty |
| --- | --- |
| `MICROSOFT_GRAPH` | `graph.microsoft.com`, `login.microsoftonline.com`, `*.sharepoint.com` |
| `MODEL_DOWNLOAD` | `huggingface.co`, `cdn-lfs.huggingface.co`, `*.hf.co` |
| `INTERNAL_API` | lista pusta, wymaga jawnej konfiguracji |

Domyślnie **żadna kategoria nie jest włączona**. `NetworkPolicy.offline()` to
stan wyjściowy. Kategoria `MICROSOFT_GRAPH` włącza się po dodaniu źródła
SharePoint, `MODEL_DOWNLOAD` po ustawieniu `allow_model_download`.

Dozwolony jest wyłącznie protokół HTTPS. Każde połączenie przechodzi przez
`policy.check(url, category)` i kończy się `FD-1005`, gdy adres jest spoza listy,
także wtedy, gdy podał go serwer w odpowiedzi.

Dodatkowo warstwa startowa ustawia `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`
i `DO_NOT_TRACK=1`, na wypadek gdyby jakaś biblioteka próbowała pobrać coś
poza naszą kontrolą.

## Rozważane alternatywy

**Poleganie na firewallu organizacji.** Nie jest częścią produktu, nie chroni
na komputerze przenośnym poza siecią firmową i nie daje użytkownikowi wglądu
w to, dokąd aplikacja mogłaby się połączyć.

**Lista blokowanych zamiast dozwolonych.** Lista blokowanych jest zawsze
niekompletna. Lista dozwolonych jest z definicji zamknięta.

**Brak warstwy, tylko dyscyplina w kodzie.** Działa do pierwszej nowej
zależności, która czegoś nie zapyta.

## Konsekwencje

Dobre:

* aplikacja domyślnie nie może się nigdzie połączyć, więc pomyłka w kodzie
  kończy się błędem, a nie cichym wyciekiem;
* lista dozwolonych adresów jest wpisana w kod i **widoczna na ekranie
  Diagnostyka**, więc użytkownik może ją sprawdzić bez czytania źródeł;
* audyt sprowadza się do przejrzenia jednego pliku.

Kosztowne:

* każde nowe połączenie wymaga dopisania hosta do listy. To jest zamierzone;
* zmiana adresów po stronie Microsoft wymagałaby aktualizacji aplikacji.
  Wzorce z gwiazdką ograniczają to ryzyko.
