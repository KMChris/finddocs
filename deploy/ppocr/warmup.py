"""Pobiera wagi modeli do obrazu.

Uruchamiane raz, w etapie pomocniczym budowania obrazu. Zbudowanie potoku
sciaga wszystkie modele wskazane w ``pipeline.yaml`` do ``/root/.paddlex``.
Pliki sa te same dla wariantu CPU i GPU, a etap docelowy tylko je kopiuje,
dzieki czemu uruchomiony kontener nie potrzebuje dostepu do sieci.

Sam potok nie jest tutaj uruchamiany. W trakcie ``docker build`` nie ma dostepu
do karty, a sciezka oneDNN kola CPU nie obsluguje czesci operacji PP-OCRv6.
Dzialanie potoku sprawdza test integracyjny na uruchomionym kontenerze
(``tests/integration/test_remote_ocr_real.py``).
"""

from __future__ import annotations

import sys
from pathlib import Path

from paddleocr import PaddleOCR

CONFIG_PATH = "/opt/finddocs-ocr/pipeline.yaml"
CACHE_DIR = Path.home() / ".paddlex" / "official_models"


def main() -> int:
    PaddleOCR(paddlex_config=CONFIG_PATH, device="cpu")
    models = sorted(path.name for path in CACHE_DIR.iterdir()) if CACHE_DIR.is_dir() else []
    if not models:
        print(f"Nie pobrano zadnych modeli do {CACHE_DIR}", file=sys.stderr)
        return 1
    print(f"Pobrane modele ({len(models)}): {', '.join(models)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
