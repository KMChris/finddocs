"""Interfejs wiersza polecen dla administratorow i diagnostyki.

Uzytkownik koncowy nie musi korzystac z terminala. CLI istnieje po to, zeby
administrator mogl zaindeksowac zbior bez interfejsu graficznego, sprawdzic stan
indeksu, wyeksportowac raport i zdiagnozowac problem.
"""

from __future__ import annotations

import argparse
import contextlib
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
from finddocs.connectors.base import SourceConnector
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
        print("Nie skonfigurowano żadnego źródła.")
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
    if args.json:
        _print(rows, as_json=True)
    else:
        for row in rows:
            print(json.dumps(row, ensure_ascii=False))
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
    print(f"Dodano źródło lokalne: {source.source_id} ({root})")
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
    print(f"Dodano źródło SharePoint: {source.source_id}")
    print("Uwaga: pierwsze uzycie wymaga zalogowania. Uruchom 'finddocs sources test'.")
    return EXIT_OK


def cmd_sources_test(args: argparse.Namespace) -> int:
    config = _load(args)
    paths = _paths(args).ensure()
    source = config.source(args.id)
    if source.kind is SourceKind.LOCAL_DIR:
        from finddocs.connectors.local_dir import LocalDirectoryConnector

        connector: SourceConnector = LocalDirectoryConnector.from_config(source)
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
        print(f"Nie znaleziono źródła {args.id}.", file=sys.stderr)
        return EXIT_ERROR
    save_config(config, _paths(args).config_file)
    if args.purge:
        index = _open_index(config, load_provider=False)
        try:
            with index.db.transaction():
                removed = index.repository.delete_source(args.id)
            print(f"Usunieto {removed} dokumentów z indeksu.")
        finally:
            index.close()
    print(f"Usunieto źródło {args.id}.")
    return EXIT_OK


def cmd_demo(args: argparse.Namespace) -> int:
    from finddocs.demo import ensure_demo_corpus

    config = _load(args)
    paths = _paths(args).ensure()
    target = Path(args.path).expanduser().resolve() if args.path else paths.root / "demo"
    info = ensure_demo_corpus(target.parent if target.name == "demo" else target, force=args.force)
    print(f"Zbiór demonstracyjny: {info.root}")
    print(f"Plików: {info.files}")
    print(f"Numer rachunku testowego: {info.account_number} ({info.account_documents} dokumentów)")
    if args.register:
        source = SourceConfig(
            source_id="demo",
            kind=SourceKind.LOCAL_DIR,
            label="Zbiór demonstracyjny",
            local=LocalDirSourceSettings(root_path=str(info.root)),
            exclude_globs=["manifest.json"],
        )
        config = config.with_source(source)
        save_config(config, paths.config_file)
        print("Zarejestrowano źródło 'demo'.")
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
                f" | niezmienione {snapshot.unchanged} | błędy {snapshot.failed}"
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
        f"niezmienione {snapshot.unchanged}, pominięte {snapshot.skipped}, "
        f"błędy {snapshot.failed}, usunięte {snapshot.deleted}, "
        f"OCR {snapshot.ocr_documents} dokumentów / {snapshot.ocr_pages} stron"
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
    print(f"Znaleziono {label} {response.total_documents} dokumentów ({response.took_ms} ms)")
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
            size_mb = int(entry["rozmiar_bajty"]) // (1024 * 1024)
            print(f"{entry['nazwa']}  {size_mb} MB  {entry['utworzono']}")
        return EXIT_OK

    if args.action == "restore":
        if not args.name:
            print("Podaj nazwe kopii: --name", file=sys.stderr)
            return EXIT_USAGE
        restore_backup(paths, args.name)
        print("Przywrocono indeks z kopii.")
        return EXIT_OK

    index = _open_index(config, load_provider=args.action in {"check", "compact"})
    try:
        if args.action == "check":
            report = index.consistency()
            _print(report.to_dict(), as_json=args.json)
            return EXIT_OK if report.is_healthy else EXIT_ERROR
        if args.action == "compact":
            if index.vector_store is None:
                print("Indeks wektorowy nie jest dostępny.", file=sys.stderr)
                return EXIT_ERROR
            count = compact_vectors(index.repository, index.vector_store)
            print(f"Skompaktowano indeks wektorowy: {count} wektorów.")
            index.db.optimize()
            return EXIT_OK
        if args.action == "rebuild":
            count = mark_all_for_reindex(index.repository, only_vectors=args.vectors_only)
            print(f"Oznaczono {count} dokumentów do ponownego przetworzenia.")
            print("Uruchom 'finddocs index', żeby przebudować indeks.")
            return EXIT_OK
    finally:
        index.close()
    return EXIT_USAGE


