"""Lokalny dostawca embeddingow oparty o ONNX Runtime na CPU.

Sesja ONNX Runtime jest tworzona wylacznie z ``CPUExecutionProvider``. Biblioteka
domyslnie wystawia takze ``AzureExecutionProvider``, ktory potrafi wysylac dane do
uslugi zdalnej. Jawne podanie listy providerow zamyka te droge.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import numpy as np

from finddocs.errors import ModelNotAvailableError, ProviderError
from finddocs.logging_setup import get_logger
from finddocs.providers.base import EmbeddingProvider, ProviderInfo, l2_normalize
from finddocs.providers.model_manifest import (
    KNOWN_MODELS,
    LocalModelManifest,
    find_model_dir,
)
from finddocs.types import CancellationToken

log = get_logger(__name__)

#: Jedyny dozwolony provider ONNX Runtime. Nie zmieniaj bez analizy bezpieczenstwa.
ALLOWED_EXECUTION_PROVIDERS: tuple[str, ...] = ("CPUExecutionProvider",)

PROVIDER_KEY = "local_onnx"


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
        self._tokenizer.enable_padding(pad_id=self._pad_id(), pad_token=self._pad_token())

        import onnxruntime as ort

        options = ort.SessionOptions()
        threads = num_threads if num_threads > 0 else max(1, (os.cpu_count() or 4) - 1)
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.enable_cpu_mem_arena = True
        options.log_severity_level = 3

        self._session: Any | None = ort.InferenceSession(
            str(model_path),
            sess_options=options,
            providers=list(ALLOWED_EXECUTION_PROVIDERS),
        )
        active = self._session.get_providers()
        if active != list(ALLOWED_EXECUTION_PROVIDERS):
            raise ProviderError(
                "ONNX Runtime uruchomil sie z niedozwolonym providerem: " + ", ".join(active)
            )
        self._input_names = {i.name for i in self._session.get_inputs()}
        self._quantized = model_path.name.endswith(".int8.onnx")
        self._model_path = model_path

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
            runtime=f"onnxruntime CPU, {threads} watkow",
        )
        log.info(
            "provider.loaded",
            model=self._info.model_key,
            dimension=self._info.dimension,
            quantized=self._quantized,
            threads=threads,
        )

    # --- pomocnicze --------------------------------------------------------

    def _pad_id(self) -> int:
        token = self._pad_token()
        value = self._tokenizer.token_to_id(token)
        return int(value) if value is not None else 1

    def _pad_token(self) -> str:
        return "<pad>"

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
            raise ProviderError("Sesja modelu zostala juz zamknieta.")
        ids, mask = self._encode(texts)
        feeds: dict[str, np.ndarray] = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self._input_names:
            feeds["token_type_ids"] = np.zeros_like(ids)
        feeds = {k: v for k, v in feeds.items() if k in self._input_names}
        outputs = session.run(None, feeds)
        hidden = np.asarray(outputs[0], dtype="float32")
        pooled = self._pool(hidden, mask)
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

    def describe(self) -> dict[str, Any]:
        data = super().describe()
        data["plik_modelu"] = str(self._model_path)
        data["katalog"] = str(self.model_dir)
        return data


def create_local_provider(
    model_key: str,
    *,
    model_path: str = "",
    prefer_quantized: bool = True,
    max_sequence_length: int | None = None,
    batch_size: int = 8,
    num_threads: int = 0,
) -> OnnxEmbeddingProvider:
    """Znajduje model na dysku i tworzy dostawce."""
    extra = Path(model_path) if model_path else None
    directory = find_model_dir(model_key, extra)
    if directory is None:
        descriptor = KNOWN_MODELS.get(model_key)
        hint = (
            f" Model mozna pobrac z {descriptor.source_url} i wyeksportowac skryptem "
            "tools/export_model_onnx.py."
            if descriptor
            else ""
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
    )


__all__ = [
    "ALLOWED_EXECUTION_PROVIDERS",
    "PROVIDER_KEY",
    "OnnxEmbeddingProvider",
    "create_local_provider",
]
