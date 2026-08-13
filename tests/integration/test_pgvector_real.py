"""Testy integracyjne magazynu pgvector na prawdziwym serwerze PostgreSQL.

Domyslnie pomijane: wymagaja dzialajacego serwera z rozszerzeniem pgvector
i zmiennych srodowiskowych. Serwer do prob mozna uruchomic w kontenerze:

    docker run -d --name finddocs-pg-test -e POSTGRES_USER=finddocs \
      -e POSTGRES_PASSWORD=finddocs-test-haslo -e POSTGRES_DB=wyszukiwarka \
      -p 54329:5432 --memory 1g --memory-swap 1g pgvector/pgvector:pg17

Limit pamieci jest czescia polecenia celowo: kontener bez limitu moze rosnac
do calego RAM maszyny wirtualnej Dockera, a serwer w tych testach zajmuje
kilkadziesiat MB. Rowny limit wymiany wylacza swap kontenera.

a potem uruchomic testy tak:

    FINDDOCS_TEST_PGVECTOR_HOST=localhost \
    FINDDOCS_TEST_PGVECTOR_PORT=54329 \
    FINDDOCS_TEST_PGVECTOR_PASSWORD=finddocs-test-haslo \
    .venv/Scripts/python.exe -m pytest tests/integration/test_pgvector_real.py -q

Kazdy test dostaje wlasna tabele o losowej nazwie i sprzata ja po sobie,
wiec testy mozna uruchamiac wielokrotnie na tym samym serwerze.
"""

from __future__ import annotations

import os
import uuid

import numpy as np
import pytest

from finddocs.chunking import ChunkingConfig, chunk_document
from finddocs.config import VectorStoreSettings
from finddocs.errors import IndexIncompatibleError
from finddocs.indexing.pgvector import PgVectorStore
from finddocs.indexing.service import IndexService
from finddocs.indexing.writer import DocumentPayload
from finddocs.providers.model_manifest import find_model_dir
from finddocs.search.service import SearchService
from finddocs.security.network import (
    EgressCategory,
    NetworkPolicy,
    policy_from_config,
    set_policy,
)
from finddocs.types import (
    ExtractedSection,
    SearchMode,
    SearchRequest,
    SourceItem,
    SourceKind,
)

HOST = os.environ.get("FINDDOCS_TEST_PGVECTOR_HOST", "")
PORT = int(os.environ.get("FINDDOCS_TEST_PGVECTOR_PORT", "5432"))
DATABASE = os.environ.get("FINDDOCS_TEST_PGVECTOR_DATABASE", "wyszukiwarka")
USER = os.environ.get("FINDDOCS_TEST_PGVECTOR_USER", "finddocs")
PASSWORD = os.environ.get("FINDDOCS_TEST_PGVECTOR_PASSWORD", "")
SSLMODE = os.environ.get("FINDDOCS_TEST_PGVECTOR_SSLMODE", "disable")

pytestmark = pytest.mark.skipif(
    not HOST,
    reason="Brak serwera PostgreSQL do prob. Ustaw FINDDOCS_TEST_PGVECTOR_HOST.",
)

DIM = 8
COMPAT = "skrot-testu-integracyjnego"


# --- pomocnicze ------------------------------------------------------------------


def make_settings(table: str) -> VectorStoreSettings:
    return VectorStoreSettings(
        backend="pgvector",
        pgvector_host=HOST,
        pgvector_port=PORT,
        pgvector_database=DATABASE,
        pgvector_user=USER,
        pgvector_table=table,
        pgvector_sslmode=SSLMODE,
    )


def allowing_policy() -> NetworkPolicy:
    """Polityka dopuszczajaca dokladnie host z konfiguracji testu."""
    return NetworkPolicy(
        enabled_categories={EgressCategory.VECTOR_DB},
        extra_hosts={EgressCategory.VECTOR_DB: (HOST.lower(),)},
    )


def _password() -> str | None:
    return PASSWORD or None


