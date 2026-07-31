"""Zadania w tle: indeksowanie, checkpointy, pauza, wznowienie."""

from __future__ import annotations

from finddocs.jobs.control import JobControl, RetryPolicy
from finddocs.jobs.indexing_job import IndexingJob, JobOptions
from finddocs.jobs.pipeline import DocumentOutcome, DocumentPipeline
from finddocs.jobs.runner import JobRunner, QueuedJob

__all__ = [
    "DocumentOutcome",
    "DocumentPipeline",
    "IndexingJob",
    "JobControl",
    "JobOptions",
    "JobRunner",
    "QueuedJob",
    "RetryPolicy",
]
