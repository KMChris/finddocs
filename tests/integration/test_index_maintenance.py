"""Testy integracyjne konserwacji indeksu.

Zakres: migracje schematu, kontrola spojnosci, kopia zapasowa i przywracanie,
kompaktacja indeksu wektorowego, oznaczanie do ponownego indeksowania oraz
zachowanie magazynu wektorow przy niezgodnej konfiguracji.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pytest

from finddocs.app_paths import AppPaths
from finddocs.chunking import build_chunk
from finddocs.config import AppConfig
from finddocs.errors import IndexIncompatibleError, MigrationError, StorageSpaceError
from finddocs.indexing import migrations as migrations_module
from finddocs.indexing.db import Database, open_connection
from finddocs.indexing.maintenance import (
    backup_index,
    check_consistency,
    compact_vectors,
    ensure_free_space,
    list_backups,
    mark_all_for_reindex,
    restore_backup,
)
from finddocs.indexing.migrations import Migration, migrate, pending_migrations
from finddocs.indexing.repository import Repository
from finddocs.indexing.schema import META_SCHEMA_VERSION, current_schema_version
from finddocs.indexing.service import IndexService
from finddocs.indexing.vector import VectorStore
from finddocs.indexing.writer import DocumentPayload
from finddocs.types import DocumentStatus, SourceItem
from finddocs.version import SCHEMA_VERSION

#: Wymiar sztucznych wektorow uzywanych w testach magazynu wektorowego.
DIM = 8

#: Skrot zgodnosci konfiguracji dla magazynu wektorowego w testach.
COMPAT = "skrot-zgodnosci-testowy"


# --- pomocnicze ------------------------------------------------------------------


def unit_vector(seed: int, dimension: int = DIM) -> np.ndarray:
    """Deterministyczny wektor jednostkowy o zadanym wymiarze."""
    generator = np.random.default_rng(seed)
    raw = generator.standard_normal(dimension).astype("float32")
    return raw / float(np.linalg.norm(raw))


def add_document(index: IndexService, name: str, text: str, *, chunks: int = 2) -> int:
    """Wstawia dokument wraz z fragmentami przez zwykla sciezke zapisu."""
    item = SourceItem(
        source_id="lokalne",
        external_id=name,
        name=name,
        logical_path=name,
        size=len(text),
        etag=f"etag-{name}",
    )
    with index.db.transaction():
        doc_id = index.repository.register_item(item, 1)
    payload = DocumentPayload(
        doc_id=doc_id,
        chunks=[build_chunk(i, f"{text} Fragment numer {i}.") for i in range(chunks)],
        change_key=item.change_key(),
        content_sha256=f"sha-{name}",
    )
    index.writer.write_document(payload)
    return doc_id


def open_store(paths: AppPaths, *, dimension: int = DIM, compat: str = COMPAT) -> VectorStore:
    store = VectorStore(paths.vector_file, paths.vector_meta_file)
    store.open(
        dimension=dimension,
        model_key="model-testowy",
        model_version="1.0",
        vector_compat_hash=compat,
    )
    return store


# --- migracje --------------------------------------------------------------------


def test_pusta_baza_dostaje_schemat_w_biezacej_wersji(tmp_path: Path) -> None:
    conn = open_connection(tmp_path / "indeks.db")
    try:
        assert current_schema_version(conn) == 0

        osiagnieta = migrate(conn)

        assert osiagnieta == SCHEMA_VERSION
        assert current_schema_version(conn) == SCHEMA_VERSION
        assert pending_migrations(conn) == []
        tabele = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {"documents", "chunks", "chunks_fts", "index_meta", "schema_migrations"} <= tabele
    finally:
        conn.close()


def test_ponowna_migracja_nic_nie_zmienia(tmp_path: Path) -> None:
    conn = open_connection(tmp_path / "indeks.db")
    try:
        migrate(conn)
        przed = conn.execute("SELECT version, applied_at FROM schema_migrations").fetchall()

        assert migrate(conn) == SCHEMA_VERSION

        po = conn.execute("SELECT version, applied_at FROM schema_migrations").fetchall()
        assert [tuple(r) for r in po] == [tuple(r) for r in przed]
    finally:
        conn.close()


def test_baza_z_nowsza_wersja_konczy_sie_bledem_migracji(tmp_path: Path) -> None:
    conn = open_connection(tmp_path / "indeks.db")
    try:
        migrate(conn)
        conn.execute(
            "INSERT OR REPLACE INTO index_meta(key, value) VALUES (?, ?)",
            (META_SCHEMA_VERSION, str(SCHEMA_VERSION + 5)),
        )

        with pytest.raises(MigrationError) as info:
            migrate(conn)

        assert "nowsza niz obslugiwana" in info.value.user_message
    finally:
        conn.close()


def test_dodatkowa_migracja_podnosi_wersje_schematu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def krok_2(conn: sqlite3.Connection) -> None:
        """Sztuczny krok migracji zarejestrowany tylko na potrzeby tego testu."""
        conn.execute("CREATE TABLE IF NOT EXISTS tabela_testowa (id INTEGER PRIMARY KEY)")

    monkeypatch.setattr(
        migrations_module,
        "MIGRATIONS",
        [*migrations_module.MIGRATIONS, Migration(2, "sztuczny krok testowy", krok_2)],
    )

    conn = open_connection(tmp_path / "indeks.db")
    try:
        migrate(conn)

        assert migrate(conn, target=2) == 2
        assert current_schema_version(conn) == 2
        tabele = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "tabela_testowa" in tabele
        wersje = [int(r[0]) for r in conn.execute("SELECT version FROM schema_migrations")]
        assert sorted(wersje) == [1, 2]
    finally:
        conn.close()


# --- kontrola spojnosci ----------------------------------------------------------


def test_check_consistency_na_zdrowym_indeksie(index_service: IndexService) -> None:
    add_document(index_service, "umowa.txt", "Tresc umowy ramowej dla testu spojnosci.")
    add_document(index_service, "notatka.txt", "Tresc notatki sluzbowej dla testu spojnosci.")

    raport = check_consistency(index_service.db, index_service.repository, None)

    assert raport.is_healthy is True
    assert raport.problems == []
    assert raport.documents == 2
    assert raport.chunks == 4
    assert raport.orphan_chunks == 0
    assert raport.schema_version == SCHEMA_VERSION
    assert raport.expected_schema_version == SCHEMA_VERSION


def test_check_consistency_wykrywa_osierocone_fragmenty(index_service: IndexService) -> None:
    doc_id = add_document(index_service, "umowa.txt", "Tresc umowy ramowej dla testu spojnosci.")
    add_document(index_service, "notatka.txt", "Tresc notatki sluzbowej dla testu spojnosci.")

    # Usuwamy sam dokument, zostawiajac jego fragmenty. Klucze obce sa wylaczone,
    # zeby odtworzyc stan po awarii, ktorej normalna sciezka zapisu nie dopuszcza.
    index_service.db.execute("PRAGMA foreign_keys=OFF")
    index_service.db.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
    index_service.db.execute("PRAGMA foreign_keys=ON")

    raport = check_consistency(index_service.db, index_service.repository, None)

    assert raport.orphan_chunks == 2
    assert raport.is_healthy is False
    assert any("bez dokumentu nadrzednego" in problem for problem in raport.problems)


# --- kopia zapasowa --------------------------------------------------------------


def test_backup_index_i_restore_backup(app_config: AppConfig, tmp_home: AppPaths) -> None:
    index = IndexService(app_config)
    index.open(load_provider=False)
    add_document(index, "umowa.txt", "Tresc umowy ramowej przed wykonaniem kopii.")
    add_document(index, "notatka.txt", "Tresc notatki sluzbowej przed wykonaniem kopii.")
    index.flush()

    kopia = backup_index(tmp_home, label="kopia-testowa")

    assert kopia == tmp_home.backup_dir / "index-kopia-testowa"
    assert (kopia / "finddocs.db").exists()
    assert [wpis["nazwa"] for wpis in list_backups(tmp_home)] == ["index-kopia-testowa"]

    add_document(index, "faktura.txt", "Dokument dodany juz po wykonaniu kopii zapasowej.")
    assert int(index.db.query_scalar("SELECT COUNT(*) FROM documents", (), 0)) == 3
    index.close()

    przywrocony = restore_backup(tmp_home, "index-kopia-testowa")

    assert przywrocony == tmp_home.index_dir
    odtworzony = IndexService(app_config)
    odtworzony.open(load_provider=False)
    try:
        nazwy = {str(r["name"]) for r in odtworzony.db.query_all("SELECT name FROM documents")}
        assert nazwy == {"umowa.txt", "notatka.txt"}
    finally:
        odtworzony.close()
    # Biezacy indeks zostal odlozony na bok, a nie skasowany.
    assert any(p.name.startswith("przed-przywroceniem-") for p in tmp_home.backup_dir.iterdir())


def test_backup_index_odmawia_nadpisania_istniejacej_kopii(
    index_service: IndexService, tmp_home: AppPaths
) -> None:
    add_document(index_service, "umowa.txt", "Tresc umowy ramowej dla testu kopii.")
    index_service.flush()
    backup_index(tmp_home, label="kopia-testowa")

    with pytest.raises(StorageSpaceError):
        backup_index(tmp_home, label="kopia-testowa")


# --- magazyn wektorow ------------------------------------------------------------


def test_vector_store_zapis_odczyt_i_wyszukiwanie(tmp_home: AppPaths) -> None:
    store = open_store(tmp_home)
    wektory = np.vstack([unit_vector(seed) for seed in range(1, 4)])
    store.add([11, 22, 33], wektory)
    store.save()
    store.close()

    ponownie = open_store(tmp_home)
    try:
        assert ponownie.count() == 3
        assert ponownie.dimension == DIM
        assert ponownie.meta.model_key == "model-testowy"

        wyniki = ponownie.search(unit_vector(2), k=1)

        assert wyniki[0][0] == 22
        assert wyniki[0][1] == pytest.approx(1.0, abs=1e-4)
        odtworzony = ponownie.reconstruct(22)
        assert odtworzony is not None
        assert np.allclose(odtworzony, wektory[1], atol=1e-5)
    finally:
        ponownie.close()


def test_vector_store_usuwa_przez_nagrobek(tmp_home: AppPaths) -> None:
    store = open_store(tmp_home)
    try:
        store.add([11, 22, 33], np.vstack([unit_vector(s) for s in range(1, 4)]))

        store.remove([22])

        assert store.raw_count() == 3
        assert store.deleted_count() == 1
        assert store.count() == 2
        assert store.reconstruct(22) is None
        assert [chunk_id for chunk_id, _ in store.search(unit_vector(2), k=3)] != [22]
        assert 22 not in [chunk_id for chunk_id, _ in store.search(unit_vector(2), k=3)]
        assert store.needs_compaction() is True
    finally:
        store.close()


def test_vector_store_niezgodny_wymiar_nie_kasuje_pliku(tmp_home: AppPaths) -> None:
    store = open_store(tmp_home)
    store.add([1], unit_vector(7).reshape(1, DIM))
    store.save()
    store.close()
    rozmiar = tmp_home.vector_file.stat().st_size

    inny = VectorStore(tmp_home.vector_file, tmp_home.vector_meta_file)
    with pytest.raises(IndexIncompatibleError) as info:
        inny.open(
            dimension=DIM * 2,
            model_key="model-testowy",
            model_version="1.0",
            vector_compat_hash=COMPAT,
        )

    assert "wymiar" in info.value.user_message
    assert tmp_home.vector_file.exists()
    assert tmp_home.vector_meta_file.exists()
    assert tmp_home.vector_file.stat().st_size == rozmiar


def test_vector_store_niezgodny_hash_nie_kasuje_pliku(tmp_home: AppPaths) -> None:
    store = open_store(tmp_home)
    store.add([1], unit_vector(7).reshape(1, DIM))
    store.save()
    store.close()

    inny = VectorStore(tmp_home.vector_file, tmp_home.vector_meta_file)
    with pytest.raises(IndexIncompatibleError) as info:
        inny.open(
            dimension=DIM,
            model_key="model-testowy",
            model_version="1.0",
            vector_compat_hash="zupelnie-inny-skrot",
        )

    assert "przebudowa" in info.value.user_message.lower()
    assert tmp_home.vector_file.exists()
    assert tmp_home.vector_meta_file.exists()


def test_compact_vectors_usuwa_nagrobki(index_service: IndexService, tmp_home: AppPaths) -> None:
    store = open_store(tmp_home)
    index_service.vector_store = store
    index_service._writer = None  # writer ma zobaczyc podstawiony magazyn wektorow

    doc_a = add_document(index_service, "umowa.txt", "Tresc umowy ramowej dla kompaktacji.")
    doc_b = add_document(index_service, "notatka.txt", "Tresc notatki sluzbowej dla kompaktacji.")
    chunk_ids = [
        int(r["chunk_id"])
        for r in index_service.db.query_all("SELECT chunk_id FROM chunks ORDER BY chunk_id")
    ]
    assert len(chunk_ids) == 4

    store.add(chunk_ids, np.vstack([unit_vector(seed) for seed in range(1, 5)]))
    index_service.repository.mark_chunks_vectorized(chunk_ids)

    usuniete = index_service.repository.delete_document(doc_b)
    store.remove(usuniete)
    assert store.deleted_count() == 2
    assert store.raw_count() == 4

    aktywne = compact_vectors(index_service.repository, store)

    assert aktywne == 2
    assert store.deleted_count() == 0
    assert store.raw_count() == 2
    assert store.count() == 2
    assert store.needs_compaction() is False
    zostale = [
        int(r["chunk_id"])
        for r in index_service.db.query_all("SELECT chunk_id FROM chunks WHERE has_vector = 1")
    ]
    assert sorted(zostale) == sorted(chunk_ids[:2])
    assert index_service.repository.get_document(doc_a) is not None
    store.close()


# --- oznaczanie do przebudowy ----------------------------------------------------


def test_mark_all_for_reindex_kasuje_fragmenty_i_ustawia_status(
    index_service: IndexService,
) -> None:
    add_document(index_service, "umowa.txt", "Tresc umowy ramowej przed przebudowa indeksu.")
    add_document(index_service, "notatka.txt", "Tresc notatki sluzbowej przed przebudowa.")

    liczba = mark_all_for_reindex(index_service.repository)

    assert liczba == 2
    assert index_service.repository.count_chunks() == 0
    statusy = {
        str(r["status"]) for r in index_service.db.query_all("SELECT status FROM documents")
    }
    assert statusy == {DocumentStatus.PENDING.value}
    klucze = [r["change_key"] for r in index_service.db.query_all("SELECT change_key FROM documents")]
    assert klucze == [None, None]


def test_mark_all_for_reindex_tylko_wektory_zachowuje_fragmenty(
    index_service: IndexService,
) -> None:
    add_document(index_service, "umowa.txt", "Tresc umowy ramowej przed przebudowa wektorow.")

    liczba = mark_all_for_reindex(index_service.repository, only_vectors=True)

    assert liczba == 1
    assert index_service.repository.count_chunks() == 2
    assert index_service.repository.count_vectors() == 0
    statusy = {
        str(r["status"]) for r in index_service.db.query_all("SELECT status FROM documents")
    }
    assert statusy == {DocumentStatus.INDEXED.value}


# --- miejsce na dysku ------------------------------------------------------------


def test_ensure_free_space_rzuca_storage_space_error(
    tmp_home: AppPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(AppPaths, "free_space_bytes", lambda self: 5 * 1024 * 1024)

    ensure_free_space(tmp_home, 1024 * 1024)

    with pytest.raises(StorageSpaceError) as info:
        ensure_free_space(tmp_home, 200 * 1024 * 1024)

    assert "Za malo miejsca" in info.value.user_message
    assert info.value.details["available"] == 5 * 1024 * 1024


def test_backup_index_rzuca_gdy_brakuje_miejsca(
    index_service: IndexService, tmp_home: AppPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_document(index_service, "umowa.txt", "Tresc umowy ramowej dla testu miejsca na dysku.")
    index_service.flush()
    monkeypatch.setattr(AppPaths, "free_space_bytes", lambda self: 1024)

    with pytest.raises(StorageSpaceError) as info:
        backup_index(tmp_home, label="kopia-bez-miejsca")

    assert "Za malo miejsca" in info.value.user_message


def test_database_wykrywa_uszkodzenie_indeksu_fts(index_service: IndexService) -> None:
    add_document(index_service, "umowa.txt", "Tresc umowy ramowej dla kontroli indeksu FTS.")

    database: Database = index_service.db
    repository: Repository = index_service.repository

    assert database.integrity_check() == []
    assert database.fts_integrity_check() == []
    assert repository.count_chunks() == 2
