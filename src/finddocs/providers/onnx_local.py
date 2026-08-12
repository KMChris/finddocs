"""Lokalny dostawca embeddingow oparty o ONNX Runtime.

Sesja ONNX Runtime jest tworzona wylacznie z jawnej listy providerow liczacych
na sprzecie tego komputera: CPU, DirectML albo CUDA. Biblioteka domyslnie
wystawia takze ``AzureExecutionProvider``, ktory potrafi wysylac dane do uslugi
zdalnej. Ten provider nigdy nie znajdzie sie na liscie, a lista aktywna po
utworzeniu sesji jest dodatkowo sprawdzana.

Domyslnym urzadzeniem jest CPU. Urzadzenia GPU wymagaja pakietu onnxruntime
z odpowiednim providerem: onnxruntime-directml (DML) albo onnxruntime-gpu (CUDA).
Gdy zadanego urzadzenia nie ma w srodowisku, dostawca liczy na CPU i zapisuje
te informacje w opisie diagnostycznym.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import numpy as np

from finddocs.errors import ConfigurationError, ModelNotAvailableError, ProviderError
from finddocs.logging_setup import get_logger
from finddocs.providers.base import EmbeddingProvider, ProviderInfo, l2_normalize
from finddocs.providers.model_manifest import (
    KNOWN_MODELS,
    LocalModelManifest,
    find_model_dir,
)
from finddocs.types import CancellationToken

log = get_logger(__name__)

#: Sesje pomocnicze (import i weryfikacja modelu) zawsze licza na CPU.
CPU_EXECUTION_PROVIDERS: tuple[str, ...] = ("CPUExecutionProvider",)

#: Wszystkie providery ONNX Runtime, ktore licza lokalnie na tym komputerze.
#: Zaden inny (w szczegolnosci AzureExecutionProvider) nie moze trafic do sesji.
#: Nie rozszerzaj bez analizy bezpieczenstwa.
ALLOWED_EXECUTION_PROVIDERS: tuple[str, ...] = (
    "DmlExecutionProvider",
    "CUDAExecutionProvider",
    "CPUExecutionProvider",
)

#: Mapa urzadzenia z konfiguracji na provider ONNX Runtime.
EXECUTION_PROVIDER_BY_DEVICE: dict[str, str] = {
    "cpu": "CPUExecutionProvider",
    "dml": "DmlExecutionProvider",
    "cuda": "CUDAExecutionProvider",
}

#: Kolejnosc probowania urzadzen w trybie auto. CUDA przed DirectML: wariant
#: onnxruntime-gpu instaluje sie wylacznie swiadomie pod karte NVIDIA, wiec
#: jego obecnosc w srodowisku jest mocniejsza deklaracja niz ogolny DirectML.
AUTO_DEVICE_ORDER: tuple[str, ...] = ("cuda", "dml", "cpu")

#: Etykiety urzadzen do opisu diagnostycznego i interfejsu.
DEVICE_LABELS: dict[str, str] = {
    "cpu": "CPU",
    "dml": "GPU (DirectML)",
    "cuda": "GPU (CUDA)",
}

PROVIDER_KEY = "local_onnx"


def available_devices() -> dict[str, bool]:
    """Zwraca dostepnosc urzadzen w biezacym srodowisku ONNX Runtime."""
    try:
        import onnxruntime as ort

        present = set(ort.get_available_providers())
    except ImportError:
        present = set()
    return {
        device: provider in present for device, provider in EXECUTION_PROVIDER_BY_DEVICE.items()
    }


def preload_cuda_libraries() -> None:
    """Laduje biblioteki CUDA i cuDNN z pakietow pip nvidia-*, jesli sa.

    Dodatek instalacyjny przynosi biblioteki NVIDIA jako zwykle pakiety pip
    (onnxruntime-gpu[cuda,cudnn]). ONNX Runtime nie znajduje ich sam: bez tego
    wywolania ladowanie providera CUDA konczy sie bledem brakujacego
    cublasLt (zmierzone). Gdy bibliotek nie ma, ORT tylko ostrzega, a sesja
    wraca na CPU, wiec wywolanie jest bezpieczne w kazdym srodowisku.
    """
    import onnxruntime as ort

    preload = getattr(ort, "preload_dlls", None)
    if callable(preload):
        preload()


def resolve_execution_providers(device: str) -> tuple[list[str], str]:
    """Dobiera liste providerow sesji dla zadanego urzadzenia.

    Zwraca pare (lista providerow, faktyczne urzadzenie). Lista zawsze konczy sie
    providerem CPU, zeby operatory bez implementacji GPU mialy dokad spasc.
    Zadanie niedostepnego urzadzenia nie jest bledem: wybor spada na CPU,
    a rozjazd widac w zwroconym urzadzeniu i w logu ostrzezenia.
    """
    requested = (device or "cpu").strip().lower()
    if requested not in {"auto", *EXECUTION_PROVIDER_BY_DEVICE}:
        raise ConfigurationError(
            f"Nieznane urządzenie obliczeń embeddingów: '{device}'. "
            "Dozwolone wartości: cpu, auto, dml, cuda."
        )
    availability = available_devices()
    candidates = AUTO_DEVICE_ORDER if requested == "auto" else (requested, "cpu")
    for candidate in candidates:
        if availability.get(candidate, False):
            resolved = candidate
            break
    else:
        resolved = "cpu"
    if requested not in {"auto", resolved}:
        log.warning(
            "provider.device_unavailable",
            requested=requested,
            resolved=resolved,
            available=[d for d, ok in availability.items() if ok],
        )
    providers = [EXECUTION_PROVIDER_BY_DEVICE[resolved]]
    if resolved != "cpu":
        providers.append(EXECUTION_PROVIDER_BY_DEVICE["cpu"])
    return providers, resolved


class OnnxEmbeddingProvider(EmbeddingProvider):
    """Embeddingi liczone lokalnie przez ONNX Runtime."""

    def __init__(
        self,
        model_dir: Path,
        *,
        prefer_quantized: bool = True,
        max_sequence_length: int | None = None,
        batch_size: int = 8,
        num_threads: int = 0,
        device: str = "cpu",
        verify_checksums: bool = False,
    ) -> None:
        self.model_dir = Path(model_dir)
        self.manifest = LocalModelManifest.load(self.model_dir)
        self.batch_size = max(1, batch_size)
        self._lock = threading.RLock()

        model_path = self.manifest.model_file(self.model_dir, prefer_quantized=prefer_quantized)
        if verify_checksums:
            self.manifest.verify(self.model_dir, files=[model_path.name])

        tokenizer_path = self.model_dir / "tokenizer.json"
        if not tokenizer_path.exists():
            raise ModelNotAvailableError(
                f"Brakuje pliku tokenizera w katalogu modelu: {tokenizer_path}."
            )

        from tokenizers import Tokenizer

        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self._max_len = int(max_sequence_length or self.manifest.max_sequence_length or 512)
        self._tokenizer.enable_truncation(max_length=self._max_len)
        pad_id, pad_token = self._resolve_padding()
        self._tokenizer.enable_padding(pad_id=pad_id, pad_token=pad_token)

        import onnxruntime as ort

        session_providers, resolved_device = resolve_execution_providers(device)
        self._requested_device = (device or "cpu").strip().lower()
        if resolved_device == "cuda":
            preload_cuda_libraries()

        options = ort.SessionOptions()
        threads = num_threads if num_threads > 0 else max(1, (os.cpu_count() or 4) - 1)
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.enable_cpu_mem_arena = True
        options.log_severity_level = 3
        if resolved_device == "dml":
            # DmlExecutionProvider nie wspiera wzorca pamieci ORT.
            options.enable_mem_pattern = False

        self._session: Any | None = ort.InferenceSession(
            str(model_path),
            sess_options=options,
            providers=session_providers,
        )
        active = list(self._session.get_providers())
        if not set(active) <= set(ALLOWED_EXECUTION_PROVIDERS):
            raise ProviderError(
                "ONNX Runtime uruchomił się z niedozwolonym providerem: " + ", ".join(active)
            )
        if EXECUTION_PROVIDER_BY_DEVICE[resolved_device] not in active:
            # ORT tworzy sesje takze wtedy, gdy bibliotek providera GPU nie da
            # sie zaladowac (np. brak cuDNN): liczy wtedy na CPU. Opis
            # i diagnostyka maja pokazywac stan faktyczny, nie zadany.
            log.warning(
                "provider.device_fallback",
                requested=resolved_device,
                active=active,
            )
            resolved_device = "cpu"
        self._device = resolved_device
        self._input_names = {i.name for i in self._session.get_inputs()}
        self._quantized = model_path.name.endswith(".int8.onnx")
        self._model_path = model_path

        device_label = DEVICE_LABELS.get(resolved_device, resolved_device)
        runtime = (
            f"onnxruntime CPU, {threads} wątków"
            if resolved_device == "cpu"
            else f"onnxruntime {device_label}, rezerwa CPU"
        )
        if self._requested_device not in {"auto", resolved_device}:
            runtime += f" (żądane {self._requested_device} niedostępne)"

        descriptor = KNOWN_MODELS.get(self.manifest.model_key)
        self._info = ProviderInfo(
            provider_key=PROVIDER_KEY,
            model_key=self.manifest.model_key,
            model_version=self.manifest.files.get(model_path.name, {}).get("sha256", "")[:16]
            or "nieznana",
            dimension=int(self.manifest.dimension),
            max_sequence_length=self._max_len,
            pooling=self.manifest.pooling,
            normalized=bool(self.manifest.normalize),
            quantized=self._quantized,
            query_prefix=self.manifest.query_prefix,
            passage_prefix=self.manifest.passage_prefix,
            license_name=descriptor.license_name if descriptor else self.manifest.license,
            source=descriptor.source_url if descriptor else self.manifest.source,
            runtime=runtime,
        )
        log.info(
            "provider.loaded",
            model=self._info.model_key,
            dimension=self._info.dimension,
            quantized=self._quantized,
            threads=threads,
            device=resolved_device,
            execution_providers=active,
        )

    # --- pomocnicze --------------------------------------------------------

    def _resolve_padding(self) -> tuple[int, str]:
        """Dobiera token wypelnienia: najpierw z manifestu, potem typowe warianty.

        Modele rodziny RoBERTa uzywaja ``<pad>``, rodziny BERT ``[PAD]``.
        Manifest moze wskazac dowolny inny token. Gdy zaden kandydat nie
        wystepuje w slowniku, zostaje historyczna para (1, "<pad>").
        """
        candidates: list[str] = []
        for token in (self.manifest.pad_token, "<pad>", "[PAD]"):
            if token and token not in candidates:
                candidates.append(token)
        for token in candidates:
            value = self._tokenizer.token_to_id(token)
            if value is not None:
                return int(value), token
        return 1, "<pad>"

    @property
    def info(self) -> ProviderInfo:
        return self._info

    # --- wlasciwe liczenie -------------------------------------------------

    def _encode(self, texts: list[str]) -> tuple[np.ndarray, np.ndarray]:
        encodings = self._tokenizer.encode_batch(texts)
        ids = np.asarray([e.ids for e in encodings], dtype=np.int64)
        mask = np.asarray([e.attention_mask for e in encodings], dtype=np.int64)
        return ids, mask

    def _pool(self, hidden: np.ndarray, mask: np.ndarray) -> np.ndarray:
        if self.manifest.pooling == "cls":
            cls_vectors: np.ndarray = hidden[:, 0, :]
            return cls_vectors
        weights = mask.astype("float32")[:, :, None]
        summed = (hidden * weights).sum(axis=1)
        counts = np.maximum(weights.sum(axis=1), 1e-9)
        pooled: np.ndarray = summed / counts
        return pooled

    def _run(self, texts: list[str]) -> np.ndarray:
        session = self._session
        if session is None:
            raise ProviderError("Sesja modelu została już zamknięta.")
        ids, mask = self._encode(texts)
        feeds: dict[str, np.ndarray] = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self._input_names:
            feeds["token_type_ids"] = np.zeros_like(ids)
        feeds = {k: v for k, v in feeds.items() if k in self._input_names}
        outputs = session.run(None, feeds)
        hidden = np.asarray(outputs[0], dtype="float32")
        # Niektore gotowe eksporty ONNX zwracaja od razu wektor zbiorczy
        # [batch, wymiar] zamiast stanow ukrytych [batch, sekwencja, wymiar].
        pooled = hidden if hidden.ndim == 2 else self._pool(hidden, mask)
        if self.manifest.normalize:
            pooled = l2_normalize(pooled)
        final: np.ndarray = pooled.astype("float32", copy=False)
        return final

    def embed_passages(
        self, texts: list[str], *, cancel: CancellationToken | None = None
    ) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype="float32")
        prefix = self._info.passage_prefix
        prepared = [prefix + (t or " ") for t in texts]
        chunks: list[np.ndarray] = []
        with self._lock:
            for start in range(0, len(prepared), self.batch_size):
                if cancel is not None:
                    cancel.raise_if_cancelled()
                batch = prepared[start : start + self.batch_size]
                chunks.append(self._run(batch))
        if not chunks:
            return np.zeros((0, self.dimension), dtype="float32")
        stacked: np.ndarray = np.vstack(chunks)
        return stacked

    def embed_query(self, text: str) -> np.ndarray:
        prepared = self._info.query_prefix + (text or " ")
        with self._lock:
            result = self._run([prepared])
        vector: np.ndarray = result[0]
        return vector

    def close(self) -> None:
        with self._lock:
            self._session = None

    @property
    def device(self) -> str:
        """Faktyczne urzadzenie obliczen: cpu, dml albo cuda."""
        return self._device

    def describe(self) -> dict[str, Any]:
        data = super().describe()
        data["plik_modelu"] = str(self._model_path)
        data["katalog"] = str(self.model_dir)
        data["urzadzenie"] = DEVICE_LABELS.get(self._device, self._device)
        data["urzadzenie_zadane"] = self._requested_device
        return data


def create_local_provider(
    model_key: str,
    *,
    model_path: str = "",
    prefer_quantized: bool = True,
    max_sequence_length: int | None = None,
    batch_size: int = 8,
    num_threads: int = 0,
    device: str = "cpu",
) -> OnnxEmbeddingProvider:
    """Znajduje model na dysku i tworzy dostawce."""
    extra = Path(model_path) if model_path else None
    directory = find_model_dir(model_key, extra)
    if directory is None:
        descriptor = KNOWN_MODELS.get(model_key)
        hint = (
            f" Model można zainstalować poleceniem: finddocs model import {descriptor.repo}"
            if descriptor
            else " Model można zainstalować poleceniem: finddocs model import"
        )
        raise ModelNotAvailableError(
            f"Nie znaleziono lokalnego modelu '{model_key}'.{hint}",
            details={"model_key": model_key},
        )
    return OnnxEmbeddingProvider(
        directory,
        prefer_quantized=prefer_quantized,
        max_sequence_length=max_sequence_length,
        batch_size=batch_size,
        num_threads=num_threads,
        device=device,
    )


__all__ = [
    "ALLOWED_EXECUTION_PROVIDERS",
    "AUTO_DEVICE_ORDER",
    "CPU_EXECUTION_PROVIDERS",
    "DEVICE_LABELS",
    "EXECUTION_PROVIDER_BY_DEVICE",
    "PROVIDER_KEY",
    "OnnxEmbeddingProvider",
    "available_devices",
    "create_local_provider",
    "preload_cuda_libraries",
    "resolve_execution_providers",
]
