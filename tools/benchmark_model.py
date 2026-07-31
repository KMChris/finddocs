"""Pomiary dostawcy embeddingow: czas, pamiec i jakosc na malym zbiorze.

Skrypt sluzy do wypelnienia raportu PoC prawdziwymi liczbami zamiast szacunkow.
Uruchamiamy go na tym samym komputerze, na ktorym powstaje raport.

Uzycie:

    .venv/Scripts/python.exe tools/benchmark_model.py
    .venv/Scripts/python.exe tools/benchmark_model.py --model mmlw-retrieval-roberta-base
    .venv/Scripts/python.exe tools/benchmark_model.py --no-quantized --json-out wynik.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

#: Ile razy powtarzamy pomiar zapytania, zeby odciac wplyw pierwszego wywolania.
QUERY_REPEATS = 20

#: Ile fragmentow przetwarzamy w pomiarze przepustowosci.
PASSAGE_BATCH = 64

#: Zdania testowe: krotkie akapity przypominajace dokumenty biurowe.
PASSAGES: tuple[tuple[str, str], ...] = (
    (
        "kredyt",
        "Umowa kredytu hipotecznego na zakup mieszkania. Zabezpieczeniem jest hipoteka "
        "wpisana do ksiegi wieczystej. Oprocentowanie zmienne oparte o wskaznik WIBOR.",
    ),
    (
        "reklamacja",
        "Reklamacja transakcji kartowej. Klient zglasza nieautoryzowana platnosc "
        "w sklepie internetowym. Bank rozpatrzy zgloszenie w terminie trzydziestu dni.",
    ),
    (
        "hasla",
        "Polityka bezpieczenstwa hasel w systemach wewnetrznych. Haslo musi miec "
        "co najmniej dwanascie znakow. Zmiana wymagana jest co dziewiecdziesiat dni.",
    ),
    (
        "spis",
        "Protokol z inwentaryzacji sprzetu biurowego. Spisano komputery, drukarki "
        "i monitory w oddziale przy ulicy Dlugiej. Braki zgloszono do administracji.",
    ),
    (
        "szkolenia",
        "Harmonogram szkolen dla nowych pracownikow. Pierwszy modul dotyczy obslugi "
        "klienta. Drugi modul obejmuje przeciwdzialanie praniu pieniedzy.",
    ),
    (
        "urlop",
        "Wniosek urlopowy. Pracownik wnosi o dziesiec dni wolnych w sierpniu. "
        "Zastepstwo zapewnia zespol operacyjny.",
    ),
    (
        "awaria",
        "Awaria serwera pocztowego. Uzytkownicy nie mogli wysylac wiadomosci przez "
        "trzy godziny. Przyczyna byla usterka zasilania w serwerowni.",
    ),
    (
        "najem",
        "Umowa najmu lokalu uzytkowego przy ulicy Krotkiej. Czynsz platny do "
        "dziesiatego dnia miesiaca. Kaucja zwrotna po zakonczeniu wspolpracy.",
    ),
    (
        "parking",
        "Regulamin korzystania z parkingu podziemnego. Miejsca oznaczone numerami "
        "sa przypisane do konkretnych samochodow sluzbowych.",
    ),
    (
        "delegacja",
        "Rozliczenie kosztow podrozy sluzbowej do Gdanska. Uwzgledniono bilety "
        "kolejowe oraz nocleg w hotelu przy dworcu.",
    ),
    (
        "materialy",
        "Zamowienie materialow biurowych na kolejny kwartal. Lista obejmuje papier, "
        "segregatory oraz tusze do drukarek atramentowych.",
    ),
    (
        "ankieta",
        "Wyniki ankiety o preferowanych godzinach pracy stolowki pracowniczej. "
        "Najwiecej glosow otrzymala godzina dwunasta.",
    ),
)

#: Zapytania w formie parafrazy: brak wspolnych slow z dokumentem istotnym.
QUERIES: tuple[tuple[str, str], ...] = (
    ("jak sfinansowac wlasny dom dlugoterminowa pozyczka bankowa", "kredyt"),
    ("nieznane obciazenie konta po zakupach w sieci, jak odzyskac srodki", "reklamacja"),
    ("zasady tworzenia i okresowej wymiany kodu dostepu uzytkownika", "hasla"),
    ("przeglad majatku trwalego w filii firmy", "spis"),
    ("plan zajec wprowadzajacych dla osob rozpoczynajacych prace", "szkolenia"),
    ("prosba o przerwe wypoczynkowa w okresie letnim", "urlop"),
    ("niedostepnosc skrzynki mailowej z powodu problemu technicznego", "awaria"),
    ("warunki wynajecia powierzchni pod dzialalnosc handlowa", "najem"),
)


def _process_rss_bytes() -> int:
    """Zajetosc pamieci roboczej procesu w bajtach. Zero, gdy nie da sie odczytac."""
    try:
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = (
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            )

        psapi = ctypes.WinDLL("kernel32", use_last_error=True)
        get_info = psapi.K32GetProcessMemoryInfo
        get_info.argtypes = (wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD)
        get_info.restype = wintypes.BOOL

        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        if not get_info(handle, ctypes.byref(counters), counters.cb):
            return 0
    except Exception:
        return 0
    return int(counters.WorkingSetSize)


def _cosine(left: Any, right: Any) -> float:
    return float(sum(a * b for a, b in zip(left, right, strict=True)))


def _metrics(ranking: list[str], relevant: str, k: int = 5) -> dict[str, float]:
    position = ranking.index(relevant) + 1 if relevant in ranking else 0
    hit = 1.0 if 0 < position <= k else 0.0
    return {
        "trafienie_at_k": hit,
        "odwrotny_rank": 1.0 / position if position else 0.0,
        "ndcg_at_k": (1.0 / math.log2(position + 1)) if 0 < position <= k else 0.0,
        "pozycja": float(position),
    }


def benchmark(model_key: str, *, quantized: bool) -> dict[str, Any]:
    from finddocs.config import EmbeddingSettings
    from finddocs.providers import create_provider
    from finddocs.providers.model_manifest import find_model_dir

    model_dir = find_model_dir(model_key)
    if model_dir is None:
        raise SystemExit(f"Nie znaleziono modelu {model_key} w katalogu models/.")

    before = _process_rss_bytes()
    settings = EmbeddingSettings(model_key=model_key, quantized=quantized)
    load_start = time.perf_counter()
    provider = create_provider(settings)
    load_seconds = time.perf_counter() - load_start
    after_load = _process_rss_bytes()

    keys = [key for key, _ in PASSAGES]
    texts = [text for _, text in PASSAGES]

    # rozgrzewka: pierwsze wywolanie ONNX Runtime zawsze jest wolniejsze
    provider.embed_passages(texts[:2])

    batch = (texts * ((PASSAGE_BATCH // len(texts)) + 1))[:PASSAGE_BATCH]
    passage_start = time.perf_counter()
    provider.embed_passages(batch)
    passage_seconds = time.perf_counter() - passage_start

    vectors = provider.embed_passages(texts)
    after_work = _process_rss_bytes()

    query_times: list[float] = []
    results: list[dict[str, Any]] = []
    for query, relevant in QUERIES:
        start = time.perf_counter()
        embedded = provider.embed_query(query)
        query_times.append(time.perf_counter() - start)
        scored = sorted(
            ((key, _cosine(embedded, vector)) for key, vector in zip(keys, vectors, strict=True)),
            key=lambda pair: pair[1],
            reverse=True,
        )
        ranking = [key for key, _ in scored]
        results.append(
            {
                "zapytanie": query,
                "oczekiwany": relevant,
                "ranking": ranking[:5],
                "podobienstwo": round(scored[0][1], 4),
                **{k: round(v, 4) for k, v in _metrics(ranking, relevant).items()},
            }
        )

    for _ in range(QUERY_REPEATS - len(QUERIES)):
        start = time.perf_counter()
        provider.embed_query(QUERIES[0][0])
        query_times.append(time.perf_counter() - start)

    model_bytes = sum(p.stat().st_size for p in model_dir.rglob("*") if p.is_file())
    weights_name = "model.int8.onnx" if quantized else "model.onnx"
    weights = model_dir / weights_name
    if not weights.exists():
        weights = next((p for p in model_dir.rglob("*.onnx")), weights)

    summary = {
        "model": model_key,
        "kwantyzacja": quantized,
        "wymiar": provider.dimension,
        "max_dlugosc_sekwencji": settings.max_sequence_length,
        "plik_wag": weights.name,
        "rozmiar_wag_mb": (
            round(weights.stat().st_size / (1024 * 1024), 1) if weights.exists() else 0
        ),
        "rozmiar_katalogu_mb": round(model_bytes / (1024 * 1024), 1),
        "czas_wczytania_s": round(load_seconds, 3),
        "pamiec_przed_mb": round(before / (1024 * 1024), 1),
        "pamiec_po_wczytaniu_mb": round(after_load / (1024 * 1024), 1),
        "pamiec_po_pracy_mb": round(after_work / (1024 * 1024), 1),
        "przyrost_pamieci_mb": round((after_work - before) / (1024 * 1024), 1),
        "fragmenty_na_sekunde": round(PASSAGE_BATCH / passage_seconds, 1),
        "czas_zapytania_mediana_ms": round(statistics.median(query_times) * 1000, 1),
        "czas_zapytania_p95_ms": round(
            sorted(query_times)[int(len(query_times) * 0.95) - 1] * 1000, 1
        ),
        "recall_at_5": round(sum(float(r["trafienie_at_k"]) for r in results) / len(results), 3),
        "mrr": round(sum(float(r["odwrotny_rank"]) for r in results) / len(results), 3),
        "ndcg_at_5": round(sum(float(r["ndcg_at_k"]) for r in results) / len(results), 3),
        "zapytania": results,
    }
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pomiary dostawcy embeddingow")
    parser.add_argument("--model", default="mmlw-retrieval-roberta-base")
    parser.add_argument("--no-quantized", action="store_true", help="uzyj wag FP32")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args(argv)

    summary = benchmark(args.model, quantized=not args.no_quantized)
    summary["srodowisko"] = {
        "python": platform.python_version(),
        "system": f"{platform.system()} {platform.release()}",
        "procesor": platform.processor(),
        "rdzenie": os.cpu_count(),
    }

    text = json.dumps(summary, ensure_ascii=False, indent=2)
    print(text)
    if args.json_out:
        args.json_out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
