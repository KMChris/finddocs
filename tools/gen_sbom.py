"""Generator SBOM w formacie CycloneDX oraz zestawienia licencji.

Skrypt czyta metadane pakietow zainstalowanych w biezacym srodowisku, uzupelnia je
o informacje o modelach i komponentach zewnetrznych, a nastepnie zapisuje:

* ``sbom.cdx.json``  Software Bill of Materials w formacie CycloneDX 1.5;
* ``docs/licencje.md``  czytelna tabela z licencjami i zrodlami.

Uzycie:

    .venv/Scripts/python.exe tools/gen_sbom.py
    .venv/Scripts/python.exe tools/gen_sbom.py --output sbom.cdx.json --docs docs/licencje.md
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from importlib.metadata import Distribution, distributions
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_NAME = "FindDocs"
APP_VERSION = "0.1.0"

#: Zastosowanie pakietu w aplikacji. Klucz to znormalizowana nazwa pakietu.
USAGE: dict[str, str] = {
    "pyside6": "interfejs graficzny",
    "pyside6-essentials": "interfejs graficzny",
    "pyside6-addons": "interfejs graficzny",
    "shiboken6": "warstwa wiazan Qt dla Pythona",
    "pypdfium2": "odczyt i rasteryzacja PDF",
    "python-docx": "odczyt plikow DOCX",
    "openpyxl": "odczyt plikow XLSX",
    "xlrd": "odczyt starych plikow XLS",
    "olefile": "odczyt kontenerow OLE (DOC, MSG)",
    "pillow": "obsluga obrazow i przygotowanie stron do OCR",
    "charset-normalizer": "wykrywanie kodowania plikow tekstowych",
    "numpy": "operacje na wektorach",
    "onnxruntime": "uruchamianie modelu embeddingow na CPU",
    "tokenizers": "tokenizacja tekstu dla modelu embeddingow",
    "faiss-cpu": "indeks wektorowy",
    "httpx": "klient HTTP dla Microsoft Graph",
    "msal": "uwierzytelnienie w Microsoft Entra ID",
    "keyring": "dostep do Menedzera poswiadczen Windows",
    "pywin32": "DPAPI, automatyzacja Office przez COM",
    "structlog": "strukturalne logowanie",
    "rapidocr-onnxruntime": "silnik OCR (opcjonalny)",
    "easyocr": "silnik OCR (opcjonalny)",
    "pyinstaller": "budowanie pakietu aplikacji (narzedzie deweloperskie)",
    "pytest": "testy (narzedzie deweloperskie)",
    "mypy": "kontrola typow (narzedzie deweloperskie)",
    "ruff": "linting i formatowanie (narzedzie deweloperskie)",
}

#: Pakiety uzywane wylacznie podczas budowania i testow.
DEV_ONLY = {
    "pyinstaller",
    "pyinstaller-hooks-contrib",
    "pytest",
    "pytest-qt",
    "pytest-cov",
    "mypy",
    "mypy-extensions",
    "ruff",
    "coverage",
    "iniconfig",
    "pluggy",
    "altgraph",
    "pefile",
    "types-openpyxl",
    "types-pywin32",
}


@dataclass(slots=True)
class ExternalComponent:
    """Komponent, ktory nie jest pakietem Pythona."""

    name: str
    version: str
    kind: str
    license_name: str
    source: str
    usage: str
    downloaded: str
    bundled: bool = False
    notes: str = ""


EXTERNAL: list[ExternalComponent] = [
    ExternalComponent(
        name="mmlw-retrieval-roberta-base",
        version="2023-12-26",
        kind="machine-learning-model",
        license_name="Apache-2.0",
        source="https://huggingface.co/sdadas/mmlw-retrieval-roberta-base",
        usage="model embeddingow do wyszukiwania semantycznego po polsku",
        downloaded="tak, jednorazowo przez uzytkownika albo dolaczony do instalatora",
        notes="Eksportowany do ONNX skryptem tools/export_model_onnx.py, wariant INT8.",
    ),
    ExternalComponent(
        name="SQLite (biblioteka wbudowana w Pythona)",
        version="3.42.0",
        kind="library",
        license_name="Public Domain",
        source="https://www.sqlite.org/",
        usage="baza metadanych i indeks pelnotekstowy FTS5",
        downloaded="nie, czesc dystrybucji Pythona",
        bundled=True,
        notes="Wymagana obsluga FTS5 oraz skladni WITH ... AS MATERIALIZED (3.35 lub nowszy).",
    ),
    ExternalComponent(
        name="PDFium",
        version="dostarczany przez pypdfium2",
        kind="library",
        license_name="BSD-3-Clause i Apache-2.0",
        source="https://pdfium.googlesource.com/pdfium/",
        usage="silnik odczytu PDF uzywany przez pypdfium2",
        downloaded="nie, dolaczony do pakietu pypdfium2",
        bundled=True,
    ),
    ExternalComponent(
        name="Tesseract OCR",
        version="5.x (opcjonalnie)",
        kind="application",
        license_name="Apache-2.0",
        source="https://github.com/UB-Mannheim/tesseract/wiki",
        usage="opcjonalny silnik OCR o najlepszej jakosci dla jezyka polskiego",
        downloaded="nie, instalowany osobno przez administratora",
        notes="Model jezyka polskiego 'pol' na licencji Apache-2.0.",
    ),
    ExternalComponent(
        name="Inno Setup",
        version="6.x",
        kind="application",
        license_name="Inno Setup License (dopuszcza uzycie komercyjne)",
        source="https://jrsoftware.org/isinfo.php",
        usage="budowanie instalatora Windows",
        downloaded="nie, narzedzie deweloperskie",
    ),
]


@dataclass(slots=True)
class Component:
    """Pozycja SBOM."""

    name: str
    version: str
    license_name: str
    source: str
    usage: str
    scope: str
    kind: str = "library"
    author: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def _normalize(name: str) -> str:
    return name.lower().replace("_", "-")


def _license_of(dist: Distribution) -> str:
    metadata = dist.metadata
    classifiers = metadata.get_all("Classifier") or []
    for classifier in classifiers:
        if classifier.startswith("License :: OSI Approved :: "):
            return classifier.rsplit("::", 1)[-1].strip()
        if classifier.startswith("License :: "):
            value = classifier.rsplit("::", 1)[-1].strip()
            if value.lower() not in {"osi approved"}:
                return value
    raw = metadata.get("License")
    if raw and raw != "UNKNOWN" and len(raw) < 120:
        return raw.strip()
    expression = metadata.get("License-Expression")
    if expression:
        return str(expression).strip()
    return "nieokreslona"


def _source_of(dist: Distribution) -> str:
    metadata = dist.metadata
    for key in ("Home-page", "Download-URL"):
        value = metadata.get(key)
        if value and value != "UNKNOWN":
            return str(value)
    for entry in metadata.get_all("Project-URL") or []:
        label, _, url = str(entry).partition(",")
        if label.strip().lower() in {"homepage", "source", "repository", "documentation"}:
            return url.strip()
    return f"https://pypi.org/project/{dist.metadata['Name']}/"


def collect_components() -> list[Component]:
    """Zbiera pakiety Pythona z biezacego srodowiska."""
    components: list[Component] = []
    for dist in distributions():
        name = str(dist.metadata["Name"] or "").strip()
        if not name or _normalize(name) == "finddocs":
            continue
        key = _normalize(name)
        components.append(
            Component(
                name=name,
                version=str(dist.version),
                license_name=_license_of(dist),
                source=_source_of(dist),
                usage=USAGE.get(key, "zaleznosc posrednia"),
                scope="deweloperska" if key in DEV_ONLY else "runtime",
                author=str(dist.metadata.get("Author") or ""),
            )
        )
    components.sort(key=lambda c: c.name.lower())
    return components


def build_cyclonedx(components: list[Component]) -> dict[str, Any]:
    """Buduje dokument CycloneDX 1.5."""
    entries: list[dict[str, Any]] = []
    for component in components:
        entry: dict[str, Any] = {
            "type": "library",
            "name": component.name,
            "version": component.version,
            "purl": f"pkg:pypi/{_normalize(component.name)}@{component.version}",
            "scope": "required" if component.scope == "runtime" else "optional",
            "licenses": [{"license": {"name": component.license_name}}],
            "externalReferences": [{"type": "website", "url": component.source}],
            "properties": [
                {"name": "finddocs:usage", "value": component.usage},
                {"name": "finddocs:scope", "value": component.scope},
            ],
        }
        if component.author:
            entry["author"] = component.author
        entries.append(entry)

    for external in EXTERNAL:
        entries.append(
            {
                "type": external.kind,
                "name": external.name,
                "version": external.version,
                "licenses": [{"license": {"name": external.license_name}}],
                "externalReferences": [{"type": "website", "url": external.source}],
                "properties": [
                    {"name": "finddocs:usage", "value": external.usage},
                    {"name": "finddocs:downloaded", "value": external.downloaded},
                    {"name": "finddocs:bundled", "value": str(external.bundled).lower()},
                ],
            }
        )

    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "tools": [{"vendor": "FindDocs", "name": "tools/gen_sbom.py", "version": APP_VERSION}],
            "component": {
                "type": "application",
                "name": APP_NAME,
                "version": APP_VERSION,
                "description": "Lokalna wyszukiwarka dokumentow korporacyjnych",
            },
            "properties": [
                {"name": "finddocs:python", "value": sys.version.split()[0]},
                {"name": "finddocs:platform", "value": sys.platform},
            ],
        },
        "components": entries,
    }


def build_markdown(components: list[Component]) -> str:
    """Buduje czytelne zestawienie licencji."""
    runtime = [c for c in components if c.scope == "runtime"]
    dev = [c for c in components if c.scope == "deweloperska"]

    lines: list[str] = [
        "# Licencje komponentow",
        "",
        f"Dokument wygenerowany automatycznie przez `tools/gen_sbom.py` dla wersji {APP_VERSION}.",
        "Odpowiadajacy mu plik SBOM w formacie CycloneDX to `sbom.cdx.json`.",
        "",
        "Wszystkie komponenty dzialaja lokalnie. Zaden z nich nie wysyla tresci dokumentow",
        "ani zapytan poza komputer uzytkownika w konfiguracji domyslnej.",
        "",
        "## Komponenty uruchomieniowe",
        "",
        "| Komponent | Wersja | Licencja | Zastosowanie | Zrodlo |",
        "| --- | --- | --- | --- | --- |",
    ]
    for component in runtime:
        lines.append(
            f"| {component.name} | {component.version} | {component.license_name} | "
            f"{component.usage} | {component.source} |"
        )

    lines += [
        "",
        "## Komponenty zewnetrzne i modele",
        "",
        "| Komponent | Wersja | Licencja | Zastosowanie | Pobierany | Zrodlo |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for external in EXTERNAL:
        lines.append(
            f"| {external.name} | {external.version} | {external.license_name} | "
            f"{external.usage} | {external.downloaded} | {external.source} |"
        )

    lines += [
        "",
        "## Narzedzia deweloperskie",
        "",
        "Nie trafiaja do pakietu instalacyjnego.",
        "",
        "| Komponent | Wersja | Licencja |",
        "| --- | --- | --- |",
    ]
    for component in dev:
        lines.append(f"| {component.name} | {component.version} | {component.license_name} |")

    unclear = [c for c in components if c.license_name == "nieokreslona"]
    lines += ["", "## Komponenty wymagajace weryfikacji licencji", ""]
    if unclear:
        lines.append(
            "Ponizsze pakiety nie deklaruja licencji w metadanych. Przed wdrozeniem "
            "sprawdz ich repozytoria."
        )
        lines.append("")
        for component in unclear:
            lines.append(f"- {component.name} {component.version}: {component.source}")
    else:
        lines.append("Wszystkie zainstalowane pakiety deklaruja licencje w metadanych.")

    lines += [
        "",
        "## Komponenty swiadomie odrzucone",
        "",
        "| Komponent | Licencja | Powod odrzucenia | Zastosowane rozwiazanie |",
        "| --- | --- | --- | --- |",
        "| PyMuPDF | AGPL-3.0 albo komercyjna | AGPL jest trudna do przyjecia "
        "w srodowisku korporacyjnym | pypdfium2 (Apache-2.0 i BSD-3-Clause) |",
        "| extract-msg | GPL-3.0 | GPL wymusza warunki na calej aplikacji | "
        "wlasny czytnik MSG oparty na olefile (BSD) |",
        "| PyQt6 | GPL-3.0 albo komercyjna | wymagalaby zakupu licencji komercyjnej | "
        "PySide6 (LGPL-3.0) |",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generuje SBOM i zestawienie licencji")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "sbom.cdx.json")
    parser.add_argument("--docs", type=Path, default=PROJECT_ROOT / "docs" / "licencje.md")
    args = parser.parse_args(argv)

    components = collect_components()
    document = build_cyclonedx(components)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")

    args.docs.parent.mkdir(parents=True, exist_ok=True)
    args.docs.write_text(build_markdown(components), encoding="utf-8")

    runtime = sum(1 for c in components if c.scope == "runtime")
    print(f"Zapisano {args.output} ({len(components)} pakietow, {runtime} uruchomieniowych)")
    print(f"Zapisano {args.docs}")
    unclear = [c.name for c in components if c.license_name == "nieokreslona"]
    if unclear:
        print(f"Uwaga: bez zadeklarowanej licencji: {', '.join(unclear)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
