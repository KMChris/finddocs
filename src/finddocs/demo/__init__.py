"""Zbior demonstracyjny FindDocs.

Pakiet udostepnia generator lokalnego, calkowicie fikcyjnego zbioru dokumentow
oraz manifest z zapytaniami referencyjnymi. Dzieki niemu aplikacje mozna
uruchomic i przetestowac bez dostepu do SharePointa.
"""

from __future__ import annotations

from finddocs.demo.generate import (
    ACCOUNT_COMPACT,
    ACCOUNT_DASHED,
    ACCOUNT_DOCUMENTS,
    ACCOUNT_SPACED,
    ACCOUNT_VARIANTS,
    DISCLAIMER,
    EXPECTED_ACCOUNT_DOCUMENTS,
    MANIFEST_NAME,
    MANIFEST_VERSION,
    DemoCorpusInfo,
    DemoQuery,
    demo_corpus_path,
    ensure_demo_corpus,
    generate_demo_corpus,
    load_manifest,
    manifest_to_dict,
    reference_queries,
    save_manifest,
)

__all__ = [
    "ACCOUNT_COMPACT",
    "ACCOUNT_DASHED",
    "ACCOUNT_DOCUMENTS",
    "ACCOUNT_SPACED",
    "ACCOUNT_VARIANTS",
    "DISCLAIMER",
    "EXPECTED_ACCOUNT_DOCUMENTS",
    "MANIFEST_NAME",
    "MANIFEST_VERSION",
    "DemoCorpusInfo",
    "DemoQuery",
    "demo_corpus_path",
    "ensure_demo_corpus",
    "generate_demo_corpus",
    "load_manifest",
    "manifest_to_dict",
    "reference_queries",
    "save_manifest",
]
