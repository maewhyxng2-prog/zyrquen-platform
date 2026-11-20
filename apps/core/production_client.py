import json

class ProductionError(Exception):
    pass

class ProductionClient:
    def __init__(self, client, timeout=60):
        self.client = client
        self.timeout = timeout

    def health(self):
        r = self.client.get(
            "/v1/native-ai/health"
        )
        if r.status_code != 200:
            return False
        return True

    def infer(
        self, prompt, max_tokens=64,
        temperature=0.7,
        top_k=0, top_p=1.0,
    ):
        r = self.client.post(
            "/v1/native-ai/infer",
            json={
                "prompt": prompt,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "top_k": top_k,
                "top_p": top_p,
            },
        )
        if r.status_code == 422:
            raise ProductionError(
                "validation: " + r.text[:200]
            )
        if r.status_code == 503:
            raise ProductionError(
                "model not ready"
            )
        if r.status_code != 200:
            raise ProductionError(
                f"infer failed: {r.status_code}"
            )
        data = r.json()
        if data.get("status") != "success":
            raise ProductionError(
                "infer status != success"
            )
        return data["result"]

    def infer_stream(
        self, prompt, max_tokens=64,
        temperature=0.7,
        top_k=0, top_p=1.0,
    ):
        r = self.client.post(
            "/v1/native-ai/infer/stream",
            json={
                "prompt": prompt,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "top_k": top_k,
                "top_p": top_p,
            },
        )
        if r.status_code != 200:
            raise ProductionError(
                f"stream failed: {r.status_code}"
            )
        full = []
        for line in r.text.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                obj = json.loads(payload)
            except Exception:
                continue
            if obj.get("is_final"):
                break
            txt = obj.get("text", "")
            if txt:
                full.append(txt)
                yield txt
        if not full:
            raise ProductionError(
                "empty stream"
            )
