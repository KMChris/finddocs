"""Warstwa diagnostyczna: statystyki, raport pokrycia i eksport raportow."""

from __future__ import annotations

from finddocs.diagnostics.coverage_report import (
    STATUS_LABELS,
    build_coverage_report,
    coverage_summary_text,
    non_searchable_count,
    status_label,
)
from finddocs.diagnostics.export import (
    coverage_to_dict,
    default_bundle_timestamp,
    export_coverage_csv,
    export_coverage_json,
    export_diagnostics_bundle,
    export_errors_csv,
)
from finddocs.diagnostics.stats import (
    collect_all,
    collect_component_info,
    collect_environment_info,
    collect_index_stats,
    format_bytes,
    memory_status,
)

__all__ = [
    "STATUS_LABELS",
    "build_coverage_report",
    "collect_all",
    "collect_component_info",
    "collect_environment_info",
    "collect_index_stats",
    "coverage_summary_text",
    "coverage_to_dict",
    "default_bundle_timestamp",
    "export_coverage_csv",
    "export_coverage_json",
    "export_diagnostics_bundle",
    "export_errors_csv",
    "format_bytes",
    "memory_status",
    "non_searchable_count",
    "status_label",
]
