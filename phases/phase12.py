"""Phase 12 — Native Intelligence Foundation — pure logic only.

No training, no dataset, no weights, no GPU, no external AI, no DB, no auth.
Foundation only — no real model yet.
"""
from abc import ABC, abstractmethod

class IntelligenceProvider(ABC):
    """Core Intelligence Interfaces — every provider must follow this."""

    @abstractmethod
    def name(self):
        raise NotImplementedError

    @abstractmethod
    def capabilities(self):
        raise NotImplementedError

    @abstractmethod
    def can_handle(self, task):
        raise NotImplementedError

    @abstractmethod
    def run(self, task, context=None):
        raise NotImplementedError

class LocalRuleProvider(IntelligenceProvider):
    """Local rule-based provider — placeholder, NOT a trained model."""

    def name(self):
        return "local_rule"

    def capabilities(self):
        return ["summarize_text", "suggest_followup"]

    def can_handle(self, task):
        return task.get("type") in self.capabilities()

    def run(self, task, context=None):
        if not self.can_handle(task):
            return {"status": "blocked", "reason": "unsupported task", "result": None}
        if task.get("type") == "summarize_text":
            text = str(task.get("text", ""))
            return {"status": "ok", "result": text[:200], "provider": self.name()}
        if task.get("type") == "suggest_followup":
            return {
                "status": "ok",
                "result": ["ดูงานที่ค้างอยู่", "สรุปบริบทปัจจุบัน"],
                "provider": self.name(),
            }
        return {"status": "blocked", "reason": "unsupported task", "result": None}

class CapabilityRegistry:
    """Capability Management — knows what is available / blocked, no fake success."""

    BLOCKED = {
        "train_model": "blocked - training not approved",
        "load_weights": "blocked - weights download not approved",
        "external_ai": "blocked - external AI not allowed",
    }

    def __init__(self):
        self._providers = {}

    def register(self, provider):
        self._providers[provider.name()] = provider

    def list_capabilities(self):
        out = []
        for p in self._providers.values():
            out.extend(p.capabilities())
        return sorted(set(out))

    def get_status(self, capability):
        if capability in self.BLOCKED:
            return {"capability": capability, "status": "blocked", "reason": self.BLOCKED[capability]}
        if capability in self.list_capabilities():
            return {"capability": capability, "status": "available", "reason": ""}
        return {"capability": capability, "status": "not_available", "reason": "no provider registered"}

class NativeIntelligence:
    """Native Intelligence Architecture — isolated from API/Auth/Quota/DB."""

    def __init__(self, registry=None):
        self.registry = registry or CapabilityRegistry()
        if not self.registry._providers:
            self.registry.register(LocalRuleProvider())

    def handle(self, task, context=None):
        cap = task.get("type", "")
        status = self.registry.get_status(cap)
        if status["status"] != "available":
            return {"status": status["status"], "reason": status["reason"], "result": None}
        for p in self.registry._providers.values():
            if p.can_handle(task):
                return p.run(task, context)
        return {"status": "not_available", "reason": "no provider can handle", "result": None}
