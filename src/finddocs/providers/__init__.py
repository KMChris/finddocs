"""Dostawcy embeddingow: lokalny ONNX i przygotowane wewnetrzne API."""

from __future__ import annotations

from finddocs.config import EmbeddingSettings
from finddocs.errors import ConfigurationError
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
from finddocs.providers.onnx_local import OnnxEmbeddingProvider, create_local_provider


def create_provider(settings: EmbeddingSettings) -> EmbeddingProvider:
    """Tworzy dostawce embeddingow zgodnie z konfiguracja."""
    if settings.provider == "local_onnx":
        return create_local_provider(
            settings.model_key,
            model_path=settings.model_path,
            prefer_quantized=settings.quantized,
            max_sequence_length=settings.max_sequence_length,
            batch_size=settings.batch_size,
            num_threads=settings.num_threads,
        )
    if settings.provider == "internal_api":
        descriptor = KNOWN_MODELS.get(settings.model_key)
        return InternalApiEmbeddingProvider(
            settings.internal_api_url,
            enabled=settings.internal_api_enabled,
            model_key=settings.model_key,
            dimension=descriptor.dimension if descriptor else 768,
            query_prefix=settings.query_prefix,
            passage_prefix=settings.passage_prefix,
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
    "create_local_provider",
    "create_provider",
    "describe_models",
    "find_model_dir",
    "l2_normalize",
]
