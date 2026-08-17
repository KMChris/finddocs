"""Eksport modelu embeddingow z formatu HuggingFace do ONNX.

Skrypt uruchamiamy raz, w srodowisku deweloperskim, ktore ma zainstalowany torch
i transformers. Runtime aplikacji korzysta juz tylko z onnxruntime i tokenizers,
dzieki czemu srodowisko na stanowisku jest o rzad wielkosci mniejsze.

Uzycie:

    python tools/export_model_onnx.py models/mmlw-retrieval-roberta-base \
        --output models/mmlw-retrieval-roberta-base/onnx --quantize

Wlasciwa logika konwersji mieszka w module
``src/finddocs/providers/model_export.py``, wspolnym z poleceniem
``finddocs model import``. Skrypt laduje ten plik bezposrednio po sciezce,
zeby dzialac takze w srodowisku bez zaleznosci uruchomieniowych aplikacji
(globalny Python z torch nie ma np. structlog ani httpx).

Skrypt zapisuje obok modelu plik ``manifest.json`` z suma kontrolna, wymiarem
wektora, licencja i informacja o pochodzeniu.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO_SRC = Path(__file__).resolve().parents[1] / "src"


def _load_model_export() -> ModuleType:
    """Laduje modul konwersji bez wykonywania __init__ pakietu providers."""
    module_path = REPO_SRC / "finddocs" / "providers" / "model_export.py"
    if module_path.exists():
        if str(REPO_SRC) not in sys.path:
            sys.path.insert(0, str(REPO_SRC))
        spec = importlib.util.spec_from_file_location("finddocs_model_export", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        # Wpis w sys.modules jest konieczny przed exec_module: dataclasses
        # rozwiazuje adnotacje przez sys.modules[cls.__module__].
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    from finddocs.providers import model_export

    return model_export


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Eksport modelu embeddingow do ONNX")
    parser.add_argument("model_dir", type=Path, help="katalog modelu HuggingFace")
    parser.add_argument("--output", type=Path, default=None, help="katalog docelowy")
    parser.add_argument("--opset", type=int, default=14)
    parser.add_argument("--quantize", action="store_true", help="dodatkowo zapisz wersje INT8")
    parser.add_argument("--pooling", choices=["cls", "mean"], default="cls")
    parser.add_argument("--query-prefix", default="zapytanie: ")
    parser.add_argument("--passage-prefix", default="")
    parser.add_argument("--license", dest="license_name", default="apache-2.0")
    parser.add_argument("--source", default="")
    args = parser.parse_args(argv)

    model_dir: Path = args.model_dir
    if not model_dir.exists():
        print(f"Nie znaleziono katalogu modelu: {model_dir}", file=sys.stderr)
        return 2
    output_dir: Path = args.output or (model_dir / "onnx")

    exporter = _load_model_export()
    result = exporter.convert_checkpoint(
        model_dir,
        output_dir,
        opset=args.opset,
        quantize=args.quantize,
        keep_fp32=True,
        progress=print,
    )
    print("Zapis manifestu")
    exporter.write_manifest(
        output_dir,
        model_key=model_dir.name,
        source=args.source or f"https://huggingface.co/sdadas/{model_dir.name}",
        license_name=args.license_name,
        architecture=result.architecture,
        dimension=result.dimension,
        max_sequence_length=result.max_sequence_length,
        pooling=args.pooling,
        normalize=True,
        query_prefix=args.query_prefix,
        passage_prefix=args.passage_prefix,
        opset=result.opset,
        quantized=result.quantized,
        pad_token=exporter.detect_pad_token(model_dir),
    )
    final_name = result.model_files[-1]
    print(f"Gotowe: {output_dir / final_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
