import math
def calculate_perplexity(loss: float) -> float:
    return math.exp(loss) if loss > 0 else 1.0
def calculate_token_accuracy(preds: list, targets: list) -> float:
    if not targets or len(preds) != len(targets): return 0.0
    return sum(1 for p, t in zip(preds, targets) if p == t) / len(targets)
