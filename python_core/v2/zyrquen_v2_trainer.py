from __future__ import annotations

import ast
import hashlib
import json
import math
import random
import re
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    from checkpoint_hash import compute_file_sha256, save_checkpoint_sha256
except ImportError:
    from python_core.checkpoint_hash import compute_file_sha256, save_checkpoint_sha256

PAD_TOKEN_ID = 256
EOS_TOKEN_ID = 257
BYTE_VOCAB_SIZE = 258
IGNORE_INDEX = -100


def _norm_code(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def _extract_function_names(code: str) -> set[str]:
    names: set[str] = set()
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.add(node.name)
    except SyntaxError:
        for m in re.finditer(r"def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", code):
            names.add(m.group(1))
    return names


@dataclass
class CodingTask:
    task_id: str
    prompt: str
    test_code: str
    reference_solution: str = ""
    family: str = "general"
    category: str = "general"  # "regression" or "unseen"


@dataclass
class EvalReport:
    avg_loss: Optional[float]
    exec_pass_rate: float
    passed_count: int
    total_count: int
    details: List[Dict[str, Any]] = field(default_factory=list)
    error_breakdown: Dict[str, int] = field(default_factory=dict)


@dataclass
class GateDecision:
    approved: bool
    reason: str
    baseline_unseen: float
    candidate_unseen: float
    baseline_regression: float
    candidate_regression: float
    leakage_count: int = 0


class ByteTokenizer:
    """Lossless UTF-8 byte tokenizer (0..255) with dedicated PAD=256 and EOS=257."""

    pad_id: int = PAD_TOKEN_ID
    eos_id: int = EOS_TOKEN_ID
    vocab_size: int = BYTE_VOCAB_SIZE

    def encode(self, text: str, *, add_eos: bool = False) -> List[int]:
        ids = list(text.encode("utf-8", errors="replace"))
        if add_eos:
            ids.append(self.eos_id)
        return ids

    def decode(self, ids: Iterable[int], *, stop_at_eos: bool = True) -> str:
        raw_bytes: List[int] = []
        for idx in ids:
            val = int(idx)
            if val == self.eos_id:
                if stop_at_eos:
                    break
                continue
            if val == self.pad_id or val < 0 or val > 255:
                continue
            raw_bytes.append(val)
        return bytes(raw_bytes).decode("utf-8", errors="replace")


def detect_task_leakage(
    train_texts: Sequence[str],
    eval_tasks: Sequence[CodingTask],
) -> List[Dict[str, str]]:
    """Verify zero text or function-name leakage between training texts and evaluation tasks."""
    train_norms = {_norm_code(t) for t in train_texts if _norm_code(t)}
    train_fn_names: set[str] = set()
    for t in train_texts:
        train_fn_names |= _extract_function_names(t)

    leaks: List[Dict[str, str]] = []
    for task in eval_tasks:
        ref_norm = _norm_code(task.reference_solution)
        prompt_norm = _norm_code(task.prompt)
        if ref_norm and ref_norm in train_norms:
            leaks.append({"task_id": task.task_id, "reason": "exact_reference_in_train"})
            continue
        if prompt_norm and any(prompt_norm in tn for tn in train_norms):
            leaks.append({"task_id": task.task_id, "reason": "prompt_substring_in_train"})
            continue
        task_fns = _extract_function_names(task.prompt) | _extract_function_names(
            task.reference_solution
        )
        overlap = sorted(task_fns & train_fn_names)
        if overlap:
            leaks.append(
                {
                    "task_id": task.task_id,
                    "reason": f"function_name_overlap:{','.join(overlap)}",
                }
            )
    return leaks


def extract_first_python_function(code: str) -> str:
    """Trim trailing partial tokens/incomplete lines while preserving valid helper + target functions."""
    lines = code.splitlines()
    if not lines:
        return ""
    for end in range(len(lines), 0, -1):
        candidate = "\n".join(lines[:end]).rstrip() + "\n"
        try:
            ast.parse(candidate)
            return candidate
        except SyntaxError:
            continue
    return code


def run_code_in_sandbox(
    candidate_code: str, test_code: str, timeout_sec: float = 2.0
) -> Tuple[bool, str]:
    """Validate AST and execute candidate Python code + assertions in isolated (-I) subprocess."""
    cleaned_code = extract_first_python_function(candidate_code)
    try:
        ast.parse(cleaned_code)
    except SyntaxError as exc:
        return False, f"SyntaxError: {exc.msg} (line {exc.lineno})"

    combined = (
        f"{cleaned_code}\n\n"
        f"# --- Verification Harness ---\n"
        f"{test_code}\n"
        f"print('__ZYRQUEN_SANDBOX_PASS__')\n"
    )
    with tempfile.NamedTemporaryFile(
        "w", suffix=".py", delete=True, encoding="utf-8"
    ) as tmp:
        tmp.write(combined)
        tmp.flush()
        try:
            proc = subprocess.run(
                [sys.executable, "-I", tmp.name],
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
            ok = proc.returncode == 0 and "__ZYRQUEN_SANDBOX_PASS__" in (
                proc.stdout or ""
            )
            msg = (proc.stderr or proc.stdout or "").strip()[-240:]
            return ok, msg
        except subprocess.TimeoutExpired:
            return False, "timeout"
        except Exception as exc:
            return False, str(exc)[:240]


class ApprovalGate:
    """Strict fail-closed gate: requires real unseen gain, >0 unseen solved, zero leakage, and no regression."""

    def __init__(
        self,
        min_unseen_gain: float = 0.01,
        max_regression_drop: float = 0.05,
        require_non_zero_unseen: bool = True,
    ) -> None:
        self.min_unseen_gain = min_unseen_gain
        self.max_regression_drop = max_regression_drop
        self.require_non_zero_unseen = require_non_zero_unseen

    def evaluate(
        self,
        baseline_unseen: EvalReport,
        candidate_unseen: EvalReport,
        baseline_regression: EvalReport,
        candidate_regression: EvalReport,
        *,
        leakage_count: int = 0,
    ) -> GateDecision:
        if leakage_count > 0:
            return GateDecision(
                approved=False,
                reason=f"BLOCKED: detected {leakage_count} data leakage item(s) in unseen evaluation",
                baseline_unseen=baseline_unseen.exec_pass_rate,
                candidate_unseen=candidate_unseen.exec_pass_rate,
                baseline_regression=baseline_regression.exec_pass_rate,
                candidate_regression=candidate_regression.exec_pass_rate,
                leakage_count=leakage_count,
            )

        if self.require_non_zero_unseen and candidate_unseen.passed_count <= 0:
            return GateDecision(
                approved=False,
                reason="Candidate solved 0 unseen tasks in sandbox execution",
                baseline_unseen=baseline_unseen.exec_pass_rate,
                candidate_unseen=candidate_unseen.exec_pass_rate,
                baseline_regression=baseline_regression.exec_pass_rate,
                candidate_regression=candidate_regression.exec_pass_rate,
                leakage_count=0,
            )

        unseen_gain = candidate_unseen.exec_pass_rate - baseline_unseen.exec_pass_rate
        reg_drop = baseline_regression.exec_pass_rate - candidate_regression.exec_pass_rate

        if unseen_gain < self.min_unseen_gain:
            return GateDecision(
                approved=False,
                reason=(
                    f"Unseen pass gain {unseen_gain:+.2f} below required "
                    f"+{self.min_unseen_gain:.2f}"
                ),
                baseline_unseen=baseline_unseen.exec_pass_rate,
                candidate_unseen=candidate_unseen.exec_pass_rate,
                baseline_regression=baseline_regression.exec_pass_rate,
                candidate_regression=candidate_regression.exec_pass_rate,
                leakage_count=0,
            )
        if reg_drop > self.max_regression_drop:
            return GateDecision(
                approved=False,
                reason=(
                    f"Regression drop {reg_drop:.2f} exceeds max allowed "
                    f"{self.max_regression_drop:.2f}"
                ),
                baseline_unseen=baseline_unseen.exec_pass_rate,
                candidate_unseen=candidate_unseen.exec_pass_rate,
                baseline_regression=baseline_regression.exec_pass_rate,
                candidate_regression=candidate_regression.exec_pass_rate,
                leakage_count=0,
            )
        return GateDecision(
            approved=True,
            reason="Passed unseen improvement, zero-leakage, and regression safety gates",
            baseline_unseen=baseline_unseen.exec_pass_rate,
            candidate_unseen=candidate_unseen.exec_pass_rate,
            baseline_regression=baseline_regression.exec_pass_rate,
            candidate_regression=candidate_regression.exec_pass_rate,
            leakage_count=0,
        )


ERROR_TYPES: Tuple[str, ...] = (
    "passed",
    "SyntaxError",
    "NameError",
    "TypeError",
    "AssertionError",
    "timeout",
    "other",
)


def classify_sandbox_failure(passed: bool, info: str) -> str:
    """Classify sandbox outcome into an explicit, auditable error category."""
    if passed:
        return "passed"
    text = str(info or "")
    if text == "timeout":
        return "timeout"
    if "IndentationError" in text or "TabError" in text or "SyntaxError" in text:
        return "SyntaxError"
    for err_type in ("NameError", "TypeError", "AssertionError"):
        if err_type in text:
            return err_type
    return "other"


def compute_error_breakdown(details: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """Summarize execution pass and categorized failure counts across evaluation details."""
    counts = Counter(
        classify_sandbox_failure(bool(d.get("passed")), str(d.get("info", "")))
        for d in details
    )
    return {err_type: int(counts.get(err_type, 0)) for err_type in ERROR_TYPES}


def record_checkpoint_approval(
    checkpoint_path: str | Path,
    sha256: str,
    decision: GateDecision,
    *,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Persist fail-closed checkpoint approval status alongside the checkpoint artifact."""
    ckpt = Path(checkpoint_path)
    # Fail-closed invariant: never permit approval if safety/leakage/unseen constraints failed
    strict_approved = bool(
        decision.approved
        and decision.leakage_count == 0
        and decision.candidate_unseen > 0.0
    )
    record: Dict[str, Any] = {
        "schema": "zyrquen.v2.checkpoint_approval",
        "checkpoint_path": str(ckpt),
        "checkpoint_sha256": sha256,
        "approved": strict_approved,
        "status": "APPROVED" if strict_approved else "REJECTED_BY_GATE",
        "approved_checkpoint": str(ckpt) if strict_approved else None,
        "gate": asdict(decision),
    }
    if metadata:
        record["metadata"] = metadata
    approval_path = ckpt.with_suffix(ckpt.suffix + ".approval.json")
    approval_path.parent.mkdir(parents=True, exist_ok=True)
    approval_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    record["approval_record_path"] = str(approval_path)
    return record


class SandboxEvaluator:
    """Evaluates models via reference-solution loss, raw output capture, and isolated sandbox execution."""

    def __init__(
        self,
        generate_fn: Callable[[str], str],
        loss_fn: Callable[[List[str]], Optional[float]],
    ) -> None:
        self.generate_fn = generate_fn
        self.loss_fn = loss_fn

    def evaluate(self, tasks: List[CodingTask]) -> EvalReport:
        if not tasks:
            return EvalReport(
                avg_loss=None,
                exec_pass_rate=0.0,
                passed_count=0,
                total_count=0,
                details=[],
                error_breakdown={err_type: 0 for err_type in ERROR_TYPES},
            )

        loss_texts = [
            t.reference_solution if t.reference_solution else t.prompt for t in tasks
        ]
        avg_loss = self.loss_fn(loss_texts)
        passed = 0
        details: List[Dict[str, Any]] = []

        for task in tasks:
            raw_output = self.generate_fn(task.prompt)
            extracted_code = extract_first_python_function(raw_output)
            ok, msg = run_code_in_sandbox(raw_output, task.test_code)
            err_type = classify_sandbox_failure(ok, msg)
            if ok:
                passed += 1
            details.append(
                {
                    "task_id": task.task_id,
                    "family": task.family,
                    "passed": ok,
                    "error_type": err_type,
                    "info": msg,
                    "raw_output": raw_output,
                    "extracted_code": extracted_code,
                }
            )

        return EvalReport(
            avg_loss=avg_loss,
            exec_pass_rate=passed / len(tasks),
            passed_count=passed,
            total_count=len(tasks),
            details=details,
            error_breakdown=compute_error_breakdown(details),
        )


def _require_torch():
    try:
        import torch
        import torch.nn.functional as F

        return torch, F
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "PyTorch ('torch') is required to run ContinualTrainerV2. "
            "Run this training engine in a PyTorch environment."
        ) from exc


def _sha256_file(path: Path) -> str:
    return compute_file_sha256(path)


class ContinualTrainerV2:
    """Trainer supporting full optimizer/scheduler resume, masked loss, replay buffer, and consolidation."""

    def __init__(
        self,
        model: Any,
        tokenizer: ByteTokenizer,
        lr: float = 3e-4,
        min_lr_ratio: float = 0.1,
        warmup_steps: int = 20,
        total_decay_steps: int = 400,
        weight_decay: float = 0.01,
        replay_capacity: int = 256,
        consolidation_lambda: float = 0.05,
        seed: int = 42,
        device: Optional[Any] = None,
    ) -> None:
        torch, _ = _require_torch()
        from v2.tpu_backend import resolve_torch_device

        self.device = resolve_torch_device(device)
        self.model = model.to(self.device)
        self.tokenizer = tokenizer
        self.base_lr = lr
        self.min_lr_ratio = min_lr_ratio
        self.warmup_steps = max(1, warmup_steps)
        self.total_decay_steps = max(self.warmup_steps + 1, total_decay_steps)
        self.consolidation_lambda = consolidation_lambda
        self.rng = random.Random(seed)

        self.optimizer = torch.optim.AdamW(
            self.model.parameters(),
            lr=lr,
            betas=(0.9, 0.95),
            weight_decay=weight_decay,
        )

        def _lr_lambda(step: int) -> float:
            if step < self.warmup_steps:
                return max(self.min_lr_ratio, float(step + 1) / float(self.warmup_steps))
            if step >= self.total_decay_steps:
                return self.min_lr_ratio
            progress = float(step - self.warmup_steps) / float(
                self.total_decay_steps - self.warmup_steps
            )
            cosine = 0.5 * (1.0 + math.cos(math.pi * progress))
            return self.min_lr_ratio + (1.0 - self.min_lr_ratio) * cosine

        self.scheduler = torch.optim.lr_scheduler.LambdaLR(
            self.optimizer, lr_lambda=_lr_lambda
        )
        self.replay_buffer: List[str] = []
        self.replay_capacity = replay_capacity
        self.anchor_params: Dict[str, Any] = {}
        self.importance_diag: Dict[str, Any] = {}
        self.global_step: int = 0

    def add_replay_samples(self, samples: List[str]) -> None:
        for s in samples:
            if s in self.replay_buffer:
                continue
            if len(self.replay_buffer) < self.replay_capacity:
                self.replay_buffer.append(s)
            else:
                idx = self.rng.randrange(self.replay_capacity)
                self.replay_buffer[idx] = s

    def _encode_batch(self, texts: List[str]):
        torch, _ = _require_torch()
        max_len = self.model.cfg.max_seq_len
        encoded = [self.tokenizer.encode(t, add_eos=True)[:max_len] for t in texts]
        longest = max((len(seq) for seq in encoded), default=2)
        longest = max(2, min(longest, max_len))
        pad_id = self.tokenizer.pad_id

        input_rows: List[List[int]] = []
        target_rows: List[List[int]] = []
        mask_rows: List[List[bool]] = []
        for seq in encoded:
            pad_len = longest - len(seq)
            padded = seq + [pad_id] * pad_len
            input_rows.append(padded[:-1])
            target_rows.append(
                [tok if tok != pad_id else IGNORE_INDEX for tok in padded[1:]]
            )
            mask_rows.append([tok != pad_id for tok in padded[:-1]])

        return (
            torch.tensor(input_rows, dtype=torch.long, device=self.device),
            torch.tensor(target_rows, dtype=torch.long, device=self.device),
            torch.tensor(mask_rows, dtype=torch.bool, device=self.device),
        )

    def snapshot_consolidation_state(self, texts: List[str], batch_size: int = 4) -> None:
        torch, F = _require_torch()
        self.model.eval()
        self.anchor_params = {
            name: param.detach().clone()
            for name, param in self.model.named_parameters()
            if param.requires_grad
        }
        acc_imp = {
            name: torch.zeros_like(param, device=self.device)
            for name, param in self.model.named_parameters()
            if param.requires_grad
        }
        if not texts:
            self.importance_diag = acc_imp
            return

        self.model.train()
        self.optimizer.zero_grad(set_to_none=True)
        batches = 0
        for i in range(0, len(texts), batch_size):
            x, y, mask = self._encode_batch(texts[i : i + batch_size])
            if x.shape[1] < 1:
                continue
            logits = self.model(x, attention_mask=mask)
            loss = F.cross_entropy(
                logits.reshape(-1, logits.shape[-1]),
                y.reshape(-1),
                ignore_index=IGNORE_INDEX,
            )
            loss.backward()
            for name, param in self.model.named_parameters():
                if param.requires_grad and param.grad is not None:
                    acc_imp[name] += param.grad.detach() ** 2
            self.optimizer.zero_grad(set_to_none=True)
            batches += 1

        denom = max(batches, 1)
        self.importance_diag = {name: val / denom for name, val in acc_imp.items()}

    def _consolidation_loss(self):
        torch, _ = _require_torch()
        if not self.anchor_params or self.consolidation_lambda <= 0.0:
            return torch.tensor(0.0, device=self.device)
        pen = torch.tensor(0.0, device=self.device)
        for name, param in self.model.named_parameters():
            if param.requires_grad and name in self.anchor_params:
                imp = self.importance_diag.get(name, 1.0)
                pen = pen + (imp * (param - self.anchor_params[name]) ** 2).sum()
        return self.consolidation_lambda * pen

    def train_steps(
        self,
        train_texts: List[str],
        steps: int = 40,
        batch_size: int = 4,
        replay_ratio: float = 0.5,
        grad_clip: float = 1.0,
    ) -> Dict[str, float]:
        torch, F = _require_torch()
        if not train_texts:
            return {"steps": 0, "final_loss": 0.0, "global_step": self.global_step}

        self.model.train()
        last_loss = 0.0
        for _ in range(steps):
            chosen = self.rng.choices(train_texts, k=batch_size)
            if self.replay_buffer and replay_ratio > 0.0:
                n_replay = int(round(batch_size * replay_ratio))
                n_replay = min(n_replay, len(self.replay_buffer), batch_size)
                if n_replay > 0:
                    chosen = chosen[: batch_size - n_replay] + self.rng.sample(
                        self.replay_buffer, n_replay
                    )

            x, y, mask = self._encode_batch(chosen)
            if x.shape[1] < 1:
                continue

            self.optimizer.zero_grad(set_to_none=True)
            logits = self.model(x, attention_mask=mask)
            ce_loss = F.cross_entropy(
                logits.reshape(-1, logits.shape[-1]),
                y.reshape(-1),
                ignore_index=IGNORE_INDEX,
            )
            total_loss = ce_loss + self._consolidation_loss()
            if torch.isnan(total_loss) or torch.isinf(total_loss):
                raise RuntimeError("Training halted: NaN/Inf loss detected")

            total_loss.backward()
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), grad_clip)
            self.optimizer.step()
            from v2.tpu_backend import tpu_sync_step

            tpu_sync_step(self.device)
            self.scheduler.step()
            self.global_step += 1
            last_loss = float(ce_loss.item())

        self.add_replay_samples(train_texts)
        return {
            "steps": steps,
            "final_loss": last_loss,
            "global_step": self.global_step,
        }

    def save_checkpoint(self, path: str | Path) -> Tuple[Path, str]:
        torch, _ = _require_torch()
        out_path = Path(path)
        if out_path.exists():
            raise FileExistsError(
                f"Refusing to overwrite existing checkpoint: {out_path}"
            )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        from v2.tpu_backend import state_dict_to_cpu

        payload = {
            "schema": "zyrquen.v2.checkpoint",
            "config": self.model.cfg.__dict__,
            "model_state_dict": state_dict_to_cpu(self.model.state_dict()),
            "optimizer_state_dict": self.optimizer.state_dict(),
            "scheduler_state_dict": self.scheduler.state_dict(),
            "replay_buffer": self.replay_buffer,
            "anchor_params": {k: v.cpu() for k, v in self.anchor_params.items()},
            "importance_diag": {k: v.cpu() for k, v in self.importance_diag.items()},
            "global_step": self.global_step,
        }
        torch.save(payload, out_path)
        _, digest = save_checkpoint_sha256(out_path)
        return out_path, digest

    @classmethod
    def load_checkpoint(
        cls,
        path: str | Path,
        tokenizer: ByteTokenizer,
        *,
        expected_sha256: Optional[str] = None,
        resume_optimizer: bool = True,
        restore_continual_state: bool = True,
        consolidation_lambda: Optional[float] = None,
        device: Optional[Any] = None,
    ) -> "ContinualTrainerV2":
        torch, _ = _require_torch()
        from v2.tpu_backend import resolve_torch_device
        from v2.zyrquen_v2_model import NativeTransformerLMV2, ZyrquenV2Config

        ckpt_path = Path(path)
        if expected_sha256 is not None:
            actual = _sha256_file(ckpt_path)
            if actual != expected_sha256:
                raise ValueError("Checkpoint SHA-256 verification failed")

        dev = resolve_torch_device(device)
        ckpt = torch.load(ckpt_path, map_location="cpu")
        cfg = ZyrquenV2Config(**ckpt["config"])
        model = NativeTransformerLMV2(cfg)
        model.load_state_dict(ckpt["model_state_dict"], strict=True)

        trainer = cls(
            model=model,
            tokenizer=tokenizer,
            consolidation_lambda=(
                0.05 if consolidation_lambda is None else consolidation_lambda
            ),
            device=dev,
        )
        trainer.global_step = int(ckpt.get("global_step", 0)) if resume_optimizer else 0
        if restore_continual_state:
            trainer.replay_buffer = list(ckpt.get("replay_buffer", []))
            trainer.anchor_params = {
                k: v.to(dev) for k, v in ckpt.get("anchor_params", {}).items()
            }
            trainer.importance_diag = {
                k: v.to(dev) for k, v in ckpt.get("importance_diag", {}).items()
            }

        if resume_optimizer and "optimizer_state_dict" in ckpt:
            trainer.optimizer.load_state_dict(ckpt["optimizer_state_dict"])
        if resume_optimizer and "scheduler_state_dict" in ckpt:
            trainer.scheduler.load_state_dict(ckpt["scheduler_state_dict"])
        return trainer
