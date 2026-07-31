"""Testy integracyjne konektora katalogu lokalnego.

Sprawdzamy cztery rzeczy, na ktorych opiera sie caly przeplyw indeksowania:
enumeracje wraz z filtrami, deterministyczna kolejnosc, pobranie pliku do
przestrzeni roboczej oraz test polaczenia ze zrodlem.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

import pytest

from finddocs.config import LocalDirSourceSettings
from finddocs.connectors.base import ScanCursor
from finddocs.connectors.local_dir import LocalDirectoryConnector
from finddocs.errors import ConnectorError, SourceUnavailableError
from finddocs.types import SourceItem

#: Zawartosc drzewa katalogow uzywanego w wiekszosci testow tego modulu.
TREE: dict[str, str] = {
    "a-umowa.txt": "Umowa ramowa nr 1. Dokument testowy, dane fikcyjne.\n",
    "b-raport.pdf": "%PDF-1.4 tresc zastepcza\n",
    "c-robocze.tmp": "plik roboczy do pominiecia\n",
    ".ukryty.txt": "notatka ukryta\n",
    "archiwum/e-stara-umowa.txt": "Umowa archiwalna. Dokument testowy.\n",
    "podkatalog/c-notatka.txt": "Notatka ze spotkania zespolu.\n",
    "podkatalog/d-zestawienie.csv": "data;kwota\n2024-01-02;100,00\n",
}

#: Kolejnosc, w jakiej konektor powinien oddawac pliki z drzewa TREE.
EXPECTED_ORDER: tuple[str, ...] = (
    "a-umowa.txt",
    "b-raport.pdf",
    "c-robocze.tmp",
    "archiwum/e-stara-umowa.txt",
    "podkatalog/c-notatka.txt",
    "podkatalog/d-zestawienie.csv",
)


def build_tree(root: Path, files: dict[str, str]) -> Path:
    """Tworzy drzewo katalogow opisane sciezkami wzglednymi."""
    root.mkdir(parents=True, exist_ok=True)
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


def build_connector(
    root: Path,
    *,
    include_hidden: bool = False,
    follow_symlinks: bool = False,
    include_extensions: Sequence[str] = (),
    exclude_extensions: Sequence[str] = (),
    exclude_globs: Sequence[str] = (),
    max_file_size_mb: int = 512,
) -> LocalDirectoryConnector:
    """Sklada konektor katalogu lokalnego z podanymi filtrami."""
    settings = LocalDirSourceSettings(
        root_path=str(root),
        follow_symlinks=follow_symlinks,
        include_hidden=include_hidden,
    )
    return LocalDirectoryConnector(
        source_id="lokalne",
        label="Katalog testowy",
        settings=settings,
        include_extensions=list(include_extensions),
        exclude_extensions=list(exclude_extensions),
        exclude_globs=list(exclude_globs),
        max_file_size_mb=max_file_size_mb,
    )


def paths_of(items: list[SourceItem]) -> list[str]:
    return [item.logical_path for item in items]


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    return build_tree(tmp_path / "zrodlo", TREE)


# --- enumeracja ------------------------------------------------------------------


def test_enumeracja_pomija_pliki_ukryte(tree: Path) -> None:
    connector = build_connector(tree)
    items = list(connector.iter_items())

    assert paths_of(items) == list(EXPECTED_ORDER)
    assert all(not item.name.startswith(".") for item in items)


def test_enumeracja_z_plikami_ukrytymi(tree: Path) -> None:
    connector = build_connector(tree, include_hidden=True)
    items = list(connector.iter_items())

    assert ".ukryty.txt" in paths_of(items)
    assert len(items) == len(EXPECTED_ORDER) + 1


def test_filtr_rozszerzen_dozwolonych(tree: Path) -> None:
    connector = build_connector(tree, include_extensions=[".txt"])
    items = list(connector.iter_items())

    assert paths_of(items) == ["a-umowa.txt", "archiwum/e-stara-umowa.txt", "podkatalog/c-notatka.txt"]


def test_filtr_rozszerzen_wykluczonych(tree: Path) -> None:
    connector = build_connector(tree, exclude_extensions=["tmp", ".PDF"])
    items = list(connector.iter_items())

    assert "c-robocze.tmp" not in paths_of(items)
    assert "b-raport.pdf" not in paths_of(items)
    assert "a-umowa.txt" in paths_of(items)


def test_filtr_globow_dopasowuje_sciezke_i_nazwe(tree: Path) -> None:
    connector = build_connector(tree, exclude_globs=["*.tmp", "archiwum/*"])
    items = list(connector.iter_items())

    assert paths_of(items) == [
        "a-umowa.txt",
        "b-raport.pdf",
        "podkatalog/c-notatka.txt",
        "podkatalog/d-zestawienie.csv",
    ]


def test_plik_za_duzy_dostaje_znacznik_too_large(tmp_path: Path) -> None:
    root = tmp_path / "duze"
    root.mkdir()
    (root / "maly.txt").write_text("krotka tresc\n", encoding="utf-8")
    (root / "wielki.txt").write_bytes(b"x" * (2 * 1024 * 1024))

    connector = build_connector(root, max_file_size_mb=1)
    items = {item.name: item for item in connector.iter_items()}

    assert items["maly.txt"].extra == {}
    assert items["wielki.txt"].extra["too_large"] is True
    assert items["wielki.txt"].extra["limit_mb"] == 1
    # Plik za duzy nadal jest zwracany, zeby warstwa wyzsza mogla go policzyc.
    assert items["wielki.txt"].size == 2 * 1024 * 1024


def test_metadane_pozycji_zrodla(tree: Path) -> None:
    connector = build_connector(tree)
    items = {item.logical_path: item for item in connector.iter_items()}
    item = items["podkatalog/c-notatka.txt"]

    assert item.source_id == "lokalne"
    assert item.external_id == "podkatalog/c-notatka.txt"
    assert item.name == "c-notatka.txt"
    assert item.extension == ".txt"
    assert item.size == (tree / "podkatalog" / "c-notatka.txt").stat().st_size
    assert item.modified_at is not None
    assert item.etag is not None
    assert item.library == tree.name
    assert item.web_url is not None and item.web_url.startswith("file:///")
    assert item.change_key() == f"etag:{item.etag}"


# --- deterministyczna kolejnosc --------------------------------------------------


def test_kolejnosc_jest_deterministyczna(tree: Path) -> None:
    pierwszy = paths_of(list(build_connector(tree).iter_items()))
    drugi = paths_of(list(build_connector(tree).iter_items()))

    assert pierwszy == drugi == list(EXPECTED_ORDER)


def test_kursor_pozwala_wznowic_od_pozycji(tree: Path) -> None:
    connector = build_connector(tree)
    items = list(connector.iter_items())
    cursor = connector.cursor()

    assert cursor.complete is True
    assert cursor.visited == len(items)

    wznowiony = build_connector(tree)
    reszta = list(wznowiony.iter_items(cursor=ScanCursor(token=None, visited=3)))
    assert paths_of(reszta) == list(EXPECTED_ORDER[3:])


# --- pobieranie ------------------------------------------------------------------


def test_fetch_kopiuje_plik_i_liczy_sha256(tree: Path, tmp_path: Path) -> None:
    connector = build_connector(tree)
    item = next(i for i in connector.iter_items() if i.name == "a-umowa.txt")
    destination = tmp_path / "praca"

    fetched = connector.fetch(item, destination)

    zrodlo = (tree / "a-umowa.txt").read_bytes()
    assert fetched.path == destination / "a-umowa.txt"
    assert fetched.path.read_bytes() == zrodlo
    assert fetched.size == len(zrodlo)
    assert fetched.sha256 == hashlib.sha256(zrodlo).hexdigest()
    # Plik zrodlowy zostaje nietkniety.
    assert (tree / "a-umowa.txt").exists()


def test_fetch_ponownie_uzywa_istniejacej_kopii(tree: Path, tmp_path: Path) -> None:
    connector = build_connector(tree)
    item = next(i for i in connector.iter_items() if i.name == "a-umowa.txt")
    destination = tmp_path / "praca"

    pierwszy = connector.fetch(item, destination)
    drugi = connector.fetch(item, destination)

    assert pierwszy.sha256 == drugi.sha256
    assert pierwszy.path == drugi.path


def test_fetch_odrzuca_identyfikator_wychodzacy_poza_korzen(tree: Path, tmp_path: Path) -> None:
    connector = build_connector(tree)
    item = SourceItem(
        source_id="lokalne",
        external_id="../poza-korzeniem.txt",
        name="poza-korzeniem.txt",
        logical_path="../poza-korzeniem.txt",
    )

    with pytest.raises(ConnectorError):
        connector.fetch(item, tmp_path / "praca")


# --- test polaczenia -------------------------------------------------------------


def test_test_connection_dla_istniejacego_katalogu(tree: Path) -> None:
    status = build_connector(tree).test_connection()

    assert status.ok is True
    assert "dostepny" in status.message
    # Sonda liczy wszystkie pozycje pierwszego poziomu, takze katalogi i pliki ukryte.
    assert status.details["pozycji_na_pierwszym_poziomie"] == 6
    assert status.details["licznik_ograniczony"] is False
    assert status.details["katalog"] == str(tree)


def test_test_connection_dla_nieistniejacego_katalogu(tmp_path: Path) -> None:
    brak = tmp_path / "nie-ma-takiego-katalogu"
    status = build_connector(brak).test_connection()

    assert status.ok is False
    assert "nie istnieje" in status.message


def test_test_connection_gdy_sciezka_wskazuje_plik(tmp_path: Path) -> None:
    plik = tmp_path / "to-jest-plik.txt"
    plik.write_text("tresc\n", encoding="utf-8")

    status = build_connector(plik).test_connection()

    assert status.ok is False
    assert "plik" in status.message


def test_test_connection_bez_wskazanego_katalogu() -> None:
    connector = LocalDirectoryConnector(
        source_id="lokalne",
        label="Zrodlo bez katalogu",
        settings=LocalDirSourceSettings(root_path=""),
        include_extensions=[],
        exclude_extensions=[],
        exclude_globs=[],
        max_file_size_mb=512,
    )

    status = connector.test_connection()

    assert status.ok is False
    assert "Nie wskazano katalogu" in status.message


def test_enumeracja_nieistniejacego_katalogu_konczy_sie_bledem(tmp_path: Path) -> None:
    connector = build_connector(tmp_path / "brak")

    with pytest.raises(SourceUnavailableError):
        list(connector.iter_items())
