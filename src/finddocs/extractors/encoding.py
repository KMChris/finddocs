"""Rozpoznawanie kodowania plikow tekstowych.

Modul jest wspolny dla parserow tekstu, CSV i HTML. Powstal, bo sama detekcja
statystyczna zawodzi na krotkich polskich plikach: bajty UTF-8 zdania
,,Zazolc gesla jazn'' potrafia zostac rozpoznane jako koreanska strona kodowa,
a plik iso-8859-2 jako cp1250. Oba bledy sa ciche, bo dekodowanie sie udaje,
tylko wynik jest bezsensowny i zanieczyszcza indeks.

Kolejnosc decyzji:

1. znacznik BOM, jesli jest, rozstrzyga bez dyskusji;
2. kodowanie zadeklarowane w pliku (naglowek ``<meta charset>``), o ile pasuje;
3. scisle UTF-8, gdy bajty tworza poprawna sekwencje i nie ma w nich bajtow zerowych;
4. ocena jakosci wyniku dla pozostalych kandydatow, wygrywa najlepszy;
5. UTF-8 z zamiana bledow, gdy nic nie zadzialalo.
"""

from __future__ import annotations

import codecs
import unicodedata
from dataclasses import dataclass
from typing import Final

#: Kodowania sprawdzane po kolei, gdy detekcja statystyczna nie da odpowiedzi.
FALLBACK_ENCODINGS: Final[tuple[str, ...]] = (
    "utf-8",
    "cp1250",
    "iso-8859-2",
    "cp1252",
    "utf-16",
    "utf-16-le",
    "utf-16-be",
    "latin-1",
)

#: Ile poczatkowych bajtow wystarcza do rozpoznania kodowania.
DETECTION_SAMPLE_BYTES: Final[int] = 256 * 1024

#: Ile poczatkowych znakow bierzemy do oceny jakosci dekodowania.
SCORING_SAMPLE_CHARS: Final[int] = 20_000

#: Znaczniki kolejnosci bajtow. UTF-32 sprawdzany przed UTF-16, bo ma wspolny prefiks.
BOM_ENCODINGS: Final[tuple[tuple[bytes, str], ...]] = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)

#: Litery polskiego alfabetu poza zakresem ASCII.
POLISH_LETTERS: Final[frozenset[str]] = frozenset("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")

#: Znaki dopuszczalne w dokumencie biurowym mimo tego, ze nie sa literami.
NEUTRAL_CHARACTERS: Final[frozenset[str]] = frozenset(" \t\n\r\f\v")

#: Symbole z bloku Latin-1, ktore w polskim tekscie prawie zawsze oznaczaja
#: pomylenie strony kodowej (typowy objaw czytania iso-8859-2 jako cp1250).
SUSPICIOUS_SYMBOLS: Final[frozenset[str]] = frozenset("¡¢£¤¥¦§¨©ª«¬®¯°±²³´µ¶·¸¹º»¼½¾¿×÷")

#: Kategorie Unicode uznawane za objaw blednego dekodowania.
BROKEN_CATEGORIES: Final[frozenset[str]] = frozenset({"Cc", "Cf", "Co", "Cs", "Cn"})

#: Poczatki blokow pisma, ktore w dokumentach tego zastosowania nie wystepuja.
FOREIGN_SCRIPT_RANGES: Final[tuple[tuple[int, int], ...]] = (
    (0x0590, 0x08FF),  # hebrajski, arabski
    (0x0E00, 0x0FFF),  # tajski, tybetanski
    (0x1100, 0x11FF),  # jamo koreanskie
    (0x2E80, 0xA4CF),  # CJK, kana, bopomofo
    (0xA960, 0xA97F),  # jamo rozszerzone
    (0xAC00, 0xD7FF),  # sylaby hangul
    (0xF900, 0xFAFF),  # zgodnosc CJK
)

#: Wagi oceny. Dodatnie premiuja tekst wygladajacy na dokument, ujemne karza smieci.
_SCORE_POLISH = 3.0
_SCORE_LETTER = 1.0
_SCORE_NEUTRAL = 0.2
_SCORE_SUSPICIOUS = -3.0
_SCORE_FOREIGN = -6.0
_SCORE_BROKEN = -8.0
_SCORE_OTHER = -0.2

#: Ponizej tego wyniku uznajemy, ze zadeklarowane kodowanie klamie.
DECLARED_MIN_SCORE: Final[float] = 0.0


@dataclass(frozen=True, slots=True)
class DecodedText:
    """Wynik dekodowania: tekst, uzyte kodowanie i ewentualne ostrzezenie."""

    text: str
    encoding: str
    replaced: bool = False
    """True, gdy czesc bajtow zastapiono znakiem zastepczym."""

    @property
    def warnings(self) -> list[str]:
        if not self.replaced:
            return []
        return ["Nie udalo sie jednoznacznie rozpoznac kodowania, czesc znakow zastapiono."]


def canonical_encoding(name: str) -> str:
    """Ujednolica zapis nazwy kodowania do postaci malymi literami z lacznikiem."""
    return name.strip().lower().replace("_", "-")


