"""Regression guard for ZYRQUEN's Native-Only model boundary."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOTS = ("apps/core", "apps/api", "tools", "phases")
FORBIDDEN_IMPORTS = {"huggingface_hub", "transformers", "tokenizers"}
FORBIDDEN_MODEL_MARKERS = ("Q" + "wen/", "meta-" + "llama/", "mistral" + "ai/", "google/" + "gemma", "snapshot_" + "download(", "hf_hub_" + "download(", "from_" + "pretrained(")


def test_no_external_model_provisioner_remains():
    assert not (ROOT / "apps/core/download_model.py").exists()


def test_runtime_python_has_no_external_model_sdk_or_pretrained_loader():
    violations = []
    for relative_root in RUNTIME_ROOTS:
        base = ROOT / relative_root
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            source = path.read_text(encoding="utf-8")
            try:
                tree = ast.parse(source, filename=str(path))
            except SyntaxError as exc:
                violations.append(f"{path}: syntax error: {exc}")
                continue
            for node in ast.walk(tree):
                imported = []
                if isinstance(node, ast.Import):
                    imported.extend(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.append(node.module.split(".")[0])
                for module in imported:
                    if module in FORBIDDEN_IMPORTS:
                        violations.append(f"{path}:{node.lineno}: forbidden import {module}")
            for marker in FORBIDDEN_MODEL_MARKERS:
                if marker in source:
                    violations.append(f"{path}: forbidden external model identifier {marker}")
    assert not violations, "\\n".join(violations)
