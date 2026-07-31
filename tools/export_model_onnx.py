"""Eksport modelu embeddingow z formatu HuggingFace do ONNX.

Skrypt uruchamiamy raz, w srodowisku deweloperskim, ktore ma zainstalowany torch
i transformers. Runtime aplikacji korzysta juz tylko z onnxruntime i tokenizers,
dzieki czemu instalator jest o rzad wielkosci mniejszy.

Uzycie:

    python tools/export_model_onnx.py models/mmlw-retrieval-roberta-base \
        --output models/mmlw-retrieval-roberta-base/onnx --quantize

Skrypt zapisuje obok modelu plik ``manifest.json`` z suma kontrolna, wymiarem
wektora, licencja i informacja o pochodzeniu.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

DEFAULT_OPSET = 14


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_state_dict(model_dir: Path, torch: object) -> dict:
    """Wczytuje wagi z safetensors albo z pliku pytorch_model.bin."""
    safetensors_path = model_dir / "model.safetensors"
    if safetensors_path.exists():
        from safetensors.torch import load_file

        return load_file(str(safetensors_path))
    bin_path = model_dir / "pytorch_model.bin"
    if bin_path.exists():
        return torch.load(str(bin_path), map_location="cpu", weights_only=True)  # type: ignore[attr-defined]
    raise SystemExit(f"Nie znaleziono plikow wag w {model_dir}")


def export(model_dir: Path, output_dir: Path, opset: int, quantize: bool) -> Path:
    import torch
    from tokenizers import Tokenizer

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"[1/5] Wczytywanie modelu z {model_dir}")
    config_data = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
    model_type = config_data.get("model_type", "")

    # Import konkretnej klasy zamiast fabryki Auto*, zeby nie ciagnac calego
    # rejestru modeli transformers (w duzych srodowiskach potrafi on nie wstac).
    if model_type in {"roberta", "xlm-roberta", "camembert"}:
        from transformers import RobertaConfig as ConfigCls
        from transformers import RobertaModel as ModelCls
    elif model_type == "bert":
        from transformers import BertConfig as ConfigCls
        from transformers import BertModel as ModelCls
    else:
        raise SystemExit(f"Nieobslugiwany typ modelu: {model_type}")

    config = ConfigCls.from_pretrained(str(model_dir))
    try:
        model = ModelCls.from_pretrained(str(model_dir), torch_dtype=torch.float32)
    except Exception as exc:
        # Sciezka zapasowa dla srodowisk, w ktorych from_pretrained nie dziala
        # z powodu konfliktu wersji accelerate lub innych zaleznosci pobocznych.
        print(f"    from_pretrained nie zadzialalo ({type(exc).__name__}), laduje wagi recznie")
        model = ModelCls(config, add_pooling_layer=False)
        state = _load_state_dict(model_dir, torch)
        state = {k.removeprefix("roberta.").removeprefix("bert."): v for k, v in state.items()}
        state = {k: v.to(torch.float32) for k, v in state.items()}
        missing, unexpected = model.load_state_dict(state, strict=False)
        blocking = [k for k in missing if "position_ids" not in k and "pooler" not in k]
        if blocking:
            raise SystemExit(f"Brakujace wagi w checkpoincie: {blocking[:6]}") from exc
        if unexpected:
            print(f"    pominieto nadmiarowe klucze: {len(unexpected)}")
    model.eval()

    tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
    tokenizer.enable_truncation(max_length=64)
    tokenizer.enable_padding()
    encodings = tokenizer.encode_batch(["zapytanie: przykladowe zdanie", "drugie zdanie kontrolne"])
    input_ids = torch.tensor([e.ids for e in encodings], dtype=torch.long)
    attention_mask = torch.tensor([e.attention_mask for e in encodings], dtype=torch.long)
    inputs = (input_ids, attention_mask)

    onnx_path = output_dir / "model.onnx"
    print(f"[2/5] Eksport do {onnx_path} (opset {opset})")

    class Wrapper(torch.nn.Module):
        def __init__(self, inner: torch.nn.Module) -> None:
            super().__init__()
            self.inner = inner

        def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
            out = self.inner(input_ids=input_ids, attention_mask=attention_mask)
            return out.last_hidden_state

    torch.onnx.export(
        Wrapper(model),
        inputs,
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

    final_path = onnx_path
    if quantize:
        print("[3/5] Kwantyzacja dynamiczna INT8")
        from onnxruntime.quantization import QuantType, quantize_dynamic

        quant_path = output_dir / "model.int8.onnx"
        quantize_dynamic(
            model_input=str(onnx_path),
            model_output=str(quant_path),
            weight_type=QuantType.QInt8,
        )
        final_path = quant_path
    else:
        print("[3/5] Pominieto kwantyzacje")

    print("[4/5] Kopiowanie plikow tokenizera")
    for name in (
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "added_tokens.json",
        "unigram.json",
        "config.json",
    ):
        source = model_dir / name
        if source.exists():
            shutil.copy2(source, output_dir / name)

    print("[5/5] Zapis manifestu")
    manifest = {
        "model_key": model_dir.name,
        "source": f"https://huggingface.co/sdadas/{model_dir.name}",
        "license": "apache-2.0",
        "architecture": config.model_type,
        "dimension": int(config.hidden_size),
        "max_sequence_length": int(min(config.max_position_embeddings - 2, 512)),
        "pooling": "cls",
        "normalize": True,
        "query_prefix": "zapytanie: ",
        "passage_prefix": "",
        "opset": opset,
        "quantized": quantize,
        "files": {
            path.name: {"sha256": sha256_of(path), "bytes": path.stat().st_size}
            for path in sorted(output_dir.glob("*"))
            if path.is_file() and path.name != "manifest.json"
        },
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Gotowe: {final_path}")
    return final_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Eksport modelu embeddingow do ONNX")
    parser.add_argument("model_dir", type=Path, help="katalog modelu HuggingFace")
    parser.add_argument("--output", type=Path, default=None, help="katalog docelowy")
    parser.add_argument("--opset", type=int, default=DEFAULT_OPSET)
    parser.add_argument("--quantize", action="store_true", help="dodatkowo zapisz wersje INT8")
    args = parser.parse_args(argv)

    model_dir: Path = args.model_dir
    if not model_dir.exists():
        print(f"Nie znaleziono katalogu modelu: {model_dir}", file=sys.stderr)
        return 2
    output_dir: Path = args.output or (model_dir / "onnx")
    export(model_dir, output_dir, args.opset, args.quantize)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