def bom_encoding(data: bytes) -> str | None:
    """Kodowanie wynikajace ze znacznika BOM albo None, gdy znacznika brak."""
    for marker, encoding in BOM_ENCODINGS:
        if data.startswith(marker):
            return encoding
    return None


def _is_foreign_script(char: str) -> bool:
    point = ord(char)
    return any(start <= point <= end for start, end in FOREIGN_SCRIPT_RANGES)


def score_text(text: str) -> float:
    """Ocenia, na ile tekst wyglada na poprawnie zdekodowany dokument.

    Wynik jest srednia wag przypadajaca na znak, wiec nie zalezy od dlugosci pliku.
    Tekst polski dostaje wyraznie wiecej niz ten sam plik odczytany zla strona kodowa.
    """
    sample = text[:SCORING_SAMPLE_CHARS]
    if not sample:
        return 0.0
    total = 0.0
    for char in sample:
        if char in POLISH_LETTERS:
            total += _SCORE_POLISH
        elif char in NEUTRAL_CHARACTERS:
            total += _SCORE_NEUTRAL
        elif char in SUSPICIOUS_SYMBOLS:
            total += _SCORE_SUSPICIOUS
        elif _is_foreign_script(char):
            total += _SCORE_FOREIGN
        elif char.isalnum():
            total += _SCORE_LETTER
        elif unicodedata.category(char) in BROKEN_CATEGORIES:
            total += _SCORE_BROKEN
        else:
            total += _SCORE_OTHER
    return total / len(sample)


def detect_encoding(data: bytes) -> str | None:
    """Proponuje kodowanie na podstawie analizy statystycznej probki poczatku pliku."""
    try:
        from charset_normalizer import from_bytes
    except ImportError:
        return None
    try:
        best = from_bytes(data[:DETECTION_SAMPLE_BYTES]).best()
    except Exception:
        return None
    if best is None or not best.encoding:
        return None
    return canonical_encoding(str(best.encoding))


def _try_decode(data: bytes, encoding: str) -> str | None:
    try:
        return data.decode(encoding)
    except (UnicodeDecodeError, LookupError, ValueError):
        return None


def candidate_encodings(
    data: bytes,
    declared: str | None = None,
    extra: tuple[str, ...] = (),
) -> list[str]:
    """Lista kodowan do sprawdzenia, w kolejnosci malejacego zaufania."""
    seen: set[str] = set()
    candidates: list[str] = []
    for name in (declared, detect_encoding(data), *extra, *FALLBACK_ENCODINGS):
        if not name:
            continue
        canonical = canonical_encoding(name)
        if canonical in seen:
            continue
        seen.add(canonical)
        candidates.append(canonical)
    return candidates


def decode_text(
    data: bytes,
    *,
    declared: str | None = None,
    extra: tuple[str, ...] = (),
) -> DecodedText:
    """Dekoduje bajty pliku tekstowego, wybierajac najbardziej wiarygodne kodowanie.

    ``declared`` to kodowanie zapisane w samym dokumencie (naglowek ``<meta charset>``).
    ``extra`` to podpowiedzi z otoczenia, na przyklad strona kodowa wiadomosci MSG.
    Zadne z nich nie jest wiazace, jesli daje bezsensowny wynik.
    """
    if not data:
        return DecodedText(text="", encoding="utf-8")

    marker = bom_encoding(data)
    if marker is not None:
        text = _try_decode(data, marker)
        if text is not None:
            return DecodedText(text=text.lstrip("﻿"), encoding=marker)

    if declared:
        text = _try_decode(data, canonical_encoding(declared))
        if text is not None and score_text(text) >= DECLARED_MIN_SCORE:
            return DecodedText(text=text.lstrip("﻿"), encoding=canonical_encoding(declared))

    # Poprawna sekwencja UTF-8 to bardzo silna przeslanka. Wyjatkiem sa pliki
    # z bajtami zerowymi: to zwykle UTF-16 bez znacznika BOM, ktory tez przechodzi
    # przez dekoder UTF-8, tyle ze z bezsensownym wynikiem.
    if b"\x00" not in data[:DETECTION_SAMPLE_BYTES]:
        strict = _try_decode(data, "utf-8")
        if strict is not None:
            return DecodedText(text=strict.lstrip("﻿"), encoding="utf-8")

    best_text: str | None = None
    best_encoding = ""
    best_score = float("-inf")
    for encoding in candidate_encodings(data, declared, extra):
        text = _try_decode(data, encoding)
        if text is None:
            continue
        score = score_text(text)
        if score > best_score:
            best_text, best_encoding, best_score = text, encoding, score

    if best_text is not None:
        return DecodedText(text=best_text.lstrip("﻿"), encoding=best_encoding)

    return DecodedText(
        text=data.decode("utf-8", errors="replace").lstrip("﻿"),
        encoding="utf-8",
        replaced=True,
    )


__all__ = [
    "BOM_ENCODINGS",
    "DETECTION_SAMPLE_BYTES",
    "FALLBACK_ENCODINGS",
    "SCORING_SAMPLE_CHARS",
    "DecodedText",
    "bom_encoding",
    "candidate_encodings",
    "canonical_encoding",
    "decode_text",
    "detect_encoding",
    "score_text",
]
