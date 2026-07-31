"""Interfejs wiersza polecen dla administratorow i diagnostyki.

Uzytkownik koncowy nie musi korzystac z terminala. CLI istnieje po to, zeby
administrator mogl zaindeksowac zbior bez interfejsu graficznego, sprawdzic stan
indeksu, wyeksportowac raport i zdiagnozowac problem.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from finddocs.app_paths import AppPaths
from finddocs.config import (
    AppConfig,
    LocalDirSourceSettings,
    SharePointSourceSettings,
    SourceConfig,
    load_config,
    save_config,
)
from finddocs.errors import FindDocsError
from finddocs.logging_setup import configure_logging, get_logger
from finddocs.types import JobState, SearchFilters, SearchMode, SearchRequest, SourceKind
from finddocs.version import APP_NAME, APP_VERSION

log = get_logger(__name__)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2


def _paths(args: argparse.Namespace) -> AppPaths:
    return AppPaths.at(args.data_dir) if args.data_dir else AppPaths.default()


def _load(args: argparse.Namespace) -> AppConfig:
    paths = _paths(args)
    config = load_config(paths.config_file)
    if args.data_dir:
        config.data_root = str(paths.root)
    return config


def _open_index(config: AppConfig, *, load_provider: bool = True) -> Any:
    from finddocs.indexing.service import IndexService

    service = IndexService(config)
    service.open(load_provider=load_provider)
    return service


def _print(data: Any, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        return
    if isinstance(data, dict):
        width = max((len(str(k)) for k in data), default=0)
        for key, value in data.items():
            print(f"{str(key).ljust(width)} : {value}")
    elif isinstance(data, list):
        for row in data:
            print(row)
    else:
        print(data)


# --- polecenia ------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    paths = _paths(args).ensure()
    config = load_config(paths.config_file)
    if args.data_dir:
        config.data_root = str(paths.root)
    save_config(config, paths.config_file)
    print(f"Katalog danych: {paths.root}")
    print(f"Plik konfiguracyjny: {paths.config_file}")
    print(f"Wolne miejsce: {paths.free_space_bytes() // (1024**3)} GB")
    return EXIT_OK


def cmd_sources_list(args: argparse.Namespace) -> int:
    config = _load(args)
    if not config.sources:
        print("Nie skonfigurowano zadnego zrodla.")
        return EXIT_OK
    rows: list[dict[str, Any]] = []
    for source in config.sources:
        rows.append(
            {
                "identyfikator": source.source_id,
                "rodzaj": source.kind.value,
                "etykieta": source.label,
                "lokalizacja": source.describe_location(),
                "aktywne": source.enabled,
            }
        )
    _print(rows if args.json else [json.dumps(r, ensure_ascii=False) for r in rows], as_json=args.json)
    return EXIT_OK


def cmd_sources_add_local(args: argparse.Namespace) -> int:
    config = _load(args)
    root = Path(args.path).expanduser().resolve()
    if not root.is_dir():
        print(f"Katalog nie istnieje: {root}", file=sys.stderr)
        return EXIT_ERROR
    source = SourceConfig(
        source_id=args.id or f"local-{uuid.uuid4().hex[:8]}",
        kind=SourceKind.LOCAL_DIR,
        label=args.label or root.name,
        local=LocalDirSourceSettings(root_path=str(root)),
    )
    config = config.with_source(source)
    save_config(config, _paths(args).config_file)
    print(f"Dodano zrodlo lokalne: {source.source_id} ({root})")
    return EXIT_OK


def cmd_sources_add_sharepoint(args: argparse.Namespace) -> int:
    config = _load(args)
    source = SourceConfig(
        source_id=args.id or f"sp-{uuid.uuid4().hex[:8]}",
        kind=SourceKind.SHAREPOINT,
        label=args.label or "SharePoint",
        sharepoint=SharePointSourceSettings(
            tenant_id=args.tenant,
            client_id=args.client_id,
            site_url=args.site,
            drive_name=args.library,
            folder_path=args.folder or "",
            auth_flow=args.auth_flow,
        ),
    )
    config = config.with_source(source)
    save_config(config, _paths(args).config_file)
    print(f"Dodano zrodlo SharePoint: {source.source_id}")
    print("Uwaga: pierwsze uzycie wymaga zalogowania. Uruchom 'finddocs sources test'.")
    return EXIT_OK


def cmd_sources_test(args: argparse.Namespace) -> int:
    config = _load(args)
    paths = _paths(args).ensure()
    source = config.source(args.id)
    if source.kind is SourceKind.LOCAL_DIR:
        from finddocs.connectors.local_dir import LocalDirectoryConnector

        connector = LocalDirectoryConnector.from_config(source)
    else:
        from finddocs.connectors.sharepoint import build_sharepoint_connector

        connector = build_sharepoint_connector(source, paths)
    try:
        status = connector.test_connection()
    finally:
        connector.close()
    print("Wynik:", "polaczono" if status.ok else "blad")
    print(status.message)
    if status.details:
        _print(status.details, as_json=args.json)
    return EXIT_OK if status.ok else EXIT_ERROR


def cmd_sources_remove(args: argparse.Namespace) -> int:
    config = _load(args)
    before = len(config.sources)
    config.sources = [s for s in config.sources if s.source_id != args.id]
    if len(config.sources) == before:
        print(f"Nie znaleziono zrodla {args.id}.", file=sys.stderr)
        return EXIT_ERROR
    save_config(config, _paths(args).config_file)
    if args.purge:
        index = _open_index(config, load_provider=False)
        try:
            with index.db.transaction():
                removed = index.repository.delete_source(args.id)
            print(f"Usunieto {removed} dokumentow z indeksu.")
        finally:
            index.close()
    print(f"Usunieto zrodlo {args.id}.")
    return EXIT_OK


def cmd_demo(args: argparse.Namespace) -> int:
    from finddocs.demo import ensure_demo_corpus

    config = _load(args)
    paths = _paths(args).ensure()
    target = Path(args.path).expanduser().resolve() if args.path else paths.root / "demo"
    info = ensure_demo_corpus(target.parent if target.name == "demo" else target, force=args.force)
    print(f"Zbior demonstracyjny: {info.root}")
    print(f"Plikow: {info.files}")
    print(f"Numer rachunku testowego: {info.account_number} ({info.account_documents} dokumentow)")
    if args.register:
        source = SourceConfig(
            source_id="demo",
            kind=SourceKind.LOCAL_DIR,
            label="Zbior demonstracyjny",
            local=LocalDirSourceSettings(root_path=str(info.root)),
            exclude_globs=["manifest.json"],
        )
        config = config.with_source(source)
        save_config(config, paths.config_file)
        print("Zarejestrowano zrodlo 'demo'.")
    return EXIT_OK


def cmd_index(args: argparse.Namespace) -> int:
    from finddocs.jobs.indexing_job import IndexingJob, JobOptions
    from finddocs.types import JobKind, ProgressSnapshot

    config = _load(args)
    index = _open_index(config)
    for note in index.notes:
        print(f"Uwaga: {note}")

    class _Printer:
        def __init__(self) -> None:
            self.last = -1

        def update(self, snapshot: ProgressSnapshot) -> None:
            done = snapshot.processed + snapshot.failed + snapshot.skipped + snapshot.unchanged
            if done == self.last:
                return
            self.last = done
            fraction = snapshot.progress_fraction
            percent = f"{fraction * 100:5.1f}%" if fraction is not None else "  ?  "
            name = (snapshot.current_file or "")[-60:]
            print(
                f"\r[{percent}] wykryte {snapshot.discovered} | przetworzone {snapshot.processed}"
                f" | niezmienione {snapshot.unchanged} | bledy {snapshot.failed}"
                f" | OCR {snapshot.ocr_documents}  {name}",
                end="",
                flush=True,
            )

    options = JobOptions(
        kind=JobKind.FULL_INDEX if args.full else JobKind.RESCAN,
        source_ids=args.source or [],
        force_reindex=args.full,
        detect_deletions=not args.no_deletions,
    )
    job = IndexingJob(config, index, options=options, progress=_Printer())
    try:
        snapshot = job.run()
    finally:
        index.close()
    print()
    print(f"Stan: {snapshot.state.value}")
    if snapshot.message:
        print(snapshot.message)
    print(
        f"Wykryte {snapshot.discovered}, przetworzone {snapshot.processed}, "
        f"niezmienione {snapshot.unchanged}, pominiete {snapshot.skipped}, "
        f"bledy {snapshot.failed}, usuniete {snapshot.deleted}, "
        f"OCR {snapshot.ocr_documents} dokumentow / {snapshot.ocr_pages} stron"
    )
    print(f"Czas: {snapshot.elapsed_seconds:.1f} s")
    return EXIT_OK if snapshot.state is JobState.COMPLETED else EXIT_ERROR


def cmd_search(args: argparse.Namespace) -> int:
    from finddocs.search.service import SearchService

    config = _load(args)
    index = _open_index(config)
    try:
        service = SearchService(index)
        filters = SearchFilters(
            extensions=args.ext or [],
            sources=args.source or [],
        )
        request = SearchRequest(
            query=args.query,
            mode=SearchMode(args.mode),
            filters=filters,
            offset=args.offset,
            limit=args.limit,
        )
        response = service.search(request)
    finally:
        index.close()

    if args.json:
        payload = {
            "zapytanie": response.query_analysis.raw_query,
            "tryb": response.mode.value,
            "liczba_dokumentow": response.total_documents,
            "liczba_dokladna": response.total_is_exact,
            "czas_ms": response.took_ms,
            "uwagi": response.notes,
            "wyniki": [
                {
                    "nazwa": hit.name,
                    "sciezka": hit.logical_path,
                    "typ": hit.extension,
                    "ocena": round(hit.score, 4),
                    "ocr": hit.used_ocr,
                    "fragmenty": [c.highlighted for c in hit.chunks],
                }
                for hit in response.hits
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return EXIT_OK

    label = "dokladnie" if response.total_is_exact else "co najmniej"
    print(f"Znaleziono {label} {response.total_documents} dokumentow ({response.took_ms} ms)")
    for note in response.notes:
        print(f"  Uwaga: {note}")
    print()
    for position, hit in enumerate(response.hits, start=request.offset + 1):
        print(f"{position}. {hit.name}   [{hit.extension or 'brak'}]")
        print(f"   {hit.logical_path}")
        if hit.used_ocr:
            print("   Tekst pochodzi z OCR")
        for chunk in hit.chunks:
            snippet = chunk.highlighted.replace("[[hl]]", "<<").replace("[[/hl]]", ">>")
            print(f"   {snippet}")
        print()
    return EXIT_OK


def cmd_report(args: argparse.Namespace) -> int:
    from finddocs.diagnostics.coverage_report import build_coverage_report, coverage_summary_text
    from finddocs.diagnostics.export import export_coverage_csv, export_coverage_json

    config = _load(args)
    index = _open_index(config, load_provider=not args.fast)
    try:
        report = build_coverage_report(index)
        print(coverage_summary_text(report))
        if args.json_out:
            path = export_coverage_json(report, Path(args.json_out))
            print(f"Zapisano JSON: {path}")
        if args.csv_out:
            path = export_coverage_csv(report, Path(args.csv_out))
            print(f"Zapisano CSV: {path}")
    finally:
        index.close()
    return EXIT_OK


def cmd_doctor(args: argparse.Namespace) -> int:
    from finddocs.diagnostics.stats import (
        collect_component_info,
        collect_environment_info,
        collect_index_stats,
    )

    config = _load(args)
    print(f"{APP_NAME} {APP_VERSION}")
    print()
    print("Srodowisko")
    _print(collect_environment_info(), as_json=args.json)
    print()
    print("Komponenty")
    _print(collect_component_info(config), as_json=args.json)
    print()
    index = _open_index(config, load_provider=True)
    try:
        print("Indeks")
        _print(collect_index_stats(index), as_json=args.json)
        print()
        print("Spojnosc")
        _print(index.consistency().to_dict(), as_json=args.json)
    finally:
        index.close()
    return EXIT_OK


def cmd_maintenance(args: argparse.Namespace) -> int:
    from finddocs.indexing.maintenance import (
        backup_index,
        compact_vectors,
        list_backups,
        mark_all_for_reindex,
        restore_backup,
    )

    config = _load(args)
    paths = _paths(args).ensure()

    if args.action == "backup":
        index = _open_index(config, load_provider=False)
        try:
            index.flush()
        finally:
            index.close()
        target = backup_index(paths)
        print(f"Kopia indeksu: {target}")
        return EXIT_OK

    if args.action == "list-backups":
        for entry in list_backups(paths):
            print(f"{entry['nazwa']}  {entry['rozmiar_bajty'] // (1024 * 1024)} MB  {entry['utworzono']}")
        return EXIT_OK

    if args.action == "restore":
        if not args.name:
            print("Podaj nazwe kopii: --name", file=sys.stderr)
            return EXIT_USAGE
        restore_backup(paths, args.name)
        print("Przywrocono indeks z kopii.")
        return EXIT_OK

    index = _open_index(config, load_provider=args.action in {"compact"})
    try:
        if args.action == "check":
            report = index.consistency()
            _print(report.to_dict(), as_json=args.json)
            return EXIT_OK if report.is_healthy else EXIT_ERROR
        if args.action == "compact":
            if index.vector_store is None:
                print("Indeks wektorowy nie jest dostepny.", file=sys.stderr)
                return EXIT_ERROR
            count = compact_vectors(index.repository, index.vector_store)
            print(f"Skompaktowano indeks wektorowy: {count} wektorow.")
            index.db.optimize()
            return EXIT_OK
        if args.action == "rebuild":
            count = mark_all_for_reindex(index.repository, only_vectors=args.vectors_only)
            print(f"Oznaczono {count} dokumentow do ponownego przetworzenia.")
            print("Uruchom 'finddocs index', zeby przebudowac indeks.")
            return EXIT_OK
    finally:
        index.close()
    return EXIT_USAGE


def cmd_gui(args: argparse.Namespace) -> int:
    from finddocs.gui.app import main as gui_main

    return gui_main(["--data-dir", args.data_dir] if args.data_dir else [])


# --- parser argumentow ----------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="finddocs",
        description=f"{APP_NAME} {APP_VERSION}: lokalna wyszukiwarka dokumentow",
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    parser.add_argument("--data-dir", help="katalog danych aplikacji")
    parser.add_argument("--json", action="store_true", help="wypisz wynik w formacie JSON")
    parser.add_argument("--verbose", action="store_true", help="szczegolowe logi na konsoli")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="tworzy katalog danych i plik konfiguracyjny").set_defaults(
        func=cmd_init
    )

    sources = sub.add_parser("sources", help="zarzadzanie zrodlami dokumentow")
    sources_sub = sources.add_subparsers(dest="sources_command", required=True)
    sources_sub.add_parser("list", help="lista zrodel").set_defaults(func=cmd_sources_list)

    add_local = sources_sub.add_parser("add-local", help="dodaje katalog lokalny")
    add_local.add_argument("path")
    add_local.add_argument("--id")
    add_local.add_argument("--label")
    add_local.set_defaults(func=cmd_sources_add_local)

    add_sp = sources_sub.add_parser("add-sharepoint", help="dodaje zrodlo SharePoint")
    add_sp.add_argument("--site", required=True, help="adres witryny SharePoint")
    add_sp.add_argument("--library", required=True, help="nazwa biblioteki dokumentow")
    add_sp.add_argument("--tenant", required=True, help="identyfikator dzierzawy Entra ID")
    add_sp.add_argument("--client-id", required=True, help="identyfikator aplikacji Entra ID")
    add_sp.add_argument("--folder", help="katalog startowy w bibliotece")
    add_sp.add_argument("--id")
    add_sp.add_argument("--label")
    add_sp.add_argument(
        "--auth-flow", choices=["interactive", "device_code"], default="interactive"
    )
    add_sp.set_defaults(func=cmd_sources_add_sharepoint)

    test = sources_sub.add_parser("test", help="test polaczenia ze zrodlem")
    test.add_argument("id")
    test.set_defaults(func=cmd_sources_test)

    remove = sources_sub.add_parser("remove", help="usuwa zrodlo")
    remove.add_argument("id")
    remove.add_argument("--purge", action="store_true", help="usun takze dokumenty z indeksu")
    remove.set_defaults(func=cmd_sources_remove)

    demo = sub.add_parser("demo", help="generuje zbior demonstracyjny")
    demo.add_argument("--path", help="katalog docelowy")
    demo.add_argument("--force", action="store_true", help="nadpisz istniejacy zbior")
    demo.add_argument(
        "--register", action="store_true", help="dodaj zbior jako zrodlo o identyfikatorze demo"
    )
    demo.set_defaults(func=cmd_demo)

    index_cmd = sub.add_parser("index", help="uruchamia indeksowanie")
    index_cmd.add_argument("--source", action="append", help="ogranicz do wskazanego zrodla")
    index_cmd.add_argument("--full", action="store_true", help="pelne przeindeksowanie")
    index_cmd.add_argument(
        "--no-deletions", action="store_true", help="nie usuwaj dokumentow znikniętych ze zrodla"
    )
    index_cmd.set_defaults(func=cmd_index)

    search = sub.add_parser("search", help="wyszukuje w indeksie")
    search.add_argument("query")
    search.add_argument(
        "--mode", choices=[m.value for m in SearchMode], default=SearchMode.HYBRID.value
    )
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--offset", type=int, default=0)
    search.add_argument("--ext", action="append", help="filtr rozszerzenia, np. .pdf")
    search.add_argument("--source", action="append", help="filtr zrodla")
    search.set_defaults(func=cmd_search)

    report = sub.add_parser("report", help="raport pokrycia indeksu")
    report.add_argument("--json-out", help="zapisz raport do pliku JSON")
    report.add_argument("--csv-out", help="zapisz raport do pliku CSV")
    report.add_argument("--fast", action="store_true", help="nie laduj modelu embeddingow")
    report.set_defaults(func=cmd_report)

    sub.add_parser("doctor", help="diagnostyka srodowiska i indeksu").set_defaults(func=cmd_doctor)

    maintenance = sub.add_parser("maintenance", help="konserwacja indeksu")
    maintenance.add_argument(
        "action", choices=["check", "backup", "list-backups", "restore", "compact", "rebuild"]
    )
    maintenance.add_argument("--name", help="nazwa kopii przy przywracaniu")
    maintenance.add_argument(
        "--vectors-only", action="store_true", help="przebuduj tylko czesc wektorowa"
    )
    maintenance.set_defaults(func=cmd_maintenance)

    sub.add_parser("gui", help="uruchamia interfejs graficzny").set_defaults(func=cmd_gui)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    paths = _paths(args).ensure()
    configure_logging(
        log_file=paths.log_file,
        level="DEBUG" if args.verbose else "INFO",
        console=args.verbose,
    )
    try:
        return int(args.func(args))
    except FindDocsError as exc:
        print(f"Blad [{exc.code}]: {exc.user_message}", file=sys.stderr)
        log.error("cli.error", code=exc.code, error_type=type(exc).__name__)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("\nPrzerwano.", file=sys.stderr)
        return EXIT_ERROR
    except Exception as exc:  # noqa: BLE001 - CLI ma zawsze zwrocic czytelny komunikat
        print(f"Nieoczekiwany blad: {type(exc).__name__}: {exc}", file=sys.stderr)
        log.exception("cli.unexpected_error")
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["EXIT_ERROR", "EXIT_OK", "EXIT_USAGE", "build_parser", "main"]
