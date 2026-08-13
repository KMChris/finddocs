"""Testy magazynu wektorow pgvector, fabryki magazynow i degradacji.

Prawdziwy serwer PostgreSQL nie jest dostepny w srodowisku testowym, wiec
testy uzywaja udawanego sterownika. Udawany serwer rozumie dokladnie te
polecenia SQL, ktore wysyla magazyn, i trzyma stan w pamieci, dzieki czemu
testy sprawdzaja pelne zachowanie: metadane zgodnosci, upsert, usuwanie,
ranking iloczynu skalarnego i obsluge awarii polaczenia.
"""

from __future__ import annotations

import json
import re
import sys

import numpy as np
import pytest

from finddocs.chunking import ChunkingConfig, chunk_document
from finddocs.config import VectorStoreSettings
from finddocs.errors import (
    ConfigurationError,
    DependencyUnavailableError,
    IndexIncompatibleError,
    NetworkPolicyError,
    VectorBackendUnavailableError,
)
from finddocs.indexing.pgvector import PgVectorStore, validate_identifier, vector_literal
from finddocs.indexing.vector import VectorStore
from finddocs.indexing.vector_factory import create_vector_store
from finddocs.indexing.writer import DocumentPayload, IndexWriter
from finddocs.search.service import SearchService
from finddocs.security.network import EgressCategory, NetworkPolicy
from finddocs.types import (
    DocumentStatus,
    ExtractedSection,
    SearchMode,
    SearchRequest,
    SourceItem,
    SourceKind,
)

DIM = 4
COMPAT = "skrot-zgodnosci-testowy"

_QUALIFIED = re.compile(r'"[a-z0-9_]+"\."[a-z0-9_]+"')


# --- udawany sterownik -----------------------------------------------------------


class FakeError(Exception):
    pass


class FakeOperationalError(FakeError):
    pass


class FakeProgrammingError(FakeError):
    pass


class FakeServer:
    """Stan wspolny dla wszystkich polaczen udawanego serwera."""

    def __init__(self):
        self.extension = True
        self.can_create_extension = True
        self.fail_connect = False
        self.broken = False
        self.extension_version = "0.8.6"
        self.tables = {}
        self.dims = {}
        self.column_types = {}
        self.meta = {}
        self.connects = []


