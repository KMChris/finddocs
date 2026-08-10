"""Wspolne typy danych przekazywane miedzy warstwami aplikacji.

Modul nie importuje niczego z warstw wyzszych. Wszystkie struktury sa niemutowalne
tam, gdzie to mozliwe, zeby uproscic przekazywanie ich miedzy watkami.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


class SourceKind(StrEnum):
    """Rodzaj zrodla dokumentow."""

    LOCAL_DIR = "local_dir"
    SHAREPOINT = "sharepoint"


class DocumentStatus(StrEnum):
    """Status dokumentu w indeksie."""

    PENDING = "pending"
    """Wykryty, jeszcze nieprzetworzony."""

    INDEXED = "indexed"
    """Przetworzony i wyszukiwalny."""

    PARTIAL = "partial"
    """Tekst zaindeksowany, ale brakuje części wektorowej."""

    SKIPPED = "skipped"
    """Świadomie pominięty, np. zbyt duży albo filtr rozszerzeń."""

    UNSUPPORTED = "unsupported"
    """Format nieobsługiwany."""

    CORRUPTED = "corrupted"
    """Plik uszkodzony."""

    PASSWORD_PROTECTED = "password_protected"
    """Plik zabezpieczony hasłem lub zaszyfrowany."""

    EMPTY = "empty"
    """Brak treści możliwej do zaindeksowania."""

    DOWNLOAD_FAILED = "download_failed"
    """Nie udało się pobrać pliku ze źródła."""

    ERROR = "error"
    """Inny błąd przetwarzania."""

    DELETED = "deleted"
    """Usunięty ze źródła, oczekuje na usunięcie z indeksu."""


#: Statusy, przy ktorych dokument nie jest wyszukiwalny.
NON_SEARCHABLE_STATUSES: frozenset[DocumentStatus] = frozenset(
    {
        DocumentStatus.PENDING,
        DocumentStatus.SKIPPED,
        DocumentStatus.UNSUPPORTED,
        DocumentStatus.CORRUPTED,
        DocumentStatus.PASSWORD_PROTECTED,
        DocumentStatus.EMPTY,
        DocumentStatus.DOWNLOAD_FAILED,
        DocumentStatus.ERROR,
        DocumentStatus.DELETED,
    }
)


class TextOrigin(StrEnum):
    """Pochodzenie tekstu fragmentu."""

    NATIVE = "native"
    """Tekst odczytany bezpośrednio z pliku."""

    OCR = "ocr"
    """Tekst rozpoznany przez OCR."""

    MIXED = "mixed"
    """Część natywna, część z OCR."""


class SupportLevel(StrEnum):
    """Deklarowany poziom wsparcia formatu."""

    FULL = "full"
    """Pełna ekstrakcja tekstu i metadanych, przetestowana."""

    GOOD = "good"
    """Ekstrakcja tekstu działa, metadane moga być niepełne."""

    LIMITED = "limited"
    """Działa warunkowo, np. zależy od zewnetrznego komponentu."""

    EXPERIMENTAL = "experimental"
    """Obsługa zaimplementowana, ale słabo przetestowana na danych produkcyjnych."""

    NONE = "none"
    """Format rozpoznawany, ale nieobsługiwany."""


class SearchMode(StrEnum):
    """Tryb wyszukiwania wybrany przez uzytkownika."""

    HYBRID = "hybrid"
    EXACT = "exact"
    SEMANTIC = "semantic"


class MatchKind(StrEnum):
    """Rodzaj dopasowania pojedynczego wyniku."""

    EXACT = "exact"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"


class JobState(StrEnum):
    """Stan zadania w kolejce."""

    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    FAILED = "failed"
    COMPLETED = "completed"


class JobKind(StrEnum):
    """Rodzaj zadania."""

    FULL_INDEX = "full_index"
    RESCAN = "rescan"
    REBUILD_VECTORS = "rebuild_vectors"
    COMPACT = "compact"


# --- opis pliku w zrodle -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceItem:
    """Jeden obiekt wykryty w zrodle dokumentow.

    Reprezentuje metadane, ktore mozna uzyskac bez pobierania tresci.
    """

    source_id: str
    """Identyfikator konfiguracji źródła."""

    external_id: str
    """Trwały identyfikator obiektu w źródle (driveItem id albo ścieżka względna)."""

    name: str
    """Nazwa pliku wraz z rozszerzeniem."""

    logical_path: str
    """Czytelna ścieżka logiczna w obrębie źródła, separator '/'."""

    size: int | None = None
    modified_at: _dt.datetime | None = None
    created_at: _dt.datetime | None = None
    etag: str | None = None
    content_hash: str | None = None
    """Skrót treści podany przez źródło (quickXorHash, sha1 albo wlasny)."""

    author: str | None = None
    mime_type: str | None = None
    web_url: str | None = None
    parent_url: str | None = None
    library: str | None = None
    """Nazwa biblioteki dokumentów albo katalogu głównego źródła."""

    is_folder: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def extension(self) -> str:
        """Rozszerzenie pliku, malymi literami, z kropka. Pusty string gdy brak."""
        suffix = Path(self.name).suffix
        return suffix.lower()

    def change_key(self) -> str:
        """Klucz uzywany do wykrywania zmiany dokumentu.

        Kolejnosc preferencji: ETag, skrot tresci, data modyfikacji z rozmiarem.
        """
        if self.etag:
            return f"etag:{self.etag}"
        if self.content_hash:
            return f"hash:{self.content_hash}"
        stamp = self.modified_at.isoformat() if self.modified_at else "?"
        return f"mtime:{stamp}:{self.size if self.size is not None else '?'}"


@dataclass(frozen=True, slots=True)
class FetchedFile:
    """Pobrany plik zapisany w bezpiecznej przestrzeni tymczasowej."""

    item: SourceItem
    path: Path
    size: int
    sha256: str


# --- wynik ekstrakcji ----------------------------------------------------------


@dataclass(slots=True)
class ExtractedAttachment:
    """Zalacznik wiadomosci e-mail albo dokumentu zlozonego."""

    name: str
    mime_type: str | None
    data: bytes
    """Surowa zawartość załącznika."""


@dataclass(slots=True)
class ExtractedSection:
    """Logiczna czesc dokumentu przekazywana do fragmentacji.

    Sekcja pozwala parserowi zasugerowac naturalne granice: strone PDF,
    arkusz Excela, akapit Worda albo tresc zalacznika.
    """

    text: str
    kind: str = "text"
    """Rodzaj sekcji: text, table_row, table_header, sheet, page, email_header."""

    order: int = 0
    page: int | None = None
    sheet: str | None = None
    row: int | None = None
    origin: TextOrigin = TextOrigin.NATIVE
    ocr_confidence: float | None = None
    heading: str | None = None
    """Nagłówek dziedziczony przez fragmenty, np. nagłówki kolumn tabeli."""

    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DocumentMetadata:
    """Metadane wyciagniete z samego pliku, uzupelniajace metadane zrodla."""

    title: str | None = None
    author: str | None = None
    subject: str | None = None
    keywords: str | None = None
    created_at: _dt.datetime | None = None
    modified_at: _dt.datetime | None = None
    page_count: int | None = None
    language: str | None = None
    producer: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExtractionResult:
    """Wynik dzialania parsera formatu."""

    sections: list[ExtractedSection] = field(default_factory=list)
    metadata: DocumentMetadata = field(default_factory=DocumentMetadata)
    attachments: list[ExtractedAttachment] = field(default_factory=list)
    origin: TextOrigin = TextOrigin.NATIVE
    ocr_pages: int = 0
    total_pages: int = 0
    ocr_confidence: float | None = None
    parser_name: str = ""
    support_level: SupportLevel = SupportLevel.FULL
    warnings: list[str] = field(default_factory=list)
    needs_ocr: bool = False
    """Parser zglasza, że warto spróbować OCR (brak użytecznej warstwy tekstowej)."""

    @property
    def text_length(self) -> int:
        return sum(len(s.text) for s in self.sections)

    def all_text(self, separator: str = "\n") -> str:
        return separator.join(s.text for s in self.sections if s.text)


# --- fragmenty -----------------------------------------------------------------


@dataclass(slots=True)
class Chunk:
    """Fragment dokumentu, jednostka indeksowania."""

    ordinal: int
    text: str
    """Tekst prezentowany użytkownikowi (oryginalny, po delikatnym oczyszczeniu)."""

    search_text: str
    """Tekst po normalizacji, używany przez indeks pełnotekstowy."""

    folded_text: str
    """Tekst po złożeniu znaków diakrytycznych, używany do wyszukiwania odpornego na OCR."""

    normalized_tokens: str = ""
    """Znormalizowane identyfikatory, numery, kwoty i daty rozdzielone spacja."""

    origin: TextOrigin = TextOrigin.NATIVE
    ocr_confidence: float | None = None
    page: int | None = None
    sheet: str | None = None
    row_start: int | None = None
    row_end: int | None = None
    heading: str | None = None
    section_kind: str = "text"
    char_start: int = 0
    char_end: int = 0

    @property
    def length(self) -> int:
        return len(self.text)


# --- dokument w indeksie -------------------------------------------------------


@dataclass(slots=True)
class DocumentRecord:
    """Rekord dokumentu w bazie metadanych."""

    doc_id: int
    source_id: str
    external_id: str
    name: str
    logical_path: str
    extension: str
    mime_type: str | None
    size: int | None
    modified_at: _dt.datetime | None
    created_at: _dt.datetime | None
    indexed_at: _dt.datetime | None
    status: DocumentStatus
    change_key: str | None
    content_sha256: str | None
    etag: str | None
    author: str | None
    title: str | None
    web_url: str | None
    parent_url: str | None
    local_path: str | None
    library: str | None
    chunk_count: int
    page_count: int | None
    used_ocr: bool
    ocr_pages: int
    ocr_confidence: float | None
    text_origin: TextOrigin
    parser_name: str | None
    support_level: SupportLevel
    error_code: str | None
    error_message: str | None
    vector_indexed: bool
    fts_indexed: bool
    normalization_version: int
    chunking_version: int
    model_key: str | None
    attachment_of: int | None = None
    """doc_id dokumentu nadrzednego, gdy rekord opisuje zalacznik."""


# --- wyniki wyszukiwania -------------------------------------------------------


@dataclass(slots=True)
class ChunkHit:
    """Pojedynczy trafiony fragment."""

    chunk_id: int
    doc_id: int
    ordinal: int
    text: str
    highlighted: str
    """Tekst z znacznikami trafien w formacie [[hl]]...[[/hl]]."""

    score: float
    match_kind: MatchKind
    origin: TextOrigin
    ocr_confidence: float | None = None
    page: int | None = None
    sheet: str | None = None
    row_start: int | None = None
    heading: str | None = None
    fts_rank: int | None = None
    vector_rank: int | None = None


@dataclass(slots=True)
class DocumentHit:
    """Wynik zgrupowany na poziomie dokumentu."""

    doc_id: int
    name: str
    logical_path: str
    library: str | None
    source_id: str
    source_kind: SourceKind
    extension: str
    mime_type: str | None
    modified_at: _dt.datetime | None
    indexed_at: _dt.datetime | None
    author: str | None
    web_url: str | None
    parent_url: str | None
    local_path: str | None
    used_ocr: bool
    ocr_confidence: float | None
    score: float
    match_kind: MatchKind
    chunks: list[ChunkHit] = field(default_factory=list)
    total_matching_chunks: int = 0
    exact_terms_found: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class DateRange:
    start: _dt.date | None = None
    end: _dt.date | None = None

    def is_empty(self) -> bool:
        return self.start is None and self.end is None


@dataclass(slots=True)
class SearchFilters:
    """Filtry metadanych zawezajace wyniki."""

    sources: list[str] = field(default_factory=list)
    libraries: list[str] = field(default_factory=list)
    path_prefix: str | None = None
    extensions: list[str] = field(default_factory=list)
    authors: list[str] = field(default_factory=list)
    modified: DateRange = field(default_factory=DateRange)
    ocr_only: bool | None = None
    """True: tylko dokumenty z OCR, False: tylko bez OCR, None: bez filtra."""

    def is_empty(self) -> bool:
        return (
            not self.sources
            and not self.libraries
            and not self.path_prefix
            and not self.extensions
            and not self.authors
            and self.modified.is_empty()
            and self.ocr_only is None
        )


@dataclass(slots=True)
class SearchRequest:
    """Zapytanie uzytkownika."""

    query: str
    mode: SearchMode = SearchMode.HYBRID
    filters: SearchFilters = field(default_factory=SearchFilters)
    offset: int = 0
    limit: int = 20
    max_chunks_per_document: int = 3
    """Ile najlepszych fragmentow pokazać dla jednego dokumentu."""

    candidate_multiplier: int = 8
    """Ile razy więcej kandydatów pobrać przed agregacja i scaleniem."""

    order_by: str = "relevance"
    """Porzadek wyników trybu dokładnego: ``relevance`` albo ``modified_desc``.

    Tryby z udziałem wektorów zwracają ranking podobieństwa, więc tam porządek
    inny niż trafność nie ma zastosowania i pole jest pomijane.
    """


@dataclass(slots=True)
class SearchResponse:
    """Odpowiedz wyszukiwarki."""

    hits: list[DocumentHit]
    total_documents: int
    """Łączna liczba dokumentów spełniających zapytanie.

    Dla trybu dokładnego jest to wartość dokładna. Dla trybów z udziałem wektorów
    jest to liczba dokumentów w rozważanym zbiorze kandydatów.
    """

    total_is_exact: bool
    mode: SearchMode
    took_ms: int
    query_analysis: QueryAnalysis
    truncated: bool = False
    notes: list[str] = field(default_factory=list)


# --- analiza zapytania ---------------------------------------------------------


class TermKind(StrEnum):
    WORD = "word"
    PHRASE = "phrase"
    DATE = "date"
    DATE_RANGE = "date_range"
    AMOUNT = "amount"
    ACCOUNT = "account"
    DIGITS = "digits"
    IDENTIFIER = "identifier"
    FILENAME = "filename"


@dataclass(frozen=True, slots=True)
class QueryTerm:
    """Element rozpoznany w zapytaniu uzytkownika."""

    kind: TermKind
    raw: str
    """Fragment zapytania w postaci wpisanej przez użytkownika."""

    normalized: str
    """Postać znormalizowana, używana do dopasowania w indeksie."""

    variants: tuple[str, ...] = ()
    """Dodatkowe warianty zapisu, np. numer z myślnikami i ze spacjami."""

    is_exact_required: bool = False
    """Element musi wystąpić dokładnie, nie wolno zastąpić go embeddingiem."""

    span: tuple[int, int] = (0, 0)


@dataclass(slots=True)
class QueryAnalysis:
    """Wynik analizy zapytania."""

    raw_query: str
    normalized_query: str
    semantic_text: str
    """Część zapytania nadająca się do embeddingu."""

    terms: list[QueryTerm] = field(default_factory=list)
    phrases: list[str] = field(default_factory=list)
    date_filters: list[DateRange] = field(default_factory=list)
    has_exact_elements: bool = False
    is_natural_language: bool = False

    def exact_terms(self) -> list[QueryTerm]:
        return [t for t in self.terms if t.is_exact_required]


# --- postep i raporty ----------------------------------------------------------


@dataclass(slots=True)
class ProgressSnapshot:
    """Migawka postepu zadania indeksowania."""

    job_id: str
    kind: JobKind
    state: JobState
    stage: str
    stage_label: str
    discovered: int = 0
    processed: int = 0
    skipped: int = 0
    failed: int = 0
    unchanged: int = 0
    deleted: int = 0
    ocr_documents: int = 0
    ocr_pages: int = 0
    current_file: str | None = None
    started_at: _dt.datetime | None = None
    updated_at: _dt.datetime | None = None
    elapsed_seconds: float = 0.0
    bytes_processed: int = 0
    temp_bytes_used: int = 0
    connection_status: str = "nieznany"
    discovery_complete: bool = False
    """Gdy False, liczba wykrytych plików jest jeszcze niepełna."""

    message: str | None = None

    @property
    def progress_fraction(self) -> float | None:
        """Ulamek postepu albo None, gdy nie da sie go wiarygodnie oszacowac."""
        if not self.discovery_complete or self.discovered <= 0:
            return None
        done = self.processed + self.skipped + self.failed + self.unchanged
        return min(1.0, done / self.discovered)


@dataclass(slots=True)
class CoverageReport:
    """Raport pokrycia zbioru dokumentow."""

    generated_at: _dt.datetime
    discovered: int
    indexed: int
    partial: int
    requiring_ocr: int
    ocr_succeeded: int
    ocr_failed: int
    skipped: int
    unsupported: int
    corrupted: int
    password_protected: int
    empty: int
    download_errors: int
    other_errors: int
    total_chunks: int
    total_vectors: int
    last_scan_at: _dt.datetime | None
    last_full_index_at: _dt.datetime | None
    schema_version: int
    app_version: str
    model_key: str | None
    model_dimension: int | None
    index_size_bytes: int
    non_searchable: list[NonSearchableDocument] = field(default_factory=list)
    by_extension: dict[str, int] = field(default_factory=dict)
    by_status: dict[str, int] = field(default_factory=dict)
    parser_errors: dict[str, int] = field(default_factory=dict)

    @property
    def is_complete(self) -> bool:
        """True tylko wtedy, gdy kazdy wykryty dokument jest wyszukiwalny."""
        return self.discovered > 0 and len(self.non_searchable) == 0 and self.indexed > 0


@dataclass(frozen=True, slots=True)
class NonSearchableDocument:
    """Dokument, ktorego nie mozna wyszukac, wraz z powodem."""

    doc_id: int
    name: str
    logical_path: str
    status: DocumentStatus
    error_code: str | None
    error_message: str | None
    extension: str


# --- protokoly -----------------------------------------------------------------


@runtime_checkable
class CancellationToken(Protocol):
    """Minimalny interfejs anulowania dzielony przez warstwy."""

    def is_cancelled(self) -> bool: ...

    def raise_if_cancelled(self) -> None: ...


@runtime_checkable
class ProgressSink(Protocol):
    """Odbiornik zdarzen postepu."""

    def update(self, snapshot: ProgressSnapshot) -> None: ...


@runtime_checkable
class TextChunker(Protocol):
    """Interfejs strategii fragmentacji."""

    name: str

    def chunk(self, sections: list[ExtractedSection]) -> Iterator[Chunk]: ...


__all__ = [
    "NON_SEARCHABLE_STATUSES",
    "CancellationToken",
    "Chunk",
    "ChunkHit",
    "CoverageReport",
    "DateRange",
    "DocumentHit",
    "DocumentMetadata",
    "DocumentRecord",
    "DocumentStatus",
    "ExtractedAttachment",
    "ExtractedSection",
    "ExtractionResult",
    "FetchedFile",
    "JobKind",
    "JobState",
    "MatchKind",
    "NonSearchableDocument",
    "ProgressSink",
    "ProgressSnapshot",
    "QueryAnalysis",
    "QueryTerm",
    "SearchFilters",
    "SearchMode",
    "SearchRequest",
    "SearchResponse",
    "SourceItem",
    "SourceKind",
    "SupportLevel",
    "TermKind",
    "TextChunker",
    "TextOrigin",
]
