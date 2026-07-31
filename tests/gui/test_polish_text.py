"""Test poprawnosci jezykowej napisow interfejsu.

Wymaganie mowi, ze interfejs jest po polsku. Polszczyzna bez znakow
diakrytycznych to nie jest polszczyzna, wiec test pilnuje, zeby napisy widoczne
dla uzytkownika mialy ogonki tam, gdzie powinny.

Test dziala na zasadzie listy slow zakazanych: sprawdza, czy w napisach nie ma
form pozbawionych znakow diakrytycznych. Nie zastapi korekty jezykowej, ale
zatrzyma regresje przy dopisywaniu nowych komunikatow.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from finddocs.gui import i18n

GUI_DIR = Path(i18n.__file__).parent

#: Caly pakiet aplikacji: komunikaty bledow tez widzi uzytkownik.
PACKAGE_DIR = GUI_DIR.parent

#: Pliki bez napisow dla uzytkownika albo z celowo uproszczonym tekstem.
#: Zbior demonstracyjny nasladuje dokumenty pisane bez polskich znakow,
#: a CLI sluzy administratorom i jego wyjscie trafia do konsoli.
SKIP_FILES = {"theme.py", "tables.py"}
SKIP_DIRS = {"demo", "__pycache__"}
SKIP_MODULES = {"cli.py"}

#: Formy bez znakow diakrytycznych, ktore nie moga wystapic w napisach.
FORBIDDEN: tuple[str, ...] = (
    "bledu",
    "bledem",
    "bledy",
    "czesc",
    "czesci",
    "dokladne",
    "dokumentow",
    "dostepne",
    "dostepny",
    "niedostepny",
    "otworz",
    "plikow",
    "pominiete",
    "postep",
    "spojnosc",
    "srodowisko",
    "szczegoly",
    "tresci",
    "wynikow",
    "zakonczone",
    "zrodla",
    "zrodlo",
)

_FORBIDDEN_RE = re.compile(r"\b(" + "|".join(FORBIDDEN) + r")\b", re.IGNORECASE)

#: Napisy, ktore nie sa tekstem dla czlowieka: nazwy zdarzen, klucze, sciezki.
_TECHNICAL = re.compile(r"^[a-z0-9_.\-/]+$")


def _docstring_ids(tree: ast.AST) -> set[int]:
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                found.add(id(body[0].value))
    return found


def _user_strings(path: Path) -> list[tuple[int, str]]:
    """Napisy z pliku, ktore trafiaja przed oczy uzytkownika."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = _docstring_ids(tree)
    result: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in skip:
            continue
        value = node.value
        if not value.strip() or _TECHNICAL.match(value):
            continue
        result.append((node.lineno, value))
    return result


def _checked_files() -> list[Path]:
    """Moduly, ktorych napisy trafiaja przed oczy uzytkownika."""
    return sorted(
        path
        for path in PACKAGE_DIR.rglob("*.py")
        if path.name not in SKIP_FILES
        and path.name not in SKIP_MODULES
        and not SKIP_DIRS.intersection(path.parts)
    )


@pytest.mark.parametrize("path", _checked_files(), ids=lambda p: p.name)
def test_napisy_maja_znaki_diakrytyczne(path: Path) -> None:
    """Zaden napis interfejsu nie zawiera polskiego slowa bez ogonkow."""
    problems = [
        f"{path.name}:{line} {match.group(0)!r} w {value!r}"
        for line, value in _user_strings(path)
        if (match := _FORBIDDEN_RE.search(value))
    ]

    assert not problems, "Napisy bez znakow diakrytycznych:\n" + "\n".join(problems)


def test_etykiety_trybow_sa_po_polsku() -> None:
    """Trzy tryby wyszukiwania maja poprawne nazwy."""
    labels = set(i18n.MODE_LABELS.values())

    assert labels == {"Hybrydowe", "Dokładne", "Semantyczne"}


def test_statusy_dokumentow_sa_po_polsku() -> None:
    """Kazdy status ma opis po polsku, rozny od nazwy technicznej."""
    for status, label in i18n.STATUS_LABELS.items():
        assert label
        assert label != status.value
        assert not _FORBIDDEN_RE.search(label), f"{status.value}: {label}"


def test_nawigacja_ma_poprawne_nazwy() -> None:
    """Piec pozycji nawigacji, kazda po polsku."""
    items = [
        i18n.NAV_SEARCH,
        i18n.NAV_SOURCES,
        i18n.NAV_INDEXING,
        i18n.NAV_REPORT,
        i18n.NAV_DIAGNOSTICS,
    ]

    assert items == [
        "Wyszukiwanie",
        "Źródła i konfiguracja",
        "Indeksowanie",
        "Raport pokrycia",
        "Diagnostyka",
    ]


def test_liczebniki_odmieniaja_sie_poprawnie() -> None:
    """Polska odmiana rzeczownika po liczbie, z ogonkami w formie mnogiej."""
    assert i18n.documents_count(1) == "1 dokument"
    assert i18n.documents_count(2) == "2 dokumenty"
    assert i18n.documents_count(5) == "5 dokumentów"
    assert i18n.files_count(1) == "1 plik"
    assert i18n.files_count(3) == "3 pliki"
    assert i18n.files_count(9) == "9 plików"