class FakeCursor:
    def __init__(self, rows, connection=None):
        self._rows = rows
        self._connection = connection

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def executemany(self, sql, rows):
        assert self._connection is not None
        for row in rows:
            self._connection.execute(sql, row)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    def __init__(self, server):
        self.server = server
        self.closed = False

    def close(self):
        self.closed = True

    def transaction(self):
        return _NullContext()

    def cursor(self):
        return FakeCursor([], connection=self)

    def execute(self, sql, params=None):
        if self.server.broken:
            raise FakeOperationalError("serwer nie odpowiada")
        s = " ".join(sql.split())
        if s.startswith("SELECT set_config"):
            return FakeCursor([])
        if s == "CREATE EXTENSION IF NOT EXISTS vector":
            if not self.server.can_create_extension:
                raise FakeProgrammingError("permission denied")
            self.server.extension = True
            return FakeCursor([])
        if s.startswith("CREATE TABLE IF NOT EXISTS"):
            name = _QUALIFIED.search(s).group(0)
            if "(key text" in s:
                self.server.meta.setdefault(name, {})
            elif name not in self.server.tables:
                match = re.search(r"embedding (halfvec|vector)\((\d+)\)", s)
                self.server.tables[name] = {}
                self.server.column_types[name] = match.group(1)
                self.server.dims[name] = int(match.group(2))
            return FakeCursor([])
        if s.startswith("CREATE INDEX"):
            return FakeCursor([])
        if s.startswith("SELECT key, value FROM"):
            name = _QUALIFIED.search(s).group(0)
            return FakeCursor(sorted(self.server.meta.get(name, {}).items()))
        if s.startswith("SELECT a.atttypmod"):
            name = f'"{params[0]}"."{params[1]}"'
            dimension = self.server.dims.get(name)
            if dimension is None:
                return FakeCursor([])
            return FakeCursor([(dimension, self.server.column_types.get(name, "halfvec"))])
        if s.startswith("INSERT INTO") and "__meta" in s:
            name = _QUALIFIED.search(s).group(0)
            key, value = params
            self.server.meta.setdefault(name, {})[key] = value
            return FakeCursor([])
        if s.startswith("INSERT INTO"):
            name = _QUALIFIED.search(s).group(0)
            chunk_id, literal = params
            self.server.tables[name][int(chunk_id)] = json.loads(literal)
            return FakeCursor([])
        if s.startswith("DELETE FROM") and "ANY" in s:
            name = _QUALIFIED.search(s).group(0)
            (ids,) = params
            for chunk_id in ids:
                self.server.tables.get(name, {}).pop(int(chunk_id), None)
            return FakeCursor([])
        if s.startswith("DELETE FROM"):
            name = _QUALIFIED.search(s).group(0)
            self.server.tables.get(name, {}).clear()
            return FakeCursor([])
        if s.startswith("SELECT COUNT(*) FROM"):
            name = _QUALIFIED.search(s).group(0)
            return FakeCursor([(len(self.server.tables.get(name, {})),)])
        if s.startswith("SELECT chunk_id, (embedding <#>"):
            name = _QUALIFIED.search(s).group(0)
            literal, _repeat, limit = params
            query = json.loads(literal)
            scored = [
                (chunk_id, float(sum(a * b for a, b in zip(query, vector, strict=True))))
                for chunk_id, vector in self.server.tables.get(name, {}).items()
            ]
            scored.sort(key=lambda row: (-row[1], row[0]))
            return FakeCursor(scored[: int(limit)])
        if s.startswith("SELECT embedding::text FROM"):
            name = _QUALIFIED.search(s).group(0)
            (chunk_id,) = params
            vector = self.server.tables.get(name, {}).get(int(chunk_id))
            return FakeCursor([(json.dumps(vector),)] if vector is not None else [])
        if s.startswith("SELECT pg_total_relation_size"):
            return FakeCursor([(4096,)])
        if s == "SHOW server_version":
            return FakeCursor([("16.4",)])
        if s.startswith("SELECT extversion"):
            return FakeCursor([(self.server.extension_version,)] if self.server.extension else [])
        raise AssertionError(f"nieobslugiwane SQL w tescie: {s}")


class FakeDriver:
    Error = FakeError
    OperationalError = FakeOperationalError
    ProgrammingError = FakeProgrammingError

    def __init__(self, server):
        self.server = server

    def connect(self, **kwargs):
        self.server.connects.append(kwargs)
        if self.server.fail_connect:
            raise FakeOperationalError("connection refused")
        return FakeConnection(self.server)


# --- pomocnicze ------------------------------------------------------------------


def make_settings(**overrides) -> VectorStoreSettings:
    values = {
        "backend": "pgvector",
        "pgvector_host": "baza.firma.local",
        "pgvector_database": "wyszukiwarka",
        "pgvector_user": "finddocs",
        "pgvector_table": "wektory_test",
    }
    values.update(overrides)
    return VectorStoreSettings(**values)


def allowing_policy(host: str = "baza.firma.local") -> NetworkPolicy:
    return NetworkPolicy(
        enabled_categories={EgressCategory.VECTOR_DB},
        extra_hosts={EgressCategory.VECTOR_DB: (host,)},
    )


def open_store(
    server: FakeServer,
    *,
    settings: VectorStoreSettings | None = None,
    compat: str = COMPAT,
    dimension: int = DIM,
    password=None,
) -> PgVectorStore:
    store = PgVectorStore(
        settings or make_settings(),
        password_provider=(lambda: password) if password is not None else None,
        policy=allowing_policy(),
        driver=FakeDriver(server),
    )
    store.open(
        dimension=dimension,
        model_key="model-testowy",
        model_version="1",
        vector_compat_hash=compat,
    )
    return store


def vectors(*rows: tuple[float, ...]) -> np.ndarray:
    return np.asarray(rows, dtype="float32")


# --- walidacja konfiguracji -------------------------------------------------------


