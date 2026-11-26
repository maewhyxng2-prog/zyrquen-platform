import logging
from .contract import validate_result
from typing import Dict, Any, List
from .knowledge import KnowledgeSystem

logger = logging.getLogger(__name__)

class ReasoningEngine:
    """
    ZYRQUEN Native Reasoning Engine.
    Responsible for breaking down problems and logical deduction.
    """
    def __init__(self, knowledge: KnowledgeSystem):
        self.knowledge = knowledge

    def _deduce_unvalidated(self, context: str, question: str) -> Dict[str, Any]:
        """
        Rule-based knowledge lookup over KnowledgeSystem.

        This is NOT model inference. It returns the related knowledge found
        for the given context and reports status as "lookup_only" or
        "no_knowledge_found". Native model reasoning is not connected yet.
        """
        logger.info(f"Reasoning on: {question}")

        # ตรวจสอบความรู้ที่มีอยู่ (Rule-based เบื้องต้น)
        related = self.knowledge.query_related(context)

        return {
            "context": context,
            "question": question,
            "related_knowledge_found": len(related) > 0,
            "reasoning_path": related,
            "status": "lookup_only" if related else "no_knowledge_found",
            "engine_type": "rule_based_scaffold",
            "model_inference": False
        }

    def deduce(self, *args, **kwargs):
        """
        Run the rule-based lookup and enforce the result contract.

        Raises ContractViolation if the result breaks the contract
        (Phase 9.3b). No native model evidence is supplied, so a result
        claiming model_inference=True is always rejected for now.
        """
        result = self._deduce_unvalidated(*args, **kwargs)
        validate_result(result)
        return result
