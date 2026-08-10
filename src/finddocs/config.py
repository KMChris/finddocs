"""Konfiguracja aplikacji: model, zapis do pliku JSON i skrot zgodnosci indeksu.

Plik konfiguracyjny nie zawiera zadnych poswiadczen. Tokeny i sekrety trafiaja
wylacznie do magazynu z modulu ``finddocs.security.credentials``.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from finddocs.app_paths import AppPaths
from finddocs.errors import ConfigurationError
from finddocs.types import SourceKind
from finddocs.version import CHUNKING_VERSION, NORMALIZATION_VERSION, SCHEMA_VERSION

CONFIG_FORMAT_VERSION = 1


@dataclass(slots=True)
class LocalDirSourceSettings:
    """Ustawienia zrodla typu katalog lokalny."""

    root_path: str = ""
    follow_symlinks: bool = False
    include_hidden: bool = False


@dataclass(slots=True)
class SharePointSourceSettings:
    """Ustawienia zrodla SharePoint / Microsoft Graph."""

    tenant_id: str = ""
    client_id: str = ""
    authority: str = "https://login.microsoftonline.com"
    graph_endpoint: str = "https://graph.microsoft.com/v1.0"
    auth_flow: str = "interactive"
    """interactive albo device_code."""

    site_url: str = ""
    """Pełny adres witryny, np. https://contoso.sharepoint.com/sites/Finanse."""

    site_id: str = ""
    drive_id: str = ""
    drive_name: str = ""
    folder_path: str = ""
    """Ścieżka katalogu startowego względem korzenia biblioteki. Pusta oznacza korzeń."""

    recursive: bool = True
    scopes: list[str] = field(default_factory=lambda: ["Files.Read.All", "Sites.Read.All"])
    request_timeout_seconds: float = 60.0
    max_retries: int = 5
    page_size: int = 200


@dataclass(slots=True)
class SourceConfig:
    """Pojedyncze skonfigurowane zrodlo dokumentow."""

    source_id: str
    kind: SourceKind
    label: str
    enabled: bool = True
    local: LocalDirSourceSettings = field(default_factory=LocalDirSourceSettings)
    sharepoint: SharePointSourceSettings = field(default_factory=SharePointSourceSettings)
    include_extensions: list[str] = field(default_factory=list)
    """Pusta lista oznacza wszystkie obslugiwane rozszerzenia."""

    exclude_extensions: list[str] = field(default_factory=list)
    exclude_globs: list[str] = field(default_factory=list)
    max_file_size_mb: int = 512

    def describe_location(self) -> str:
        if self.kind is SourceKind.LOCAL_DIR:
            return self.local.root_path or "(nie wskazano katalogu)"
        sp = self.sharepoint
        base = sp.site_url or sp.site_id or "(nie wskazano witryny)"
        library = sp.drive_name or sp.drive_id
        parts = [base]
        if library:
            parts.append(library)
        if sp.folder_path:
            parts.append(sp.folder_path.strip("/"))
        return " / ".join(parts)


@dataclass(slots=True)
class EmbeddingSettings:
    """Ustawienia dostawcy embeddingow."""

    semantic_enabled: bool = True
    """Wylaczenie pomija liczenie embeddingow przy indeksowaniu i tryby semantyczne.

    Indeks pelnotekstowy dziala bez zmian. Po ponownym wlaczeniu zwykle
    skanowanie uzupelnia brakujace wektory, bo dokumenty bez wektorow sa
    kwalifikowane do ponownego przetworzenia.
    """

    provider: str = "local_onnx"
    """local_onnx albo internal_api (drugi jest przygotowany, ale wylaczony)."""

    model_key: str = "mmlw-retrieval-roberta-base"
    model_path: str = ""
    """Katalog z modelem. Pusty oznacza wyszukiwanie w standardowych lokalizacjach."""

    max_sequence_length: int = 512
    batch_size: int = 8
    num_threads: int = 0
    """0 oznacza automatyczny dobór na podstawie liczby rdzeni."""

    quantized: bool = True
    query_prefix: str = "zapytanie: "
    passage_prefix: str = ""
    normalize: bool = True
    internal_api_url: str = ""
    internal_api_enabled: bool = False


@dataclass(slots=True)
class OcrSettings:
    """Ustawienia OCR."""

    enabled: bool = True
    engine: str = "auto"
    """auto, tesseract, rapidocr, easyocr albo none."""

    languages: list[str] = field(default_factory=lambda: ["pol"])
    tesseract_path: str = ""
    render_dpi: int = 220
    max_pages_per_document: int = 60
    min_chars_per_page: int = 90
    """Poniżej tej liczby znaków na stronę uznajemy warstwę tekstowa za bezużyteczna."""

    min_alpha_ratio: float = 0.45
    """Minimalny udział liter w tekście, poniżej którego podejrzewamy śmieci."""

    max_image_pixels: int = 40_000_000
    page_timeout_seconds: float = 120.0
    auto_rotate: bool = True
    min_confidence_to_keep: float = 0.30