def test_konstruktor_wymaga_kompletu_danych_polaczenia():
    with pytest.raises(ConfigurationError):
        PgVectorStore(make_settings(pgvector_host=" "))
    with pytest.raises(ConfigurationError):
        PgVectorStore(make_settings(pgvector_database=""))
    with pytest.raises(ConfigurationError):
        PgVectorStore(make_settings(pgvector_user=""))


def test_sslmode_disable_poza_localhost_jest_odrzucany():
    with pytest.raises(ConfigurationError) as blad:
        PgVectorStore(make_settings(pgvector_sslmode="disable"))
    assert "TLS" in blad.value.user_message


def test_sslmode_disable_dla_localhost_przechodzi():
    store = PgVectorStore(
        make_settings(pgvector_host="localhost", pgvector_sslmode="disable"),
        driver=FakeDriver(FakeServer()),
    )
    assert store is not None


def test_nieznany_sslmode_jest_odrzucany():
    with pytest.raises(ConfigurationError):
        PgVectorStore(make_settings(pgvector_sslmode="dziwny"))


def test_walidacja_identyfikatorow_sql():
    assert validate_identifier("finddocs_vectors", "tabela") == "finddocs_vectors"
    for zla in ("public; DROP TABLE x", 'a"b', "Wielkie", "1start", "a" * 58, ""):
        with pytest.raises(ConfigurationError):
            validate_identifier(zla, "tabela")


def test_brak_sterownika_daje_czytelny_blad(monkeypatch):
    monkeypatch.setitem(sys.modules, "psycopg", None)
    store = PgVectorStore(make_settings(), policy=allowing_policy())
    with pytest.raises(DependencyUnavailableError) as blad:
        store.open(dimension=DIM, model_key="m", model_version="1", vector_compat_hash=COMPAT)
    assert "finddocs[pgvector]" in blad.value.user_message


# --- polityka sieciowa ------------------------------------------------------------


def test_otwarcie_wymaga_wlaczonej_kategorii_vector_db():
    store = PgVectorStore(
        make_settings(),
        policy=NetworkPolicy.offline(),
        driver=FakeDriver(FakeServer()),
    )
    with pytest.raises(NetworkPolicyError):
        store.open(dimension=DIM, model_key="m", model_version="1", vector_compat_hash=COMPAT)


def test_localhost_dziala_bez_kategorii():
    server = FakeServer()
    store = PgVectorStore(
        make_settings(pgvector_host="localhost", pgvector_sslmode="disable"),
        policy=NetworkPolicy.offline(),
        driver=FakeDriver(server),
    )
    store.open(dimension=DIM, model_key="m", model_version="1", vector_compat_hash=COMPAT)
    assert store.is_open


# --- cykl zycia i metadane ----------------------------------------------------------


def test_otwarcie_tworzy_tabele_i_metadane():
    server = FakeServer()
    store = open_store(server)

    assert store.is_open
    assert store.dimension == DIM
    assert store.count() == 0
    meta = next(iter(server.meta.values()))
    assert meta["vector_compat_hash"] == COMPAT
    assert meta["dimension"] == str(DIM)
    assert meta["model_key"] == "model-testowy"
    kwargs = server.connects[-1]
    assert kwargs["sslmode"] == "require"
    assert kwargs["application_name"] == "FindDocs"


def test_haslo_pochodzi_z_dostawcy_i_trafia_do_polaczenia():
    server = FakeServer()
    open_store(server, password="sekretne-haslo")
    assert server.connects[-1]["password"] == "sekretne-haslo"


def test_ponowne_otwarcie_z_ta_sama_konfiguracja_przechodzi():
    server = FakeServer()
    first = open_store(server)
    first.add([1], vectors((1.0, 0.0, 0.0, 0.0)))
    first.close()

    second = open_store(server)
    assert second.count() == 1


def test_otwarcie_z_innym_skrotem_zgodnosci_jest_odrzucane():
    server = FakeServer()
    open_store(server).close()

    with pytest.raises(IndexIncompatibleError):
        open_store(server, compat="inny-skrot")


