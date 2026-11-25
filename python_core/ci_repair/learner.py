import json
import os
from datetime import datetime

MEMORY_FILE_PATH = "/content/zyrquen-platform/python_core/ci_repair/repair_memory.json"

def record_repair_attempt(category: str, file_path: str, was_successful: bool, message: str = "") -> None:
    """Records the results of a repair run into a local JSON file for historical analytics."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "category": category,
        "file_path": file_path,
        "was_successful": was_successful,
        "message": message
    }

    history = []
    if os.path.exists(MEMORY_FILE_PATH):
        try:
            with open(MEMORY_FILE_PATH, 'r', encoding='utf-8') as f:
                history = json.load(f)
        except Exception:
            history = []

    history.append(entry)

    try:
        with open(MEMORY_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=4, ensure_ascii=False)
        print("Successfully saved repair feedback into local learning memory.")
    except Exception as e:
        print(f"Failed to write to learning memory: {e}")

def get_learning_stats() -> dict:
    """Retrieves historical stats of local repairs."""
    if not os.path.exists(MEMORY_FILE_PATH):
        return {"total_attempts": 0, "success_rate": 0.0}

    try:
        with open(MEMORY_FILE_PATH, 'r', encoding='utf-8') as f:
            history = json.load(f)
        total = len(history)
        if total == 0:
            return {"total_attempts": 0, "success_rate": 0.0}
        successes = sum(1 for item in history if item["was_successful"])
        return {
            "total_attempts": total,
            "success_rate": round((successes / total) * 100, 2),
            "successful_attempts": successes
        }
    except Exception:
        return {"total_attempts": 0, "success_rate": 0.0}
