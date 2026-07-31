"""Stan aplikacji wspoldzielony przez widoki interfejsu.

Kontekst tworzy i trzyma obiekty dlugozyjace: konfiguracje, indeks, wyszukiwarke
i wykonawce zadan. Widoki nie tworza tych obiektow samodzielnie, dzieki czemu
mamy jedno miejsce, w ktorym zarzadza sie cyklem zycia i zamknieciem zasobow.
"""

from __future__ import annotations

import os
import subprocess
import webbrowser
from pathlib import Path
from typing import Any

from finddocs.app_paths import AppPaths
from finddocs.config import AppConfig, load_config, save_config
from finddocs.errors import ConfigurationError, FindDocsError
from finddocs.indexing.service import IndexService
from finddocs.jobs.runner import JobRunner
from finddocs.logging_setup import get_logger
from finddocs.search.service import SearchService
from finddocs.security.network import EgressCategory, NetworkPolicy, set_policy
from finddocs.types import SourceKind

log = get_logger(__name__)


class AppContext:
    """Zbiera obiekty aplikacji potrzebne widokom."""

    def __init__(self, data_dir: str | None = None) -> None:
        self.paths = (AppPaths.at(data_dir) if data_dir else AppPaths.default()).ensure()
        self.config: AppConfig = load_config(self.paths.config_file)
        if data_dir:
            self.config.data_root = str(self.paths.root)
        self.index: IndexService | None = None
        self.search: SearchService | None = None
        self.runner: JobRunner | None = None
        self.startup_notes: list[str] = []
        self.rebuild_required = False

    # --- cykl zycia -------------------------------------------------------

    def open(self) -> None:
        """Otwiera indeks i przygotowuje serwisy."""
        self._apply_network_policy()
        self.index = IndexService(self.config, self.paths)
        self.index.open()
        self.startup_notes = list(self.index.notes)
        self.rebuild_required = self.index.rebuild_required
        self.search = SearchService(self.index)
        self.runner = JobRunner(self.config, self.index, paths=self.paths)
        self.runner.mark_interrupted_jobs()

    def close(self) -> None:
        if self.runner is not None:
            self.runner.stop(wait=True, timeout=10.0)
            self.runner = None
        if self.index is not None:
            self.index.close()
            self.index = None
        self.search = None

    def reload_index(self) -> None:
        """Zamyka i otwiera indeks ponownie, np. po zmianie modelu albo katalogu."""
        self.close()
        self.open()

    # --- konfiguracja -----------------------------------------------------

    def save(self) -> None:
        save_config(self.config, self.paths.config_file)
        self._apply_network_policy()

    def _apply_network_policy(self) -> None:
        policy = NetworkPolicy.offline()
        if any(s.kind is SourceKind.SHAREPOINT and s.enabled for s in self.config.sources):
            policy.enable(EgressCategory.MICROSOFT_GRAPH)
        if self.config.allow_model_download:
            policy.enable(EgressCategory.MODEL_DOWNLOAD)
        if self.config.embedding.internal_api_enabled:
            policy.enable(EgressCategory.INTERNAL_API)
        set_policy(policy)

    # --- otwieranie dokumentow -------------------------------------------

    def open_document(self, *, web_url: str | None, local_path: str | None) -> tuple[bool, str]:
        """Otwiera dokument. Zwraca (czy_sie_udalo, komunikat)."""
        preference = self.config.ui.open_documents_with
        candidates: list[tuple[str, str]] = []
        if preference == "local_path":
            if local_path:
                candidates.append(("local", local_path))
            if web_url:
                candidates.append(("web", web_url))
        else:
            if web_url:
                candidates.append(("web", web_url))
            if local_path:
                candidates.append(("local", local_path))

        for kind, target in candidates:
            try:
                if kind == "web" and target.lower().startswith(("http://", "https://")):
                    webbrowser.open(target)
                    return True, ""
                path = Path(target.removeprefix("file:///").replace("/", os.sep))
                if not path.exists():
                    path = Path(target)
                if path.exists():
                    os.startfile(str(path))  # noqa: S606 - otwarcie w domyslnej aplikacji
                    return True, ""
                if kind == "web":
                    webbrowser.open(target)
                    return True, ""
            except OSError as exc:
                log.warning("gui.open_document_failed", kind=kind, error_type=type(exc).__name__)
        return False, "Nie udalo sie otworzyc dokumentu. Sprawdz, czy plik nadal istnieje."

    def open_location(self, *, parent_url: str | None, local_path: str | None) -> tuple[bool, str]:
        """Otwiera katalog dokumentu albo lokalizacje w SharePoint."""
        if local_path:
            path = Path(local_path.removeprefix("file:///").replace("/", os.sep))
            if not path.exists():
                path = Path(local_path)
            if path.exists():
                try:
                    subprocess.Popen(["explorer", "/select,", str(path)])  # noqa: S603, S607
                    return True, ""
                except OSError:
                    parent = path.parent
                    if parent.exists():
                        os.startfile(str(parent))  # noqa: S606
                        return True, ""
        if parent_url:
            try:
                webbrowser.open(parent_url)
                return True, ""
            except OSError as exc:
                log.warning("gui.open_location_failed", error_type=type(exc).__name__)
        return False, "Nie udalo sie otworzyc lokalizacji dokumentu."

    def open_path(self, path: Path) -> bool:
        try:
            os.startfile(str(path))  # noqa: S606
        except OSError as exc:
            log.warning("gui.open_path_failed", error_type=type(exc).__name__)
            return False
        return True

    # --- pomocnicze -------------------------------------------------------

    def require_index(self) -> IndexService:
        if self.index is None:
            raise ConfigurationError("Indeks nie zostal otwarty.")
        return self.index

    def require_search(self) -> SearchService:
        if self.search is None:
            raise ConfigurationError("Wyszukiwarka nie zostala przygotowana.")
        return self.search

    def require_runner(self) -> JobRunner:
        if self.runner is None:
            raise ConfigurationError("Wykonawca zadan nie zostal uruchomiony.")
        return self.runner

    def status_summary(self) -> dict[str, Any]:
        if self.index is None:
            return {}
        try:
            return self.index.status().to_dict()
        except FindDocsError as exc:
            log.warning("gui.status_failed", code=exc.code)
            return {}


__all__ = ["AppContext"]