def test_otwarcie_z_innym_wymiarem_jest_odrzucane():
    server = FakeServer()
    open_store(server).close()

    with pytest.raises(IndexIncompatibleError):
        open_store(server, dimension=DIM + 1)


def test_tabela_ze_starym_typem_vector_wymaga_przebudowy():
    """Indeksy sprzed przejscia na halfvec nie moga byc czytane po cichu."""
    server = FakeServer()
    open_store(server).close()
    name = '"public"."wektory_test"'
    # Migawka sprzed zmiany: metadane bez klucza vector_type i kolumna vector.
    del server.meta['"public"."wektory_test__meta"']["vector_type"]
    server.column_types[name] = "vector"

    with pytest.raises(IndexIncompatibleError) as blad:
        open_store(server)

    assert "vector" in blad.value.user_message
    assert "przebudowa" in blad.value.user_message.lower()


def test_nowa_tabela_zapisuje_typ_halfvec_w_metadanych():
    server = FakeServer()
    store = open_store(server)
    store.close()

    meta = server.meta['"public"."wektory_test__meta"']
    assert meta["vector_type"] == "halfvec"
    assert server.column_types['"public"."wektory_test"'] == "halfvec"


def test_za_stare_pgvector_daje_czytelny_blad():
    """Typ halfvec pojawil sie w pgvector 0.7.0."""
    server = FakeServer()
    server.extension_version = "0.6.2"

    with pytest.raises(ConfigurationError) as blad:
        open_store(server)

    assert "0.6.2" in blad.value.user_message
    assert "0.7.0" in blad.value.user_message


def test_nietypowa_wersja_rozszerzenia_nie_blokuje_pracy():
    """Nieczytelny numer wersji przepuszczamy zamiast blokowac dzialajaca baze."""
    server = FakeServer()
    server.extension_version = "0.8.6-custom"
    open_store(server).close()

    server.extension_version = "wersja-nieznana"
    open_store(server).close()


def test_obca_tabela_o_innym_wymiarze_jest_odrzucana():
    server = FakeServer()
    name = '"public"."wektory_test"'
    server.tables[name] = {}
    server.dims[name] = DIM + 4

    with pytest.raises(IndexIncompatibleError) as blad:
        open_store(server)
    assert str(DIM + 4) in blad.value.user_message


def test_brak_rozszerzenia_bez_uprawnien_daje_czytelny_blad():
    server = FakeServer()
    server.extension = False
    server.can_create_extension = False

    with pytest.raises(ConfigurationError) as blad:
        open_store(server)
    assert "pgvector" in blad.value.user_message


def test_brak_rozszerzenia_z_uprawnieniami_instaluje_je():
    server = FakeServer()
    server.extension = False

    store = open_store(server)
    assert store.is_open
    assert server.extension is True


# --- operacje na wektorach -----------------------------------------------------------


def test_add_i_search_zwracaja_ranking_iloczynu_skalarnego():
    store = open_store(FakeServer())
    store.add(
        [10, 20, 30],
        vectors((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.7, 0.7, 0.0, 0.0)),
    )

    wyniki = store.search(np.asarray([1.0, 0.0, 0.0, 0.0], dtype="float32"), 2)

    assert [chunk_id for chunk_id, _ in wyniki] == [10, 30]
    assert wyniki[0][1] == pytest.approx(1.0)
    assert wyniki[1][1] == pytest.approx(0.7, abs=1e-6)


def test_ponowny_zapis_identyfikatora_nadpisuje_wektor():
    store = open_store(FakeServer())
    store.add([1], vectors((1.0, 0.0, 0.0, 0.0)))
    store.add([1], vectors((0.0, 1.0, 0.0, 0.0)))

    assert store.count() == 1
    odtworzony = store.reconstruct(1)
    np.testing.assert_allclose(odtworzony, [0.0, 1.0, 0.0, 0.0])


def test_remove_usuwa_od_razu_bez_nagrobkow():
    store = open_store(FakeServer())
    store.add([1, 2, 3], vectors((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0)))

    store.remove([1, 3])

    assert store.count() == 1
    assert store.deleted_count() == 0
    assert store.needs_compaction() is False
    assert store.reconstruct(1) is None


