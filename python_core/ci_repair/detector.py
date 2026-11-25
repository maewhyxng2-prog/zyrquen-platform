from collections.abc import Iterable
from .models import CIJob, DetectionReport

FAILED_CONCLUSIONS = {"failure", "timed_out"}
IGNORED_CONCLUSIONS = {"cancelled", "skipped", "success", "neutral", "stale"}


def is_failed_job(job: CIJob) -> bool:
    """Return True only when a completed/active job explicitly failed."""
    conclusion = (job.conclusion or "").strip().lower()
    status = (job.status or "").strip().lower()

    if conclusion in IGNORED_CONCLUSIONS:
        return False
    if conclusion in FAILED_CONCLUSIONS:
        return True
    if status == "failed" and conclusion not in IGNORED_CONCLUSIONS:
        return True
    return False


def detect_failures(jobs: Iterable[CIJob]) -> DetectionReport:
    """Separate actionable failed jobs from cancelled, skipped, or passing jobs."""
    failed_jobs: list[CIJob] = []
    ignored_jobs: list[CIJob] = []
    total = 0

    for job in jobs:
        total += 1
        if is_failed_job(job):
            failed_jobs.append(job)
        else:
            ignored_jobs.append(job)

    return DetectionReport(
        total_jobs=total,
        failed_jobs=failed_jobs,
        ignored_jobs=ignored_jobs,
    )
