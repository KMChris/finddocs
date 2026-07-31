"""Integracja z SharePoint przez Microsoft Graph.

Fabryka ``build_sharepoint_connector`` sklada trzy warstwy: uwierzytelnienie MSAL,
klienta HTTP z ponawianiem i stronicowaniem oraz sam konektor. Tokeny trafiaja do
magazynu poswiadczen systemu, nigdy do plikow konfiguracyjnych.
"""

from __future__ import annotations

from collections.abc import Callable

from finddocs.app_paths import AppPaths
from finddocs.config import SourceConfig
from finddocs.connectors.sharepoint.auth import GraphAuthenticator
from finddocs.connectors.sharepoint.connector import SharePointConnector
from finddocs.connectors.sharepoint.graph_client import GraphClient
from finddocs.errors import ConfigurationError
from finddocs.security.credentials import CredentialStore, create_credential_store
from finddocs.security.network import EgressCategory, NetworkPolicy, get_policy
from finddocs.types import SourceKind


def build_authenticator(
    source: SourceConfig,
    paths: AppPaths,
    *,
    credential_store: CredentialStore | None = None,
    policy: NetworkPolicy | None = None,
) -> GraphAuthenticator:
    """Tworzy obiekt uwierzytelniajacy dla zrodla SharePoint."""
    if source.kind is not SourceKind.SHAREPOINT:
        raise ConfigurationError(f"Źródło {source.source_id} nie jest źródłem SharePoint.")
    store = credential_store or create_credential_store(paths.config_dir)
    return GraphAuthenticator(source.sharepoint, store, source.source_id, policy)


def build_sharepoint_connector(
    source: SourceConfig,
    paths: AppPaths,
    *,
    credential_store: CredentialStore | None = None,
    policy: NetworkPolicy | None = None,
    device_code_callback: Callable[[str, str], None] | None = None,
) -> SharePointConnector:
    """Sklada gotowy konektor SharePoint dla wskazanego zrodla."""
    effective_policy = policy if policy is not None else get_policy()
    if not effective_policy.is_enabled(EgressCategory.MICROSOFT_GRAPH):
        effective_policy.enable(EgressCategory.MICROSOFT_GRAPH)
    authenticator = build_authenticator(
        source, paths, credential_store=credential_store, policy=effective_policy
    )
    if device_code_callback is not None:
        authenticator.set_device_code_callback(device_code_callback)
    client = GraphClient(authenticator, source.sharepoint, effective_policy)
    return SharePointConnector.from_config(source, client)


__all__ = [
    "GraphAuthenticator",
    "GraphClient",
    "SharePointConnector",
    "build_authenticator",
    "build_sharepoint_connector",
]