def test_reconstruct_zachowuje_precyzje_float32():
    store = open_store(FakeServer())
    original = np.asarray([[0.1, -2.5, 3.25, 1e-7]], dtype="float32")
    store.add([7], original)

    odtworzony = store.reconstruct(7)

    np.testing.assert_array_equal(odtworzony, original[0])


def test_compact_zastepuje_zawartosc_tabeli():
    store = open_store(FakeServer())
    store.add([1, 2], vectors((1, 0, 0, 0), (0, 1, 0, 0)))

    store.compact([5], vectors((0, 0, 1, 0)))

    assert store.count() == 1
    assert store.reconstruct(5) is not None
    assert store.reconstruct(1) is None


def test_reset_czysci_tabele():
    store = open_store(FakeServer())
    store.add([1], vectors((1, 0, 0, 0)))
    store.reset()
    assert store.count() == 0


def test_add_odrzuca_zly_ksztalt():
    store = open_store(FakeServer())
    from finddocs.errors import IndexCorruptedError

    with pytest.raises(IndexCorruptedError):
        store.add([1], np.zeros((1, DIM + 1), dtype="float32"))
    with pytest.raises(IndexCorruptedError):
        store.add([1, 2], np.zeros((1, DIM), dtype="float32"))


def test_describe_i_size_bytes():
    store = open_store(FakeServer())
    opis = store.describe()

    assert opis["magazyn"] == "pgvector"
    assert opis["tabela"] == "public.wektory_test"
    assert opis["wymiar"] == DIM
    assert store.size_bytes() == 4096


def test_ping_zwraca_wersje_serwera_i_rozszerzenia():
    server = FakeServer()
    store = PgVectorStore(make_settings(), policy=allowing_policy(), driver=FakeDriver(server))

    wynik = store.ping()

    assert wynik["wersja_serwera"] == "16.4"
    assert wynik["pgvector"] == "0.8.6"
    # Probne polaczenie nie zostaje otwarte na stale.
    assert not store.is_open


# --- awarie polaczenia ---------------------------------------------------------------


def test_blad_polaczenia_przy_otwarciu():
    server = FakeServer()
    server.fail_connect = True

    with pytest.raises(VectorBackendUnavailableError):
        open_store(server)


def test_awaria_w_trakcie_pracy_i_powrot():
    server = FakeServer()
    store = open_store(server)
    store.add([1], vectors((1, 0, 0, 0)))

    server.broken = True
    with pytest.raises(VectorBackendUnavailableError):
        store.add([2], vectors((0, 1, 0, 0)))

    server.broken = False
    store.add([2], vectors((0, 1, 0, 0)))
    assert store.count() == 2
    # Po awarii polaczenie zostalo nawiazane od nowa.
    assert len(server.connects) >= 2


def test_vector_literal_jest_zgodny_z_json():
    literal = vector_literal(np.asarray([0.5, -1.25], dtype="float32"))
    assert json.loads(literal) == [0.5, -1.25]


# --- fabryka magazynow ----------------------------------------------------------------


def test_fabryka_domyslnie_zwraca_faiss(tmp_home, app_config):
    store = create_vector_store(app_config, tmp_home)
    assert isinstance(store, VectorStore)


def test_fabryka_zwraca_pgvector_po_wlaczeniu(tmp_home, app_config):
    app_config.vector_store = make_settings()
    store = create_vector_store(app_config, tmp_home)
    assert isinstance(store, PgVectorStore)


def test_fabryka_odrzuca_nieznany_backend(tmp_home, app_config):
    app_config.vector_store.backend = "chmura"
    with pytest.raises(ConfigurationError):
        create_vector_store(app_config, tmp_home)


def test_fabryka_odrzuca_pgvector_bez_hosta(tmp_home, app_config):
    app_config.vector_store.backend = "pgvector"
    with pytest.raises(ConfigurationError):
        create_vector_store(app_config, tmp_home)


# --- degradacja zapisu i wyszukiwania ---------------------------------------------------


