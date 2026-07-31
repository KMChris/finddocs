"""Uruchomienie aplikacji graficznej.

Aplikacja startuje bez terminala i bez recznego uruchamiania serwera. Bledy startu
sa pokazywane w oknie dialogowym, a szczegoly trafiaja do pliku logu.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

from finddocs.app_paths import AppPaths
from finddocs.errors import FindDocsError
from finddocs.logging_setup import configure_logging, get_logger
from finddocs.version import APP_NAME, APP_VERSION

log = get_logger(__name__)

ICON_CANDIDATES = ("finddocs.ico", "finddocs.png")


def _find_icon() -> Path | None:
    resources = Path(__file__).resolve().parents[1] / "resources"
    for name in ICON_CANDIDATES:
        candidate = resources / name
        if candidate.exists():
            return candidate
    return None


def _show_startup_error(message: str, log_path: Path) -> None:
    """Pokazuje blad startu w oknie, a gdy Qt nie wstaje, na standardowym wyjsciu."""
    from finddocs.gui import i18n

    text = i18n.STARTUP_ERROR.format(message=message, log=log_path)
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication(sys.argv[:1])
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle(f"{APP_NAME}: blad uruchomienia")
        box.setText(text)
        box.exec()
        del app
    except Exception:  # noqa: BLE001 - ostatnia deska ratunku
        print(text, file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="finddocs-gui", description=f"{APP_NAME} {APP_VERSION}")
    parser.add_argument("--data-dir", help="katalog danych aplikacji")
    parser.add_argument("--query", help="wpisz zapytanie zaraz po starcie")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="tworzy okno i zamyka je od razu, uzywane w tescie dymnym",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    paths = (AppPaths.at(args.data_dir) if args.data_dir else AppPaths.default()).ensure()
    configure_logging(log_file=paths.log_file, level="INFO", console=False)
    log.info("gui.starting", version=APP_VERSION)

    try:
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication

        from finddocs.gui.context import AppContext
        from finddocs.gui.main_window import MainWindow
        from finddocs.gui.theme import apply_theme
    except ImportError as exc:  # pragma: no cover - brak Qt to blad instalacji
        _show_startup_error(
            "Brakuje bibliotek interfejsu graficznego (PySide6). "
            f"Szczegoly: {exc}",
            paths.log_file,
        )
        return 1

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)

    icon_path = _find_icon()
    icon = QIcon(str(icon_path)) if icon_path else None
    if icon is not None:
        app.setWindowIcon(icon)

    context = AppContext(args.data_dir)
    try:
        palette = apply_theme(app, context.config.ui.theme)
        context.open()
        window = MainWindow(context, palette, icon)
    except FindDocsError as exc:
        log.error("gui.startup_failed", code=exc.code)
        _show_startup_error(f"[{exc.code}] {exc.user_message}", paths.log_file)
        context.close()
        return 1
    except Exception as exc:  # noqa: BLE001 - uzytkownik ma dostac czytelny komunikat
        log.error("gui.startup_crashed", error_type=type(exc).__name__)
        log.debug("gui.startup_traceback", traceback=traceback.format_exc())
        _show_startup_error(f"{type(exc).__name__}: {exc}", paths.log_file)
        context.close()
        return 1

    window.show()
    if args.query:
        window.search_view.query_edit.setText(args.query)
        window.search_view.run_search()

    if args.self_test:
        app.processEvents()
        window.close()
        context.close()
        log.info("gui.self_test_ok")
        return 0

    exit_code = app.exec()
    log.info("gui.stopped", exit_code=exit_code)
    return int(exit_code)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
