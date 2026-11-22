"""ZYRQUEN Native Evaluation Engine.

Provides verifiable checkpoint integrity, dataset manifest/SHA-256 verification,
and evaluation threshold validation without hardcoded datasets or dummy metrics.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.core.native.checkpoint import VersionedCheckpointManager
from apps.core.native.config import MAX_V10_PARAMETERS, ZyrquenConfig
from apps.core.native.dataset import (
    SCHEMA as DATASET_SCHEMA,
    SPLITS as DATASET_SPLITS,
    detect_dataset_format,
    load_sft_split,
)
from apps.core.native.sft import (
    SFT_SEP,
    bind_ephemeral_slots,
    encode_sft_prompt,
    restore_ephemeral_slots,
)
from apps.core.native.tokenizer import ZyrquenTokenizer
from apps.core.training_infrastructure.validation.model_validator import ModelValidator


class EvaluationError(ValueError):
    """Base error for verifiable evaluation failures."""


class EvaluationEvidenceError(EvaluationError):
    """Raised when required dataset, checkpoint, or evaluation evidence is missing or invalid."""


class EvaluationNotConfiguredError(RuntimeError):
    """Raised when evaluation artifacts or native evaluation execution are not configured."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class EvaluationEngine:
    def __init__(
        self,
        checkpoint_dir: str | Path | None = None,
        max_val_loss: float | None = None,
        max_perplexity: float | None = None,
    ):
        self.max_val_loss = max_val_loss
        self.max_perplexity = max_perplexity
        self.validator = ModelValidator(
            max_val_loss=max_val_loss,
            max_perplexity=max_perplexity,
        )
        if checkpoint_dir is None:
            self.checkpoint_dir: Path | None = None
            self.versions: VersionedCheckpointManager | None = None
        else:
            self.checkpoint_dir = Path(checkpoint_dir)
            self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
            self.versions = VersionedCheckpointManager(self.checkpoint_dir)

    def get_status(self) -> dict[str, Any]:
        configured = self.checkpoint_dir is not None and self.checkpoint_dir.is_dir()
        torch_installed = importlib.util.find_spec("torch") is not None
        if not configured:
            status = "not_configured"
        elif torch_installed:
            status = "ready"
        else:
            status = "evidence_validation_only"
        return {
            "status": status,
            "checkpoint_dir_configured": configured,
            "native_inference_evaluation_wired": True,
            "torch_installed": torch_installed,
        }

    def _require_configured(self) -> tuple[Path, VersionedCheckpointManager]:
        if self.checkpoint_dir is None or self.versions is None:
            raise EvaluationNotConfiguredError(
                "checkpoint_dir is not configured for evaluation"
            )
        return self.checkpoint_dir, self.versions

    def verify_checkpoint_version(
        self,
        model_version: str,
        *,
        checkpoint_id: str | None = None,
    ) -> dict[str, Any]:
        _, versions = self._require_configured()
        if not isinstance(model_version, str) or not model_version.strip():
            raise EvaluationEvidenceError("model_version must be a non-empty string")
        version = versions.get_version(model_version)
        if not version:
            raise EvaluationEvidenceError(f"ไม่เจอ model_version: {model_version}")
        if not versions.verify_version(model_version):
            raise EvaluationEvidenceError(
                f"checkpoint integrity check failed for model_version: {model_version}"
            )
        if checkpoint_id is not None and checkpoint_id not in {
            version.get("checkpoint_file"),
            version.get("checkpoint_sha256"),
        }:
            raise EvaluationEvidenceError(
                f"checkpoint_id does not match model_version {model_version}"
            )
        return version

    def verify_dataset(
        self,
        dataset_dir: str | Path,
        *,
        expected_version: str | None = None,
        expected_checksum: str | None = None,
    ) -> dict[str, Any]:
        if dataset_dir is None or str(dataset_dir).strip() == "":
            raise EvaluationEvidenceError("dataset_dir is required for evaluation")
        root = Path(dataset_dir)
        if not root.is_dir():
            raise EvaluationEvidenceError(f"dataset directory not found: {root}")
        manifest_path = root / "manifest.json"
        if not manifest_path.is_file():
            raise EvaluationEvidenceError(f"dataset manifest.json not found in: {root}")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EvaluationEvidenceError(
                f"dataset manifest.json is unreadable: {root}"
            ) from exc

        if not isinstance(manifest, dict) or manifest.get("schema") != DATASET_SCHEMA:
            raise EvaluationEvidenceError("unsupported or invalid dataset manifest schema")

        files = manifest.get("files")
        if not isinstance(files, dict):
            raise EvaluationEvidenceError("dataset manifest missing files metadata")

        for split in DATASET_SPLITS:
            filename = f"{split}.jsonl"
            entry = files.get(filename)
            split_path = root / filename
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("sha256"), str)
                or not split_path.is_file()
            ):
                raise EvaluationEvidenceError(
                    f"dataset integrity check failed: missing {filename}"
                )
            if _sha256_file(split_path) != entry["sha256"]:
                raise EvaluationEvidenceError(
                    f"dataset integrity check failed: {filename} checksum mismatch"
                )

        combined = hashlib.sha256(
            "".join(files[f"{split}.jsonl"]["sha256"] for split in DATASET_SPLITS).encode("utf-8")
        ).hexdigest()
        if combined != manifest.get("content_sha256"):
            raise EvaluationEvidenceError("dataset content_sha256 does not match manifest")

        eval_doc_count = sum(
            int(files[f"{split}.jsonl"].get("documents", 0))
            for split in ("validation", "test")
        )
        if eval_doc_count <= 0:
            raise EvaluationEvidenceError(
                "dataset contains no validation or test documents for evaluation"
            )

        if expected_version is not None and manifest.get("version") != expected_version:
            raise EvaluationEvidenceError(
                "dataset version does not match checkpoint dataset_version"
            )
        if (
            expected_checksum is not None
            and manifest["content_sha256"].lower() != expected_checksum.lower()
        ):
            raise EvaluationEvidenceError(
                "dataset checksum does not match expected dataset_checksum"
            )
        return manifest

    def evaluate(
        self,
        model_version: str,
        metrics: dict[str, Any],
        *,
        dataset_dir: str | Path | None = None,
        dataset_checksum: str | None = None,
    ) -> dict[str, Any]:
        checkpoint_dir, _ = self._require_configured()
        version = self.verify_checkpoint_version(model_version)

        if not isinstance(metrics, dict) or not metrics:
            raise EvaluationEvidenceError(
                "metrics must be a non-empty dictionary of verifiable evaluation evidence"
            )
        for key in ("val_loss", "perplexity"):
            if key in metrics and isinstance(metrics[key], bool):
                raise EvaluationEvidenceError(f"metric {key!r} must not be a boolean")

        dataset_manifest: dict[str, Any] | None = None
        if dataset_dir is not None:
            dataset_manifest = self.verify_dataset(
                dataset_dir,
                expected_version=version.get("dataset_version"),
                expected_checksum=dataset_checksum or version.get("dataset_content_hash"),
            )
        elif dataset_checksum is not None:
            expected_hash = version.get("dataset_content_hash")
            if not expected_hash or expected_hash.lower() != dataset_checksum.lower():
                raise EvaluationEvidenceError(
                    "dataset_checksum does not match checkpoint dataset_content_hash"
                )

        report = self.validator.validate(checkpoint_dir, metrics)
        if isinstance(report, dict):
            passed = bool(report.get("passed", report.get("is_valid", report.get("valid", False))))
            detail = report
        else:
            passed = bool(getattr(report, "passed", getattr(report, "is_valid", getattr(report, "valid", False))))
            detail = {"checks": getattr(report, "checks", []), "passed": passed}

        result = {
            "schema": "zyrquen.evaluation.v1",
            "model_version": model_version,
            "dataset_version": version.get("dataset_version"),
            "dataset_content_hash": (
                dataset_manifest["content_sha256"]
                if dataset_manifest is not None
                else version.get("dataset_content_hash")
            ),
            "checkpoint_file": version.get("checkpoint_file"),
            "checkpoint_sha256": version.get("checkpoint_sha256"),
            "metrics": dict(metrics),
            "val_loss": metrics.get("val_loss"),
            "perplexity": metrics.get("perplexity"),
            "passed": passed,
            "validator": detail,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }
        out = (checkpoint_dir / f"evaluation_{model_version}.json").resolve()
        if not out.is_relative_to(checkpoint_dir.resolve()):
            raise EvaluationEvidenceError("model_version produces an invalid report path")
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, out)
        return result

    def evaluate_native_model(
        self,
        model_version: str,
        *,
        dataset_dir: str | Path,
        tokenizer_path: str | Path | None = None,
        splits: tuple[str, ...] = ("validation", "test"),
        max_examples: int | None = None,
        max_new_tokens: int = 32,
        use_slots: bool | None = None,
        device: str = "cpu",
        capability_pass_threshold: float = 0.5,
    ) -> dict[str, Any]:
        """Execute greedy native ZyrquenModel inference over verified SFT splits."""
        checkpoint_dir, _ = self._require_configured()
        try:
            import torch
            from apps.core.native.model import ZyrquenModel
            from apps.core.native.registry import _safe_torch_load
        except ModuleNotFoundError as exc:
            raise EvaluationNotConfiguredError(
                "PyTorch runtime is not installed; native inference evaluation cannot run"
            ) from exc

        version = self.verify_checkpoint_version(model_version)
        manifest = self.verify_dataset(
            dataset_dir,
            expected_version=version.get("dataset_version"),
            expected_checksum=version.get("dataset_content_hash"),
        )
        if detect_dataset_format(dataset_dir) != "sft":
            raise EvaluationEvidenceError(
                "evaluate_native_model requires an SFT dataset with 'input' and 'target' fields"
            )

        tok_candidate = Path(tokenizer_path) if tokenizer_path else (checkpoint_dir / "tokenizer.json")
        if not tok_candidate.is_file() or tok_candidate.is_symlink():
            raise EvaluationEvidenceError(
                f"tokenizer.json missing or symlinked: {tok_candidate}"
            )
        try:
            tok = ZyrquenTokenizer.load(tok_candidate)
        except (OSError, ValueError, KeyError) as exc:
            raise EvaluationEvidenceError(f"failed to load tokenizer: {exc}") from exc

        ckpt_file = version.get("checkpoint_file")
        if not ckpt_file:
            raise EvaluationEvidenceError(f"checkpoint_file missing for {model_version}")
        ckpt_path = (checkpoint_dir / str(ckpt_file)).resolve()
        if not ckpt_path.is_relative_to(checkpoint_dir.resolve()) or not ckpt_path.is_file():
            raise EvaluationEvidenceError(f"invalid checkpoint file for {model_version}")

        state = _safe_torch_load(str(ckpt_path))
        if not isinstance(state, dict) or "model" not in state or "model_config" not in state:
            raise EvaluationEvidenceError("checkpoint missing model weights or model_config")

        expected_tok_sha = state.get("tokenizer_sha256") or version.get("tokenizer_sha256")
        if expected_tok_sha and expected_tok_sha != tok.fingerprint():
            raise EvaluationEvidenceError(
                "tokenizer SHA-256 does not match checkpoint tokenizer_sha256"
            )

        cfg = ZyrquenConfig.from_dict(state["model_config"])
        if cfg.vocab_size != tok.vocab_size:
            raise EvaluationEvidenceError(
                f"model vocab_size ({cfg.vocab_size}) != tokenizer vocab_size ({tok.vocab_size})"
            )
        cfg.validate_parameter_budget(MAX_V10_PARAMETERS)

        model = ZyrquenModel(cfg)
        model.load_state_dict(state["model"])
        model.to(device)
        model.eval()

        sep = str(state.get("sep") or SFT_SEP)
        is_v10 = manifest.get("dataset") == "nagi_v10"
        resolved_slots = use_slots if use_slots is not None else is_v10

        total_examples = 0
        total_correct = 0
        eos_hits = 0
        split_stats: dict[str, dict[str, Any]] = {}
        cap_stats: dict[str, dict[str, int]] = {}

        for split_name in splits:
            records = list(load_sft_split(dataset_dir, split_name))
            if max_examples is not None and max_examples > 0:
                records = records[:max_examples]
            split_correct = 0
            split_total = 0
            for row in records:
                prompt_text = str(row["input"])
                expected_target = str(row["target"]).strip()
                cap = str(row.get("capability") or "general")

                binding = None
                bound_prompt = prompt_text
                if resolved_slots:
                    bound_prompt, _, binding = bind_ephemeral_slots(
                        prompt_text, None, permute_slots=False
                    )

                prefix_ids = encode_sft_prompt(tok, bound_prompt, sep=sep)
                if len(prefix_ids) >= cfg.max_seq_len:
                    prefix_ids = prefix_ids[-(cfg.max_seq_len - 1) :]
                prompt_tensor = torch.tensor([prefix_ids], dtype=torch.long, device=device)

                generated_ids: list[int] = []
                hit_eos = False
                with torch.no_grad():
                    seq = prompt_tensor
                    budget_new = min(max_new_tokens, max(1, cfg.max_seq_len - seq.size(1)))
                    for _ in range(budget_new):
                        logits, _ = model(seq[:, -cfg.max_seq_len :])
                        next_tok = int(logits[:, -1, :].argmax(-1).item())
                        if next_tok == tok.eos_id:
                            hit_eos = True
                            break
                        generated_ids.append(next_tok)
                        seq = torch.cat(
                            (seq, torch.tensor([[next_tok]], dtype=torch.long, device=device)),
                            dim=1,
                        )

                raw_pred = tok.decode(generated_ids, skip_special=True, skip_slots=False)
                restored_pred = restore_ephemeral_slots(raw_pred, binding).strip()
                is_match = restored_pred == expected_target

                total_examples += 1
                split_total += 1
                if hit_eos:
                    eos_hits += 1
                if is_match:
                    total_correct += 1
                    split_correct += 1

                bucket = cap_stats.setdefault(cap, {"correct": 0, "total": 0})
                bucket["total"] += 1
                if is_match:
                    bucket["correct"] += 1

            split_stats[split_name] = {
                "total": split_total,
                "correct": split_correct,
                "exact_match": (split_correct / split_total) if split_total else 0.0,
            }

        if total_examples == 0:
            raise EvaluationEvidenceError("no evaluation examples executed")

        exact_match = total_correct / total_examples
        eos_hit_rate = eos_hits / total_examples
        capability_eval: dict[str, dict[str, Any]] = {}
        for cap, counts in sorted(cap_stats.items()):
            acc = counts["correct"] / counts["total"] if counts["total"] else 0.0
            capability_eval[cap] = {
                "status": "PASS" if acc >= capability_pass_threshold else "FAIL",
                "accuracy": round(acc, 6),
                "correct": counts["correct"],
                "total": counts["total"],
            }

        metrics: dict[str, Any] = {
            "exact_match": round(exact_match, 6),
            "eos_hit_rate": round(eos_hit_rate, 6),
            "examples_evaluated": float(total_examples),
        }
        for split_name, st in split_stats.items():
            metrics[f"{split_name}_exact_match"] = round(st["exact_match"], 6)
        for cap, info in capability_eval.items():
            metrics[f"cap_{cap}_accuracy"] = info["accuracy"]

        return {
            "schema": "zyrquen.native_inference_evaluation.v1",
            "model_version": model_version,
            "dataset_version": manifest.get("version"),
            "dataset_content_hash": manifest.get("content_sha256"),
            "checkpoint_file": version.get("checkpoint_file"),
            "checkpoint_sha256": version.get("checkpoint_sha256"),
            "tokenizer_sha256": tok.fingerprint(),
            "inference_status": "PASS",
            "metrics": metrics,
            "splits": split_stats,
            "capability_evaluation": capability_eval,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }

    def run_evaluation(
        self,
        model_version: str,
        *,
        dataset_dir: str | Path | None = None,
        dataset_checksum: str | None = None,
        metrics: dict[str, Any] | None = None,
        run_inference: bool = False,
        tokenizer_path: str | Path | None = None,
        max_examples: int | None = None,
        max_new_tokens: int = 32,
    ) -> dict[str, Any]:
        self._require_configured()
        version = self.verify_checkpoint_version(model_version)
        if dataset_dir is None:
            raise EvaluationEvidenceError(
                "dataset_dir is required; hardcoded dataset paths are not permitted"
            )
        self.verify_dataset(
            dataset_dir,
            expected_version=version.get("dataset_version"),
            expected_checksum=dataset_checksum,
        )
        if metrics is None:
            if not run_inference:
                raise EvaluationNotConfiguredError(
                    "Native model inference evaluation was not requested (pass run_inference=True with torch or supply verified metrics)"
                )
            return self.evaluate_native_model(
                model_version,
                dataset_dir=dataset_dir,
                tokenizer_path=tokenizer_path,
                max_examples=max_examples,
                max_new_tokens=max_new_tokens,
            )
        return self.evaluate(
            model_version,
            metrics,
            dataset_dir=dataset_dir,
            dataset_checksum=dataset_checksum,
        )
