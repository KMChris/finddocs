"""Wzbogacenie semantyczne fragmentow o kontekst dokumentu.

Przed policzeniem wektora fragment moze dostac naglowek z nazwa pliku
i sciezka w zrodle. Dzieki temu zapytania odwolujace sie do nazw katalogow
albo plikow (np. "regulamin z katalogu Kadry") znajduja dokumenty, ktorych
tresc o tych nazwach nie wspomina.

Naglowek jest ulotny: wchodzi wylacznie do tekstu podawanego dostawcy
embeddingow. Nie trafia do bazy, indeksu pelnotekstowego ani do fragmentow
pokazywanych uzytkownikowi. Format naglowka wchodzi do skrotu zgodnosci
czesci wektorowej jako ``EMBED_CONTEXT_VERSION`` z ``finddocs.version``:
kazda zmiana formatu wymaga podniesienia tej stalej, inaczej stare i nowe
wektory przestana byc porownywalne bez ostrzezenia.
"""

from __future__ import annotations

#: Gorny limit dlugosci linii sciezki w naglowku. Chroni okno kontekstu modelu
#: przed patologicznie dlugimi sciezkami; obcinanie zachowuje koncowe segmenty,
#: bo najblizsze katalogi i nazwa pliku niosa najwiecej znaczenia.
MAX_PATH_CHARS = 240

#: Separator dokumentu podrzednego w sciezce logicznej (zalacznik, wpis archiwum).
_ATTACHMENT_SEPARATOR = "::"


def _shorten_path(path: str, limit: int) -> str:
    """Skraca sciezke do koncowych segmentow mieszczacych sie w limicie."""
    if len(path) <= limit:
        return path
    parts = [part for part in path.split("/") if part]
    kept: list[str] = []
    total = 0
    for part in reversed(parts):
        extra = len(part) + (1 if kept else 0)
        if kept and total + extra > limit:
            break
        kept.append(part)
        total += extra
    shortened = "/".join(reversed(kept))
    if len(shortened) > limit:
        shortened = shortened[-limit:]
    return f"…/{shortened}"


def _folder_of(name: str, logical_path: str) -> str:
    """Czesc katalogowa sciezki logicznej, bez nazwy samego pliku."""
    path = (logical_path or "").replace("\\", "/").strip().strip("/")
    if not path or path == name:
        return ""
    if name and path.endswith(name):
        path = path[: -len(name)].rstrip("/ ")
        # Dokument podrzedny ma sciezke "rodzic :: nazwa": po odcieciu nazwy
        # zostaje separator, a kontekstem jest sciezka dokumentu nadrzednego.
        path = path.removesuffix(_ATTACHMENT_SEPARATOR).rstrip("/ ")
    return path


def document_context_header(
    name: str,
    logical_path: str,
    library: str | None = None,
) -> str:
    """Buduje naglowek kontekstu dokumentu doklejany do fragmentu przed osadzeniem.

    Zwraca pusty napis, gdy dokument nie ma zadnych danych kontekstu; wtedy
    fragmenty ida do modelu bez zmian.
    """
    clean_name = (name or "").strip()
    folder = _folder_of(clean_name, logical_path)
    location_parts: list[str] = []
    clean_library = (library or "").strip().strip("/")
    if clean_library and clean_library != folder.split("/", 1)[0]:
        location_parts.append(clean_library)
    if folder:
        location_parts.append(folder)
    location = "/".join(location_parts)

    lines: list[str] = []
    if clean_name:
        lines.append(f"Plik: {clean_name}")
    if location:
        lines.append(f"Ścieżka: {_shorten_path(location, MAX_PATH_CHARS)}")
    return "\n".join(lines)


def enrich_passages(texts: list[str], header: str) -> list[str]:
    """Dokleja naglowek kontekstu do kazdego fragmentu. Pusty naglowek nic nie zmienia."""
    if not header:
        return texts
    return [f"{header}\n{text}" for text in texts]


__all__ = ["MAX_PATH_CHARS", "document_context_header", "enrich_passages"]
