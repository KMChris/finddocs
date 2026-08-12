"""Jawna kontrola polaczen sieciowych.

FindDocs domyslnie nie wychodzi poza komputer uzytkownika. Kazde polaczenie musi
przejsc przez ``NetworkPolicy.check``, ktora dopuszcza wylacznie hosty z jawnie
wlaczonych kategorii. Kategorie sa wlaczane przez konfiguracje, nigdy domyslnie.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import urlparse

from finddocs.errors import NetworkPolicyError
from finddocs.logging_setup import get_logger
from finddocs.security.redaction import safe_url
from finddocs.types import SourceKind

log = get_logger(__name__)


class EgressCategory(StrEnum):
    """Kategorie dozwolonego ruchu wychodzacego."""

    MICROSOFT_GRAPH = "microsoft_graph"
    """Microsoft Graph i Entra ID, potrzebne do pracy z SharePoint."""

    MODEL_DOWNLOAD = "model_download"
    """Jednorazowe pobranie modeli z adresow zapisanych w manifeście."""

    INTERNAL_API = "internal_api"
    """Wewnetrzne API organizacji (przyszły provider embeddingów na GPU)."""


DEFAULT_ALLOWLIST: dict[EgressCategory, tuple[str, ...]] = {
    EgressCategory.MICROSOFT_GRAPH: (
        "graph.microsoft.com",
        "*.graph.microsoft.com",
        "login.microsoftonline.com",
        "*.login.microsoftonline.com",
        "login.microsoft.com",
        "*.sharepoint.com",
    ),
    EgressCategory.MODEL_DOWNLOAD: (
        "huggingface.co",
        "cdn-lfs.huggingface.co",
        "cdn-lfs-us-1.huggingface.co",
        "*.hf.co",
    ),
    EgressCategory.INTERNAL_API: (),
}

ALLOWED_SCHEMES = frozenset({"https"})
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


@dataclass(slots=True)
class NetworkPolicy:
    """Polityka ruchu wychodzacego."""

    enabled_categories: set[EgressCategory] = field(default_factory=set)
    extra_hosts: dict[EgressCategory, tuple[str, ...]] = field(default_factory=dict)
    allow_plain_http_localhost: bool = False

    @classmethod
    def offline(cls) -> NetworkPolicy:
        """Polityka calkowicie offline. Kazde polaczenie zostanie odrzucone."""
        return cls(enabled_categories=set())

    def enable(self, category: EgressCategory) -> None:
        self.enabled_categories.add(category)

    def disable(self, category: EgressCategory) -> None:
        self.enabled_categories.discard(category)

    def is_enabled(self, category: EgressCategory) -> bool:
        return category in self.enabled_categories

    def allowed_hosts(self, category: EgressCategory) -> tuple[str, ...]:
        return DEFAULT_ALLOWLIST.get(category, ()) + self.extra_hosts.get(category, ())

    def check(self, url: str, category: EgressCategory) -> str:
        """Sprawdza adres. Zwraca host, gdy polaczenie jest dozwolone.

        Rzuca ``NetworkPolicyError``, gdy kategoria jest wylaczona, schemat nie jest
        https albo host nie pasuje do listy dozwolonych wzorcow.
        """
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        scheme = (parsed.scheme or "").lower()

        if not host:
            raise NetworkPolicyError(f"Adres {safe_url(url)} nie zawiera nazwy hosta.")

        if host in LOCAL_HOSTS:
            if scheme == "https" or self.allow_plain_http_localhost:
                return host
            raise NetworkPolicyError(
                "Połączenia http z localhost są wyłączone w bieżącej konfiguracji."
            )

        if scheme not in ALLOWED_SCHEMES:
            raise NetworkPolicyError(
                f"Dozwolone jest wyłącznie połączenie https. Adres używa schematu '{scheme}'."
            )

        if category not in self.enabled_categories:
            raise NetworkPolicyError(
                f"Kategoria połączeń '{category.value}' jest wylaczona. "
                "Wlacz ja w konfiguracji, jesli organizacja na to pozwala."
            )

        patterns = self.allowed_hosts(category)
        if not any(fnmatch.fnmatch(host, pattern) for pattern in patterns):
            log.warning(
                "network.blocked",
                host=host,
                category=category.value,
                url=safe_url(url),
            )
            raise NetworkPolicyError(
                f"Host {host} nie znajduje sie na liscie dozwolonych adresow "
                f"dla kategorii '{category.value}'."
            )
        return host

    def describe(self) -> dict[str, object]:
        """Opis polityki do ekranu diagnostyki."""
        return {
            "kategorie_wlaczone": sorted(c.value for c in self.enabled_categories),
            "kategorie_wylaczone": sorted(
                c.value for c in EgressCategory if c not in self.enabled_categories
            ),
            "dozwolone_hosty": {
                c.value: list(self.allowed_hosts(c))
                for c in EgressCategory
                if c in self.enabled_categories
            },
        }


def policy_from_config(config: object) -> NetworkPolicy:
    """Buduje polityke sieciowa z konfiguracji aplikacji.

    Kategorie sa wlaczane wylacznie na podstawie jawnych ustawien. Dla zdalnego
    API embeddingow do listy dozwolonych trafia dokladnie jeden host: ten z
    adresu podanego w konfiguracji. Argument jest typowany jako ``object``,
    zeby modul sieciowy nie zalezal od modulu konfiguracji.
    """
    policy = NetworkPolicy.offline()

    sources = getattr(config, "sources", []) or []
    if any(
        getattr(s, "enabled", False) and getattr(s, "kind", None) is SourceKind.SHAREPOINT
        for s in sources
    ):
        policy.enable(EgressCategory.MICROSOFT_GRAPH)

    if getattr(config, "allow_model_download", False):
        policy.enable(EgressCategory.MODEL_DOWNLOAD)

    embedding = getattr(config, "embedding", None)
    if embedding is not None and getattr(embedding, "internal_api_enabled", False):
        api_url = str(getattr(embedding, "internal_api_url", "") or "")
        host = (urlparse(api_url).hostname or "").lower()
        if host:
            policy.enable(EgressCategory.INTERNAL_API)
            policy.extra_hosts[EgressCategory.INTERNAL_API] = (host,)
    return policy


_policy = NetworkPolicy.offline()


def get_policy() -> NetworkPolicy:
    """Zwraca globalna polityke sieciowa procesu."""
    return _policy


def set_policy(policy: NetworkPolicy) -> None:
    global _policy
    _policy = policy


def check_url(url: str, category: EgressCategory) -> str:
    """Skrot do sprawdzenia adresu wzgledem globalnej polityki."""
    return _policy.check(url, category)


__all__ = [
    "ALLOWED_SCHEMES",
    "DEFAULT_ALLOWLIST",
    "EgressCategory",
    "NetworkPolicy",
    "check_url",
    "get_policy",
    "policy_from_config",
    "set_policy",
]
