"""Rejestr modeli embeddingow: pochodzenie, licencja, sumy kontrolne, rozmiar.

Aplikacja nie pobiera plikow z nieudokumentowanych zrodel. Kazdy model, ktory da sie
zainstalowac, jest opisany w tym module: adres, licencja, wielkosc pobierania i suma
kontrolna po eksporcie do ONNX. Pobieranie wymaga jawnej zgody uzytkownika.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from finddocs.config import EmbeddingSettings
from finddocs.errors import ModelIntegrityError, ModelNotAvailableError

MANIFEST_FILENAME = "manifest.json"
ONNX_SUBDIR = "onnx"


@dataclass(frozen=True, slots=True)
class ModelDescriptor:
    """Opis modelu dostepnego dla aplikacji."""

    key: str
    display_name: str
    repo: str
    source_url: str
    license_name: str
    license_url: str
    dimension: int
    max_sequence_length: int
    pooling: str
    query_prefix: str
    passage_prefix: str
    approx_download_mb: int
    approx_onnx_int8_mb: int
    language_notes: str
    recommended: bool = False
    notes: str = ""


#: Modele porownane w raporcie PoC. Domyslny jest oznaczony jako recommended.
KNOWN_MODELS: dict[str, ModelDescriptor] = {
    "mmlw-retrieval-roberta-base": ModelDescriptor(
        key="mmlw-retrieval-roberta-base",
        display_name="MMLW retrieval RoBERTa base (polski)",
        repo="sdadas/mmlw-retrieval-roberta-base",
        source_url="https://huggingface.co/sdadas/mmlw-retrieval-roberta-base",
        license_name="Apache-2.0",
        license_url="https://www.apache.org/licenses/LICENSE-2.0",
        dimension=768,
        max_sequence_length=512,
        pooling="cls",
        query_prefix="zapytanie: ",
        passage_prefix="",
        approx_download_mb=475,
        approx_onnx_int8_mb=120,
        language_notes="Model trenowany dla języka polskiego, zadanie retrieval.",
        recommended=True,
        notes="Domyślny model aplikacji. NDCG@10 56,38 na benchmarku PIRB.",
    ),
    "mmlw-retrieval-roberta-small": ModelDescriptor(
        key="mmlw-retrieval-roberta-small",
        display_name="MMLW retrieval RoBERTa small (polski)",
        repo="sdadas/mmlw-retrieval-roberta-small",
        source_url="https://huggingface.co/sdadas/mmlw-retrieval-roberta-small",
        license_name="Apache-2.0",
        license_url="https://www.apache.org/licenses/LICENSE-2.0",
        dimension=384,
        max_sequence_length=512,
        pooling="cls",
        query_prefix="zapytanie: ",
        passage_prefix="",
        approx_download_mb=180,
        approx_onnx_int8_mb=50,
        language_notes="Lżejszy wariant tej samej rodziny. Szybszy, nieco słabszy ranking.",
        notes="Wariant dla komputerów o małej liczbie rdzeni.",
    ),
    "multilingual-e5-small": ModelDescriptor(
        key="multilingual-e5-small",
        display_name="Multilingual E5 small",
        repo="intfloat/multilingual-e5-small",
        source_url="https://huggingface.co/intfloat/multilingual-e5-small",
        license_name="MIT",
        license_url="https://opensource.org/license/mit",
        dimension=384,
        max_sequence_length=512,
        pooling="mean",
        query_prefix="query: ",
        passage_prefix="passage: ",
        approx_download_mb=470,
        approx_onnx_int8_mb=120,
        language_notes="Model wielojęzyczny, polski obsługiwany, ale słabiej niż MMLW.",
        notes="Punkt odniesienia w porównaniu modeli.",
    ),
}

DEFAULT_MODEL_KEY = "mmlw-retrieval-roberta-base"


@dataclass(slots=True)
class LocalModelManifest:
    """Manifest wygenerowany przy eksporcie modelu do ONNX."""

    model_key: str
    source: str
    license: str
    architecture: str
    dimension: int
    max_sequence_length: int
    pooling: str
    normalize: bool
    query_prefix: str
    passage_prefix: str
    opset: int
    quantized: bool
    display_name: str = ""
    pad_token: str = ""
    files: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def load(cls, directory: Path) -> LocalModelManifest:
        path = directory / MANIFEST_FILENAME
        if not path.exists():
            raise ModelNotAvailableError(
                f"Katalog modelu {directory} nie zawiera pliku {MANIFEST_FILENAME}."
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})

    def model_file(self, directory: Path, *, prefer_quantized: bool) -> Path:
        """Zwraca sciezke do pliku ONNX, ktory nalezy zaladowac."""
        candidates = (
            ["model.int8.onnx", "model.onnx"]
            if prefer_quantized
            else ["model.onnx", "model.int8.onnx"]
        )
        for name in candidates:
            path = directory / name
            if path.exists():
                return path
        raise ModelNotAvailableError(f"W katalogu {directory} nie ma pliku modelu ONNX.")

    def verify(self, directory: Path, *, files: list[str] | None = None) -> None:
        """Sprawdza sumy kontrolne wskazanych plikow."""
        targets = files if files is not None else list(self.files)
        for name in targets:
            expected = self.files.get(name, {}).get("sha256")
            if not expected:
                continue
            path = directory / name
            if not path.exists():
                raise ModelIntegrityError(f"Brakuje pliku modelu: {name}.")
            actual = sha256_of(path)
            if actual != expected:
                raise ModelIntegrityError(
                    f"Suma kontrolna pliku {name} nie zgadza się z manifestem.",
                    details={"expected": expected, "actual": actual},
                )


def sha256_of(path: Path, *, block: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(block), b""):
            digest.update(chunk)
    return digest.hexdigest()


def candidate_model_dirs(model_key: str, extra: Path | None = None) -> list[Path]:
    """Lokalizacje, w ktorych aplikacja szuka modelu, w kolejnosci preferencji."""
    from finddocs.app_paths import AppPaths

    paths: list[Path] = []
    if extra:
        base = Path(extra)
        paths.extend([base, base / ONNX_SUBDIR])
    user_models = AppPaths.default().models_dir
    paths.extend([user_models / model_key / ONNX_SUBDIR, user_models / model_key])

    # katalog "models" obok kodu, czyli w katalogu repozytorium
    package_root = Path(__file__).resolve().parents[3]
    paths.extend(
        [
            package_root / "models" / model_key / ONNX_SUBDIR,
            package_root / "models" / model_key,
        ]
    )

    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def find_model_dir(model_key: str, extra: Path | None = None) -> Path | None:
    """Zwraca pierwszy katalog z kompletnym modelem ONNX albo None."""
    for candidate in candidate_model_dirs(model_key, extra):
        if _is_complete_model_dir(candidate):
            return candidate
    return None


def _is_complete_model_dir(directory: Path) -> bool:
    return (directory / MANIFEST_FILENAME).exists() and (
        (directory / "model.onnx").exists() or (directory / "model.int8.onnx").exists()
    )


def sync_embedding_settings(
    settings: EmbeddingSettings, model_key: str, *, extra: Path | None = None
) -> LocalModelManifest | None:
    """Ustawia aktywny model i przepisuje jego parametry do konfiguracji.

    Zrodlem prawdy jest manifest zainstalowanego modelu. Gdy modelu nie ma na
    dysku, parametry pochodza z wbudowanego rejestru. Skrot zgodnosci czesci
    wektorowej liczy sie z konfiguracji, wiec bez tej synchronizacji zmiana
    modelu zostawilaby w konfiguracji przedrostki poprzedniego modelu.
    Zwraca manifest, jesli zostal znaleziony.
    """
    settings.model_key = model_key
    directory = find_model_dir(model_key, extra)
    if directory is not None:
        manifest = LocalModelManifest.load(directory)
        settings.max_sequence_length = int(manifest.max_sequence_length or 512)
        settings.query_prefix = manifest.query_prefix
        settings.passage_prefix = manifest.passage_prefix
        settings.normalize = bool(manifest.normalize)
        return manifest
    descriptor = KNOWN_MODELS.get(model_key)
    if descriptor is not None:
        settings.max_sequence_length = descriptor.max_sequence_length
        settings.query_prefix = descriptor.query_prefix
        settings.passage_prefix = descriptor.passage_prefix
        settings.normalize = True
    return None


def update_manifest_prefixes(directory: Path, *, query_prefix: str, passage_prefix: str) -> None:
    """Zapisuje nowe przedrostki w manifescie zainstalowanego modelu.

    Dostawca lokalny czyta przedrostki z manifestu, wiec to jest miejsce,
    w ktorym zmiana faktycznie wplywa na liczenie embeddingow.
    """
    path = directory / MANIFEST_FILENAME
    if not path.exists():
        raise ModelNotAvailableError(
            f"Katalog modelu {directory} nie zawiera pliku {MANIFEST_FILENAME}."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ModelNotAvailableError(f"Manifest modelu {path} ma nieprawidłową strukturę.")
    data["query_prefix"] = query_prefix
    data["passage_prefix"] = passage_prefix
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def model_base_dirs() -> list[Path]:
    """Katalogi, w ktorych moga byc zainstalowane modele, w kolejnosci preferencji."""
    from finddocs.app_paths import AppPaths

    package_root = Path(__file__).resolve().parents[3]
    return [
        AppPaths.default().models_dir,
        package_root / "models",
    ]


def installed_models() -> list[tuple[str, Path, LocalModelManifest]]:
    """Wszystkie zainstalowane modele: klucz, katalog i manifest.

    Przeszukuje katalog modeli uzytkownika oraz katalog obok kodu. Katalogi
    z uszkodzonym manifestem sa pomijane. Przy powtorzonym kluczu wygrywa
    pierwsza lokalizacja, tak samo jak w :func:`candidate_model_dirs`.
    """
    result: list[tuple[str, Path, LocalModelManifest]] = []
    seen: set[str] = set()
    for base in model_base_dirs():
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            if not entry.is_dir() or entry.name in seen:
                continue
            for candidate in (entry / ONNX_SUBDIR, entry):
                if not _is_complete_model_dir(candidate):
                    continue
                try:
                    manifest = LocalModelManifest.load(candidate)
                except (OSError, ValueError, TypeError, ModelNotAvailableError):
                    break
                result.append((entry.name, candidate, manifest))
                seen.add(entry.name)
                break
    return result


def describe_models() -> list[dict[str, Any]]:
    """Opis modeli dla ekranu konfiguracji i dokumentacji.

    Lista zawiera modele wbudowane w rejestr oraz wszystkie modele
    zainstalowane lokalnie, takze te zaimportowane poleceniem
    ``run.py model import``. Dzieki temu wlasny model pojawia sie
    w interfejsie bez zadnej dodatkowej konfiguracji.
    """
    result: list[dict[str, Any]] = []
    for descriptor in KNOWN_MODELS.values():
        local = find_model_dir(descriptor.key)
        result.append(
            {
                "klucz": descriptor.key,
                "nazwa": descriptor.display_name,
                "licencja": descriptor.license_name,
                "zrodlo": descriptor.source_url,
                "wymiar": descriptor.dimension,
                "pobranie_mb": descriptor.approx_download_mb,
                "onnx_int8_mb": descriptor.approx_onnx_int8_mb,
                "zainstalowany": local is not None,
                "katalog": str(local) if local else "",
                "domyślny": descriptor.recommended,
                "uwagi": descriptor.notes,
            }
        )
    for key, directory, manifest in installed_models():
        if key in KNOWN_MODELS:
            continue
        size_bytes = sum(p.stat().st_size for p in directory.glob("*") if p.is_file())
        result.append(
            {
                "klucz": key,
                "nazwa": manifest.display_name or key,
                "licencja": manifest.license,
                "zrodlo": manifest.source,
                "wymiar": manifest.dimension,
                "pobranie_mb": 0,
                "onnx_int8_mb": size_bytes // (1024 * 1024),
                "zainstalowany": True,
                "katalog": str(directory),
                "domyślny": False,
                "uwagi": "Model zaimportowany lokalnie.",
            }
        )
    return result


__all__ = [
    "DEFAULT_MODEL_KEY",
    "KNOWN_MODELS",
    "MANIFEST_FILENAME",
    "ONNX_SUBDIR",
    "LocalModelManifest",
    "ModelDescriptor",
    "candidate_model_dirs",
    "describe_models",
    "find_model_dir",
    "installed_models",
    "model_base_dirs",
    "sha256_of",
    "sync_embedding_settings",
    "update_manifest_prefixes",
]
