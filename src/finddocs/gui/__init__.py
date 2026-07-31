"""Interfejs graficzny FindDocs (PySide6)."""

from __future__ import annotations

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    """Uruchamia aplikacje graficzna."""
    from finddocs.gui.app import main as run

    return run(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
