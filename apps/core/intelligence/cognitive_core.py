"""Native Cognitive Core Orchestrator & Strict Native-Only Policy Auditor.

Enforces:
- All cognitive reasoning, planning, and synthesis remain under NativeRuntime control.
- When NativeRuntime is unavailable (not_configured/BLOCKED), fail closed as BLOCKED
  and NEVER substitute external LLMs or fake template outputs.
- Every cognitive decision emits a typed DecisionTrace with rationale, confidence,
  and verification conditions.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .memory_layers import SegmentedKnowledgeEngine
from .research import ResearchSource, ResearchVerifier

PROHIBITED_PYTHON_LLM_MODULES = frozenset({
    "openai",
    "anthropic",
    "groq",
    "together",
    "mistralai",
    "cohere",
    "huggingface_hub",
})

PROHIBITED_PYTHON_DOTTED_PREFIXES = (
    "google.generativeai",
    "google.genai",
)

PROHIBITED_WEB_LLM_PACKAGES = (
    "@google/genai",
    "@google/generative-ai",
    "openai",
    "@anthropic-ai/sdk",
    "groq-sdk",
)

_FROM_PRETRAINED_RE = re.compile(r"\bfrom_pretrained\s*\(")
_SNAPSHOT_DOWNLOAD_RE = re.compile(r"\bsnapshot_download\s*\(")


@dataclass(frozen=True)
class DecisionTrace:
    rationale: str
    confidence: float
    verification_conditions: tuple[str, ...]
    model_version: str | None
    artifact_origin: str | None
    provider: str
    evidence_refs: tuple[str, ...] = ()
    policy_compliant: bool = True


@dataclass(frozen=True)
class CognitiveDecisionResult:
    status: str  # "COMPLETED" | "BLOCKED"
    inference_available: bool
    model_inference: bool
    response_text: str | None
    blocker: str | None
    decision_trace: DecisionTrace
    research_verdict: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class NativeCognitiveOrchestrator:
    """Single cognitive authority binding NativeRuntime + SegmentedMemory + ResearchVerifier."""

    def __init__(
        self,
        *,
        native_runtime: Any,
        knowledge_engine: SegmentedKnowledgeEngine | None = None,
        research_verifier: ResearchVerifier | None = None,
    ) -> None:
        self.native_runtime = native_runtime
        self.knowledge = knowledge_engine or SegmentedKnowledgeEngine()
        self.research = research_verifier or ResearchVerifier()

    def reason_and_respond(
        self,
        *,
        prompt: str,
        context_key: str = "default",
        sources: list[ResearchSource] | None = None,
        max_tokens: int = 128,
        temperature: float = 0.0,
    ) -> CognitiveDecisionResult:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be non-empty string")

        research_status: str | None = None
        evidence_refs: list[str] = []
        if sources is not None:
            rv = self.research.verify_claim(
                topic=context_key,
                sources=sources,
                knowledge_store=self.knowledge.verified,
            )
            research_status = rv.status
            evidence_refs.extend(rv.sources_used)

        health = self.native_runtime.get_health_status()
        if not self.native_runtime.is_ready():
            runtime_status = str(health.get("runtime_status", "blocked")).upper()
            return CognitiveDecisionResult(
                status="BLOCKED",
                inference_available=False,
                model_inference=False,
                response_text=None,
                blocker=f"NATIVE_MODEL_UNAVAILABLE:{runtime_status}",
                research_verdict=research_status,
                decision_trace=DecisionTrace(
                    rationale="Native Cognitive Core blocked: no trained native weights loaded.",
                    confidence=0.0,
                    verification_conditions=(
                        "native_runtime.is_ready() == True",
                        "verified checkpoint + tokenizer loaded",
                    ),
                    model_version=health.get("model_version"),
                    artifact_origin=health.get("artifact_origin"),
                    provider="ZYRQUEN_NATIVE_CORE",
                    evidence_refs=tuple(evidence_refs),
                    policy_compliant=True,
                ),
            )

        output = self.native_runtime.engine.generate(
            prompt,
            max_new_tokens=max_tokens,
            temperature=temperature,
        )
        return CognitiveDecisionResult(
            status="COMPLETED",
            inference_available=True,
            model_inference=True,
            response_text=str(output),
            blocker=None,
            research_verdict=research_status,
            decision_trace=DecisionTrace(
                rationale="Synthesized strictly via NativeRuntime.engine under Native Cognitive Core.",
                confidence=1.0 if research_status == "VERIFIED" else 0.7,
                verification_conditions=(
                    "native_runtime.is_ready() == True",
                    "non_empty_native_output",
                ),
                model_version=health.get("model_version"),
                artifact_origin=health.get("artifact_origin"),
                provider="ZYRQUEN_NATIVE_CORE",
                evidence_refs=tuple(evidence_refs),
                policy_compliant=True,
            ),
        )


def audit_strict_native_only_compliance(repo_root: str | Path) -> dict[str, Any]:
    """Static AST + dependency audit ensuring zero external LLMs or pretrained weights exist."""
    root = Path(repo_root)
    violations: list[dict[str, str]] = []
    scanned_files = 0

    for rel_dir in ("apps/core", "apps/api"):
        target = root / rel_dir
        if not target.is_dir():
            continue
        for py_path in sorted(target.rglob("*.py")):
            # Ignore self-referential policy constant definitions
            if py_path.name in {"cognitive_core.py", "policy.py", "auditor.py"}:
                continue
            scanned_files += 1
            text = py_path.read_text(encoding="utf-8", errors="replace")
            if _FROM_PRETRAINED_RE.search(text):
                violations.append({"file": str(py_path.relative_to(root)), "rule": "from_pretrained_call"})
            if _SNAPSHOT_DOWNLOAD_RE.search(text):
                violations.append({"file": str(py_path.relative_to(root)), "rule": "snapshot_download_call"})
            try:
                tree = ast.parse(text, filename=str(py_path))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".", 1)[0]
                        if top in PROHIBITED_PYTHON_LLM_MODULES or any(
                            alias.name.startswith(p) for p in PROHIBITED_PYTHON_DOTTED_PREFIXES
                        ):
                            violations.append({
                                "file": str(py_path.relative_to(root)),
                                "rule": f"prohibited_import:{alias.name}",
                            })
                elif isinstance(node, ast.ImportFrom) and node.module:
                    top = node.module.split(".", 1)[0]
                    if top in PROHIBITED_PYTHON_LLM_MODULES or any(
                        node.module.startswith(p) for p in PROHIBITED_PYTHON_DOTTED_PREFIXES
                    ):
                        violations.append({
                            "file": str(py_path.relative_to(root)),
                            "rule": f"prohibited_import:{node.module}",
                        })

    web_src = root / "apps" / "web" / "src"
    if web_src.is_dir():
        for ts_path in sorted(web_src.rglob("*.ts*")):
            if ts_path.name.endswith(".test.ts") or ts_path.name.endswith(".test.tsx"):
                continue
            scanned_files += 1
            content = ts_path.read_text(encoding="utf-8", errors="replace")
            for pkg in PROHIBITED_WEB_LLM_PACKAGES:
                if f'"{pkg}"' in content or f"'{pkg}'" in content:
                    violations.append({
                        "file": str(ts_path.relative_to(root)),
                        "rule": f"prohibited_web_pkg:{pkg}",
                    })

    return {
        "compliant": len(violations) == 0,
        "status": "VERIFIED" if not violations else "BLOCKED",
        "scanned_files": scanned_files,
        "violations": violations,
    }
