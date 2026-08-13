"""Katalogi danych aplikacji zgodne z konwencjami Windows.

Domyslnie wszystko trafia do %LOCALAPPDATA%\\FindDocs. Zmienna srodowiskowa
FINDDOCS_HOME pozwala przeniesc caly katalog danych, co uzywamy w testach
oraz przy pracy na dysku o wiekszej pojemnosci.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from finddocs.version import APP_NAME

ENV_HOME = "FINDDOCS_HOME"


def _default_root() -> Path:
    override = os.environ.get(ENV_HOME)
    if override:
        return Path(override).expanduser().resolve()
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / APP_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"


@dataclass(frozen=True, slots=True)
class AppPaths:
    """Zestaw katalogow uzywanych przez aplikacje."""

    root: Path

    @classmethod
    def default(cls) -> AppPaths:
        return cls(root=_default_root())

    @classmethod
    def at(cls, root: Path | str) -> AppPaths:
        return cls(root=Path(root).expanduser().resolve())

    # katalogi ------------------------------------------------------------

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def index_dir(self) -> Path:
        return self.root / "index"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def models_dir(self) -> Path:
        return self.root / "models"

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    @property
    def temp_dir(self) -> Path:
        return self.root / "temp"

    @property
    def reports_dir(self) -> Path:
        return self.root / "reports"

    @property
    def backup_dir(self) -> Path:
        return self.root / "backup"

    # pliki ---------------------------------------------------------------

    @property
    def config_file(self) -> Path:
        return self.config_dir / "settings.json"

    @property
    def database_file(self) -> Path:
        return self.index_dir / "finddocs.db"

    @property
    def vector_file(self) -> Path:
        return self.index_dir / "vectors.faiss"

    @property
    def vector_meta_file(self) -> Path:
        return self.index_dir / "vectors.json"

    @property
    def log_file(self) -> Path:
        return self.logs_dir / "finddocs.log"

    @property
    def lock_file(self) -> Path:
        return self.root / "finddocs.lock"

    # operacje ------------------------------------------------------------

    def all_dirs(self) -> tuple[Path, ...]:
        return (
            self.root,
            self.config_dir,
            self.index_dir,
            self.logs_dir,
            self.models_dir,
            self.cache_dir,
            self.temp_dir,
            self.reports_dir,
            self.backup_dir,
        )

    def ensure(self) -> AppPaths:
        """Tworzy brakujace katalogi i zwraca ten sam obiekt."""
        for directory in self.all_dirs():
            directory.mkdir(parents=True, exist_ok=True)
        return self

    def free_space_bytes(self) -> int:
        """Wolne miejsce na wolumenie, na ktorym lezy katalog danych."""
        target = self.root
        while not target.exists() and target.parent != target:
            target = target.parent
        return shutil.disk_usage(target).free

    def total_space_bytes(self) -> int:
        target = self.root
        while not target.exists() and target.parent != target:
            target = target.parent
        return shutil.disk_usage(target).total

    def index_size_bytes(self) -> int:
        """Sumaryczny rozmiar plikow indeksu."""
        if not self.index_dir.exists():
            return 0
        return sum(p.stat().st_size for p in self.index_dir.rglob("*") if p.is_file())

    def temp_size_bytes(self) -> int:
        """Laczny rozmiar przestrzeni tymczasowej.

        Pliki robocze znikaja rownolegle z pomiarem (watki przetwarzania
        sprzataja swoje katalogi), wiec wpis, ktorego nie da sie juz odczytac,
        jest po prostu pomijany.
        """
        if not self.temp_dir.exists():
            return 0
        total = 0
        for root, _dirs, files in os.walk(self.temp_dir):
            base = Path(root)
            for name in files:
                try:
                    total += (base / name).stat().st_size
                except OSError:
                    continue
        return total

    def new_temp_workspace(self, prefix: str = "fd-") -> Path:
        """Tworzy izolowany katalog roboczy w przestrzeni tymczasowej aplikacji."""
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix=prefix, dir=str(self.temp_dir)))

    def purge_temp(self) -> int:
        """Usuwa zawartosc katalogu tymczasowego. Zwraca liczbe usunietych pozycji."""
        if not self.temp_dir.exists():
            return 0
        removed = 0
        for entry in self.temp_dir.iterdir():
            try:
                if entry.is_dir():
                    shutil.rmtree(entry, ignore_errors=True)
                else:
                    entry.unlink(missing_ok=True)
                removed += 1
            except OSError:
                continue
        return removed


__all__ = ["ENV_HOME", "AppPaths"]
