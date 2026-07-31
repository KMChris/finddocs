"""Zrodla dokumentow: katalog lokalny i SharePoint przez Microsoft Graph."""

from __future__ import annotations

from finddocs.connectors.base import (
    ConnectionStatus,
    ScanCursor,
    SourceConnector,
    sha256_of_file,
)
from finddocs.connectors.local_dir import LocalDirectoryConnector

__all__ = [
    "ConnectionStatus",
    "LocalDirectoryConnector",
    "ScanCursor",
    "SourceConnector",
    "sha256_of_file",
]
