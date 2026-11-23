import json
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class EvaluationEngine:
    def __init__(self, golden_dataset_path: str = "apps/core/evaluation/golden_dataset.json"):
        self.golden_dataset_path = golden_dataset_path

    def _load_golden_dataset(self) -> List[Dict]:
        import os
        if not os.path.exists(self.golden_dataset_path):
            return []
        with open(self.golden_dataset_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def calculate_perplexity(self, logits: Any, target_ids: Any) -> float:
        return 15.5 # Mock for testing flow

    def calculate_token_accuracy(self, predicted_ids: Any, target_ids: Any) -> float:
        return 0.85 # Mock for testing flow

    def run_safety_check(self, text: str) -> bool:
        banned_words = ["โง่", "ฆ่า", "ระเบิด", "stupid", "kill"]
        return not any(word in text.lower() for word in banned_words)

    async def execute_evaluation(self, model_version: str) -> Dict[str, Any]:
        dataset = self._load_golden_dataset()
        if not dataset:
            raise ValueError("Golden Dataset is missing or empty.")

        perplexity = self.calculate_perplexity(None, None)
        accuracy = self.calculate_token_accuracy(None, None)

        safety_violations = 0
        for item in dataset:
            if not self.run_safety_check(item.get("expected_response", "")):
                safety_violations += 1

        return {
            "perplexity": perplexity,
            "token_accuracy": accuracy,
            "safety_violations": float(safety_violations),
            "evaluated_model": model_version
        }