@dataclass(slots=True)
class ChunkingSettings:
    """Ustawienia podzialu na fragmenty."""

    target_chars: int = 1100
    overlap_chars: int = 180
    min_chars: int = 120
    max_chars: int = 2200
    table_rows_per_chunk: int = 12
    table_include_header: bool = True
    max_chunks_per_document: int = 20000


@dataclass(slots=True)
class SearchSettings:
    """Ustawienia wyszukiwania."""

    default_mode: str = "hybrid"
    page_size: int = 20
    max_chunks_per_document: int = 3
    rrf_k: int = 60
    fts_weight: float = 1.0
    vector_weight: float = 1.0
    exact_boost: float = 0.6
    """Premia dodawana do wyniku dokumentu zawierajacego wszystkie elementy dokładne."""

    semantic_candidates: int = 400
    fts_candidates: int = 2000
    snippet_chars: int = 320


@dataclass(slots=True)
class IndexingSettings:
    """Ustawienia procesu indeksowania."""

    checkpoint_every: int = 20
    max_temp_bytes: int = 4 * 1024**3
    min_free_disk_bytes: int = 2 * 1024**3
    download_timeout_seconds: float = 300.0
    max_retries_per_document: int = 3
    retry_backoff_seconds: float = 2.0
    retry_backoff_max_seconds: float = 60.0
    max_file_size_mb: int = 512
    extraction_timeout_seconds: float = 300.0
    office_com_enabled: bool = True
    office_com_timeout_seconds: float = 90.0


@dataclass(slots=True)
class DiagnosticsSettings:
    """Ustawienia logowania i diagnostyki."""

    log_level: str = "INFO"
    log_queries: bool = False
    """Lokalny tryb diagnostyczny. Domyślnie wyłączony, zapytania nie trafiaja do logów."""

    keep_log_files: int = 5
    max_log_size_mb: int = 20
    json_logs: bool = True


@dataclass(slots=True)
class UiSettings:
    """Ustawienia interfejsu."""

    theme: str = "system"
    font_scale: float = 1.0
    open_documents_with: str = "system"
    """system, browser albo local_path."""

    window_width: int = 1280
    window_height: int = 820
    show_scores: bool = True
    mica: bool = True
    """Tlo Mica okna glownego na Windows 11. Starsze systemy ja pomijaja."""