def cmd_gui(args: argparse.Namespace) -> int:
    from finddocs.gui.app import main as gui_main

    return gui_main(["--data-dir", args.data_dir] if args.data_dir else [])


# --- modele embeddingow ---------------------------------------------------------


def _confirm(question: str) -> bool:
    """Pyta w konsoli o potwierdzenie. Brak wejscia oznacza odmowe."""
    try:
        answer = input(f"{question} [t/N] ")
    except (EOFError, OSError):
        return False
    return answer.strip().lower() in {"t", "tak", "y", "yes"}


def cmd_model_list(args: argparse.Namespace) -> int:
    from finddocs.providers.model_manifest import describe_models

    config = _load(args)
    active = config.embedding.model_key
    rows = describe_models()
    for row in rows:
        row["aktywny"] = row["klucz"] == active
    if args.json:
        _print(rows, as_json=True)
        return EXIT_OK
    for row in rows:
        marks = []
        if row["aktywny"]:
            marks.append("aktywny")
        marks.append("zainstalowany" if row["zainstalowany"] else "brak plików")
        print(f"{row['klucz']}  ({', '.join(marks)})")
        print(f"    {row['nazwa']}, wymiar {row['wymiar']}, licencja: {row['licencja']}")
        if row["katalog"]:
            print(f"    katalog: {row['katalog']}")
    print()
    print("Instalacja: finddocs model import [katalog albo repozytorium]")
    print("Przełączenie: finddocs model use <klucz>")
    return EXIT_OK


def _activate_model(args: argparse.Namespace, key: str) -> int:
    """Ustawia model jako aktywny i synchronizuje ustawienia z jego manifestem."""
    from finddocs.providers.model_manifest import LocalModelManifest, find_model_dir

    config = _load(args)
    extra = Path(config.embedding.model_path) if config.embedding.model_path else None
    directory = find_model_dir(key, extra)
    if directory is None:
        print(
            f"Model '{key}' nie jest zainstalowany. Lista: finddocs model list",
            file=sys.stderr,
        )
        return EXIT_ERROR
    manifest = LocalModelManifest.load(directory)
    changed = config.embedding.model_key != key
    config.embedding.model_key = key
    config.embedding.max_sequence_length = int(manifest.max_sequence_length or 512)
    config.embedding.query_prefix = manifest.query_prefix
    config.embedding.passage_prefix = manifest.passage_prefix
    config.embedding.normalize = bool(manifest.normalize)
    config.embedding.quantized = bool(manifest.quantized)
    save_config(config, _paths(args).config_file)
    print(f"Aktywny model: {key} ({directory})")
    if changed:
        print("Zmiana modelu wymaga przebudowy części semantycznej indeksu:")
        print("  finddocs maintenance rebuild --vectors-only")
        print("  finddocs index")
        print("Do tego czasu wyszukiwanie dokładne działa bez zmian.")
    return EXIT_OK


def cmd_model_import(args: argparse.Namespace) -> int:
    from finddocs.providers.model_manifest import DEFAULT_MODEL_KEY, KNOWN_MODELS
    from finddocs.providers.model_store import (
        ImportOptions,
        import_from_repo,
        import_local_model,
    )
    from finddocs.security.network import (
        DEFAULT_ALLOWLIST,
        EgressCategory,
        NetworkPolicy,
    )

    config = _load(args)
    paths = _paths(args).ensure()
    options = ImportOptions(
        name=args.name or "",
        quantize=not args.no_quantize,
        keep_fp32=args.keep_fp32,
        pooling=args.pooling or "",
        query_prefix=args.query_prefix,
        passage_prefix=args.passage_prefix,
        force=args.force,
    )

    from finddocs.providers.model_store import looks_like_repo_id

    source = args.source or ""
    local_dir = Path(source).expanduser() if source else None
    if local_dir is not None and local_dir.exists():
        imported = import_local_model(local_dir, options, paths=paths, progress=print)
    else:
        if source and not looks_like_repo_id(source):
            print(
                f"Źródło '{source}' nie jest ani istniejącym katalogiem, ani "
                "identyfikatorem repozytorium w formacie organizacja/nazwa.",
                file=sys.stderr,
            )
            return EXIT_ERROR
        repo = source or KNOWN_MODELS[DEFAULT_MODEL_KEY].repo
        if not source:
            print(f"Nie podano źródła. Zostanie pobrany model domyślny: {repo}")
        if not config.allow_model_download:
            hosts = ", ".join(DEFAULT_ALLOWLIST[EgressCategory.MODEL_DOWNLOAD])
            print("Pobranie modelu wymaga jednorazowego połączenia z Hugging Face.")
            print(f"Dozwolone adresy: {hosts}")
            if not args.yes and not _confirm("Zgadzasz się na to połączenie?"):
                print("Przerwano. Połączenie nie zostało nawiązane.", file=sys.stderr)
                return EXIT_ERROR
        policy = NetworkPolicy(enabled_categories={EgressCategory.MODEL_DOWNLOAD})
        imported = import_from_repo(repo, options, paths=paths, policy=policy, progress=print)

    print()
    print(f"Zaimportowano model: {imported.key}")
    print(f"  katalog: {imported.directory}")
    print(f"  wymiar: {imported.dimension}, pooling: {imported.pooling}")
    print(f"  pliki modelu: {', '.join(imported.model_files)}")
    if imported.query_prefix or imported.passage_prefix:
        print(
            f"  przedrostki: zapytanie '{imported.query_prefix}', treść '{imported.passage_prefix}'"
        )
    for note in imported.notes:
        print(f"  Uwaga: {note}")
    if args.use:
        print()
        return _activate_model(args, imported.key)
    print()
    print(f"Model pojawi się na liście w GUI. Aktywacja: finddocs model use {imported.key}")
    return EXIT_OK


