from __future__ import annotations

from pathlib import Path
from typing import List, Optional

try:
    from .evidence_models import ClaimSpec, EvidenceItem, RealityReport
    from .probes import dispatch_probe
except ImportError:
    from evidence_models import ClaimSpec, EvidenceItem, RealityReport
    from probes import dispatch_probe


def run_reality_check(
    suite_name: str,
    claims: List[ClaimSpec],
    report_out: Optional[Path] = None,
) -> RealityReport:
    """Evaluates every claim actively without trusting reported status."""
    evidence: List[EvidenceItem] = [dispatch_probe(c) for c in claims]
    verified_true = sum(1 for ev in evidence if ev.verified_real)
    contradictions = len(evidence) - verified_true

    report = RealityReport(
        suite_name=suite_name,
        total_claims=len(evidence),
        verified_true_count=verified_true,
        contradiction_count=contradictions,
        all_verified_true=(len(evidence) > 0 and contradictions == 0),
        evidence=evidence,
    )
    if report_out is not None:
        report.save_json(report_out)
    return report
