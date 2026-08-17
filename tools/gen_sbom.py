"""Generator SBOM w formacie CycloneDX oraz zestawienia licencji.

Wykaz komponentow powstaje z zaleznosci zadeklarowanych w plikach
``requirements*.txt`` rozwinietych o zaleznosci przechodnie z metadanych
``Requires-Dist``. Wersje i licencje czytamy z pakietow zainstalowanych
w biezacym srodowisku, ale sama obecnosc pakietu w ``.venv`` nie wystarczy:
narzedzie doinstalowane doraznie nie jest komponentem produktu.
Do tego dochodza modele i komponenty zewnetrzne z listy ``EXTERNAL``.

Skrypt zapisuje:

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

# packaging jest wymaganiem onnxruntime i faiss-cpu, czyli zawsze jest
# w srodowisku razem z zaleznosciami podstawowymi.
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from finddocs.version import APP_NAME, APP_VERSION  # noqa: E402

#: Pliki z zaleznosciami, od ktorych zaczyna sie przejscie po grafie.
#: Wpisy ``-r`` wewnatrz plikow sa rozwijane, wiec wystarcza korzenie.
REQUIREMENT_FILES: tuple[str, ...] = (
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-ocr.txt",
    "requirements-export.txt",
    "requirements-pgvector.txt",
    "requirements-gpu-dml.txt",
    "requirements-gpu-cuda.txt",
)

#: Zastosowanie pakietu w aplikacji. Klucz to znormalizowana nazwa pakietu.
USAGE: dict[str, str] = {
    "pyside6": "interfejs graficzny",
    "pyside6-essentials": "interfejs graficzny",
    "pyside6-addons": "interfejs graficzny",
    "shiboken6": "warstwa wiazan Qt dla Pythona",
    "pypdfium2": "odczyt i rasteryzacja PDF",
    "python-docx": "odczyt plikow DOCX",
    "python-pptx": "odczyt plikow PPTX",
    "openpyxl": "odczyt plikow XLSX",
    "xlrd": "odczyt starych plikow XLS",
    "olefile": "odczyt kontenerow OLE (DOC, MSG)",
    "py7zr": "odczyt archiwow 7z",
    "rarfile": "odczyt archiwow RAR",
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
    "rapidocr": "silnik OCR (opcjonalny)",
    "rapidocr-onnxruntime": "silnik OCR (opcjonalny, starsze wydania)",
    "easyocr": "silnik OCR (opcjonalny)",
    "psycopg": "klient PostgreSQL dla magazynu wektorow pgvector (opcjonalny)",
    "psycopg-binary": "biblioteka libpq dla klienta psycopg (opcjonalna)",
    "pytest": "testy (narzedzie deweloperskie)",
    "mypy": "kontrola typow (narzedzie deweloperskie)",
    "ruff": "linting i formatowanie (narzedzie deweloperskie)",
}

#: Pakiety uzywane wylacznie podczas testow i kontroli jakosci.
DEV_ONLY = {
    "pytest",
    "pytest-qt",
    "pytest-cov",
    "pygments",
    "mypy",
    "mypy-extensions",
    "ruff",
    "coverage",
    "iniconfig",
    "pluggy",
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
        downloaded="tak, jednorazowo przez uzytkownika",
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


@dataclass(slots=True)
class Resolution:
    """Wynik przejscia po zadeklarowanych zaleznosciach."""

    #: Zainstalowane pakiety osiagalne z plikow requirements*.txt.
    reachable: set[str] = field(default_factory=set)
    #: Zadeklarowane pakiety, ktorych nie ma w srodowisku (np. torch z eksportu).
    missing: set[str] = field(default_factory=set)
    #: Wpisy Requires-Dist, ktorych nie dalo sie sparsowac.
    broken: list[str] = field(default_factory=list)


def _installed_distributions() -> dict[str, Distribution]:
    """Zainstalowane pakiety pod znormalizowanymi nazwami."""
    found: dict[str, Distribution] = {}
    for dist in distributions():
        name = str(dist.metadata["Name"] or "").strip()
        if name:
            found.setdefault(canonicalize_name(name), dist)
    return found


def _requirement_applies(requirement: Requirement, extras: frozenset[str]) -> bool:
    """Czy wymaganie dotyczy tego srodowiska i tych dodatkow.

    Marker pyta albo o srodowisko (``sys_platform == 'win32'``), albo o dodatek
    (``extra == "export"``). Sprawdzamy kontekst bez dodatku i po jednym
    kontekscie na kazdy zadany dodatek; wystarczy, ze pasuje ktorykolwiek.
    """
    if requirement.marker is None:
        return True
    contexts: list[dict[str, str]] = [{"extra": ""}]
    contexts += [{"extra": extra} for extra in sorted(extras)]
    return any(requirement.marker.evaluate(context) for context in contexts)


def read_requirements(path: Path, seen: set[Path] | None = None) -> list[str]:
    """Czyta plik requirements i rozwija wpisy ``-r`` na miejscu.

    Obsluguje tylko to, czego uzywaja pliki projektu: komentarze, puste linie
    i dolaczanie innego pliku. Opcje pipa (``--index-url`` i podobne) sa
    pomijane, bo nie opisuja komponentu.
    """
    resolved = path.resolve()
    seen = seen if seen is not None else set()
    if resolved in seen or not resolved.is_file():
        return []
    seen.add(resolved)

    entries: list[str] = []
    for line in resolved.read_text(encoding="utf-8").splitlines():
        text = line.split(" #", 1)[0].strip()
        if not text or text.startswith("#"):
            continue
        if text.startswith(("-r", "--requirement")):
            target = text.split(maxsplit=1)[1].strip() if " " in text else ""
            if target:
                entries += read_requirements(resolved.parent / target, seen)
            continue
        if text.startswith("-"):
            continue
        entries.append(text)
    return entries


def resolve_declared(installed: dict[str, Distribution]) -> Resolution:
    """Przechodzi graf zaleznosci zadeklarowanych w plikach requirements*.txt.

    Zaczynamy od wszystkich plikow z ``REQUIREMENT_FILES``, a potem schodzimy
    po ``Requires-Dist`` zainstalowanych pakietow. Wezlem jest para (pakiet,
    zadane dodatki), bo ten sam pakiet moze byc odwiedzony raz bez dodatkow,
    a raz z dodatkiem, ktory doklada wlasne zaleznosci.
    """
    result = Resolution()
    queue: list[tuple[str, frozenset[str]]] = []
    for name in REQUIREMENT_FILES:
        queue += [(raw, frozenset()) for raw in read_requirements(PROJECT_ROOT / name)]

    visited: set[tuple[str, frozenset[str]]] = set()
    while queue:
        raw, context = queue.pop()
        try:
            requirement = Requirement(raw)
        except InvalidRequirement:
            result.broken.append(raw)
            continue
        if not _requirement_applies(requirement, context):
            continue
        name = canonicalize_name(requirement.name)
        extras = frozenset(canonicalize_name(extra) for extra in requirement.extras)
        if (name, extras) in visited:
            continue
        visited.add((name, extras))
        dist = installed.get(name)
        if dist is None:
            result.missing.add(name)
            continue
        result.reachable.add(name)
        queue += [(entry, extras) for entry in dist.metadata.get_all("Requires-Dist") or []]
    return result


def collect_components() -> tuple[list[Component], Resolution, list[str]]:
    """Zbiera pakiety osiagalne z zaleznosci zadeklarowanych w requirements*.txt.

    Zwraca komponenty, wynik przejscia po grafie oraz nazwy pakietow obecnych
    w srodowisku, ale nieosiagalnych z tego grafu. Sieroty biora sie z recznych
    instalacji i z pakietow, ktore przestaly byc czyjas zaleznoscia, a pip ich
    nie usunal. Do wykazu komponentow produktu nie naleza.
    """
    installed = _installed_distributions()
    resolution = resolve_declared(installed)
    components: list[Component] = []
    for key, dist in installed.items():
        if key not in resolution.reachable:
            continue
        name = str(dist.metadata["Name"] or "").strip()
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
    orphans = sorted(set(installed) - resolution.reachable)
    return components, resolution, orphans


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
        "Wykaz obejmuje zaleznosci zadeklarowane w plikach `requirements*.txt` wraz",
        "z zaleznosciami przechodnimi. Pakiet doinstalowany doraznie do srodowiska",
        "deweloperskiego nie jest komponentem produktu i nie wchodzi na te liste.",
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
        "Potrzebne tylko do testow i kontroli jakosci, aplikacja ich nie uzywa.",
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

    components, resolution, orphans = collect_components()
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
    if orphans:
        print(
            f"Uwaga: pominieto {len(orphans)} pakietow spoza zaleznosci projektu: "
            f"{', '.join(orphans)}"
        )
    if resolution.missing:
        print(
            "Uwaga: zadeklarowane, ale niezainstalowane, wiec bez wpisu w wykazie: "
            f"{', '.join(sorted(resolution.missing))}"
        )
    if resolution.broken:
        print(f"Uwaga: nieczytelne wpisy Requires-Dist: {', '.join(resolution.broken)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
