"""Pobieranie modeli embeddingow z Hugging Face przez polityke sieciowa.

Kazde zadanie HTTP, takze po przekierowaniu na serwer CDN, przechodzi przez
``NetworkPolicy.check`` w kategorii ``model_download``. Kategoria jest domyslnie
wylaczona: wlacza ja dopiero jawna zgoda administratora w CLI albo ustawienie
``allow_model_download`` w konfiguracji.

Modul nie zapisuje zadnych danych poza wskazanym katalogiem docelowym i nie
loguje pelnych adresow. Sumy kontrolne plikow LFS zadeklarowane w repozytorium
sa weryfikowane po pobraniu.
"""

from __future__ import annotations

import hashlib
import importlib.util
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from finddocs.errors import DownloadError, ModelNotAvailableError
from finddocs.logging_setup import get_logger
from finddocs.providers.model_export import TOKENIZER_FILES, ProgressCallback
from finddocs.security.network import EgressCategory, NetworkPolicy, get_policy
from finddocs.security.redaction import safe_url

log = get_logger(__name__)

HF_BASE_URL = "https://huggingface.co"

#: Margines wolnego miejsca wymagany ponad rozmiar pobieranych plikow.
DISK_MARGIN_BYTES = 200 * 1024 * 1024

#: Pliki konfiguracji pobierane zawsze, gdy istnieja w repozytorium.
_CONFIG_FILES: tuple[str, ...] = (
    *TOKENIZER_FILES,
    "modules.json",
    "1_Pooling/config.json",
    "sentence_bert_config.json",
)

#: Kwantyzowane warianty ONNX rozpoznawane w gotowych eksportach.
_REPO_QUANTIZED: tuple[str, ...] = (
    "onnx/model.int8.onnx",
    "onnx/model_quantized.onnx",
    "onnx/model_qint8_avx512_vnni.onnx",
    "onnx/model_qint8_arm64.onnx",
)


@dataclass(slots=True)
class RepoFile:
    """Pojedynczy plik w repozytorium modelu."""

    path: str
    size: int
    sha256: str = ""


@dataclass(slots=True)
class RepoInfo:
    """Informacje o repozytorium modelu."""

    repo_id: str
    license_name: str
    files: dict[str, RepoFile]


@dataclass(slots=True)
class DownloadPlan:
    """Wynik doboru plikow do pobrania."""

    strategy: str
    """``onnx`` (gotowy eksport) albo ``weights`` (checkpoint do konwersji)."""

    paths: list[str]
    total_bytes: int
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DownloadResult:
    """Podsumowanie pobrania repozytorium."""

    repo_id: str
    directory: Path
    strategy: str
    license_name: str
    files: list[str]
    notes: list[str] = field(default_factory=list)


def _client(policy: NetworkPolicy, transport: httpx.BaseTransport | None) -> httpx.Client:
    def _enforce(request: httpx.Request) -> None:
        policy.check(str(request.url), EgressCategory.MODEL_DOWNLOAD)

    return httpx.Client(
        timeout=httpx.Timeout(120.0, connect=30.0),
        follow_redirects=True,
        transport=transport,
        event_hooks={"request": [_enforce]},
        headers={"Accept": "application/json"},
    )


def _api_error(repo_id: str, response: httpx.Response) -> ModelNotAvailableError:
    if response.status_code in (401, 403):
        return ModelNotAvailableError(
            f"Repozytorium {repo_id} wymaga uwierzytelnienia. Aplikacja pobiera "
            "wyłącznie modele publiczne."
        )
    if response.status_code == 404:
        return ModelNotAvailableError(f"Repozytorium {repo_id} nie istnieje na Hugging Face.")
    return ModelNotAvailableError(
        f"Serwer Hugging Face odpowiedział kodem {response.status_code} dla repozytorium {repo_id}."
    )


