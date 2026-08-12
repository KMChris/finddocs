"""Magazyn modeli embeddingow: import z katalogu lub Hugging Face, walidacja, usuwanie.

Modul realizuje polecenie ``finddocs model import``. Zrodlem moze byc:

1. katalog z gotowym eksportem ONNX (z manifestem aplikacji albo bez niego),
2. katalog z checkpointem HuggingFace (konwersja wymaga dodatku ``finddocs[export]``),
3. identyfikator repozytorium na Hugging Face (pobranie przez polityke sieciowa).

Kazdy zaimportowany model przechodzi walidacje: sesja ONNX Runtime na CPU liczy
probne embeddingi i dopiero po zgodnym wyniku model trafia do katalogu modeli
uzytkownika. Dzieki temu lista modeli w GUI zawiera tylko dzialajace pozycje.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from finddocs.app_paths import AppPaths
from finddocs.errors import ModelNotAvailableError, ProviderError
from finddocs.logging_setup import get_logger
from finddocs.providers.model_export import (
    TOKENIZER_FILES,
    ProgressCallback,
    convert_checkpoint,
    detect_pad_token,
    missing_export_packages,
    read_checkpoint_config,
    write_manifest,
)
from finddocs.providers.model_manifest import (
    KNOWN_MODELS,
    MANIFEST_FILENAME,
    ONNX_SUBDIR,
    LocalModelManifest,
    ModelDescriptor,
)

log = get_logger(__name__)

#: Dozwolone znaki klucza modelu (nazwa katalogu w magazynie).
_KEY_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")

#: Wzorzec identyfikatora repozytorium Hugging Face, np. ``sdadas/mmlw-...``.
_REPO_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")

#: Nazwy plikow z kwantyzowanym modelem spotykane w gotowych eksportach.
_QUANTIZED_CANDIDATES: tuple[str, ...] = (
    "model.int8.onnx",
    "model_quantized.onnx",
    "model_qint8_arm64.onnx",
    "model_qint8_avx512_vnni.onnx",
)

#: Pliki konfiguracji sentence-transformers przydatne do wykrycia poolingu.
_SENTENCE_TRANSFORMERS_FILES: tuple[str, ...] = (
    "modules.json",
    "1_Pooling/config.json",
    "sentence_bert_config.json",
)


@dataclass(slots=True)
class ImportedModel:
    """Wynik importu modelu."""

    key: str
    directory: Path
    display_name: str
    dimension: int
    pooling: str
    quantized: bool
    query_prefix: str
    passage_prefix: str
    model_files: list[str]
    notes: list[str] = field(default_factory=list)


def sanitize_model_key(raw: str) -> str:
    """Zamienia dowolna nazwe na bezpieczna nazwe katalogu modelu."""
    cleaned = _KEY_SAFE_RE.sub("-", raw.strip()).strip(".-")
    if not cleaned:
        raise ModelNotAvailableError(f"Nazwa modelu '{raw}' jest nieprawidłowa.")
    return cleaned


def looks_like_repo_id(source: str) -> bool:
    """Czy tekst wyglada na identyfikator repozytorium Hugging Face."""
    return bool(_REPO_ID_RE.match(source))


def descriptor_for_repo(repo_id: str) -> ModelDescriptor | None:
    """Wbudowany opis modelu dla repozytorium, jesli model jest znany."""
    for descriptor in KNOWN_MODELS.values():
        if descriptor.repo.lower() == repo_id.lower():
            return descriptor
    return None


# --- rozpoznawanie zrodla -------------------------------------------------------


def classify_local_source(source_dir: Path) -> tuple[str, Path]:
    """Rozpoznaje rodzaj lokalnego zrodla modelu.

    Zwraca pare (rodzaj, katalog), gdzie rodzaj to ``onnx`` albo ``checkpoint``.
    Katalog moze byc podkatalogiem ``onnx`` wskazanego zrodla.
    """
    for candidate in (source_dir, source_dir / ONNX_SUBDIR):
        if not candidate.is_dir():
            continue
        model_names = ("model.onnx", *_QUANTIZED_CANDIDATES)
        has_model = any((candidate / name).exists() for name in model_names)
        if has_model:
            if not _tokenizer_file(candidate, source_dir):
                raise ModelNotAvailableError(
                    f"Katalog {candidate} zawiera model ONNX, ale nie ma pliku tokenizer.json."
                )
            return "onnx", candidate
    if (source_dir / "config.json").exists() and (
        (source_dir / "model.safetensors").exists() or (source_dir / "pytorch_model.bin").exists()
    ):
        return "checkpoint", source_dir
    raise ModelNotAvailableError(
        f"Katalog {source_dir} nie wygląda na model: nie znaleziono ani plików ONNX, "
        "ani checkpointu HuggingFace (config.json z wagami)."
    )


def _tokenizer_file(primary: Path, fallback: Path) -> Path | None:
    for base in (primary, fallback):
        path = base / "tokenizer.json"
        if path.exists():
            return path
    return None


# --- wykrywanie metadanych ------------------------------------------------------


def detect_pooling(source_dir: Path) -> str | None:
    """Odczytuje tryb poolingu z konfiguracji sentence-transformers.

    Zwraca ``cls`` albo ``mean``, a ``None`` gdy konfiguracji nie ma.
    """
    for base in (source_dir, source_dir.parent):
        path = base / "1_Pooling" / "config.json"
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        if data.get("pooling_mode_cls_token"):
            return "cls"
        if data.get("pooling_mode_mean_tokens"):
            return "mean"
    return None


def probe_onnx_model(directory: Path) -> dict[str, Any]:
    """Uruchamia probny przebieg modelu ONNX i zwraca jego rzeczywiste wymiary.

    Sesja jest tworzona wylacznie z providerem CPU, tak samo jak w dostawcy
    embeddingow. Zwraca slownik z kluczami ``dimension``, ``rank`` i ``model_file``.
    """
    import numpy as np
    import onnxruntime as ort
    from tokenizers import Tokenizer

    from finddocs.providers.onnx_local import CPU_EXECUTION_PROVIDERS

    model_path = None
    for name in ("model.int8.onnx", "model.onnx"):
        candidate = directory / name
        if candidate.exists():
            model_path = candidate
            break
    if model_path is None:
        raise ModelNotAvailableError(f"W katalogu {directory} nie ma pliku modelu ONNX.")

    tokenizer_path = directory / "tokenizer.json"
    if not tokenizer_path.exists():
        raise ModelNotAvailableError(f"W katalogu {directory} nie ma pliku tokenizer.json.")
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    tokenizer.enable_truncation(max_length=32)
    tokenizer.enable_padding()

    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.log_severity_level = 3
    session = ort.InferenceSession(
        str(model_path), sess_options=options, providers=list(CPU_EXECUTION_PROVIDERS)
    )
    input_names = {i.name for i in session.get_inputs()}
    encodings = tokenizer.encode_batch(["probne zdanie testowe", "druga proba"])
    ids = np.asarray([e.ids for e in encodings], dtype=np.int64)
    mask = np.asarray([e.attention_mask for e in encodings], dtype=np.int64)
    feeds: dict[str, Any] = {"input_ids": ids, "attention_mask": mask}
    if "token_type_ids" in input_names:
        feeds["token_type_ids"] = np.zeros_like(ids)
    feeds = {k: v for k, v in feeds.items() if k in input_names}
    outputs = session.run(None, feeds)
    hidden = np.asarray(outputs[0], dtype="float32")
    if not np.isfinite(hidden).all():
        raise ModelNotAvailableError(
            f"Model {model_path.name} zwraca wartości nieskończone lub NaN."
        )
    if hidden.ndim not in (2, 3):
        raise ModelNotAvailableError(
            f"Model {model_path.name} zwraca tensor o nieobsługiwanym kształcie {hidden.shape}."
        )
    return {
        "dimension": int(hidden.shape[-1]),
        "rank": int(hidden.ndim),
        "model_file": model_path.name,
    }


def try_quantize(directory: Path, *, progress: ProgressCallback | None = None) -> bool:
    """Kwantyzuje model.onnx do model.int8.onnx, jesli dostepny jest pakiet onnx.

    Zwraca True po udanej kwantyzacji. Brak pakietu onnx nie jest bledem:
    aplikacja dziala takze na modelu FP32, tylko wolniej.
    """
    source = directory / "model.onnx"
    if not source.exists() or (directory / "model.int8.onnx").exists():
        return (directory / "model.int8.onnx").exists()
    try:
        from onnxruntime.quantization import QuantType, quantize_dynamic
    except ImportError:
        return False
    if progress:
        progress("Kwantyzacja dynamiczna INT8")
    quantize_dynamic(
        model_input=str(source),
        model_output=str(directory / "model.int8.onnx"),
        weight_type=QuantType.QInt8,
    )
    return True


# --- import ---------------------------------------------------------------------


def _copy_onnx_source(source_dir: Path, staging: Path, fallback_dir: Path) -> list[str]:
    """Kopiuje pliki modelu i tokenizera do katalogu roboczego.

    Rozpoznane nazwy kwantyzowanych eksportow sa ujednolicane do
    ``model.int8.onnx``. Pliki danych zewnetrznych (``model.onnx.data``)
    sa kopiowane bez zmiany nazwy, bo graf ONNX odwoluje sie do nich po nazwie.
    """
    copied: list[str] = []
    fp32 = source_dir / "model.onnx"
    if fp32.exists():
        shutil.copy2(fp32, staging / "model.onnx")
        copied.append("model.onnx")
        for extra in source_dir.glob("model.onnx*"):
            if extra.name != "model.onnx":
                shutil.copy2(extra, staging / extra.name)
                copied.append(extra.name)
    for name in _QUANTIZED_CANDIDATES:
        candidate = source_dir / name
        if candidate.exists():
            shutil.copy2(candidate, staging / "model.int8.onnx")
            copied.append("model.int8.onnx")
            break
    if not copied:
        raise ModelNotAvailableError(f"Katalog {source_dir} nie zawiera pliku modelu ONNX.")

    for name in TOKENIZER_FILES:
        for base in (source_dir, fallback_dir):
            path = base / name
            if path.exists():
                shutil.copy2(path, staging / name)
                copied.append(name)
                break
    return copied


def _read_source_manifest(source_dir: Path) -> LocalModelManifest | None:
    if not (source_dir / MANIFEST_FILENAME).exists():
        return None
    try:
        return LocalModelManifest.load(source_dir)
    except (OSError, ValueError, TypeError, ModelNotAvailableError):
        return None


def _config_max_sequence(directory: Path) -> int | None:
    path = directory / "config.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    positions = data.get("max_position_embeddings")
    if isinstance(positions, int) and positions > 2:
        return min(positions - 2, 512)
    return None


@dataclass(slots=True)
class ImportOptions:
    """Parametry importu modelu podane przez administratora."""

    name: str = ""
    quantize: bool = True
    keep_fp32: bool = False
    pooling: str = ""
    query_prefix: str | None = None
    passage_prefix: str | None = None
    force: bool = False


def import_local_model(
    source_dir: Path,
    options: ImportOptions,
    *,
    paths: AppPaths | None = None,
    repo_id: str = "",
    license_hint: str = "",
    progress: ProgressCallback | None = None,
) -> ImportedModel:
    """Importuje model z lokalnego katalogu do magazynu modeli uzytkownika.

    Katalog moze zawierac gotowy eksport ONNX albo checkpoint HuggingFace.
    Checkpoint jest konwertowany na miejscu, co wymaga dodatku ``finddocs[export]``.
    """
    app_paths = (paths or AppPaths.default()).ensure()
    source_dir = source_dir.expanduser().resolve()
    if not source_dir.is_dir():
        raise ModelNotAvailableError(f"Katalog modelu nie istnieje: {source_dir}")

    kind, resolved = classify_local_source(source_dir)
    default_name = repo_id.split("/")[-1] if repo_id else source_dir.name
    key = sanitize_model_key(options.name or default_name)
    target = app_paths.models_dir / key / ONNX_SUBDIR
    if target.parent.exists() and not options.force:
        raise ModelNotAvailableError(
            f"Model '{key}' jest już zainstalowany w {target.parent}. "
            "Użyj --force, żeby go nadpisać, albo --name, żeby nadać inną nazwę."
        )

    notes: list[str] = []
    staging = app_paths.new_temp_workspace(prefix=f"model-{key}-")
    try:
        if kind == "checkpoint":
            missing = missing_export_packages()
            if missing:
                raise ModelNotAvailableError(
                    "Ten katalog zawiera checkpoint wymagający konwersji do ONNX, "
                    "a w środowisku brakuje pakietów: " + ", ".join(missing) + ". "
                    'Zainstaluj dodatek: pip install "finddocs[export]".'
                )
            result = convert_checkpoint(
                resolved,
                staging,
                quantize=options.quantize,
                keep_fp32=options.keep_fp32,
                progress=progress,
            )
            model_files = result.model_files
        else:
            model_files = _copy_onnx_source(resolved, staging, source_dir)
            if options.quantize and "model.int8.onnx" not in model_files:
                if try_quantize(staging, progress=progress):
                    model_files.append("model.int8.onnx")
                    if not options.keep_fp32:
                        (staging / "model.onnx").unlink(missing_ok=True)
                        model_files.remove("model.onnx")
                else:
                    notes.append(
                        "Pominięto kwantyzację INT8: brak pakietu onnx. Model będzie "
                        "działał w pełnej precyzji, tylko wolniej. Kwantyzację umożliwia "
                        'dodatek: pip install "finddocs[export]".'
                    )
            if (
                "model.int8.onnx" in model_files
                and "model.onnx" in model_files
                and not options.keep_fp32
            ):
                for leftover in staging.glob("model.onnx*"):
                    leftover.unlink()
                model_files = [name for name in model_files if not name.startswith("model.onnx")]
            for extra_name in _SENTENCE_TRANSFORMERS_FILES:
                for base in (resolved, source_dir):
                    extra = base / extra_name
                    if extra.exists():
                        destination = staging / extra_name
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(extra, destination)
                        break

        probe = probe_onnx_model(staging)
        source_manifest = _read_source_manifest(resolved)
        descriptor = descriptor_for_repo(repo_id) if repo_id else KNOWN_MODELS.get(key)

        if probe["rank"] == 2:
            pooling = "none"
            if options.pooling and options.pooling != "none":
                notes.append(
                    "Model zwraca gotowy wektor zbiorczy, wiec podany tryb poolingu "
                    "zostal zignorowany."
                )
        else:
            detected = detect_pooling(resolved) or detect_pooling(staging)
            pooling = (
                options.pooling
                or (source_manifest.pooling if source_manifest else "")
                or detected
                or (descriptor.pooling if descriptor else "")
            )
            if not pooling:
                pooling = "mean"
                notes.append(
                    "Nie znaleziono konfiguracji poolingu, przyjęto uśrednianie (mean). "
                    "Jeśli model wymaga wektora CLS, powtórz import z opcją --pooling cls."
                )

        if options.query_prefix is not None:
            query_prefix = options.query_prefix
        elif source_manifest is not None:
            query_prefix = source_manifest.query_prefix
        elif descriptor is not None:
            query_prefix = descriptor.query_prefix
        else:
            query_prefix = ""
        if options.passage_prefix is not None:
            passage_prefix = options.passage_prefix
        elif source_manifest is not None:
            passage_prefix = source_manifest.passage_prefix
        elif descriptor is not None:
            passage_prefix = descriptor.passage_prefix
        else:
            passage_prefix = ""
        if descriptor is None and source_manifest is None and options.query_prefix is None:
            notes.append(
                "Model spoza wbudowanej listy: przyjęto puste przedrostki zapytania "
                "i treści. Jeśli model wymaga przedrostków (np. rodzina E5), powtórz "
                "import z opcjami --query-prefix i --passage-prefix."
            )

        max_sequence = (
            (source_manifest.max_sequence_length if source_manifest else 0)
            or _config_max_sequence(staging)
            or _config_max_sequence(resolved)
            or 512
        )
        display_name = (
            (source_manifest.display_name if source_manifest else "")
            or (descriptor.display_name if descriptor else "")
            or (repo_id or key)
        )
        license_name = (
            (source_manifest.license if source_manifest else "")
            or (descriptor.license_name if descriptor else "")
            or license_hint
            or "nieznana"
        )
        source_url = (
            (source_manifest.source if source_manifest else "")
            or (descriptor.source_url if descriptor else "")
            or (f"https://huggingface.co/{repo_id}" if repo_id else str(source_dir))
        )
        architecture = source_manifest.architecture if source_manifest else ""
        if not architecture:
            try:
                architecture = str(read_checkpoint_config(staging).get("model_type", ""))
            except ModelNotAvailableError:
                architecture = ""

        write_manifest(
            staging,
            model_key=key,
            source=source_url,
            license_name=license_name,
            architecture=architecture or "nieznana",
            dimension=int(probe["dimension"]),
            max_sequence_length=int(max_sequence),
            pooling=pooling,
            normalize=True,
            query_prefix=query_prefix,
            passage_prefix=passage_prefix,
            opset=source_manifest.opset if source_manifest else 0,
            quantized=(staging / "model.int8.onnx").exists(),
            pad_token=detect_pad_token(staging) or detect_pad_token(resolved),
            display_name=display_name,
        )

        _validate_with_provider(staging, expected_dimension=int(probe["dimension"]))

        if target.parent.exists():
            shutil.rmtree(target.parent)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staging), str(target))
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    quantized = (target / "model.int8.onnx").exists()
    log.info("model.imported", key=key, quantized=quantized, pooling=pooling)
    return ImportedModel(
        key=key,
        directory=target,
        display_name=display_name,
        dimension=int(probe["dimension"]),
        pooling=pooling,
        quantized=quantized,
        query_prefix=query_prefix,
        passage_prefix=passage_prefix,
        model_files=sorted(p.name for p in target.glob("model*.onnx") if p.is_file()),
        notes=notes,
    )


def import_from_repo(
    repo_id: str,
    options: ImportOptions,
    *,
    paths: AppPaths | None = None,
    policy: Any = None,
    transport: Any = None,
    progress: ProgressCallback | None = None,
) -> ImportedModel:
    """Pobiera repozytorium z Hugging Face i importuje je jak katalog lokalny.

    Pobrane pliki laduja w tymczasowym katalogu roboczym aplikacji i sa
    usuwane po imporcie, takze przy bledzie.
    """
    from finddocs.providers.model_download import download_repo

    if not looks_like_repo_id(repo_id):
        raise ModelNotAvailableError(
            f"'{repo_id}' nie jest ani istniejącym katalogiem, ani identyfikatorem "
            "repozytorium Hugging Face w formacie organizacja/nazwa."
        )
    app_paths = (paths or AppPaths.default()).ensure()
    workspace = app_paths.new_temp_workspace(prefix="model-pobieranie-")
    try:
        result = download_repo(
            repo_id,
            workspace,
            quantize=options.quantize,
            policy=policy,
            transport=transport,
            progress=progress,
        )
        imported = import_local_model(
            workspace,
            options,
            paths=app_paths,
            repo_id=repo_id,
            license_hint=result.license_name,
            progress=progress,
        )
        imported.notes = [*result.notes, *imported.notes]
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
    return imported


def _validate_with_provider(directory: Path, *, expected_dimension: int) -> None:
    """Ostateczna walidacja: dostawca embeddingow liczy probne wektory."""
    from finddocs.providers.onnx_local import OnnxEmbeddingProvider

    provider = OnnxEmbeddingProvider(directory, batch_size=2, num_threads=1)
    try:
        query = provider.embed_query("probne zapytanie")
        passages = provider.embed_passages(["pierwszy tekst probny", "drugi tekst probny"])
    finally:
        provider.close()
    if query.shape != (expected_dimension,) or passages.shape != (2, expected_dimension):
        raise ModelNotAvailableError(
            "Walidacja modelu nie powiodła się: wymiary wektorów nie zgadzają się "
            f"z oczekiwanym wymiarem {expected_dimension}."
        )


def remove_model(key: str, *, paths: AppPaths | None = None) -> Path:
    """Usuwa model z katalogu modeli uzytkownika. Zwraca usuniety katalog."""
    app_paths = paths or AppPaths.default()
    safe_key = sanitize_model_key(key)
    target = (app_paths.models_dir / safe_key).resolve()
    models_root = app_paths.models_dir.resolve()
    if models_root not in target.parents:
        raise ProviderError(f"Katalog {target} leży poza magazynem modeli.")
    if not target.is_dir():
        raise ModelNotAvailableError(
            f"Model '{safe_key}' nie jest zainstalowany w katalogu modeli użytkownika."
        )
    shutil.rmtree(target)
    log.info("model.removed", key=safe_key)
    return target


__all__ = [
    "ImportOptions",
    "ImportedModel",
    "classify_local_source",
    "descriptor_for_repo",
    "detect_pooling",
    "import_from_repo",
    "import_local_model",
    "looks_like_repo_id",
    "probe_onnx_model",
    "remove_model",
    "sanitize_model_key",
    "try_quantize",
]
