"""Kontrolowany korpus dokumentow dla testow wyszukiwania.

Dokumenty powstaja w kodzie, bez plikow na dysku i bez parserow. Tekst przechodzi
przez prawdziwa fragmentacje i prawdziwy zapis do indeksu, wiec testy sprawdzaja
cala sciezke wyszukiwania, a jednoczesnie znaja dokladna liczbe wystapien kazdego
elementu.

Liczby, ktore musza sie zgadzac (patrz ``build_corpus_docs``):

* numer rachunku 00 1234 5678 9012 3456 7890 1234: 17 dokumentow, trzy zapisy;
* fraza "procedura realizacji przelewow": 3 dokumenty (plus 2 dokumenty, ktore
  maja te same slowa, ale nie obok siebie);
* data 24 lipca 2015: 5 dokumentow w trzech zapisach;
* nazwisko Kowalski: 7 dokumentow, w tym 3 z odmiana "Kowalskiego";
* kwota 314 zl: 4 dokumenty;
* zdanie z polskimi znakami: 2 dokumenty;
* razem 66 dokumentow, zeby bylo co stronicowac.

Kazdy dokument ma zestaw cech (``features``). Testy licza oczekiwane zbiory
wynikow z tych cech, a nie z zakodowanych na sztywno liczb, wiec zmiana korpusu
nie wymaga poprawiania asercji w wielu miejscach.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from finddocs.chunking import ChunkingConfig, chunk_document
from finddocs.config import AppConfig
from finddocs.indexing.service import IndexService
from finddocs.indexing.writer import DocumentPayload
from finddocs.normalization.text import fold_for_search
from finddocs.providers.model_manifest import find_model_dir
from finddocs.search.service import SearchService
from finddocs.types import (
    DocumentHit,
    ExtractedSection,
    SearchFilters,
    SearchMode,
    SearchRequest,
    SearchResponse,
    SourceItem,
    SourceKind,
    TextOrigin,
)

# --- elementy, ktorych szukaja testy -------------------------------------------

#: Numer rachunku w trzech zapisach. Wszystkie daja ten sam token znormalizowany.
ACCOUNT_SPACED = "00 1234 5678 9012 3456 7890 1234"
ACCOUNT_DASHED = "00-1234-5678-9012-3456-7890-1234"
ACCOUNT_PLAIN = "00123456789012345678901234"
ACCOUNT_VARIANTS: tuple[str, ...] = (ACCOUNT_SPACED, ACCOUNT_DASHED, ACCOUNT_PLAIN)
ACCOUNT_DOCUMENTS = 17

#: Fraza szukana w cudzyslowie. W dokumentach zapisana poprawna polszczyzna.
PHRASE_TEXT = "procedura realizacji przelewów"
PHRASE_ASCII = "procedura realizacji przelewow"
PHRASE_DOCUMENTS = 3

#: Data w trzech zapisach: dziennikowym, ISO i slownym.
DATE_VARIANTS: tuple[str, ...] = ("24.07.2015", "2015-07-24", "24 lipca 2015")
DATE_DOCUMENTS = 5

SURNAME_DOCUMENTS = 7
AMOUNT_DOCUMENTS = 4
DIACRITICS_DOCUMENTS = 2

#: Zdanie pangramowe z kompletem polskich znakow.
DIACRITICS_TEXT = "zażółć gęślą jaźń"
DIACRITICS_ASCII = "zazolc gesla jazn"

#: Slowo wystepujace w kazdym dokumencie korpusu. Sluzy do testu paginacji.
COMMON_WORD = "archiwum"

#: Slowa oznaczajace dokumenty specjalne. Kazde wystepuje tylko w jednym dokumencie.
MULTI_CHUNK_WORD = "inwentaryzacja"
DUPLICATE_WORD = "windykacja"

#: Slowo, ktorego nie ma w zadnym dokumencie.
MISSING_WORD = "hipopotam"

TOTAL_DOCUMENTS = 66

# --- metadane rozdzielane cyklicznie -------------------------------------------

LOCAL_SOURCE = "zrodlo-lokalne"
SHAREPOINT_SOURCE = "zrodlo-sharepoint"
SOURCES: tuple[tuple[str, SourceKind, str], ...] = (
    (LOCAL_SOURCE, SourceKind.LOCAL_DIR, "Katalog lokalny"),
    (SHAREPOINT_SOURCE, SourceKind.SHAREPOINT, "Biblioteka SharePoint"),
)
LIBRARIES: tuple[str, ...] = ("Finanse", "Kadry", "Operacje")
AUTHORS: tuple[str, ...] = ("Anna Nowak", "Piotr Zielinski", "Maria Wisniewska", "Tomasz Baran")
EXTENSIONS: tuple[str, ...] = (".pdf", ".docx", ".xlsx", ".txt", ".msg")

#: Data modyfikacji pierwszego dokumentu. Kolejne sa co tydzien pozniej.
FIRST_MODIFIED = _dt.datetime(2018, 1, 3, 12, 0)
MODIFIED_STEP = _dt.timedelta(days=7)


@dataclass(frozen=True, slots=True)
class CorpusDoc:
    """Opis jednego dokumentu korpusu wraz z cechami sprawdzanymi w testach."""

    key: str
    name: str
    logical_path: str
    text: str
    source_id: str
    library: str
    author: str
    modified_at: _dt.datetime
    used_ocr: bool
    features: frozenset[str]

    @property
    def extension(self) -> str:
        return Path(self.name).suffix.lower()


# --- tresci dokumentow ---------------------------------------------------------

#: Zdania uzywane w dokumencie wielofragmentowym. Kazde jest inne, zeby fragmenty
#: nie zostaly uznane za powtorzenia i nie wypadly przy deduplikacji.
_INVENTORY_SENTENCES: tuple[str, ...] = (
    "Regal metalowy w magazynie glownym wymaga wymiany polek.",
    "Drukarka laserowa z dzialu ksiegowosci zostala przekazana do serwisu.",
    "Klimatyzator w sali konferencyjnej pracuje z podwyzszonym halasem.",
    "Krzesla obrotowe z pokoju numer siedem maja uszkodzone kolka.",
    "Rzutnik multimedialny zabezpieczono w szafie pancernej sekretariatu.",
    "Zestaw sluchawkowy telefonisty nie nadaje sie do dalszego uzytku.",
    "Laptop sluzbowy dzialu prawnego ma pekniete zawiasy obudowy.",
    "Skaner plaski pracuje wolniej niz przewiduje dokumentacja producenta.",
    "Niszczarka biurowa zostala oddana do naprawy gwarancyjnej.",
    "Czajnik elektryczny z aneksu kuchennego wycofano z uzytkowania.",
    "Szafa aktowa w kancelarii nie posiada sprawnego zamka bebenkowego.",
    "Monitor panoramiczny wykazuje przebarwienia w lewym gornym rogu.",
    "Router bezprzewodowy na pietrze drugim traci polaczenie wieczorem.",
    "Fotel gabinetowy poddano czyszczeniu chemicznemu przez firme zewnetrzna.",
    "Tablica suchoscieralna wymaga wymiany powierzchni roboczej.",
    "Aparat fotograficzny uzywany na szkoleniach ma zuzyta bateria.",
    "Wentylator stojacy przestal reagowac na zmiane biegow.",
    "Serwer plikow otrzymal dodatkowa pamiec operacyjna.",
    "Telefon stacjonarny w recepcji nie przekazuje polaczen wewnetrznych.",
    "Lampa biurowa z pokoju szkoleniowego swieci z przerwami.",
    "Waga listowa uzywana przez kancelarie zostala skalibrowana.",
    "Kalkulator z drukarka termiczna wymaga wymiany tasmy barwiacej.",
    "Podnosnik magazynowy przeszedl przeglad okresowy bez uwag.",
    "Zestaw narzedzi technicznych uzupelniono o brakujace klucze plaskie.",
    "Kopiarka wielofunkcyjna zglasza blad podajnika dolnego.",
    "Rolety okienne w pokoju obslugi klienta sa czesciowo zerwane.",
    "Odkurzacz przemyslowy pracuje ze zmniejszona sila ssania.",
    "Gasnica proszkowa przy wyjsciu ewakuacyjnym traci cisnienie.",
    "Zamek elektroniczny przy wejsciu bocznym gubi ustawienia czasu.",
    "Mikrofon konferencyjny przekazuje dzwiek z wyraznym szumem.",
)

#: Zdania wypelniajace. Nie zawieraja zadnego z elementow sprawdzanych w testach.
_FILLER_SENTENCES: tuple[str, ...] = (
    "Zespol wsparcia przygotowal zestawienie zgloszen z ostatniego kwartalu.",
    "Koszty eksploatacji budynku rozliczono zgodnie z zawarta umowa najmu.",
    "Dyzur techniczny w weekend obejmuje wylacznie awarie krytyczne.",
    "Wniosek o dostep do systemu kadrowego czeka na akceptacje przelozonego.",
    "Raport z badania satysfakcji zostanie omowiony na najblizszej naradzie.",
    "Plan remontu sali szkoleniowej przewiduje wymiane oswietlenia.",
    "Umowa serwisowa z dostawca uslug drukarskich wygasa z koncem roku.",
    "Zestawienie godzin nadliczbowych przekazano do dzialu personalnego.",
    "Rejestr korespondencji przychodzacej prowadzi kancelaria glowna.",
    "Szkolenie z ochrony danych osobowych odbedzie sie w trybie zdalnym.",
    "Zmiana godzin otwarcia placowki zostala ogloszona na tablicy informacyjnej.",
    "Protokol odbioru prac malarskich podpisano bez zastrzezen.",
)


def _header(position: int, title: str) -> str:
    """Naglowek obecny w kazdym dokumencie. Zawiera slowo wspolne dla korpusu."""
    return f"Archiwum FindDocs, pozycja {position:03d}. {title}."


def _inventory_text(position: int) -> str:
    """Dokument o wielu fragmentach: dziesiec roznych akapitow z tym samym slowem."""
    paragraphs = [_header(position, "Protokol z przegladu wyposazenia")]
    for part in range(10):
        chosen = _INVENTORY_SENTENCES[part * 3 : part * 3 + 3]
        body = " ".join(chosen)
        paragraphs.append(f"{MULTI_CHUNK_WORD.capitalize()}, czesc {part + 1}. {body}")
    return "\n\n".join(paragraphs)


def _duplicate_text(position: int) -> str:
    """Dokument z akapitami prawie identycznymi, roznia sie jednym slowem.

    Akapity sa na tyle dlugie, ze kazde powtorzenie trafia do wlasnego fragmentu.
    Naglowek jest na koncu, zeby nie rozcienczyl pierwszego powtorzenia.
    """
    ordinals = ("pierwsza", "druga", "trzecia", "czwarta")
    paragraphs: list[str] = []
    for ordinal in ordinals:
        paragraphs.append(
            f"{DUPLICATE_WORD.capitalize()} polubowna. Zespol skontaktowal sie z klientem "
            "w sprawie zaleglosci i ustalil nowy termin splaty calego zobowiazania. "
            f"Klient potwierdzil, ze ureguluje naleznosc w czesciach, a rata {ordinal} "
            "zostanie przekazana po weryfikacji salda przez oddzial prowadzacy sprawe. "
            "Rozmowe przeprowadzil pracownik zespolu do spraw naleznosci trudnych. "
            "Notatke dolaczono do akt postepowania."
        )
    paragraphs.append(_header(position, "Notatka z rozmow z dluznikiem"))
    return "\n\n".join(paragraphs)


def _filler_text(position: int, index: int) -> str:
    """Dokument wypelniajacy, zbudowany z dwoch zdan neutralnych."""
    first = _FILLER_SENTENCES[index % len(_FILLER_SENTENCES)]
    second = _FILLER_SENTENCES[(index + 5) % len(_FILLER_SENTENCES)]
    return f"{_header(position, 'Notatka biezaca')}\n\n{first} {second}"


# --- budowa korpusu ------------------------------------------------------------


def _metadata(position: int) -> tuple[str, str, str, str, _dt.datetime, bool]:
    """Metadane przydzielane cyklicznie. Kazdy cykl ma inna dlugosc, wiec filtry
    metadanych nie sa ze soba skorelowane."""
    source_id = SHAREPOINT_SOURCE if position % 4 == 3 else LOCAL_SOURCE
    library = LIBRARIES[position % len(LIBRARIES)]
    author = AUTHORS[position % len(AUTHORS)]
    extension = EXTENSIONS[position % len(EXTENSIONS)]
    modified = FIRST_MODIFIED + MODIFIED_STEP * position
    used_ocr = position % 7 == 0
    return source_id, library, author, extension, modified, used_ocr


def _make_doc(position: int, key: str, stem: str, text: str, features: Iterable[str]) -> CorpusDoc:
    source_id, library, author, extension, modified, used_ocr = _metadata(position)
    name = f"{stem}{extension}"
    return CorpusDoc(
        key=key,
        name=name,
        logical_path=f"{library}/{modified.year}/{name}",
        text=text,
        source_id=source_id,
        library=library,
        author=author,
        modified_at=modified,
        used_ocr=used_ocr,
        features=frozenset(features),
    )


def build_corpus_docs() -> tuple[CorpusDoc, ...]:
    """Buduje pelny korpus. Kolejnosc jest staly elementem umowy z testami."""
    docs: list[CorpusDoc] = []
    position = 0

    def add(key: str, stem: str, text: str, features: Iterable[str]) -> None:
        nonlocal position
        docs.append(_make_doc(position, key, stem, text, features))
        position += 1

    # 1. Numer rachunku w 17 dokumentach, w trzech zapisach.
    for number in range(ACCOUNT_DOCUMENTS):
        variant = ACCOUNT_VARIANTS[number % len(ACCOUNT_VARIANTS)]
        variant_name = ("spacje", "myslniki", "ciagly")[number % 3]
        body = (
            f"{_header(position, 'Potwierdzenie operacji bankowej')}\n\n"
            f"Srodki zostaly zaksiegowane na rachunku {variant}. "
            "Operacje wykonano w oddziale przy ulicy Krotkiej."
        )
        add(
            f"rachunek-{number + 1:02d}",
            f"potwierdzenie-{number + 1:02d}",
            body,
            {"rachunek", f"rachunek-{variant_name}"},
        )

    # 2. Fraza w trzech dokumentach.
    for number in range(PHRASE_DOCUMENTS):
        body = (
            f"{_header(position, 'Instrukcja operacyjna')}\n\n"
            f"{PHRASE_TEXT.capitalize()} obowiazuje we wszystkich oddzialach. "
            "Dokument opisuje kolejne kroki pracownika."
        )
        add(f"fraza-{number + 1:02d}", f"instrukcja-{number + 1:02d}", body, {"fraza"})

    # 3. Dokumenty z tymi samymi slowami, ale bez pelnej frazy.
    for number in range(2):
        body = (
            f"{_header(position, 'Pismo wewnetrzne')}\n\n"
            "Procedura wewnetrzna opisuje zasady realizacji zlecen oraz obsluge "
            "przelewów zagranicznych w oddziale."
        )
        add(f"fraza-luzna-{number + 1:02d}", f"pismo-{number + 1:02d}", body, {"fraza-luzna"})

    # 4. Data w pieciu dokumentach, w trzech zapisach.
    date_plan = (
        (DATE_VARIANTS[0], "dzienny"),
        (DATE_VARIANTS[0], "dzienny"),
        (DATE_VARIANTS[1], "iso"),
        (DATE_VARIANTS[1], "iso"),
        (DATE_VARIANTS[2], "slowny"),
    )
    for number, (written, variant_name) in enumerate(date_plan):
        body = (
            f"{_header(position, 'Dyspozycja klienta')}\n\n"
            f"Dyspozycje przyjeto w dniu {written} w oddziale glownym. "
            "Realizacja nastapila tego samego dnia."
        )
        add(
            f"data-{number + 1:02d}",
            f"dyspozycja-{number + 1:02d}",
            body,
            {"data", f"data-{variant_name}"},
        )

    # 5. Nazwisko w siedmiu dokumentach: cztery w mianowniku, dwa w odmianie,
    #    jeden zawiera obie formy.
    surname_plan = (
        ("Wniosek zlozyl Jan Kowalski, klient oddzialu w Krakowie.", {"nazwisko-mianownik"}),
        ("Rachunek prowadzony jest dla klienta Jan Kowalski.", {"nazwisko-mianownik"}),
        ("Reklamacje podpisal Jan Kowalski w obecnosci pracownika.", {"nazwisko-mianownik"}),
        ("Do akt dolaczono oswiadczenie, ktore zlozyl Jan Kowalski.", {"nazwisko-mianownik"}),
        ("Sprawa dotyczy pelnomocnictwa Jana Kowalskiego.", {"nazwisko-odmiana"}),
        ("Wypowiedzenie umowy Jana Kowalskiego wplynelo w terminie.", {"nazwisko-odmiana"}),
        (
            "Jan Kowalski przekazal komplet dokumentow. Podpis Jana Kowalskiego "
            "widnieje na ostatniej stronie.",
            {"nazwisko-mianownik", "nazwisko-odmiana"},
        ),
    )
    for number, (sentence, extra) in enumerate(surname_plan):
        body = f"{_header(position, 'Sprawa klienta')}\n\n{sentence}"
        add(
            f"nazwisko-{number + 1:02d}",
            f"sprawa-{number + 1:02d}",
            body,
            {"nazwisko", *extra},
        )

    # 6. Kwota w czterech zapisach.
    amount_plan = ("314 zl", "314,00 zl", "314.00 PLN", "314 złotych")
    for number, written in enumerate(amount_plan):
        body = (
            f"{_header(position, 'Nota ksiegowa')}\n\n"
            f"Do zaplaty pozostaje {written} tytulem oplaty rocznej."
        )
        add(f"kwota-{number + 1:02d}", f"nota-{number + 1:02d}", body, {"kwota"})

    # 7. Polskie znaki.
    for number in range(DIACRITICS_DOCUMENTS):
        body = (
            f"{_header(position, 'Zalacznik testowy')}\n\n"
            f"W tresci pisma pojawilo sie zdanie: {DIACRITICS_TEXT}. "
            "Zdanie sluzy do sprawdzenia poprawnosci druku."
        )
        add(f"polskie-{number + 1:02d}", f"zalacznik-{number + 1:02d}", body, {"polskie-znaki"})

    # 8. Dokument o wielu roznych fragmentach i dokument z powtorzeniami.
    add("wielofragmentowy", "protokol-przegladu", _inventory_text(position), {"wielofragmentowy"})
    add("powtorzenia", "notatka-windykacyjna", _duplicate_text(position), {"powtorzenia"})

    # 9. Wypelniacze do liczby TOTAL_DOCUMENTS.
    filler_index = 0
    while len(docs) < TOTAL_DOCUMENTS:
        add(
            f"wypelniacz-{filler_index + 1:02d}",
            f"notatka-{filler_index + 1:02d}",
            _filler_text(position, filler_index),
            {"wypelniacz"},
        )
        filler_index += 1

    return tuple(docs)


# --- zapis korpusu do indeksu --------------------------------------------------


def _chunking_config(config: AppConfig) -> ChunkingConfig:
    return ChunkingConfig(
        target_chars=config.chunking.target_chars,
        overlap_chars=config.chunking.overlap_chars,
        min_chars=config.chunking.min_chars,
        max_chars=config.chunking.max_chars,
        table_rows_per_chunk=config.chunking.table_rows_per_chunk,
        table_include_header=config.chunking.table_include_header,
        max_chunks=config.chunking.max_chunks_per_document,
    )


def _corpus_config(root: Path) -> AppConfig:
    """Konfiguracja z krotkimi fragmentami, zeby dokumenty testowe dzielily sie
    na akapity zamiast trafiac w calosci do jednego fragmentu."""
    config = AppConfig(data_root=str(root))
    config.chunking.target_chars = 400
    config.chunking.overlap_chars = 60
    config.chunking.min_chars = 80
    config.chunking.max_chars = 900
    return config


def index_documents(
    service: IndexService,
    config: AppConfig,
    docs: Sequence[CorpusDoc],
    *,
    with_vectors: bool,
) -> dict[str, int]:
    """Zapisuje dokumenty do indeksu. Zwraca mape klucz dokumentu na doc_id."""
    repository = service.repository
    for source_id, kind, label in SOURCES:
        repository.upsert_source(source_id, kind, label, location="pamiec", enabled=True)
    scan_id = repository.next_scan_id()
    chunking = _chunking_config(config)
    provider = service.provider if with_vectors else None

    doc_ids: dict[str, int] = {}
    for doc in docs:
        item = SourceItem(
            source_id=doc.source_id,
            external_id=doc.key,
            name=doc.name,
            logical_path=doc.logical_path,
            size=len(doc.text),
            modified_at=doc.modified_at,
            author=doc.author,
            library=doc.library,
            mime_type=None,
        )
        doc_id = repository.register_item(item, scan_id)
        sections = [ExtractedSection(text=doc.text, kind="text", order=0)]
        chunks = chunk_document(sections, chunking, extension=doc.extension)
        assert chunks, f"dokument {doc.key} nie dal zadnego fragmentu"
        embeddings = None
        if provider is not None:
            embeddings = provider.embed_passages([chunk.text for chunk in chunks])
        service.writer.write_document(
            DocumentPayload(
                doc_id=doc_id,
                chunks=chunks,
                change_key=f"test:{doc.key}",
                content_sha256=None,
                used_ocr=doc.used_ocr,
                ocr_pages=1 if doc.used_ocr else 0,
                ocr_confidence=0.91 if doc.used_ocr else None,
                text_origin=TextOrigin.OCR if doc.used_ocr else TextOrigin.NATIVE,
                parser_name="test",
                author=doc.author,
                embeddings=embeddings,
                model_key=provider.info.model_key if provider is not None else None,
            )
        )
        doc_ids[doc.key] = doc_id
    service.flush()
    return doc_ids


# --- obiekt udostepniany testom ------------------------------------------------


@dataclass(slots=True)
class SearchCorpus:
    """Gotowy indeks wraz z opisem dokumentow, ktore sie w nim znalazly."""

    index: IndexService
    service: SearchService
    docs: tuple[CorpusDoc, ...]
    doc_ids: dict[str, int]
    keys_by_id: dict[int, str] = field(init=False)

    def __post_init__(self) -> None:
        self.keys_by_id = {doc_id: key for key, doc_id in self.doc_ids.items()}

    # --- opis korpusu -------------------------------------------------

    @property
    def total(self) -> int:
        return len(self.docs)

    def spec(self, key: str) -> CorpusDoc:
        for doc in self.docs:
            if doc.key == key:
                return doc
        raise KeyError(key)

    def keys_with(self, feature: str) -> set[str]:
        return {doc.key for doc in self.docs if feature in doc.features}

    def ids_with(self, feature: str) -> set[int]:
        return self.ids_of(self.keys_with(feature))

    def ids_of(self, keys: Iterable[str]) -> set[int]:
        return {self.doc_ids[key] for key in keys}

    def all_ids(self) -> set[int]:
        return set(self.doc_ids.values())

    def key_of(self, doc_id: int) -> str:
        return self.keys_by_id[doc_id]

    # --- wygodne wywolania wyszukiwania -------------------------------

    def search(
        self,
        query: str,
        *,
        mode: SearchMode = SearchMode.EXACT,
        filters: SearchFilters | None = None,
        limit: int = 100,
        offset: int = 0,
        max_chunks: int = 3,
    ) -> SearchResponse:
        request = SearchRequest(
            query=query,
            mode=mode,
            filters=filters or SearchFilters(),
            limit=limit,
            offset=offset,
            max_chunks_per_document=max_chunks,
        )
        return self.service.search(request)

    def paginate(
        self,
        query: str,
        *,
        mode: SearchMode = SearchMode.EXACT,
        filters: SearchFilters | None = None,
        limit: int = 5,
        max_pages: int = 200,
    ) -> list[int]:
        """Przechodzi wszystkie strony wynikow i zwraca identyfikatory po kolei."""
        collected: list[int] = []
        for page in range(max_pages):
            response = self.search(
                query, mode=mode, filters=filters, limit=limit, offset=page * limit
            )
            if not response.hits:
                break
            collected.extend(hit.doc_id for hit in response.hits)
            if len(response.hits) < limit:
                break
        return collected


def hit_ids(hits: Sequence[DocumentHit]) -> list[int]:
    return [hit.doc_id for hit in hits]


def folded(text: str) -> str:
    return fold_for_search(text)


# --- fixture -------------------------------------------------------------------


@pytest.fixture(scope="session")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> Iterator[SearchCorpus]:
    """Indeks kontrolowanego korpusu, bez modelu embeddingow.

    Fixture jest w zasiegu sesji, bo wszystkie testy tylko czytaja z indeksu.
    """
    root = tmp_path_factory.mktemp("korpus-dokladny")
    config = _corpus_config(root)
    service = IndexService(config)
    service.open(load_provider=False)
    try:
        docs = build_corpus_docs()
        doc_ids = index_documents(service, config, docs, with_vectors=False)
        yield SearchCorpus(
            index=service,
            service=SearchService(service),
            docs=docs,
            doc_ids=doc_ids,
        )
    finally:
        service.close()


# --- korpus semantyczny --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SemanticCase:
    """Zapytanie semantyczne wraz z recznie oznaczonymi dokumentami istotnymi."""

    query: str
    relevant: tuple[str, ...]
    comment: str = ""


@dataclass(frozen=True, slots=True)
class HybridCase:
    """Zapytanie hybrydowe: opis znaczeniowy plus element doslowny."""

    query: str
    expected_first: str
    element: str


#: Dokumenty korpusu semantycznego. Klucz, tytul pliku i tresc.
SEMANTIC_DOCS: tuple[tuple[str, str, str], ...] = (
    (
        "kredyt",
        "umowa-kredytowa.pdf",
        "Umowa kredytu hipotecznego na zakup mieszkania. Zabezpieczeniem jest "
        "hipoteka wpisana do ksiegi wieczystej. Oprocentowanie zmienne oparte "
        "o wskaznik WIBOR.",
    ),
    (
        "reklamacja",
        "reklamacja-karta.pdf",
        "Reklamacja transakcji kartowej. Klient zglasza nieautoryzowana platnosc "
        "w sklepie internetowym. Bank rozpatrzy zgloszenie w terminie trzydziestu dni.",
    ),
    (
        "hasla",
        "polityka-hasel.docx",
        "Polityka bezpieczenstwa hasel w systemach wewnetrznych. Haslo musi miec "
        "co najmniej dwanascie znakow. Zmiana wymagana jest co dziewiecdziesiat dni.",
    ),
    (
        "spis",
        "protokol-spisu.docx",
        "Protokol z inwentaryzacji sprzetu biurowego. Spisano komputery, drukarki "
        "i monitory w oddziale przy ulicy Dlugiej. Braki zgloszono do administracji.",
    ),
    (
        "szkolenia",
        "harmonogram-szkolen.xlsx",
        "Harmonogram szkolen dla nowych pracownikow. Pierwszy modul dotyczy obslugi "
        "klienta. Drugi modul obejmuje przeciwdzialanie praniu pieniedzy.",
    ),
    (
        "urlop",
        "wniosek-urlopowy.docx",
        "Wniosek urlopowy. Pracownik wnosi o dziesiec dni wolnych w sierpniu. "
        "Zastepstwo zapewnia zespol operacyjny.",
    ),
    (
        "awaria",
        "zgloszenie-awarii.txt",
        "Awaria serwera pocztowego. Uzytkownicy nie mogli wysylac wiadomosci przez "
        "trzy godziny. Przyczyna byla usterka zasilania w serwerowni.",
    ),
    (
        "najem",
        "umowa-najmu.pdf",
        "Umowa najmu lokalu uzytkowego przy ulicy Krotkiej. Czynsz platny do "
        "dziesiatego dnia miesiaca. Kaucja zwrotna po zakonczeniu wspolpracy.",
    ),
    # dokumenty do trybu hybrydowego, kazdy ma odpowiednik bez elementu doslownego
    (
        "zlecenie-numer",
        "zlecenie-stale.pdf",
        f"Zlecenie stale obciazenia rachunku {ACCOUNT_SPACED}. Kwota bedzie "
        "pobierana w kazdym miesiacu az do odwolania dyspozycji.",
    ),
    (
        "zlecenie-bez-numeru",
        "zlecenie-stale-informacja.pdf",
        "Zlecenie stale mozna ustanowic w bankowosci internetowej. Kwota bedzie "
        "pobierana w kazdym miesiacu az do odwolania dyspozycji.",
    ),
    (
        "notatka-data",
        "notatka-zarzad-lipiec.docx",
        "Notatka ze spotkania zarzadu z dnia 24.07.2015. Omowiono plan otwarcia "
        "nowego oddzialu oraz budzet na promocje.",
    ),
    (
        "notatka-inna-data",
        "notatka-zarzad-marzec.docx",
        "Notatka ze spotkania zarzadu z dnia 12.03.2016. Omowiono plan otwarcia "
        "nowego oddzialu oraz budzet na promocje.",
    ),
    (
        "faktura-kwota",
        "faktura-kurier-314.pdf",
        "Faktura za uslugi kurierskie na kwote 314 zl. Platnosc przelewem "
        "w terminie czternastu dni od daty wystawienia.",
    ),
    (
        "faktura-inna-kwota",
        "faktura-kurier-980.pdf",
        "Faktura za uslugi kurierskie na kwote 980 zl. Platnosc przelewem "
        "w terminie czternastu dni od daty wystawienia.",
    ),
    (
        "klient-fabryka",
        "umowa-fabryka-domow.pdf",
        "Umowa o wspolpracy z firma Fabryka Domow. Zakres obejmuje obsluge "
        "rachunkow biezacych oraz doradztwo walutowe.",
    ),
    (
        "klient-stolarnia",
        "umowa-stolarnia-marzen.pdf",
        "Umowa o wspolpracy z firma Stolarnia Marzen. Zakres obejmuje obsluge "
        "rachunkow biezacych oraz doradztwo walutowe.",
    ),
    # dokumenty odciagajace uwage
    (
        "parking",
        "regulamin-parkingu.docx",
        "Regulamin korzystania z parkingu podziemnego. Miejsca oznaczone numerami "
        "sa przypisane do konkretnych samochodow sluzbowych.",
    ),
    (
        "delegacja",
        "rozliczenie-delegacji.xlsx",
        "Rozliczenie kosztow podrozy sluzbowej do Gdanska. Uwzgledniono bilety "
        "kolejowe oraz nocleg w hotelu przy dworcu.",
    ),
    (
        "materialy",
        "zamowienie-materialow.xlsx",
        "Zamowienie materialow biurowych na kolejny kwartal. Lista obejmuje papier, "
        "segregatory oraz tusze do drukarek atramentowych.",
    ),
    (
        "ankieta",
        "wyniki-ankiety.pdf",
        "Wyniki ankiety o preferowanych godzinach pracy stolowki pracowniczej. "
        "Najwiecej glosow otrzymala godzina dwunasta.",
    ),
    (
        "instalacja",
        "kontrola-instalacji.pdf",
        "Kontrola instalacji elektrycznej w budynku przy rynku. Pomiary rezystancji "
        "wykonano zgodnie z norma i bez zastrzezen.",
    ),
    (
        "logo",
        "konkurs-logo.docx",
        "Konkurs na nowe logo dla wewnetrznej gazetki firmowej. Prace mozna skladac "
        "w sekretariacie do konca miesiaca.",
    ),
    (
        "telefonia",
        "zmiana-operatora.docx",
        "Zmiana operatora telefonii komorkowej dla telefonow sluzbowych. Numery "
        "zostana przeniesione bez przerwy w dzialaniu.",
    ),
    (
        "rezerwacja",
        "rezerwacja-sali.txt",
        "Rezerwacja sali konferencyjnej na spotkanie z audytorem. Sala jest zajeta "
        "we wtorek od godziny osmej do poludnia.",
    ),
)

#: Zapytania semantyczne. Parafrazy nie maja wspolnych slow z dokumentem istotnym.
SEMANTIC_CASES: tuple[SemanticCase, ...] = (
    SemanticCase(
        query="jak sfinansowac wlasny dom dlugoterminowa pozyczka bankowa",
        relevant=("kredyt",),
        comment="kredyt hipoteczny opisany innymi slowami",
    ),
    SemanticCase(
        query="nieznane obciazenie konta po zakupach w sieci, jak odzyskac srodki",
        relevant=("reklamacja",),
        comment="reklamacja transakcji kartowej",
    ),
    SemanticCase(
        query="zasady tworzenia i okresowej wymiany kodu dostepu uzytkownika",
        relevant=("hasla",),
        comment="polityka hasel",
    ),
    SemanticCase(
        query="przeglad majatku trwalego w filii firmy",
        relevant=("spis",),
        comment="protokol inwentaryzacji",
    ),
    SemanticCase(
        query="plan zajec wprowadzajacych dla osob rozpoczynajacych prace",
        relevant=("szkolenia",),
        comment="harmonogram szkolen",
    ),
    SemanticCase(
        query="prosba o przerwe wypoczynkowa w okresie letnim",
        relevant=("urlop",),
        comment="wniosek urlopowy",
    ),
    SemanticCase(
        query="niedostepnosc skrzynki mailowej z powodu problemu technicznego",
        relevant=("awaria",),
        comment="awaria serwera pocztowego",
    ),
    SemanticCase(
        query="warunki wynajecia powierzchni pod dzialalnosc handlowa",
        relevant=("najem",),
        comment="umowa najmu lokalu",
    ),
)

#: Zapytania hybrydowe: tresc znaczeniowa plus element doslowny.
HYBRID_CASES: tuple[HybridCase, ...] = (
    HybridCase(
        query=f"stala dyspozycja obciazania konta {ACCOUNT_SPACED}",
        expected_first="zlecenie-numer",
        element="numer rachunku",
    ),
    HybridCase(
        query="notatka ze spotkania zarzadu 24.07.2015",
        expected_first="notatka-data",
        element="data",
    ),
    HybridCase(
        query="faktura za przesylki kurierskie na 314 zl",
        expected_first="faktura-kwota",
        element="kwota",
    ),
    HybridCase(
        query='umowa o wspolpracy z klientem "Fabryka Domow"',
        expected_first="klient-fabryka",
        element="nazwa klienta",
    ),
)


@dataclass(slots=True)
class SemanticCorpus:
    """Maly korpus polski z wektorami, uzywany w testach jakosci."""

    index: IndexService
    service: SearchService
    doc_ids: dict[str, int]
    cases: tuple[SemanticCase, ...] = SEMANTIC_CASES
    hybrid_cases: tuple[HybridCase, ...] = HYBRID_CASES

    def key_of(self, doc_id: int) -> str:
        for key, value in self.doc_ids.items():
            if value == doc_id:
                return key
        raise KeyError(doc_id)

    def ranking(self, response: SearchResponse) -> list[str]:
        return [self.key_of(hit.doc_id) for hit in response.hits]

    def search(
        self,
        query: str,
        *,
        mode: SearchMode,
        limit: int = 10,
    ) -> SearchResponse:
        return self.service.search(SearchRequest(query=query, mode=mode, limit=limit))


def build_semantic_docs() -> tuple[CorpusDoc, ...]:
    """Dokumenty korpusu semantycznego z prostymi metadanymi."""
    docs: list[CorpusDoc] = []
    for position, (key, name, text) in enumerate(SEMANTIC_DOCS):
        source_id, library, author, _extension, modified, used_ocr = _metadata(position)
        docs.append(
            CorpusDoc(
                key=key,
                name=name,
                logical_path=f"{library}/{modified.year}/{name}",
                text=f"{_header(position, 'Dokument testowy')}\n\n{text}",
                source_id=source_id,
                library=library,
                author=author,
                modified_at=modified,
                used_ocr=used_ocr,
                features=frozenset({"semantyczny"}),
            )
        )
    return tuple(docs)


@pytest.fixture(scope="session")
def semantic_corpus(tmp_path_factory: pytest.TempPathFactory) -> Iterator[SemanticCorpus]:
    """Indeks z wektorami. Pomija testy, gdy modelu nie ma na dysku."""
    root = tmp_path_factory.mktemp("korpus-semantyczny")
    config = _corpus_config(root)
    if find_model_dir(config.embedding.model_key) is None:
        pytest.skip("Brak lokalnego modelu embeddingow.")
    service = IndexService(config)
    service.open(load_provider=True)
    if not service.semantic_available:
        service.close()
        pytest.skip("Dostawca embeddingow nie zostal zaladowany.")
    try:
        docs = build_semantic_docs()
        doc_ids = index_documents(service, config, docs, with_vectors=True)
        yield SemanticCorpus(
            index=service,
            service=SearchService(service),
            doc_ids=doc_ids,
        )
    finally:
        service.close()