@dataclass(slots=True)
class AppConfig:
    """Pelna konfiguracja aplikacji."""

    format_version: int = CONFIG_FORMAT_VERSION
    data_root: str = ""
    """Pusty oznacza domyślny katalog danych użytkownika."""

    sources: list[SourceConfig] = field(default_factory=list)
    embedding: EmbeddingSettings = field(default_factory=EmbeddingSettings)
    ocr: OcrSettings = field(default_factory=OcrSettings)
    chunking: ChunkingSettings = field(default_factory=ChunkingSettings)
    search: SearchSettings = field(default_factory=SearchSettings)
    indexing: IndexingSettings = field(default_factory=IndexingSettings)
    diagnostics: DiagnosticsSettings = field(default_factory=DiagnosticsSettings)
    ui: UiSettings = field(default_factory=UiSettings)
    first_run_completed: bool = False
    allow_model_download: bool = False
    """Pobieranie modeli wymaga jawnej zgody użytkownika."""

    # --- zgodnosc indeksu -------------------------------------------------

    def index_compat_payload(self) -> dict[str, Any]:
        """Elementy konfiguracji, ktorych zmiana uniewaznia indeks."""
        return {
            "schema_version": SCHEMA_VERSION,
            "normalization_version": NORMALIZATION_VERSION,
            "chunking_version": CHUNKING_VERSION,
            "chunk_target_chars": self.chunking.target_chars,
            "chunk_overlap_chars": self.chunking.overlap_chars,
            "chunk_min_chars": self.chunking.min_chars,
            "chunk_max_chars": self.chunking.max_chars,
            "table_rows_per_chunk": self.chunking.table_rows_per_chunk,
            "table_include_header": self.chunking.table_include_header,
        }

    def index_compat_hash(self) -> str:
        """Skrot konfiguracji majacej wplyw na zgodnosc indeksu pelnotekstowego."""
        payload = json.dumps(self.index_compat_payload(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    def vector_compat_payload(self) -> dict[str, Any]:
        """Elementy konfiguracji, ktorych zmiana uniewaznia indeks wektorowy."""
        payload = self.index_compat_payload()
        payload.update(
            {
                "provider": self.embedding.provider,
                "model_key": self.embedding.model_key,
                "quantized": self.embedding.quantized,
                "max_sequence_length": self.embedding.max_sequence_length,
                "query_prefix": self.embedding.query_prefix,
                "passage_prefix": self.embedding.passage_prefix,
                "normalize": self.embedding.normalize,
            }
        )
        return payload

    def vector_compat_hash(self) -> str:
        payload = json.dumps(self.vector_compat_payload(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    # --- pomocnicze -------------------------------------------------------

    def paths(self) -> AppPaths:
        return AppPaths.at(self.data_root) if self.data_root else AppPaths.default()

    def source(self, source_id: str) -> SourceConfig:
        for src in self.sources:
            if src.source_id == source_id:
                return src
        raise ConfigurationError(f"Nie znaleziono źródła o identyfikatorze {source_id}.")

    def enabled_sources(self) -> list[SourceConfig]:
        return [s for s in self.sources if s.enabled]

    def with_source(self, source: SourceConfig) -> AppConfig:
        """Zwraca kopie konfiguracji z dodanym lub zaktualizowanym zrodlem."""
        sources = [s for s in self.sources if s.source_id != source.source_id]
        sources.append(source)
        return replace(self, sources=sources)


# --- serializacja ---------------------------------------------------------------


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, SourceKind):
        return value.value
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    return value


def config_to_dict(config: AppConfig) -> dict[str, Any]:
    return _to_jsonable(asdict(config))  # type: ignore[no-any-return]


def _build(cls: type, data: dict[str, Any]) -> Any:
    """Tworzy dataclass, ignorujac nieznane klucze i uzupelniajac brakujace."""
    fields = {f.name: f for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    kwargs: dict[str, Any] = {}
    for name, spec in fields.items():
        if name not in data:
            continue
        raw = data[name]
        ftype = spec.type
        if isinstance(ftype, str):
            ftype_name = ftype
        else:  # pragma: no cover - dataclasses zwykle trzymaja stringi
            ftype_name = getattr(ftype, "__name__", str(ftype))
        if ftype_name.startswith("SourceKind"):
            kwargs[name] = SourceKind(raw)
        elif isinstance(raw, dict) and ftype_name in _NESTED:
            kwargs[name] = _build(_NESTED[ftype_name], raw)
        elif name == "sources" and isinstance(raw, list):
            kwargs[name] = [_build(SourceConfig, item) for item in raw]
        else:
            kwargs[name] = raw
    return cls(**kwargs)


_NESTED: dict[str, type] = {
    "LocalDirSourceSettings": LocalDirSourceSettings,
    "SharePointSourceSettings": SharePointSourceSettings,
    "EmbeddingSettings": EmbeddingSettings,
    "OcrSettings": OcrSettings,
    "ChunkingSettings": ChunkingSettings,
    "SearchSettings": SearchSettings,
    "IndexingSettings": IndexingSettings,
    "DiagnosticsSettings": DiagnosticsSettings,
    "UiSettings": UiSettings,
    "SourceConfig": SourceConfig,
}


def config_from_dict(data: dict[str, Any]) -> AppConfig:
    version = int(data.get("format_version", CONFIG_FORMAT_VERSION))
    if version > CONFIG_FORMAT_VERSION:
        raise ConfigurationError(
            "Plik konfiguracyjny pochodzi z nowszej wersji aplikacji. "
            "Zaktualizuj FindDocs albo usun plik konfiguracyjny."
        )
    return _build(AppConfig, data)  # type: ignore[no-any-return]


def load_config(path: Path | None = None) -> AppConfig:
    """Wczytuje konfiguracje. Gdy plik nie istnieje, zwraca ustawienia domyslne."""
    target = path or AppPaths.default().config_file
    if not target.exists():
        return AppConfig()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"Plik konfiguracyjny {target} jest uszkodzony i nie da się go odczytać.",
            cause=exc,
        ) from exc
    if not isinstance(raw, dict):
        raise ConfigurationError(f"Plik konfiguracyjny {target} ma nieprawidłowa strukturę.")
    return config_from_dict(raw)


def save_config(config: AppConfig, path: Path | None = None) -> Path:
    """Zapisuje konfiguracje atomowo (zapis do pliku tymczasowego i podmiana)."""
    target = path or config.paths().config_file
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(config_to_dict(config), ensure_ascii=False, indent=2, sort_keys=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".settings-", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        tmp_path.replace(target)
    finally:
        tmp_path.unlink(missing_ok=True)
    return target


__all__ = [
    "CONFIG_FORMAT_VERSION",
    "AppConfig",
    "ChunkingSettings",
    "DiagnosticsSettings",
    "EmbeddingSettings",
    "IndexingSettings",
    "LocalDirSourceSettings",
    "OcrSettings",
    "SearchSettings",
    "SharePointSourceSettings",
    "SourceConfig",
    "UiSettings",
    "config_from_dict",
    "config_to_dict",
    "load_config",
    "save_config",
]
