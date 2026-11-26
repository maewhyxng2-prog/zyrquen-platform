import time

def evaluate_quality(
    output, expected_keywords=None
):
    if not isinstance(output, str):
        return {
            "is_valid": False,
            "length": 0,
            "keyword_coverage": 0.0,
        }
    text = output.strip()
    words = text.split() if text else []
    keywords = expected_keywords or []
    found = 0
    low = text.lower()
    for k in keywords:
        if k.lower() in low:
            found += 1
    coverage = 0.0
    if keywords:
        coverage = found / len(keywords)
    return {
        "is_valid": len(words) > 0,
        "length": len(text),
        "word_count": len(words),
        "keyword_coverage": round(coverage, 4),
        "keywords_found": found,
        "keywords_total": len(keywords),
    }

def run_single(
    generate_fn, prompt, max_tokens=0
):
    start = time.time()
    output = generate_fn(prompt)
    elapsed = time.time() - start
    if not isinstance(output, str):
        raise ValueError(
            "generate_fn must return str"
        )
    words = output.strip().split()
    count = len(words)
    if max_tokens:
        count = min(count, max_tokens)
    tps = 0.0
    if elapsed > 0:
        tps = count / elapsed
    q = evaluate_quality(output)
    return {
        "prompt": prompt,
        "output": output,
        "latency_sec": round(elapsed, 4),
        "token_count": count,
        "tokens_per_sec": round(tps, 2),
        "quality": q,
        "success": q["is_valid"],
    }

def run_stability(
    generate_fn, prompt, runs=3
):
    if runs < 1:
        raise ValueError("runs >= 1")
    results = []
    for _ in range(runs):
        try:
            r = run_single(
                generate_fn, prompt
            )
            results.append(r)
        except Exception as e:
            results.append(
                {
                    "success": False,
                    "error": str(e),
                    "latency_sec": 0.0,
                    "token_count": 0,
                }
            )
    ok = [r for r in results if r["success"]]
    lat = [r["latency_sec"] for r in ok]
    avg = 0.0
    if lat:
        avg = sum(lat) / len(lat)
    return {
        "prompt": prompt,
        "runs": runs,
        "success_count": len(ok),
        "success_rate": round(
            len(ok) / runs, 4
        ),
        "avg_latency_sec": round(avg, 4),
        "min_latency_sec": round(
            min(lat), 4
        ) if lat else 0.0,
        "max_latency_sec": round(
            max(lat), 4
        ) if lat else 0.0,
        "results": results,
    }