def _raw_connection():
    import psycopg

    return psycopg.connect(
        host=HOST,
        port=PORT,
        dbname=DATABASE,
        user=USER,
        password=_password(),
        sslmode=SSLMODE,
        connect_timeout=10,
        autocommit=True,
    )


def _drop_tables(table: str) -> None:
    from psycopg import sql

    with _raw_connection() as conn:
        for name in (f"{table}__meta", table):
            conn.execute(
                sql.SQL("DROP TABLE IF EXISTS {}.{}").format(
                    sql.Identifier("public"), sql.Identifier(name)
                )
            )


def new_store(table: str) -> PgVectorStore:
    return PgVectorStore(
        make_settings(table),
        password_provider=_password,
        policy=allowing_policy(),
    )


def open_store(store: PgVectorStore, *, compat: str = COMPAT, dimension: int = DIM) -> None:
    store.open(
        dimension=dimension,
        model_key="model-it",
        model_version="1",
        vector_compat_hash=compat,
    )


@pytest.fixture
def table_name():
    name = f"wektory_it_{uuid.uuid4().hex[:10]}"
    yield name
    _drop_tables(name)


@pytest.fixture
def store(table_name):
    instance = new_store(table_name)
    yield instance
    instance.close()


# --- podstawowy cykl zycia --------------------------------------------------------


def test_otwarcie_tworzy_tabele_i_rozszerzenie(store, table_name):
    open_store(store)

    assert store.is_open
    assert store.count() == 0
    with _raw_connection() as conn:
        extension = conn.execute(
            "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
        ).fetchone()
        assert extension is not None
        column = conn.execute(
            "SELECT a.atttypmod, format_type(a.atttypid, a.atttypmod) FROM pg_attribute a "
            "JOIN pg_class c ON c.oid = a.attrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relname = %s AND a.attname = 'embedding'",
            (table_name,),
        ).fetchone()
        assert column is not None
        # Zalozenie produkcyjne z _check_column_dimension: atttypmod typu
        # halfvec przechowuje wprost liczbe wymiarow, tak samo jak vector.
        assert int(column[0]) == DIM
        assert column[1] == f"halfvec({DIM})"


