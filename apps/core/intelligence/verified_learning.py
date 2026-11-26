"""Verified Feedback Learning Curator (P2).

Enforces:
- Feedback or research items NEVER mutate model weights directly (model_weights_changed=False).
- Only feedback backed by VERIFIED research/evidence passes curation.
- CONFLICTING_SOURCES, SINGLE_SOURCE_UNVERIFIED, STALE, INSUFFICIENT_EVIDENCE,
  and BLOCKED items are rejected (CONFLICTING_SOURCES -> NOT_LEARNED).
- Prompt-injection screening and held-out EvaluationCorpus contamination checks
  run strictly before any item enters TrainingCorpusStore.
- Admitted corpus exports still require Tier-2 human approval before training.
"""

from __future__ import annotations

from typing import Any

from .feedback_log import FeedbackLog
from .memory_layers import SegmentedKnowledgeEngine
from .research import ResearchSource, ResearchVerifier, sanitize_untrusted_source


class VerifiedFeedbackCurator:
    def __init__(
        self,
        *,
        knowledge_engine: SegmentedKnowledgeEngine | None = None,
        feedback_log: FeedbackLog | None = None,
        research_verifier: ResearchVerifier | None = None,
    ) -> None:
        self.knowledge = knowledge_engine or SegmentedKnowledgeEngine()
        self.feedback_log = feedback_log or FeedbackLog()
        self.research = research_verifier or ResearchVerifier()

    def curate_feedback_sample(
        self,
        *,
        feedback_record: dict[str, Any],
        training_text: str,
        topic: str,
        sources: list[ResearchSource],
    ) -> dict[str, Any]:
        logged = self.feedback_log.submit(feedback_record)
        if not logged["stored"]:
            return {
                "status": "rejected",
                "learned": False,
                "reason": f"invalid_feedback:{';'.join(logged['problems'])}",
                "evidence_status": "BLOCKED",
                "model_weights_changed": False,
                "requires_tier2_approval": True,
            }

        envelope = sanitize_untrusted_source(training_text, feedback_record["id"])
        if envelope.compromised:
            return {
                "status": "rejected",
                "learned": False,
                "reason": f"prompt_injection_blocked:{','.join(envelope.injection_flags)}",
                "evidence_status": "BLOCKED",
                "model_weights_changed": False,
                "requires_tier2_approval": True,
            }

        verification = self.research.verify_claim(
            topic=topic,
            sources=sources,
            knowledge_store=self.knowledge.verified,
            record_id_prefix="feedback",
        )
        if verification.status != "VERIFIED" or not verification.learnable:
            return {
                "status": "rejected",
                "learned": False,
                "reason": f"not_learned:{verification.status}",
                "evidence_status": verification.status,
                "model_weights_changed": False,
                "requires_tier2_approval": True,
            }

        lead_src = sources[0]
        admitted = self.knowledge.training_corpus.admit(
            record_id=feedback_record["id"],
            content=envelope.sanitized_content,
            source_id=",".join(verification.sources_used),
            retrieved_at=lead_src.retrieved_at,
            evidence_status="VERIFIED",
        )
        if not admitted["admitted"]:
            return {
                "status": "rejected",
                "learned": False,
                "reason": admitted["reason"],
                "evidence_status": "BLOCKED",
                "model_weights_changed": False,
                "requires_tier2_approval": True,
            }

        return {
            "status": "curated",
            "learned": True,
            "evidence_status": "VERIFIED",
            "content_hash": admitted["content_hash"],
            "model_weights_changed": False,
            "requires_tier2_approval": True,
        }
