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
    detect_dataset_format,
    load_sft_split,
    resolve_dataset_splits,
    verify_dataset_manifest,
)
from apps.core.native.sft import (
    SFT_SEP,
    bind_ephemeral_slots,
    encode_sft_prompt,
    extract_entities,
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
        *,
        registry_root: str | Path | None = None,
        load_fn: Any | None = None,
    ):
        self.max_val_loss = max_val_loss
        self.max_perplexity = max_perplexity
        self._load_fn = load_fn
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
            ckpt_kwargs = {"load_fn": load_fn} if load_fn is not None else {}
            self.versions = VersionedCheckpointManager(self.checkpoint_dir, **ckpt_kwargs)

        self.registry_root: Path | None = Path(registry_root) if registry_root is not None else None

    def get_status(self) -> dict[str, Any]:
        ckpt_configured = self.checkpoint_dir is not None and self.checkpoint_dir.is_dir()
        reg_configured = self.registry_root is not None and self.registry_root.is_dir()
        configured = ckpt_configured or reg_configured
        torch_installed = importlib.util.find_spec("torch") is not None
        if not configured:
            status = "not_configured"
        elif torch_installed:
            status = "ready"
        else:
            status = "evidence_validation_only"
        return {
            "status": status,
            "checkpoint_dir_configured": ckpt_configured,
            "registry_root_configured": reg_configured,
            "native_inference_evaluation_wired": True,
            "torch_installed": torch_installed,
        }

    def _require_configured(self) -> tuple[Path, VersionedCheckpointManager | None]:
        if self.checkpoint_dir is None and self.registry_root is None:
            raise EvaluationNotConfiguredError(
                "checkpoint_dir or registry_root must be configured for evaluation"
            )
        if self.checkpoint_dir is not None:
            return self.checkpoint_dir, self.versions
        assert self.registry_root is not None
        return self.registry_root, None

    def _resolve_version_artifacts(
        self,
        model_version: str,
        *,
        checkpoint_id: str | None = None,
    ) -> dict[str, Any]:
        base_dir, versions = self._require_configured()
        if not isinstance(model_version, str) or not model_version.strip():
            raise EvaluationEvidenceError("model_version must be a non-empty string")

        # 1. Try VersionedCheckpointManager (version_manifest.json)
        if versions is not None and self.checkpoint_dir is not None:
            version = versions.get_version(model_version)
            if version:
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
                ckpt_file = version.get("checkpoint_file")
                if not ckpt_file:
                    raise EvaluationEvidenceError(f"checkpoint_file missing for {model_version}")
                ckpt_path = (self.checkpoint_dir / str(ckpt_file)).resolve()
                if not ckpt_path.is_relative_to(self.checkpoint_dir.resolve()) or not ckpt_path.is_file():
                    raise EvaluationEvidenceError(f"invalid checkpoint file for {model_version}")
                if self.registry_root is not None:
                    from apps.core.native.registry import ModelRegistry, RegistryError

                    reg_kwargs = {"load_fn": self._load_fn} if self._load_fn is not None else {}
                    reg = ModelRegistry(self.registry_root, **reg_kwargs)
                    try:
                        reg_rec = reg.get(model_version)
                    except RegistryError:
                        reg_rec = None
                    if reg_rec is not None:
                        if not reg.verify(model_version):
                            raise EvaluationEvidenceError(
                                f"registry artifact integrity check failed for model_version: {model_version}"
                            )
                        reg_ckpt_sha = (reg_rec.get("checkpoint") or {}).get("sha256")
                        if reg_ckpt_sha != version.get("checkpoint_sha256"):
                            raise EvaluationEvidenceError(
                                f"artifact mismatch between checkpoint_dir and registry for {model_version}"
                            )

                return {
                    **version,
                    "_source": "versioned_checkpoint",
                    "_checkpoint_path": ckpt_path,
                    "_tokenizer_path": self.checkpoint_dir / "tokenizer.json",
                    "_report_dir": self.checkpoint_dir,
                }

        # 2. Fallback / Direct load from ModelRegistry artifacts/<version>/
        if self.registry_root is not None:
            from apps.core.native.registry import ModelRegistry, RegistryError

            reg_kwargs = {"load_fn": self._load_fn} if self._load_fn is not None else {}
            reg = ModelRegistry(self.registry_root, **reg_kwargs)
            try:
                if not reg.verify(model_version):
                    raise EvaluationEvidenceError(
                        f"registry artifact integrity check failed for model_version: {model_version}"
                    )
                rec = reg.get(model_version)
            except RegistryError as exc:
                raise EvaluationEvidenceError(f"registry lookup failed for {model_version}: {exc}") from exc

            ckpt_info = rec.get("checkpoint") or {}
            tok_info = rec.get("tokenizer") or {}
            ds_info = rec.get("dataset") or {}
            ckpt_rel = str(ckpt_info.get("path") or "")
            tok_rel = str(tok_info.get("path") or "")
            ckpt_path = (self.registry_root / ckpt_rel).resolve()
            tok_path = (self.registry_root / tok_rel).resolve()
            if not ckpt_path.is_relative_to(self.registry_root.resolve()) or not ckpt_path.is_file():
                raise EvaluationEvidenceError(f"registry checkpoint missing for {model_version}")
            if not tok_path.is_relative_to(self.registry_root.resolve()) or not tok_path.is_file():
                raise EvaluationEvidenceError(f"registry tokenizer missing for {model_version}")
            if checkpoint_id is not None and checkpoint_id not in {
                ckpt_path.name,
                ckpt_info.get("sha256"),
                ckpt_rel,
            }:
                raise EvaluationEvidenceError(
                    f"checkpoint_id does not match model_version {model_version}"
                )
            report_dir = self.checkpoint_dir or (self.registry_root / "artifacts" / model_version)
            return {
                "model_version": model_version,
                "dataset_version": ds_info.get("version"),
                "dataset_content_hash": ds_info.get("content_sha256"),
                "checkpoint_file": ckpt_rel,
                "checkpoint_sha256": ckpt_info.get("sha256"),
                "tokenizer_sha256": tok_info.get("sha256"),
                "_source": "model_registry",
                "_checkpoint_path": ckpt_path,
                "_tokenizer_path": tok_path,
                "_report_dir": report_dir,
            }

        raise EvaluationEvidenceError(f"ไม่เจอ model_version: {model_version}")

    def verify_checkpoint_version(
        self,
        model_version: str,
        *,
        checkpoint_id: str | None = None,
    ) -> dict[str, Any]:
        resolved = self._resolve_version_artifacts(model_version, checkpoint_id=checkpoint_id)
        return {k: v for k, v in resolved.items() if not k.startswith("_")}

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
        if root.is_symlink() or not root.is_dir():
            raise EvaluationEvidenceError(f"dataset directory not found: {root}")
        manifest_path = root / "manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise EvaluationEvidenceError(f"dataset manifest.json not found in: {root}")
        try:
            raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EvaluationEvidenceError(
                f"dataset manifest.json is unreadable: {root}"
            ) from exc

        if not isinstance(raw_manifest, dict) or raw_manifest.get("schema") != DATASET_SCHEMA:
            raise EvaluationEvidenceError("unsupported or invalid dataset manifest schema")

        try:
            manifest = verify_dataset_manifest(root)
        except ValueError as exc:
            raise EvaluationEvidenceError(f"dataset integrity check failed: {exc}") from exc

        resolved_splits = resolve_dataset_splits(manifest)
        files = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
        splits_map = manifest.get("splits") if isinstance(manifest.get("splits"), dict) else {}

        def _split_doc_count(split_name: str) -> int:
            if f"{split_name}.jsonl" in files and isinstance(files[f"{split_name}.jsonl"], dict):
                entry = files[f"{split_name}.jsonl"]
                return int(entry.get("documents", entry.get("count", 0)) or 0)
            if split_name in splits_map and isinstance(splits_map[split_name], dict):
                entry = splits_map[split_name]
                return int(entry.get("documents", entry.get("count", 0)) or 0)
            return 0

        non_train_splits = tuple(s for s in resolved_splits if s != "train")
        eval_doc_count = sum(_split_doc_count(split) for split in non_train_splits)
        if eval_doc_count <= 0:
            raise EvaluationEvidenceError(
                "dataset contains no validation/evaluation documents for evaluation"
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
        resolved = self._resolve_version_artifacts(model_version)
        version = {k: v for k, v in resolved.items() if not k.startswith("_")}
        report_dir = Path(resolved["_report_dir"])

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

        validate_dir = self.checkpoint_dir if self.checkpoint_dir is not None else report_dir
        report = self.validator.validate(validate_dir, metrics)
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
        report_dir.mkdir(parents=True, exist_ok=True)
        out = (report_dir / f"evaluation_{model_version}.json").resolve()
        if not out.is_relative_to(report_dir.resolve()):
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
        splits: tuple[str, ...] | None = None,
        max_examples: int | None = None,
        max_new_tokens: int = 32,
        use_slots: bool | None = None,
        device: str = "cpu",
        capability_pass_threshold: float = 0.5,
    ) -> dict[str, Any]:
        """Execute greedy native ZyrquenModel inference over verified SFT splits."""
        self._require_configured()
        try:
            import torch
            from apps.core.native.model import ZyrquenModel
            from apps.core.native.registry import _safe_torch_load
            from apps.core.workflow.resource_guard import MAX_CPU_THREADS, enforce_cpu_thread_cap
        except ModuleNotFoundError as exc:
            raise EvaluationNotConfiguredError(
                "PyTorch runtime is not installed; native inference evaluation cannot run"
            ) from exc

        if str(device).startswith("cpu"):
            enforce_cpu_thread_cap(MAX_CPU_THREADS, torch_mod=torch)

        resolved = self._resolve_version_artifacts(model_version)
        version = {k: v for k, v in resolved.items() if not k.startswith("_")}
        ckpt_path = Path(resolved["_checkpoint_path"])
        default_tok_path = Path(resolved["_tokenizer_path"])

        manifest = self.verify_dataset(
            dataset_dir,
            expected_version=version.get("dataset_version"),
            expected_checksum=version.get("dataset_content_hash"),
        )
        if detect_dataset_format(dataset_dir) != "sft":
            raise EvaluationEvidenceError(
                "evaluate_native_model requires an SFT dataset with 'input' and 'target' fields"
            )

        tok_candidate = Path(tokenizer_path) if tokenizer_path else default_tok_path
        if not tok_candidate.is_file() or tok_candidate.is_symlink():
            raise EvaluationEvidenceError(
                f"tokenizer.json missing or symlinked: {tok_candidate}"
            )
        try:
            tok = ZyrquenTokenizer.load(tok_candidate)
        except (OSError, ValueError, KeyError) as exc:
            raise EvaluationEvidenceError(f"failed to load tokenizer: {exc}") from exc

        loader = self._load_fn or _safe_torch_load
        state = loader(str(ckpt_path))
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
        manifest_splits = resolve_dataset_splits(manifest)
        is_v11_dataset = (
            manifest.get("dataset") == "nagi_v11"
            or ("unseen" in manifest_splits and "ood" in manifest_splits)
        )
        if splits is None:
            resolved_splits = ("validation", "unseen", "ood") if is_v11_dataset else ("validation", "test")
        else:
            resolved_splits = tuple(splits)

        is_slot_dataset = manifest.get("dataset") in {"nagi_v10", "nagi_v11"}
        resolved_slots = use_slots if use_slots is not None else is_slot_dataset

        total_examples = 0
        total_correct = 0
        eos_hits = 0
        split_stats: dict[str, dict[str, Any]] = {}
        cap_stats: dict[str, dict[str, int]] = {}
        split_cap_stats: dict[str, dict[str, dict[str, int]]] = {}
        unseen_entity_total = 0
        unseen_entity_correct = 0

        for split_name in resolved_splits:
            records = list(load_sft_split(dataset_dir, split_name))
            if max_examples is not None and max_examples > 0:
                records = records[:max_examples]
            split_correct = 0
            split_total = 0
            split_entity_total = 0
            split_entity_correct = 0
            split_caps: dict[str, dict[str, int]] = {}
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
                    raise EvaluationEvidenceError(
                        f"encoded prompt length ({len(prefix_ids)}) exceeds or equals model max_seq_len ({cfg.max_seq_len}); silent truncation is forbidden"
                    )
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

                if extract_entities(expected_target):
                    split_entity_total += 1
                    if is_match:
                        split_entity_correct += 1
                    if split_name in {"unseen", "ood"}:
                        unseen_entity_total += 1
                        if is_match:
                            unseen_entity_correct += 1

                bucket = cap_stats.setdefault(cap, {"correct": 0, "total": 0})
                bucket["total"] += 1
                if is_match:
                    bucket["correct"] += 1

                sc_bucket = split_caps.setdefault(cap, {"correct": 0, "total": 0})
                sc_bucket["total"] += 1
                if is_match:
                    sc_bucket["correct"] += 1

                cap_by_split = split_cap_stats.setdefault(cap, {}).setdefault(
                    split_name, {"correct": 0, "total": 0}
                )
                cap_by_split["total"] += 1
                if is_match:
                    cap_by_split["correct"] += 1

            split_entry: dict[str, Any] = {
                "total": split_total,
                "evaluated": split_total,
                "correct": split_correct,
                "exact_match": (split_correct / split_total) if split_total else 0.0,
                "per_capability": {
                    cap: {
                        "total": cnt["total"],
                        "correct": cnt["correct"],
                        "exact_match": round((cnt["correct"] / cnt["total"]) if cnt["total"] else 0.0, 6),
                    }
                    for cap, cnt in sorted(split_caps.items())
                },
            }
            if split_name == "train":
                split_entry["diagnostic_only"] = True
            if split_entity_total > 0:
                split_entry["unseen_entity_copy_acc"] = round(
                    split_entity_correct / split_entity_total, 6
                )
            split_stats[split_name] = split_entry

        if total_examples == 0:
            raise EvaluationEvidenceError("no evaluation examples executed")

        exact_match = total_correct / total_examples
        eos_hit_rate = eos_hits / total_examples
        capability_eval: dict[str, dict[str, Any]] = {}
        for cap, counts in sorted(cap_stats.items()):
            acc = counts["correct"] / counts["total"] if counts["total"] else 0.0
            per_split_info: dict[str, dict[str, Any]] = {}
            for sp_name, sp_cnt in split_cap_stats.get(cap, {}).items():
                sp_acc = sp_cnt["correct"] / sp_cnt["total"] if sp_cnt["total"] else 0.0
                per_split_info[sp_name] = {
                    "status": "PASS" if sp_acc >= capability_pass_threshold else "FAIL",
                    "accuracy": round(sp_acc, 6),
                    "exact_match": round(sp_acc, 6),
                    "correct": sp_cnt["correct"],
                    "total": sp_cnt["total"],
                }
            capability_eval[cap] = {
                "status": "PASS" if acc >= capability_pass_threshold else "FAIL",
                "accuracy": round(acc, 6),
                "correct": counts["correct"],
                "total": counts["total"],
                "splits": per_split_info,
            }

        metrics: dict[str, Any] = {
            "exact_match": round(exact_match, 6),
            "eos_hit_rate": round(eos_hit_rate, 6),
            "examples_evaluated": float(total_examples),
        }
        for split_name, st in split_stats.items():
            metrics[f"{split_name}_exact_match"] = round(st["exact_match"], 6)
        if "train" in split_stats and "unseen" in split_stats:
            metrics["overfit_gap"] = round(
                split_stats["train"]["exact_match"] - split_stats["unseen"]["exact_match"], 6
            )
        if "unseen" in split_stats and "ood" in split_stats:
            metrics["ood_transfer_gap"] = round(
                split_stats["unseen"]["exact_match"] - split_stats["ood"]["exact_match"], 6
            )
        if unseen_entity_total > 0:
            metrics["unseen_entity_copy_acc"] = round(
                unseen_entity_correct / unseen_entity_total, 6
            )
        for cap, info in capability_eval.items():
            metrics[f"cap_{cap}_accuracy"] = info["accuracy"]
            for sp_name, sp_info in info["splits"].items():
                metrics[f"cap_{cap}_{sp_name}_accuracy"] = sp_info["accuracy"]

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