def test_add_search_remove_na_prawdziwym_serwerze(store):
    open_store(store)
    wektory = np.asarray(
        [
            [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.7, 0.7, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        ],
        dtype="float32",
    )
    store.add([10, 20, 30], wektory)
    assert store.count() == 3

    zapytanie = np.asarray([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype="float32")
    wyniki = store.search(zapytanie, 3)

    assert [chunk_id for chunk_id, _ in wyniki] == [10, 30, 20]
    oczekiwane = wektory @ zapytanie
    # Kolumna ma typ halfvec (float16), wiec podobienstwo zgadza sie do okolo
    # trzech cyfr znaczacych. Kolejnosc wynikow pozostaje bez zmian.
    assert wyniki[0][1] == pytest.approx(float(oczekiwane[0]), rel=1e-3)
    assert wyniki[1][1] == pytest.approx(float(oczekiwane[2]), rel=1e-3)

    store.remove([10])
    assert store.count() == 2
    assert store.deleted_count() == 0
    assert store.reconstruct(10) is None


def test_upsert_i_odtworzenie_wektora_z_precyzja_float16(store):
    """Kolumna halfvec zaokragla do float16; wartosci dokladne w tym typie wracaja bez zmian."""
    open_store(store)
    # Same potegi dwojki i ich sumy: reprezentowalne dokladnie w float16.
    dokladny = np.asarray([[0.5, -2.5, 3.25, 0.0, 128.0, -0.0625, 7.0, 0.0]], dtype="float32")
    store.add([7], dokladny)
    store.add([7], dokladny * 2.0)

    assert store.count() == 1
    np.testing.assert_array_equal(store.reconstruct(7), (dokladny * 2.0)[0])

    # Wartosc spoza siatki float16 wraca zaokraglona, ale w granicach typu.
    niedokladny = np.asarray([[0.1, -2.5, 3.25, 1e-7, 123.456, -0.0625, 7.0, 0.0]], dtype="float32")
    store.add([8], niedokladny)
    odtworzony = store.reconstruct(8)
    np.testing.assert_allclose(odtworzony, niedokladny[0], rtol=1e-3, atol=1e-6)


def test_zaokraglenie_do_float16_jest_stabilne_przy_kompaktacji(store):
    """Kompaktacja czyta wektory i zapisuje je z powrotem, wiec blad nie moze narastac."""
    open_store(store)
    pierwotny = np.asarray([[0.1, -2.5, 3.25, 1e-7, 123.456, -0.0625, 7.0, 0.31]], dtype="float32")
    store.add([11], pierwotny)

    poprzedni = store.reconstruct(11)
    assert poprzedni is not None
    for _ in range(3):
        store.compact([11], np.asarray([poprzedni], dtype="float32"))
        biezacy = store.reconstruct(11)
        assert biezacy is not None
        np.testing.assert_array_equal(biezacy, poprzedni)
        poprzedni = biezacy


def test_reset_compact_describe_i_rozmiar(store):
    open_store(store)
    store.add([1, 2], np.eye(2, DIM, dtype="float32"))

    store.compact([5], np.ones((1, DIM), dtype="float32"))
    assert store.count() == 1
    assert store.reconstruct(5) is not None

    opis = store.describe()
    assert opis["magazyn"] == "pgvector"
    assert opis["wymiar"] == DIM
    assert store.size_bytes() > 0

    store.reset()
    assert store.count() == 0


def test_duze_paczki_i_glebokie_wyszukiwanie(store):
    """Wsad wiekszy niz INSERT_BATCH_ROWS i zapytanie glebsze niz domyslny ef_search.

    Wektory sa znormalizowane L2, tak jak w produkcji: iloczyn skalarny jest
    wtedy podobienstwem cosinusowym i wektor zapytania jest swoim najlepszym
    dopasowaniem. Bez normalizacji najwiekszy iloczyn moze osiagnac inny
    wektor o duzej normie i test bylby matematycznie bledny.
    """
    open_store(store)
    generator = np.random.default_rng(0)
    liczba = 1200
    wektory = generator.standard_normal((liczba, DIM)).astype("float32")
    wektory /= np.linalg.norm(wektory, axis=1, keepdims=True)
    identyfikatory = list(range(1, liczba + 1))
    store.add(identyfikatory, wektory)
    assert store.count() == liczba

    zapytanie = wektory[17]
    wyniki = store.search(zapytanie, 600)

    assert len(wyniki) == 600
    assert wyniki[0][0] == 18
    # Kolumna halfvec zaokragla skladowe do float16, wiec samopodobienstwo
    # wypada tuz pod 1.0. Blad rzedu 1e-3 nie zmienia kolejnosci wynikow.
    assert wyniki[0][1] == pytest.approx(1.0, abs=1e-3)
    oceny = [score for _, score in wyniki]
    assert oceny == sorted(oceny, reverse=True)

    # Ranking przyblizony HNSW ma przy ef_search >= k odnalezc czolowke
    # dokladnego rankingu liczonego w numpy.
    dokladne = wektory @ zapytanie
    czolowka = {int(pozycja) + 1 for pozycja in np.argsort(-dokladne)[:10]}
    zwrocone = {chunk_id for chunk_id, _ in wyniki}
    assert czolowka <= zwrocone


def test_ping_zwraca_wersje_serwera_i_rozszerzenia(table_name):
    wynik = new_store(table_name).ping()

    assert wynik["pgvector"] is not None
    assert wynik["wersja_serwera"]


# --- metadane zgodnosci -------------------------------------------------------------


def test_metadane_zgodnosci_na_serwerze(table_name):
    pierwszy = new_store(table_name)
    open_store(pierwszy)
    pierwszy.add([1], np.ones((1, DIM), dtype="float32"))
    pierwszy.close()

    drugi = new_store(table_name)
    open_store(drugi)
    assert drugi.count() == 1
    drugi.close()

    inny_skrot = new_store(table_name)
    with pytest.raises(IndexIncompatibleError):
        open_store(inny_skrot, compat="inny-skrot")

    inny_wymiar = new_store(table_name)
    with pytest.raises(IndexIncompatibleError):
        open_store(inny_wymiar, dimension=DIM + 8)


# --- pelny potok z modelem embeddingow ------------------------------------------------


_E2E_DOCS: tuple[tuple[str, str, str], ...] = (
    (
        "kredyt",
        "umowa-kredytowa.txt",
        "Umowa kredytu hipotecznego na zakup mieszkania. Zabezpieczeniem jest "
        "hipoteka wpisana do ksiegi wieczystej, oprocentowanie zmienne.",
    ),
    (
        "awaria",
        "zgloszenie-awarii.txt",
        "Awaria serwera pocztowego. Uzytkownicy nie mogli wysylac wiadomosci "
        "przez trzy godziny z powodu usterki zasilania w serwerowni.",
    ),
    (
        "urlop",
        "wniosek-urlopowy.txt",
        "Wniosek urlopowy. Pracownik wnosi o dziesiec dni wolnych w sierpniu, "
        "zastepstwo zapewnia zespol operacyjny.",
    ),
)


@pytest.mark.slow
@pytest.mark.requires_model
def test_pelny_potok_indeksowania_i_wyszukiwania_na_pgvector(app_config, table_name, monkeypatch):
    """Prawdziwy model MMLW liczy wektory, prawdziwy PostgreSQL je przechowuje."""
    if find_model_dir(app_config.embedding.model_key) is None:
        pytest.skip("Brak lokalnego modelu embeddingow w katalogu models/.")

    app_config.vector_store = make_settings(table_name)
    monkeypatch.setattr(
        "finddocs.indexing.vector_factory.pgvector_password_provider",
        lambda config_dir: _password,
    )
    set_policy(policy_from_config(app_config))
    service = IndexService(app_config)
    try:
        service.open(load_provider=True)
        if not service.semantic_available:
            pytest.skip("Semantyka niedostepna: " + "; ".join(service.notes))
        assert isinstance(service.vector_store, PgVectorStore)

        repository = service.repository
        repository.upsert_source(
            "zrodlo-it", SourceKind.LOCAL_DIR, "Testowe", location="pamiec", enabled=True
        )
        scan_id = repository.next_scan_id()
        doc_ids: dict[str, int] = {}
        for key, name, text in _E2E_DOCS:
            item = SourceItem(
                source_id="zrodlo-it",
                external_id=key,
                name=name,
                logical_path=f"testy/{name}",
                size=len(text),
            )
            doc_id = repository.register_item(item, scan_id)
            sections = [ExtractedSection(text=text, kind="text", order=0)]
            chunks = chunk_document(sections, ChunkingConfig(), extension=".txt")
            assert service.provider is not None
            embeddings = service.provider.embed_passages([c.text for c in chunks])
            service.writer.write_document(
                DocumentPayload(
                    doc_id=doc_id,
                    chunks=chunks,
                    change_key=f"it:{key}",
                    content_sha256=None,
                    embeddings=embeddings,
                    model_key=service.provider.info.model_key,
                )
            )
            doc_ids[key] = doc_id
        service.flush()

        raport = service.consistency()
        assert raport.vectors_in_store == raport.vectors_in_db
        assert raport.vectors_in_store >= len(_E2E_DOCS)

        search = SearchService(service)
        odpowiedz = search.search(
            SearchRequest(
                query="jak sfinansowac zakup wlasnego mieszkania pozyczka z banku",
                mode=SearchMode.SEMANTIC,
                limit=3,
            )
        )
        assert odpowiedz.hits
        assert odpowiedz.hits[0].doc_id == doc_ids["kredyt"]
    finally:
        service.close()
        set_policy(NetworkPolicy.offline())