class _FailingVectorStore:
    """Magazyn, ktory udaje niedostepna baze przy wybranych operacjach."""

    def __init__(self, fail_add=False, fail_remove=False):
        self.fail_add = fail_add
        self.fail_remove = fail_remove
        self.added = []
        self.removed = []

    def add(self, ids, vectors_):
        if self.fail_add:
            raise VectorBackendUnavailableError()
        self.added.extend(ids)

    def remove(self, ids):
        if self.fail_remove:
            raise VectorBackendUnavailableError()
        self.removed.extend(ids)

    def save(self):
        pass


def _register_document(service, external_id="doc-1"):
    repository = service.repository
    repository.upsert_source(
        "zrodlo-testowe", SourceKind.LOCAL_DIR, "Testowe", location="pamiec", enabled=True
    )
    scan_id = repository.next_scan_id()
    item = SourceItem(
        source_id="zrodlo-testowe",
        external_id=external_id,
        name=f"{external_id}.txt",
        logical_path=f"testy/{external_id}.txt",
        size=64,
        modified_at=None,
    )
    doc_id = repository.register_item(item, scan_id)
    sections = [
        ExtractedSection(
            text="Notatka testowa o procedurze przelewow w oddziale glownym banku. " * 3,
            kind="text",
            order=0,
        )
    ]
    chunks = chunk_document(sections, ChunkingConfig(), extension=".txt")
    assert chunks
    return doc_id, chunks


def _payload(doc_id, chunks):
    return DocumentPayload(
        doc_id=doc_id,
        chunks=chunks,
        change_key="test:1",
        content_sha256=None,
        embeddings=np.ones((len(chunks), DIM), dtype="float32"),
        model_key="model-testowy",
    )


def test_zapis_przy_niedostepnej_bazie_konczy_sie_statusem_partial(index_service):
    doc_id, chunks = _register_document(index_service)
    writer = IndexWriter(index_service.repository, _FailingVectorStore(fail_add=True))

    wynik = writer.write_document(_payload(doc_id, chunks))

    assert wynik.status is DocumentStatus.PARTIAL
    assert wynik.vectors_written == 0
    record = index_service.repository.get_document(doc_id)
    assert record.status is DocumentStatus.PARTIAL
    bez_wektora = index_service.db.query_scalar(
        "SELECT COUNT(*) FROM chunks WHERE doc_id = ? AND has_vector = 1", (doc_id,), 0
    )
    assert int(bez_wektora) == 0


def test_zapis_dziala_gdy_baza_odpowiada(index_service):
    doc_id, chunks = _register_document(index_service, external_id="doc-2")
    store = _FailingVectorStore()
    writer = IndexWriter(index_service.repository, store)

    wynik = writer.write_document(_payload(doc_id, chunks))

    assert wynik.status is DocumentStatus.INDEXED
    assert wynik.vectors_written == len(chunks)
    assert store.added


def test_usuniecie_dokumentu_przezywa_awarie_usuwania_wektorow(index_service):
    doc_id, chunks = _register_document(index_service, external_id="doc-3")
    store = _FailingVectorStore()
    writer = IndexWriter(index_service.repository, store)
    writer.write_document(_payload(doc_id, chunks))

    store.fail_remove = True
    writer.delete_document(doc_id)

    assert index_service.repository.get_document(doc_id) is None


def test_wyszukiwanie_dziala_mimo_awarii_bazy_wektorowej(index_service, monkeypatch):
    service = SearchService(index_service)
    monkeypatch.setattr(type(index_service), "semantic_available", property(lambda self: True))

    def niedostepna(analysis, filters, cancel):
        raise VectorBackendUnavailableError()

    monkeypatch.setattr(service, "_vector_candidates", niedostepna)

    hybrydowa = service.search(SearchRequest(query="procedura", mode=SearchMode.HYBRID))
    semantyczna = service.search(SearchRequest(query="procedura", mode=SearchMode.SEMANTIC))

    komunikat = VectorBackendUnavailableError().user_message
    assert hybrydowa.mode is SearchMode.HYBRID
    assert komunikat in hybrydowa.notes
    assert semantyczna.mode is SearchMode.SEMANTIC
    assert komunikat in semantyczna.notes
