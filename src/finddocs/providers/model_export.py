"""Konwersja modelu HuggingFace do ONNX oraz zapis manifestu modelu.

Modul ma dwa zastosowania:

1. ``finddocs model import`` konwertuje checkpoint na stacji administratora,
   jesli srodowisko ma zainstalowany dodatek ``finddocs[export]``.
2. Skrypt ``tools/export_model_onnx.py`` laduje ten plik bezposrednio po sciezce
   (bez importu pakietu ``finddocs.providers``), zeby dzialac takze w srodowisku
   deweloperskim, ktore ma torch, ale nie ma zaleznosci uruchomieniowych aplikacji.

Z tego powodu na poziomie modulu wolno importowac wylacznie biblioteke standardowa
oraz ``finddocs.errors``. Ciezkie biblioteki (torch, transformers, onnxruntime,
tokenizers) sa importowane dopiero wewnatrz funkcji.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from finddocs.errors import ModelNotAvailableError

DEFAULT_OPSET = 14

#: Pakiety wymagane do konwersji checkpointu. Instaluje je dodatek finddocs[export].
EXPORT_PACKAGES: tuple[str, ...] = ("torch", "transformers", "onnx")

#: Pliki tokenizera i konfiguracji kopiowane obok modelu ONNX.
TOKENIZER_FILES: tuple[str, ...] = (
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "added_tokens.json",
    "unigram.json",
    "config.json",
)

ProgressCallback = Callable[[str], None]


def _noop_progress(_message: str) -> None:
    return None


def missing_export_packages() -> list[str]:
    """Lista brakujacych pakietow potrzebnych do konwersji checkpointu.

    Pakiet ``onnx`` jest wymagany zawsze: torch.onnx.export uzywa go do zapisu
    grafu, nie tylko do kwantyzacji.
    """
    return [name for name in EXPORT_PACKAGES if importlib.util.find_spec(name) is None]


def sha256_of_file(path: Path, *, block: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(block), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(slots=True)
class ConversionResult:
    """Wynik konwersji checkpointu do ONNX."""

    output_dir: Path
    model_files: list[str]
    architecture: str
    dimension: int
    max_sequence_length: int
    opset: int
    quantized: bool


def write_manifest(
    directory: Path,
    *,
    model_key: str,
    source: str,
    license_name: str,
    architecture: str,
    dimension: int,
    max_sequence_length: int,
    pooling: str,
    normalize: bool,
    query_prefix: str,
    passage_prefix: str,
    opset: int,
    quantized: bool,
    pad_token: str = "",
    display_name: str = "",
) -> dict[str, Any]:
    """Zapisuje manifest.json z sumami kontrolnymi wszystkich plikow katalogu."""
    manifest: dict[str, Any] = {
        "model_key": model_key,
        "display_name": display_name or model_key,
        "source": source,
        "license": license_name,
        "architecture": architecture,
        "dimension": int(dimension),
        "max_sequence_length": int(max_sequence_length),
        "pooling": pooling,
        "normalize": bool(normalize),
        "query_prefix": query_prefix,
        "passage_prefix": passage_prefix,
        "pad_token": pad_token,
        "opset": int(opset),
        "quantized": bool(quantized),
        "files": {
            path.name: {"sha256": sha256_of_file(path), "bytes": path.stat().st_size}
            for path in sorted(directory.glob("*"))
            if path.is_file() and path.name != "manifest.json"
        },
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def detect_pad_token(model_dir: Path) -> str:
    """Odczytuje token wypelnienia z plikow konfiguracji tokenizera.

    Zwraca pusty tekst, gdy zaden plik go nie deklaruje. Wartosc trafia do
    manifestu, a dostawca embeddingow uzywa jej przy ustawianiu paddingu.
    """
    for name in ("special_tokens_map.json", "tokenizer_config.json"):
        path = model_dir / name
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        raw = data.get("pad_token")
        if isinstance(raw, str) and raw:
            return raw
        if isinstance(raw, dict):
            content = raw.get("content")
            if isinstance(content, str) and content:
                return content
    return ""


def read_checkpoint_config(checkpoint_dir: Path) -> dict[str, Any]:
    """Czyta config.json checkpointu. Brak pliku oznacza nieprawidlowy katalog."""
    path = checkpoint_dir / "config.json"
    if not path.exists():
        raise ModelNotAvailableError(
            f"Katalog {checkpoint_dir} nie zawiera pliku config.json modelu.",
            details={"katalog": str(checkpoint_dir)},
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ModelNotAvailableError(f"Plik config.json w {checkpoint_dir} ma zły format.")
    return data


def _load_state_dict(model_dir: Path, torch: Any) -> dict[str, Any]:
    """Wczytuje wagi z safetensors albo z pliku pytorch_model.bin."""
    safetensors_path = model_dir / "model.safetensors"
    if safetensors_path.exists():
        from safetensors.torch import load_file

        loaded: dict[str, Any] = load_file(str(safetensors_path))
        return loaded
    bin_path = model_dir / "pytorch_model.bin"
    if bin_path.exists():
        result: dict[str, Any] = torch.load(str(bin_path), map_location="cpu", weights_only=True)
        return result
    raise ModelNotAvailableError(
        f"Katalog {model_dir} nie zawiera wag modelu (model.safetensors ani pytorch_model.bin)."
    )


def _model_classes(model_type: str) -> tuple[Any, Any, str]:
    """Dobiera klasy transformers dla typu modelu.

    Import konkretnej klasy zamiast fabryki Auto*, zeby nie ciagnac calego
    rejestru modeli transformers (w duzych srodowiskach potrafi on nie wstac).
    Zwraca klase konfiguracji, klase modelu i przedrostek kluczy wag.
    """
    if model_type in {"roberta", "xlm-roberta", "camembert"}:
        from transformers import RobertaConfig, RobertaModel

        return RobertaConfig, RobertaModel, "roberta."
    if model_type in {"bert", "herbert"}:
        from transformers import BertConfig, BertModel

        return BertConfig, BertModel, "bert."
    if model_type == "distilbert":
        from transformers import DistilBertConfig, DistilBertModel

        return DistilBertConfig, DistilBertModel, "distilbert."
    raise ModelNotAvailableError(
        f"Nieobsługiwany typ modelu: {model_type}. "
        "Obsługiwane rodziny to RoBERTa, XLM-RoBERTa, BERT i DistilBERT."
    )


def convert_checkpoint(
    checkpoint_dir: Path,
    output_dir: Path,
    *,
    opset: int = DEFAULT_OPSET,
    quantize: bool = True,
    keep_fp32: bool = False,
    progress: ProgressCallback | None = None,
) -> ConversionResult:
    """Konwertuje checkpoint HuggingFace do ONNX w katalogu docelowym.

    Wymaga pakietow z dodatku ``finddocs[export]`` (torch, transformers, onnx).
    Przy ``quantize`` zapisuje wariant INT8, a plik FP32 zostawia tylko przy
    ``keep_fp32``. Manifest zapisuje osobno funkcja :func:`write_manifest`.
    """
    notify = progress or _noop_progress
    missing = missing_export_packages()
    if missing:
        raise ModelNotAvailableError(
            "Konwersja modelu do ONNX wymaga pakietów: " + ", ".join(missing) + ". "
            'Zainstaluj je poleceniem: pip install "finddocs[export]".',
            details={"brakujace": missing},
        )

    import torch
    from tokenizers import Tokenizer

    output_dir.mkdir(parents=True, exist_ok=True)
    notify(f"Wczytywanie modelu z {checkpoint_dir}")
    config_data = read_checkpoint_config(checkpoint_dir)
    model_type = str(config_data.get("model_type", ""))
    config_cls, model_cls, weight_prefix = _model_classes(model_type)

    config = config_cls.from_pretrained(str(checkpoint_dir))
    try:
        model = model_cls.from_pretrained(str(checkpoint_dir), torch_dtype=torch.float32)
    except Exception as exc:
        # Sciezka zapasowa dla srodowisk, w ktorych from_pretrained nie dziala
        # z powodu konfliktu wersji accelerate lub innych zaleznosci pobocznych.
        notify(f"from_pretrained nie zadziałało ({type(exc).__name__}), ładuję wagi ręcznie")
        model = model_cls(config, add_pooling_layer=False)
        state = _load_state_dict(checkpoint_dir, torch)
        state = {k.removeprefix(weight_prefix): v for k, v in state.items()}
        state = {k: v.to(torch.float32) for k, v in state.items()}
        missing_keys, unexpected = model.load_state_dict(state, strict=False)
        blocking = [k for k in missing_keys if "position_ids" not in k and "pooler" not in k]
        if blocking:
            raise ModelNotAvailableError(
                f"W checkpoincie brakuje wag modelu: {blocking[:6]}"
            ) from exc
        if unexpected:
            notify(f"pominięto nadmiarowe klucze wag: {len(unexpected)}")
    model.eval()

    tokenizer_path = checkpoint_dir / "tokenizer.json"
    if not tokenizer_path.exists():
        raise ModelNotAvailableError(
            f"Katalog {checkpoint_dir} nie zawiera pliku tokenizer.json. "
            "Aplikacja obsługuje wyłącznie szybkie tokenizery HuggingFace."
        )
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    tokenizer.enable_truncation(max_length=64)
    tokenizer.enable_padding()
    encodings = tokenizer.encode_batch(["przykladowe zdanie testowe", "drugie zdanie kontrolne"])
    input_ids = torch.tensor([e.ids for e in encodings], dtype=torch.long)
    attention_mask = torch.tensor([e.attention_mask for e in encodings], dtype=torch.long)

    onnx_path = output_dir / "model.onnx"
    notify(f"Eksport do {onnx_path} (opset {opset})")

    class _Wrapper(torch.nn.Module):  # type: ignore[misc]
        def __init__(self, inner: Any) -> None:
            super().__init__()
            self.inner = inner

        def forward(self, input_ids: Any, attention_mask: Any) -> Any:
            out = self.inner(input_ids=input_ids, attention_mask=attention_mask)
            return out.last_hidden_state

    torch.onnx.export(
        _Wrapper(model),
        (input_ids, attention_mask),
        str(onnx_path),
        input_names=["input_ids", "attention_mask"],
        output_names=["last_hidden_state"],
        dynamic_axes={
            "input_ids": {0: "batch", 1: "sequence"},
            "attention_mask": {0: "batch", 1: "sequence"},
            "last_hidden_state": {0: "batch", 1: "sequence"},
        },
        opset_version=opset,
        do_constant_folding=True,
    )

    model_files = ["model.onnx"]
    if quantize:
        notify("Kwantyzacja dynamiczna INT8")
        from onnxruntime.quantization import QuantType, quantize_dynamic

        quant_path = output_dir / "model.int8.onnx"
        quantize_dynamic(
            model_input=str(onnx_path),
            model_output=str(quant_path),
            weight_type=QuantType.QInt8,
        )
        if keep_fp32:
            model_files = ["model.onnx", "model.int8.onnx"]
        else:
            onnx_path.unlink()
            model_files = ["model.int8.onnx"]

    notify("Kopiowanie plików tokenizera")
    for name in TOKENIZER_FILES:
        source = checkpoint_dir / name
        if source.exists() and source.resolve() != (output_dir / name).resolve():
            shutil.copy2(source, output_dir / name)

    max_positions = int(config_data.get("max_position_embeddings", 514))
    return ConversionResult(
        output_dir=output_dir,
        model_files=model_files,
        architecture=model_type,
        dimension=int(config_data.get("hidden_size", 768)),
        max_sequence_length=min(max_positions - 2, 512),
        opset=opset,
        quantized=quantize,
    )


__all__ = [
    "DEFAULT_OPSET",
    "EXPORT_PACKAGES",
    "TOKENIZER_FILES",
    "ConversionResult",
    "convert_checkpoint",
    "detect_pad_token",
    "missing_export_packages",
    "read_checkpoint_config",
    "sha256_of_file",
    "write_manifest",
]
