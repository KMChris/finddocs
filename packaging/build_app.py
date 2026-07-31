"""Budowanie aplikacji FindDocs do postaci katalogu z plikiem wykonywalnym.

Skrypt:

1. sprawdza srodowisko (interpreter, zaleznosci, obecnosc ikony);
2. czysci poprzednie wyniki;
3. uruchamia PyInstaller ze specyfikacja ``packaging/finddocs.spec``;
4. opcjonalnie dolacza model embeddingow w wersji ONNX;
5. wykonuje test dymny zbudowanej aplikacji (uruchomienie z ``--self-test``);
6. wypisuje rozmiar wyniku i sciezke artefaktu.

Uzycie:

    .venv/Scripts/python.exe packaging/build_app.py
    .venv/Scripts/python.exe packaging/build_app.py --with-model
    .venv/Scripts/python.exe packaging/build_app.py --console --skip-smoke-test
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGING = PROJECT_ROOT / "packaging"
SPEC = PACKAGING / "finddocs.spec"
BUILD_DIR = PACKAGING / "build"
DIST_DIR = PACKAGING / "output"
APP_NAME = "FindDocs"
DEFAULT_MODEL_KEY = "mmlw-retrieval-roberta-base"

REQUIRED_MODULES = ("PyInstaller", "PySide6", "onnxruntime", "faiss", "pypdfium2")

#: Dokumenty robocze zespolu. Nie trafiaja do pakietu dla uzytkownika, bo opisuja
#: proces powstawania produktu, a nie sam produkt.
INTERNAL_DOCS = ("spec.md", "requirements-matrix.md")


def _fail(message: str) -> None:
    print(f"BLAD: {message}", file=sys.stderr)
    raise SystemExit(1)


def check_environment() -> None:
    print("[1/6] Sprawdzanie srodowiska")
    for module in REQUIRED_MODULES:
        try:
            __import__(module)
        except ImportError:
            _fail(f"brakuje modulu {module}. Zainstaluj zaleznosci: pip install -e .[dev]")
    icon = PROJECT_ROOT / "src" / "finddocs" / "resources" / "finddocs.ico"
    if not icon.exists():
        print("    Ikona nie istnieje, generuje ja teraz")
        subprocess.run(  # noqa: S603
            [sys.executable, str(PROJECT_ROOT / "tools" / "make_icon.py")],
            check=True,
            cwd=str(PROJECT_ROOT),
        )
    print(f"    Python {sys.version.split()[0]}, interpreter {sys.executable}")


def clean() -> None:
    print("[2/6] Czyszczenie poprzednich wynikow")
    for directory in (BUILD_DIR, DIST_DIR):
        if directory.exists():
            shutil.rmtree(directory, ignore_errors=True)


def find_model(model_key: str) -> Path | None:
    candidates = [
        PROJECT_ROOT / "models" / model_key / "onnx",
        PROJECT_ROOT / "models" / model_key,
    ]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "FindDocs" / "models" / model_key / "onnx")
    for candidate in candidates:
        if (candidate / "manifest.json").exists():
            return candidate
    return None


def run_pyinstaller(*, console: bool, model_dir: Path | None, full_precision: bool = False) -> Path:
    print("[3/6] Uruchamianie PyInstaller")
    env = dict(os.environ)
    env["FINDDOCS_BUILD_CONSOLE"] = "1" if console else "0"
    if model_dir is not None:
        env["FINDDOCS_BUNDLE_MODEL"] = str(model_dir)
        env["FINDDOCS_BUNDLE_QUANTIZED"] = "0" if full_precision else "1"
        wariant = "FP32 i INT8" if full_precision else "INT8"
        print(f"    Dolaczam model ({wariant}): {model_dir}")
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(SPEC),
        "--noconfirm",
        "--clean",
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BUILD_DIR),
    ]
    started = time.monotonic()
    result = subprocess.run(command, cwd=str(PROJECT_ROOT), env=env, check=False)  # noqa: S603
    if result.returncode != 0:
        _fail(f"PyInstaller zakonczyl prace kodem {result.returncode}")
    print(f"    Gotowe w {time.monotonic() - started:.1f} s")
    return DIST_DIR / APP_NAME


def copy_extra_files(app_dir: Path) -> None:
    print("[4/6] Kopiowanie dodatkowych plikow")
    for name in ("LICENSE", "README.md"):
        source = PROJECT_ROOT / name
        if source.exists():
            shutil.copy2(source, app_dir / name)
    docs_source = PROJECT_ROOT / "docs"
    if docs_source.is_dir():
        target = app_dir / "docs"
        shutil.copytree(
            docs_source,
            target,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(*INTERNAL_DOCS),
        )
    third_party = PROJECT_ROOT / "docs" / "licencje.md"
    if third_party.exists():
        shutil.copy2(third_party, app_dir / "LICENCJE-KOMPONENTOW.md")


def smoke_test(app_dir: Path) -> bool:
    print("[5/6] Test dymny zbudowanej aplikacji")
    executable = app_dir / f"{APP_NAME}.exe"
    if not executable.exists():
        _fail(f"nie znaleziono pliku wykonywalnego {executable}")
    temp_home = BUILD_DIR / "smoke-home"
    temp_home.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["FINDDOCS_HOME"] = str(temp_home)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["FINDDOCS_NO_DIALOG"] = "1"
    try:
        result = subprocess.run(  # noqa: S603
            [str(executable), "--self-test"],
            capture_output=True,
            timeout=240,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired:
        print("    Test dymny przekroczyl limit czasu")
        return False
    finally:
        error_file = temp_home / "logs" / "blad-uruchomienia.txt"
        if error_file.exists():
            print("    Zapisany blad uruchomienia:")
            print(error_file.read_text(encoding="utf-8", errors="replace")[-3000:])
    if result.returncode != 0:
        print(f"    Test dymny zakonczyl sie kodem {result.returncode}")
        print(result.stdout.decode("utf-8", "replace")[-2000:])
        print(result.stderr.decode("utf-8", "replace")[-3000:])
        return False
    print("    Aplikacja uruchomila sie i zamknela poprawnie")
    return True


def summarize(app_dir: Path) -> None:
    print("[6/6] Podsumowanie")
    total = sum(p.stat().st_size for p in app_dir.rglob("*") if p.is_file())
    files = sum(1 for p in app_dir.rglob("*") if p.is_file())
    print(f"    Katalog aplikacji: {app_dir}")
    print(f"    Plikow: {files}, rozmiar: {total / (1024 * 1024):.0f} MB")
    print(f"    Plik wykonywalny: {app_dir / (APP_NAME + '.exe')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Buduje aplikacje FindDocs")
    parser.add_argument(
        "--with-model", action="store_true", help="dolacz model embeddingow do pakietu"
    )
    parser.add_argument(
        "--full-precision-model",
        action="store_true",
        help="dolacz takze wagi FP32 modelu, pakiet urosnie o okolo 470 MB",
    )
    parser.add_argument("--model-key", default=DEFAULT_MODEL_KEY)
    parser.add_argument(
        "--console", action="store_true", help="wariant z konsola, tylko do diagnostyki"
    )
    parser.add_argument("--skip-smoke-test", action="store_true")
    args = parser.parse_args(argv)

    check_environment()
    clean()

    model_dir: Path | None = None
    if args.with_model:
        model_dir = find_model(args.model_key)
        if model_dir is None:
            _fail(
                f"nie znaleziono modelu {args.model_key}. Uruchom najpierw "
                "tools/export_model_onnx.py albo pomin opcje --with-model."
            )

    app_dir = run_pyinstaller(
        console=args.console, model_dir=model_dir, full_precision=args.full_precision_model
    )
    copy_extra_files(app_dir)

    ok = True
    if not args.skip_smoke_test:
        ok = smoke_test(app_dir)
    summarize(app_dir)
    if not ok:
        print("Test dymny nie powiodl sie. Pakiet powstal, ale wymaga sprawdzenia.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