def fetch_repo_info(
    repo_id: str,
    *,
    revision: str = "main",
    policy: NetworkPolicy | None = None,
    transport: httpx.BaseTransport | None = None,
) -> RepoInfo:
    """Pobiera licencje i liste plikow repozytorium z API Hugging Face."""
    active_policy = policy if policy is not None else get_policy()
    with _client(active_policy, transport) as client:
        try:
            meta = client.get(f"{HF_BASE_URL}/api/models/{repo_id}")
            if meta.status_code != 200:
                raise _api_error(repo_id, meta)
            tree = client.get(
                f"{HF_BASE_URL}/api/models/{repo_id}/tree/{revision}",
                params={"recursive": "true"},
            )
            if tree.status_code != 200:
                raise _api_error(repo_id, tree)
        except httpx.HTTPError as exc:
            log.warning("model.download_api_failed", error_type=type(exc).__name__)
            raise DownloadError(
                f"Nie udało się połączyć z Hugging Face: {type(exc).__name__}.",
                details={"repo": repo_id},
                cause=exc,
            ) from exc

        payload = meta.json()
        license_name = ""
        if isinstance(payload, dict):
            card = payload.get("cardData")
            if isinstance(card, dict) and isinstance(card.get("license"), str):
                license_name = card["license"]
            if not license_name:
                for tag in payload.get("tags", []) or []:
                    if isinstance(tag, str) and tag.startswith("license:"):
                        license_name = tag.removeprefix("license:")
                        break

        files: dict[str, RepoFile] = {}
        entries = tree.json()
        if not isinstance(entries, list):
            raise DownloadError(f"API Hugging Face zwróciło zły format listy plików dla {repo_id}.")
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("type") != "file":
                continue
            path = str(entry.get("path", ""))
            if not path:
                continue
            lfs = entry.get("lfs")
            sha = ""
            if isinstance(lfs, dict) and isinstance(lfs.get("oid"), str):
                sha = lfs["oid"]
            files[path] = RepoFile(path=path, size=int(entry.get("size", 0)), sha256=sha)
    return RepoInfo(repo_id=repo_id, license_name=license_name, files=files)


def select_download_files(
    info: RepoInfo,
    *,
    torch_available: bool,
    can_quantize_locally: bool,
    quantize: bool,
) -> DownloadPlan:
    """Dobiera pliki do pobrania w zaleznosci od zawartosci repozytorium.

    Preferowany jest gotowy eksport ``onnx/model.onnx``, bo nie wymaga torch.
    W przeciwnym razie pobierany jest checkpoint do lokalnej konwersji.
    """
    if "tokenizer.json" not in info.files:
        raise ModelNotAvailableError(
            f"Repozytorium {info.repo_id} nie zawiera pliku tokenizer.json. "
            "Aplikacja obsługuje wyłącznie szybkie tokenizery HuggingFace."
        )

    selected = [name for name in _CONFIG_FILES if name in info.files]
    notes: list[str] = []

    if "onnx/model.onnx" in info.files:
        strategy = "onnx"
        selected.extend(path for path in info.files if path.startswith("onnx/model.onnx"))
        if quantize and not can_quantize_locally:
            for candidate in _REPO_QUANTIZED:
                if candidate in info.files:
                    selected.append(candidate)
                    notes.append(
                        f"Pobrano gotowy wariant INT8 z repozytorium ({candidate.split('/')[-1]})."
                    )
                    break
    elif "model.safetensors" in info.files or "pytorch_model.bin" in info.files:
        if not torch_available:
            raise ModelNotAvailableError(
                f"Repozytorium {info.repo_id} zawiera tylko checkpoint wymagający "
                "konwersji do ONNX, a w środowisku brakuje pakietu torch. "
                "Zainstaluj je poleceniem: pip install -r requirements-export.txt."
            )
        strategy = "weights"
        weight = "model.safetensors" if "model.safetensors" in info.files else "pytorch_model.bin"
        selected.append(weight)
    else:
        raise ModelNotAvailableError(
            f"Repozytorium {info.repo_id} nie zawiera ani eksportu ONNX, ani wag modelu."
        )

    unique = list(dict.fromkeys(selected))
    total = sum(info.files[path].size for path in unique)
    return DownloadPlan(strategy=strategy, paths=unique, total_bytes=total, notes=notes)


