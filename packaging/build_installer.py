"""Budowanie instalatora Windows przy uzyciu Inno Setup.

Skrypt wykrywa kompilator ``iscc.exe``, sprawdza, czy aplikacja zostala wczesniej
zbudowana, i uruchamia kompilacje instalatora. Gdy Inno Setup nie jest zainstalowany,
skrypt wypisuje dokladna instrukcje zamiast cicho konczyc prace.

Uzycie:

    .venv/Scripts/python.exe packaging/build_installer.py
    .venv/Scripts/python.exe packaging/build_installer.py --build-app --with-model
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGING = PROJECT_ROOT / "packaging"
SCRIPT = PACKAGING / "finddocs.iss"
APP_DIR = PACKAGING / "output" / "FindDocs"
OUTPUT_DIR = PACKAGING / "output"

#: Typowe lokalizacje kompilatora. Instalacja przez ``winget --scope user``
#: trafia do profilu uzytkownika, wiec sprawdzamy takze LOCALAPPDATA.
ISCC_CANDIDATES = (
    str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe"),
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
    r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
)

INSTALL_HINT = """
Nie znaleziono kompilatora Inno Setup (ISCC.exe).

Zainstaluj Inno Setup 6 jedna z metod:

  winget install --id JRSoftware.InnoSetup --source winget
  choco install innosetup

albo pobierz instalator ze strony https://jrsoftware.org/isdl.php
(licencja Inno Setup License, dopuszcza uzycie komercyjne).

Po instalacji uruchom ten skrypt ponownie. Mozesz tez wskazac sciezke recznie:

  .venv/Scripts/python.exe packaging/build_installer.py --iscc "C:/sciezka/ISCC.exe"
"""


def find_iscc(explicit: str = "") -> Path | None:
    if explicit:
        candidate = Path(explicit)
        return candidate if candidate.is_file() else None
    found = shutil.which("iscc") or shutil.which("ISCC")
    if found:
        return Path(found)
    for path in ISCC_CANDIDATES:
        if Path(path).is_file():
            return Path(path)
    return None


def build_app(with_model: bool) -> None:
    command = [sys.executable, str(PACKAGING / "build_app.py")]
    if with_model:
        command.append("--with-model")
    result = subprocess.run(command, cwd=str(PROJECT_ROOT), check=False)  # noqa: S603
    if result.returncode not in (0, 2):
        raise SystemExit("Budowanie aplikacji nie powiodlo sie.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Buduje instalator Windows dla FindDocs")
    parser.add_argument("--iscc", default="", help="sciezka do ISCC.exe")
    parser.add_argument(
        "--build-app", action="store_true", help="najpierw zbuduj aplikacje przez PyInstaller"
    )
    parser.add_argument("--with-model", action="store_true", help="dolacz model do pakietu")
    args = parser.parse_args(argv)

    if args.build_app:
        build_app(args.with_model)

    if not APP_DIR.is_dir():
        print(
            "Nie znaleziono zbudowanej aplikacji. Uruchom najpierw:\n"
            "  .venv/Scripts/python.exe packaging/build_app.py",
            file=sys.stderr,
        )
        return 1

    iscc = find_iscc(args.iscc)
    if iscc is None:
        print(INSTALL_HINT, file=sys.stderr)
        return 3

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Kompilator: {iscc}")
    result = subprocess.run(  # noqa: S603
        [str(iscc), str(SCRIPT)],
        cwd=str(PACKAGING),
        check=False,
        env=dict(os.environ),
    )
    if result.returncode != 0:
        print(f"Inno Setup zakonczyl prace kodem {result.returncode}", file=sys.stderr)
        return result.returncode

    installers = sorted(OUTPUT_DIR.glob("FindDocs-*-instalator.exe"))
    if installers:
        target = installers[-1]
        size = target.stat().st_size / (1024 * 1024)
        print(f"Instalator: {target} ({size:.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
