"""Dostawcy embeddingow: lokalny ONNX (CPU/GPU) i zdalne API z kluczem."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from finddocs.config import EmbeddingSettings
from finddocs.errors import ConfigurationError
from finddocs.logging_setup import get_logger
from finddocs.providers.base import EmbeddingProvider, ProviderInfo, l2_normalize
from finddocs.providers.internal_api import InternalApiEmbeddingProvider
from finddocs.providers.model_manifest import (
    DEFAULT_MODEL_KEY,
    KNOWN_MODELS,
    LocalModelManifest,
    ModelDescriptor,
    describe_models,
    find_model_dir,
)
from finddocs.providers.onnx_local import (
    OnnxEmbeddingProvider,
    available_devices,
    create_local_provider,
    resolve_execution_providers,
)

log = get_logger(__name__)


def _api_key_provider(config_dir: Path | None) -> Callable[[], str | None] | None:
    """Buduje funkcje odczytu klucza API z magazynu poswiadczen.

    Klucz jest odczytywany dopiero w chwili wysylki zadania, wiec jego zmiana
    w magazynie dziala bez ponownego tworzenia dostawcy.
    """
    if config_dir is None:
        return None

    from finddocs.security.credentials import (
        EMBEDDING_API_KEY_NAME,
        create_credential_store,
    )

    def read_key() -> str | None:
        try:
            store = create_credential_store(config_dir)
            return store.get_secret(EMBEDDING_API_KEY_NAME)
        except Exception as exc:
            log.warning("provider.api_key_unavailable", error_type=type(exc).__name__)
            return None

    return read_key


def create_provider(
    settings: EmbeddingSettings,
    *,
    credentials_dir: Path | None = None,
) -> EmbeddingProvider:
    """Tworzy dostawce embeddingow zgodnie z konfiguracja.

    ``credentials_dir`` wskazuje katalog magazynu poswiadczen DPAPI. Jest
    potrzebny tylko dostawcy zdalnego API do odczytu klucza.
    """
    if settings.provider == "local_onnx":
        return create_local_provider(
            settings.model_key,
            model_path=settings.model_path,
            prefer_quantized=settings.quantized,
            max_sequence_length=settings.max_sequence_length,
            batch_size=settings.batch_size,
            num_threads=settings.num_threads,
            device=settings.device,
        )
    if settings.provider == "internal_api":
        return InternalApiEmbeddingProvider(
            settings.internal_api_url,
            enabled=settings.internal_api_enabled,
            model=settings.internal_api_model,
            dimension=settings.internal_api_dimension,
            protocol=settings.internal_api_protocol,
            query_prefix=settings.query_prefix,
            passage_prefix=settings.passage_prefix,
            batch_size=settings.internal_api_batch_size,
            timeout=settings.internal_api_timeout_seconds,
            max_retries=settings.internal_api_max_retries,
            api_key_provider=_api_key_provider(credentials_dir),
            api_key_header=settings.internal_api_key_header,
            send_dimensions=settings.internal_api_send_dimensions,
        )
    raise ConfigurationError(f"Nieznany dostawca embeddingów: {settings.provider}")


__all__ = [
    "DEFAULT_MODEL_KEY",
    "KNOWN_MODELS",
    "EmbeddingProvider",
    "InternalApiEmbeddingProvider",
    "LocalModelManifest",
    "ModelDescriptor",
    "OnnxEmbeddingProvider",
    "ProviderInfo",
    "available_devices",
    "create_local_provider",
    "create_provider",
    "describe_models",
    "find_model_dir",
    "l2_normalize",
    "resolve_execution_providers",
]