def download_files(
    info: RepoInfo,
    plan: DownloadPlan,
    target_dir: Path,
    *,
    revision: str = "main",
    policy: NetworkPolicy | None = None,
    transport: httpx.BaseTransport | None = None,
    progress: ProgressCallback | None = None,
) -> None:
    """Pobiera zaplanowane pliki do katalogu docelowego i weryfikuje sumy LFS."""
    target_dir.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(target_dir).free
    if plan.total_bytes + DISK_MARGIN_BYTES > free:
        raise DownloadError(
            f"Za mało miejsca na dysku: pobranie wymaga około "
            f"{plan.total_bytes // (1024 * 1024)} MB, wolne "
            f"{free // (1024 * 1024)} MB."
        )

    active_policy = policy if policy is not None else get_policy()
    with _client(active_policy, transport) as client:
        for path in plan.paths:
            meta = info.files[path]
            destination = target_dir / Path(path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            url = f"{HF_BASE_URL}/{info.repo_id}/resolve/{revision}/{path}"
            if progress:
                size_mb = meta.size // (1024 * 1024)
                label = f"{size_mb} MB" if size_mb else f"{meta.size} B"
                progress(f"Pobieranie {path} ({label})")
            digest = hashlib.sha256()
            received = 0
            next_report = 25
            try:
                with client.stream("GET", url) as response:
                    if response.status_code != 200:
                        raise _api_error(info.repo_id, response)
                    with destination.open("wb") as handle:
                        for chunk in response.iter_bytes(1024 * 1024):
                            handle.write(chunk)
                            digest.update(chunk)
                            received += len(chunk)
                            if progress and meta.size > 0:
                                percent = received * 100 // meta.size
                                if percent >= next_report and percent < 100:
                                    progress(f"  {path}: {percent}%")
                                    next_report = (percent // 25 + 1) * 25
            except httpx.HTTPError as exc:
                log.warning(
                    "model.download_failed",
                    file=path,
                    url=safe_url(url),
                    error_type=type(exc).__name__,
                )
                raise DownloadError(
                    f"Nie udało się pobrać pliku {path}: {type(exc).__name__}.",
                    details={"repo": info.repo_id, "plik": path},
                    cause=exc,
                ) from exc
            if meta.sha256 and digest.hexdigest() != meta.sha256:
                destination.unlink(missing_ok=True)
                raise DownloadError(
                    f"Suma kontrolna pobranego pliku {path} nie zgadza się "
                    "z zadeklarowaną w repozytorium."
                )


def download_repo(
    repo_id: str,
    target_dir: Path,
    *,
    quantize: bool = True,
    revision: str = "main",
    policy: NetworkPolicy | None = None,
    transport: httpx.BaseTransport | None = None,
    progress: ProgressCallback | None = None,
    torch_available: bool | None = None,
    can_quantize_locally: bool | None = None,
) -> DownloadResult:
    """Pobiera z repozytorium komplet plikow potrzebnych do importu modelu.

    Parametry ``torch_available`` i ``can_quantize_locally`` pozwalaja testom
    wymusic strategie; ``None`` oznacza wykrycie na podstawie srodowiska.
    """
    if torch_available is None:
        torch_available = importlib.util.find_spec("torch") is not None
    if can_quantize_locally is None:
        can_quantize_locally = importlib.util.find_spec("onnx") is not None
    info = fetch_repo_info(repo_id, revision=revision, policy=policy, transport=transport)
    plan = select_download_files(
        info,
        torch_available=torch_available,
        can_quantize_locally=can_quantize_locally,
        quantize=quantize,
    )
    if progress:
        total_mb = plan.total_bytes // (1024 * 1024)
        progress(
            f"Do pobrania: {len(plan.paths)} plików, około {total_mb} MB "
            f"(strategia: {'gotowy eksport ONNX' if plan.strategy == 'onnx' else 'checkpoint'})"
        )
    download_files(
        info,
        plan,
        target_dir,
        revision=revision,
        policy=policy,
        transport=transport,
        progress=progress,
    )
    log.info(
        "model.repo_downloaded",
        repo=repo_id,
        strategy=plan.strategy,
        files=len(plan.paths),
        bytes=plan.total_bytes,
    )
    return DownloadResult(
        repo_id=repo_id,
        directory=target_dir,
        strategy=plan.strategy,
        license_name=info.license_name,
        files=list(plan.paths),
        notes=list(plan.notes),
    )


__all__ = [
    "DISK_MARGIN_BYTES",
    "HF_BASE_URL",
    "DownloadPlan",
    "DownloadResult",
    "RepoFile",
    "RepoInfo",
    "download_files",
    "download_repo",
    "fetch_repo_info",
    "select_download_files",
]
