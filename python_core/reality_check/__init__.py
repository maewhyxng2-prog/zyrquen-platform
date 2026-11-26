"""RealityCheck — Independent Deterministic System Verification Engine."""

from .evidence_models import ClaimSpec, EvidenceItem, RealityReport, sha256_file
from .probes import dispatch_probe, verify_execution_claim, verify_restore_claim, verify_sync_claim
from .runner import run_reality_check

__all__ = [
    "ClaimSpec",
    "EvidenceItem",
    "RealityReport",
    "dispatch_probe",
    "run_reality_check",
    "sha256_file",
    "verify_execution_claim",
    "verify_restore_claim",
    "verify_sync_claim",
]
