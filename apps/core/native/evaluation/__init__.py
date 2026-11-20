"""
ZYRQUEN Native Evaluation Engine.

Phase 3.6: Evaluation Engine
Provides native model evaluation, benchmark, regression,
and safety evaluation components.
"""

from .engine import EvaluationEngine
from .metrics import calculate_perplexity, calculate_token_accuracy

__all__ = [
    "EvaluationEngine",
    "calculate_perplexity",
    "calculate_token_accuracy",
]