def cmd_model_use(args: argparse.Namespace) -> int:
    return _activate_model(args, args.key)


def cmd_model_remove(args: argparse.Namespace) -> int:
    from finddocs.providers.model_store import remove_model

    config = _load(args)
    if not args.yes and not _confirm(f"Usunąć model '{args.key}' z dysku?"):
        print("Przerwano.", file=sys.stderr)
        return EXIT_ERROR
    removed = remove_model(args.key, paths=_paths(args))
    print(f"Usunięto katalog: {removed}")
    if config.embedding.model_key == args.key:
        print(
            "Uwaga: usunięty model był aktywny. Wyszukiwanie semantyczne nie będzie "
            "działać do czasu instalacji modelu (finddocs model import)."
        )
    return EXIT_OK


# --- parser argumentow ----------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="finddocs",
        description=f"{APP_NAME} {APP_VERSION}: lokalna wyszukiwarka dokumentów",
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    parser.add_argument("--data-dir", help="katalog danych aplikacji")
    parser.add_argument("--json", action="store_true", help="wypisz wynik w formacie JSON")
    parser.add_argument("--verbose", action="store_true", help="szczegolowe logi na konsoli")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="tworzy katalog danych i plik konfiguracyjny").set_defaults(
        func=cmd_init
    )

    sources = sub.add_parser("sources", help="zarzadzanie źródłami dokumentów")
    sources_sub = sources.add_subparsers(dest="sources_command", required=True)
    sources_sub.add_parser("list", help="lista źródeł").set_defaults(func=cmd_sources_list)

    add_local = sources_sub.add_parser("add-local", help="dodaje katalog lokalny")
    add_local.add_argument("path")
    add_local.add_argument("--id")
    add_local.add_argument("--label")
    add_local.set_defaults(func=cmd_sources_add_local)

    add_sp = sources_sub.add_parser("add-sharepoint", help="dodaje źródło SharePoint")
    add_sp.add_argument("--site", required=True, help="adres witryny SharePoint")
    add_sp.add_argument("--library", required=True, help="nazwa biblioteki dokumentów")
    add_sp.add_argument("--tenant", required=True, help="identyfikator dzierzawy Entra ID")
    add_sp.add_argument("--client-id", required=True, help="identyfikator aplikacji Entra ID")
    add_sp.add_argument("--folder", help="katalog startowy w bibliotece")
    add_sp.add_argument("--id")
    add_sp.add_argument("--label")
    add_sp.add_argument(
        "--auth-flow", choices=["interactive", "device_code"], default="interactive"
    )
    add_sp.set_defaults(func=cmd_sources_add_sharepoint)

    test = sources_sub.add_parser("test", help="test połączenia że źródłem")
    test.add_argument("id")
    test.set_defaults(func=cmd_sources_test)

    remove = sources_sub.add_parser("remove", help="usuwa źródło")
    remove.add_argument("id")
    remove.add_argument("--purge", action="store_true", help="usuń także dokumenty z indeksu")
    remove.set_defaults(func=cmd_sources_remove)

    demo = sub.add_parser("demo", help="generuje zbiór demonstracyjny")
    demo.add_argument("--path", help="katalog docelowy")
    demo.add_argument("--force", action="store_true", help="nadpisz istniejący zbiór")
    demo.add_argument(
        "--register", action="store_true", help="dodaj zbiór jako źródło o identyfikatorze demo"
    )
    demo.set_defaults(func=cmd_demo)

    index_cmd = sub.add_parser("index", help="uruchamia indeksowanie")
    index_cmd.add_argument("--source", action="append", help="ogranicz do wskazanego źródła")
    index_cmd.add_argument("--full", action="store_true", help="pełne przeindeksowanie")
    index_cmd.add_argument(
        "--no-deletions", action="store_true", help="nie usuwaj dokumentów znikniętych że źródła"
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
    search.add_argument("--source", action="append", help="filtr źródła")
    search.set_defaults(func=cmd_search)

    report = sub.add_parser("report", help="raport pokrycia indeksu")
    report.add_argument("--json-out", help="zapisz raport do pliku JSON")
    report.add_argument("--csv-out", help="zapisz raport do pliku CSV")
    report.add_argument("--fast", action="store_true", help="nie laduj modelu embeddingów")
    report.set_defaults(func=cmd_report)

    sub.add_parser("doctor", help="diagnostyka srodowiska i indeksu").set_defaults(func=cmd_doctor)

    maintenance = sub.add_parser("maintenance", help="konserwacja indeksu")
    maintenance.add_argument(
        "action", choices=["check", "backup", "list-backups", "restore", "compact", "rebuild"]
    )
    maintenance.add_argument("--name", help="nazwa kopii przy przywracaniu")
    maintenance.add_argument(
        "--vectors-only", action="store_true", help="przebuduj tylko część wektorowa"
    )
    maintenance.set_defaults(func=cmd_maintenance)

    model_cmd = sub.add_parser("model", help="zarzadzanie modelami embeddingów")
    model_sub = model_cmd.add_subparsers(dest="model_command", required=True)
    model_sub.add_parser("list", help="lista modeli wbudowanych i zainstalowanych").set_defaults(
        func=cmd_model_list
    )

    model_import = model_sub.add_parser(
        "import",
        help="instaluje model z katalogu albo z Hugging Face",
        description=(
            "Importuje model embeddingów. Źródłem może być katalog z eksportem ONNX, "
            "katalog z checkpointem HuggingFace (konwersja wymaga dodatku finddocs[export]) "
            "albo identyfikator repozytorium, np. sdadas/mmlw-retrieval-roberta-base. "
            "Bez argumentu pobierany jest model domyślny."
        ),
    )
    model_import.add_argument(
        "source", nargs="?", help="katalog z modelem albo repozytorium organizacja/nazwa"
    )
    model_import.add_argument("--name", help="własna nazwa modelu w magazynie")
    model_import.add_argument(
        "--force", action="store_true", help="nadpisz model o tej samej nazwie"
    )
    model_import.add_argument("--no-quantize", action="store_true", help="nie twórz wariantu INT8")
    model_import.add_argument(
        "--keep-fp32", action="store_true", help="zachowaj plik FP32 obok wariantu INT8"
    )
    model_import.add_argument(
        "--pooling", choices=["cls", "mean"], help="wymuś tryb poolingu zamiast wykrywania"
    )
    model_import.add_argument("--query-prefix", help="przedrostek zapytania, np. 'query: '")
    model_import.add_argument("--passage-prefix", help="przedrostek treści, np. 'passage: '")
    model_import.add_argument(
        "--use", action="store_true", help="od razu przełącz konfigurację na ten model"
    )
    model_import.add_argument(
        "--yes", action="store_true", help="nie pytaj o zgodę na połączenie sieciowe"
    )
    model_import.set_defaults(func=cmd_model_import)

    model_use = model_sub.add_parser("use", help="przełącza aktywny model")
    model_use.add_argument("key", help="klucz modelu z listy finddocs model list")
    model_use.set_defaults(func=cmd_model_use)

    model_remove = model_sub.add_parser("remove", help="usuwa zainstalowany model")
    model_remove.add_argument("key")
    model_remove.add_argument("--yes", action="store_true", help="nie pytaj o potwierdzenie")
    model_remove.set_defaults(func=cmd_model_remove)

    sub.add_parser("gui", help="uruchamia interfejs graficzny").set_defaults(func=cmd_gui)
    return parser


def _use_utf8_output() -> None:
    """Wymusza UTF-8 na wyjsciu konsoli.

    Polskie znaki w komunikatach sa poprawne, ale konsola Windows domyslnie
    uzywa strony kodowej cp852 albo cp1250 i czesc z nich zamienia na smieci.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            # Przekierowany strumien moze nie pozwolic na zmiane kodowania.
            with contextlib.suppress(OSError, ValueError):
                reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _use_utf8_output()
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
        print(f"Błąd [{exc.code}]: {exc.user_message}", file=sys.stderr)
        log.error("cli.error", code=exc.code, error_type=type(exc).__name__)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("\nPrzerwano.", file=sys.stderr)
        return EXIT_ERROR
    except Exception as exc:
        print(f"Nieoczekiwany błąd: {type(exc).__name__}: {exc}", file=sys.stderr)
        log.exception("cli.unexpected_error")
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["EXIT_ERROR", "EXIT_OK", "EXIT_USAGE", "build_parser", "main"]
