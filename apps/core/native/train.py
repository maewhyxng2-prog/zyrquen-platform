"""Phase 3.4 training pipeline for the ZYRQUEN native model.

Pure-Python parts (token stream, batch sampling, LR schedule) are unit-tested without
torch. The training loop itself needs torch and has NOT been run in the authoring
environment - run apps/core/native/test_train.py with torch installed first.
"""
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


STRICT_MAX_BATCH_SIZE = 4
STRICT_BLOCK_SIZE = 256
STRICT_MAX_SEGMENT_STEPS = 500
ALLOWED_MIXED_PRECISION = frozenset({"off", "auto", "bf16", "fp16"})


def resolve_amp_dtype(
    device: str,
    mixed_precision: str = "off",
    torch_mod=None,
) -> str | None:
    """Resolve hardware-gated AMP dtype ('bfloat16' | 'float16' | None).

    Pure-Python safe: returns None whenever CPU device or CUDA unavailable.
    """
    if mixed_precision not in ALLOWED_MIXED_PRECISION:
        raise ValueError(
            f"mixed_precision={mixed_precision!r} must be one of {sorted(ALLOWED_MIXED_PRECISION)}"
        )
    if mixed_precision == "off" or str(device).startswith("cpu"):
        return None
    if torch_mod is None:
        return None
    cuda = getattr(torch_mod, "cuda", None)
    if cuda is None or not callable(getattr(cuda, "is_available", None)) or not cuda.is_available():
        return None
    bf16_ok = bool(callable(getattr(cuda, "is_bf16_supported", None)) and cuda.is_bf16_supported())
    if mixed_precision == "bf16":
        return "bfloat16" if bf16_ok else None
    if mixed_precision == "fp16":
        return "float16"
    return "bfloat16" if bf16_ok else "float16"


def validate_strict_resource_limits(cfg: "TrainConfig") -> None:
    """Enforce strict Tier-0 CPU resource limits: batch_size <= 4, block_size == 256, segment <= 500."""
    if cfg.batch_size > STRICT_MAX_BATCH_SIZE:
        raise ValueError(
            f"batch_size={cfg.batch_size} exceeds strict resource limit ({STRICT_MAX_BATCH_SIZE})"
        )
    if cfg.block_size != STRICT_BLOCK_SIZE:
        raise ValueError(
            f"block_size={cfg.block_size} violates strict resource limit (must equal {STRICT_BLOCK_SIZE})"
        )
    if cfg.segment_max_steps is None or cfg.segment_max_steps > STRICT_MAX_SEGMENT_STEPS:
        raise ValueError(
            f"segment_max_steps={cfg.segment_max_steps} violates strict resource limit (must be 1..{STRICT_MAX_SEGMENT_STEPS})"
        )


@dataclass(frozen=True)
class TrainConfig:
    block_size: int = 128
    batch_size: int = 16
    grad_accum_steps: int = 1
    max_steps: int = 1000
    lr: float = 3e-4
    min_lr: float = 3e-5
    warmup_steps: int = 100
    weight_decay: float = 0.1
    grad_clip: float = 1.0
    eval_interval: int = 200
    eval_batches: int = 20
    checkpoint_interval: int = 200
    log_interval: int = 10
    seed: int = 1337
    segment_max_steps: int | None = None
    lr_total_steps: int | None = None
    stage_id: int | None = None
    experiment_index: int | None = None
    strict_limits: bool = False
    mixed_precision: str = "off"

    def __post_init__(self):
        if self.block_size < 2 or self.batch_size < 1 or self.grad_accum_steps < 1 or self.max_steps < 1:
            raise ValueError("invalid training sizes")
        if self.mixed_precision not in ALLOWED_MIXED_PRECISION:
            raise ValueError("invalid mixed_precision setting")
        if self.segment_max_steps is not None and self.segment_max_steps < 1:
            raise ValueError("segment_max_steps must be >= 1")
        if self.lr_total_steps is not None and self.lr_total_steps < 1:
            raise ValueError("lr_total_steps must be >= 1")
        if self.stage_id is not None and self.stage_id < 1:
            raise ValueError("stage_id must be >= 1")
        if self.experiment_index is not None and self.experiment_index < 1:
            raise ValueError("experiment_index must be >= 1")
        horizon = self.lr_total_steps if self.lr_total_steps is not None else self.max_steps
        if not (0 < self.min_lr <= self.lr) or not (0 <= self.warmup_steps < horizon):
            raise ValueError("invalid learning-rate settings")
        if self.strict_limits:
            validate_strict_resource_limits(self)

    def validate_strict_limits(self) -> None:
        """Validate this config against strict Tier-0 resource limits."""
        validate_strict_resource_limits(self)

    @classmethod
    def tier0_v11(
        cls,
        *,
        max_steps: int = 500,
        segment_max_steps: int | None = 500,
        lr_total_steps: int | None = 10_000,
        stage_id: int | None = None,
        experiment_index: int | None = None,
        strict_limits: bool = True,
        **overrides,
    ) -> "TrainConfig":
        """Canonical V11-Tier0 CPU-safe config (`batch_size <= 4`, `block_size == 256`, `segment <= 500`)."""
        params = {
            "block_size": STRICT_BLOCK_SIZE,
            "batch_size": STRICT_MAX_BATCH_SIZE,
            "grad_accum_steps": 1,
            "max_steps": max_steps,
            "lr": 3e-4,
            "min_lr": 3e-5,
            "warmup_steps": 100,
            "weight_decay": 0.1,
            "grad_clip": 1.0,
            "eval_interval": 250,
            "eval_batches": 20,
            "checkpoint_interval": 250,
            "log_interval": 10,
            "seed": 1337,
            "segment_max_steps": segment_max_steps,
            "lr_total_steps": lr_total_steps,
            "stage_id": stage_id,
            "experiment_index": experiment_index,
            "strict_limits": strict_limits,
        }
        params.update(overrides)
        return cls(**params)


# ---- pure-python helpers ----
def lr_at(step: int, cfg: TrainConfig) -> float:
    """Linear warm-up then cosine decay to min_lr across `lr_total_steps or max_steps`. `step` is 0-based."""
    total_steps = cfg.lr_total_steps if cfg.lr_total_steps is not None else cfg.max_steps
    if cfg.warmup_steps > 0 and step < cfg.warmup_steps:
        return cfg.lr * (step + 1) / cfg.warmup_steps
    if step >= total_steps:
        return cfg.min_lr
    progress = (step - cfg.warmup_steps) / max(1, total_steps - cfg.warmup_steps)
    return cfg.min_lr + 0.5 * (1 + math.cos(math.pi * progress)) * (cfg.lr - cfg.min_lr)


def build_token_stream(
    texts: Iterable[str], tokenizer, max_tokens: int | None = None
) -> list[int]:
    """Concatenate documents, each followed by <|eos|>."""
    ids: list[int] = []
    for text in texts:
        document_ids = tokenizer.encode(text, add_eos=True)
        if max_tokens is not None and len(ids) + len(document_ids) > max_tokens:
            raise TokenStreamLimitExceeded(
                f"token stream exceeds the {max_tokens}-token limit"
            )
        ids.extend(document_ids)
    return ids


class TokenStreamLimitExceeded(ValueError):
    """Raised when an encoded corpus exceeds its configured memory bound."""


def sample_batch(ids: list[int], block_size: int, batch_size: int,
                 rng: random.Random) -> tuple[list[list[int]], list[list[int]]]:
    """Random windows; targets are inputs shifted by one token."""
    if len(ids) < block_size + 1:
        raise ValueError("token stream shorter than block_size + 1")
    xs, ys = [], []
    for _ in range(batch_size):
        i = rng.randrange(0, len(ids) - block_size)
        xs.append(ids[i:i + block_size])
        ys.append(ids[i + 1:i + block_size + 1])
    return xs, ys


def perplexity(loss: float) -> float:
    return math.exp(min(loss, 50.0))


def _training_resume_identity(cfg: TrainConfig) -> dict:
    """Stable optimizer/data sampling settings across segmented resume."""
    ignored = {"max_steps", "segment_max_steps", "stage_id", "experiment_index"}
    return {key: value for key, value in cfg.__dict__.items() if key not in ignored}


# ---- torch training loop (not run in authoring environment) ----
def train(model, train_ids: list[int], val_ids: list[int], cfg: TrainConfig,
          checkpoint_dir: str | Path, log_path: str | Path, device: str = "cpu",
          cost_controller=None, tokenizer_fingerprint: str | None = None,
          dataset_version: str | None = None,
          dataset_content_sha256: str | None = None,
          runtime_guard=None, disk_reserve_gb: float | None = None,
          cpu_threads: int | None = None, max_checkpoints: int = 3,
          enforce_limits: bool = False) -> dict:
    if enforce_limits or cfg.strict_limits:
        validate_strict_resource_limits(cfg)
    segment_cap = (
        min(cfg.segment_max_steps, STRICT_MAX_SEGMENT_STEPS)
        if (enforce_limits or cfg.strict_limits) and cfg.segment_max_steps is not None
        else cfg.segment_max_steps
    )
    import torch

    from apps.core.training_infrastructure.monitoring.training_monitor import TrainingMonitor
    from apps.core.training_infrastructure.recovery.checkpoint_recovery import (
        CheckpointManager, capture_rng_state, restore_rng_state,
        serialize_python_rng_state, validate_resume_identity)
    from apps.core.workflow.resource_guard import (
        MAX_CPU_THREADS, check_disk_reserve, enforce_cpu_thread_cap)

    if str(device).startswith("cpu") or cpu_threads is not None or runtime_guard is not None:
        target_threads = int(
            cpu_threads
            if cpu_threads is not None
            else (getattr(runtime_guard, "cpu_threads", MAX_CPU_THREADS))
        )
        enforce_cpu_thread_cap(target_threads, torch_mod=torch)

    rng = random.Random(cfg.seed)
    torch.manual_seed(cfg.seed)
    model.to(device)

    decay = [p for p in model.parameters() if p.requires_grad and p.dim() >= 2]
    no_decay = [p for p in model.parameters() if p.requires_grad and p.dim() < 2]
    optimizer = torch.optim.AdamW(
        [{"params": decay, "weight_decay": cfg.weight_decay},
         {"params": no_decay, "weight_decay": 0.0}], lr=cfg.lr, betas=(0.9, 0.95))

    amp_dtype_name = resolve_amp_dtype(device, cfg.mixed_precision, torch_mod=torch)
    amp_dtype = (
        getattr(torch, amp_dtype_name, None) if amp_dtype_name is not None else None
    )
    scaler = (
        torch.amp.GradScaler("cuda", enabled=True)
        if amp_dtype_name == "float16" and hasattr(torch, "amp")
        else None
    )

    ckpts = CheckpointManager(checkpoint_dir, keep_last=max(1, int(max_checkpoints)))
    monitor = TrainingMonitor(log_path)
    start_step = 0
    resumed = ckpts.load_latest()
    if resumed is not None:
        start_step, state = resumed
        validate_resume_identity(
            state,
            expected={
                "dataset_version": dataset_version,
                "dataset_content_sha256": dataset_content_sha256,
                "tokenizer_sha256": tokenizer_fingerprint,
                "model_config": model.cfg.to_dict(),
                "training_identity": _training_resume_identity(cfg),
            },
        )
        if state.get("batch_rng") is None or state.get("rng") is None:
            raise ValueError("resume checkpoint is missing RNG state")
        model.load_state_dict(state["model"])
        optimizer.load_state_dict(state["optimizer"])
        restore_python_rng_state(rng, state["batch_rng"])
        restore_rng_state(state["rng"])

    initial_parameters = {
        name: parameter.detach().clone()
        for name, parameter in model.named_parameters()
    }

    def to_tensor(rows):
        return torch.tensor(rows, dtype=torch.long, device=device)

    @torch.no_grad()
    def evaluate() -> float:
        model.eval()
        eval_rng = random.Random(0)  # fixed windows -> comparable across evaluations
        losses = []
        for _ in range(cfg.eval_batches):
            x, y = sample_batch(val_ids, cfg.block_size, cfg.batch_size, eval_rng)
            losses.append(model(to_tensor(x), to_tensor(y))[1].item())
        model.train()
        return sum(losses) / len(losses)

    stopped_reason = None
    checkpoint_blocked = False
    checkpoint_saved = False

    def save(step: int) -> bool:
        nonlocal stopped_reason, checkpoint_blocked, checkpoint_saved
        if runtime_guard is not None:
            ok_guard, guard_reason, _ = runtime_guard.check_runtime(
                "before_checkpoint", step=step, checkpoint_write=True
            )
            if not ok_guard:
                checkpoint_blocked = True
                if stopped_reason is None:
                    stopped_reason = guard_reason
                return False
        elif disk_reserve_gb is not None:
            ok_disk, _ = check_disk_reserve(checkpoint_dir, reserve_gb=float(disk_reserve_gb))
            if not ok_disk:
                checkpoint_blocked = True
                if stopped_reason is None:
                    stopped_reason = "disk_reserve_violated"
                return False
        ckpts.save(step, {
            "model": model.state_dict(), "optimizer": optimizer.state_dict(),
            "step": step, "global_step_start": start_step, "experiment_steps": step - start_step,
            "stage_id": cfg.stage_id, "experiment_index": cfg.experiment_index,
            "batch_rng": serialize_python_rng_state(rng.getstate()), "rng": capture_rng_state(),
            "config": cfg.__dict__, "model_config": model.cfg.to_dict(),
            "training_identity": _training_resume_identity(cfg),
            "tokenizer_sha256": tokenizer_fingerprint, "dataset_version": dataset_version,
            "dataset_content_sha256": dataset_content_sha256,
        })
        checkpoint_saved = True
        return True

    model.train()
    last_val = None
    last_train_loss = None
    if cost_controller is not None:
        cost_controller.start()
    if runtime_guard is not None:
        runtime_guard.start()
    step = start_step
    executed_steps = 0
    while step < cfg.max_steps and (
        segment_cap is None or executed_steps < segment_cap
    ):
        if cost_controller is not None and cost_controller.should_stop():
            stopped_reason = cost_controller.exceeded()
            break
        if runtime_guard is not None:
            ok_guard, guard_reason, _ = runtime_guard.check_runtime("before_step", step=step)
            if not ok_guard:
                stopped_reason = guard_reason
                break
        lr = lr_at(step, cfg)
        for group in optimizer.param_groups:
            group["lr"] = lr
        optimizer.zero_grad(set_to_none=True)
        total_loss = 0.0
        for _ in range(cfg.grad_accum_steps):
            x, y = sample_batch(train_ids, cfg.block_size, cfg.batch_size, rng)
            if amp_dtype is not None and hasattr(torch, "amp"):
                with torch.amp.autocast("cuda", dtype=amp_dtype):
                    loss = model(to_tensor(x), to_tensor(y))[1] / cfg.grad_accum_steps
            else:
                loss = model(to_tensor(x), to_tensor(y))[1] / cfg.grad_accum_steps
            if scaler is not None:
                scaler.scale(loss).backward()
            else:
                loss.backward()
            total_loss += loss.item()
        if not math.isfinite(total_loss):
            optimizer.zero_grad(set_to_none=True)
            monitor.log(step + 1, total_loss, lr, tokens=0)
            stopped_reason = "loss_diverged"
            break
        if cost_controller is not None and cost_controller.should_stop():
            optimizer.zero_grad(set_to_none=True)
            stopped_reason = cost_controller.exceeded()
            break
        if runtime_guard is not None:
            ok_guard, guard_reason, _ = runtime_guard.check_runtime("before_optimizer_step", step=step)
            if not ok_guard:
                optimizer.zero_grad(set_to_none=True)
                stopped_reason = guard_reason
                break
        if scaler is not None:
            scaler.unscale_(optimizer)
        torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.grad_clip)
        if scaler is not None:
            scaler.step(optimizer)
            scaler.update()
        else:
            optimizer.step()
        last_train_loss = total_loss
        step += 1
        executed_steps += 1
        segment_done = (
            segment_cap is not None and executed_steps >= segment_cap
        )

        if step % cfg.log_interval == 0 or step == cfg.max_steps or segment_done:
            tokens = cfg.batch_size * cfg.block_size * cfg.grad_accum_steps * cfg.log_interval
            rec = monitor.log(step, total_loss, lr, tokens=tokens)
            if rec["diverged"]:
                stopped_reason = "loss_diverged"
                break
        if step % cfg.eval_interval == 0 or step == cfg.max_steps or segment_done:
            last_val = evaluate()
        if step % cfg.checkpoint_interval == 0 or step == cfg.max_steps or segment_done:
            if not save(step):
                break

    if stopped_reason in (
        "loss_diverged",
        "ram_hard_limit",
        "disk_reserve_violated",
        "disk_budget_violated",
    ):
        pass  # do not checkpoint a diverged or unsafe state
    elif stopped_reason is not None and step > start_step and not checkpoint_blocked:
        save(step)  # timeout/budget stop: keep safe progress only if disk/RAM checks pass
    if cost_controller is not None:
        cost_controller.pause()
    if runtime_guard is not None:
        runtime_guard.pause()
    if last_val is None and stopped_reason is None:
        last_val = evaluate()
    parameter_changed = any(
        not torch.equal(initial_parameters[name], parameter.detach())
        for name, parameter in model.named_parameters()
    )
    return {
        "steps": step,
        "resumed_from": start_step,
        "global_step_start": start_step,
        "global_step_end": step,
        "experiment_steps": executed_steps,
        "stage_id": cfg.stage_id,
        "experiment_index": cfg.experiment_index,
        "stopped_reason": stopped_reason,
        "train_loss": last_train_loss,
        "parameter_changed": parameter_changed,
        "val_loss": last_val,
        "perplexity": perplexity(last_val) if last_val is not None else None,
        "checkpoint_blocked": checkpoint_blocked,
        "checkpoint_saved": checkpoint_saved,
    }


def train_sft(
    model,
    train_pairs: list[tuple[list[int], list[int]]],
    val_pairs: list[tuple[list[int], list[int]]],
    cfg: TrainConfig,
    checkpoint_dir: str | Path,
    log_path: str | Path,
    device: str = "cpu",
    cost_controller=None,
    tokenizer_fingerprint: str | None = None,
    dataset_version: str | None = None,
    dataset_content_sha256: str | None = None,
    prompt_format: str | None = None,
    sep: str | None = None,
    pad_id: int = 0,
    runtime_guard=None,
    disk_reserve_gb: float | None = None,
    cpu_threads: int | None = None,
    max_checkpoints: int = 3,
    enforce_limits: bool = False,
) -> dict:
    """Supervised fine-tuning / native SFT training over `(x, y)` pairs with `-100` label masking."""
    if enforce_limits or cfg.strict_limits:
        validate_strict_resource_limits(cfg)
    segment_cap = (
        min(cfg.segment_max_steps, STRICT_MAX_SEGMENT_STEPS)
        if (enforce_limits or cfg.strict_limits) and cfg.segment_max_steps is not None
        else cfg.segment_max_steps
    )
    import torch

    from apps.core.native.sft import SFT_FORMAT_VERSION, SFT_SEP, collate_sft_batch
    from apps.core.training_infrastructure.monitoring.training_monitor import TrainingMonitor
    from apps.core.training_infrastructure.recovery.checkpoint_recovery import (
        CheckpointManager,
        capture_rng_state,
        restore_rng_state,
        serialize_python_rng_state,
        restore_python_rng_state,
        validate_resume_identity,
    )
    from apps.core.workflow.resource_guard import (
        MAX_CPU_THREADS,
        check_disk_reserve,
        enforce_cpu_thread_cap,
    )

    if not train_pairs or not val_pairs:
        raise ValueError("train_pairs and val_pairs must both be non-empty")

    if str(device).startswith("cpu") or cpu_threads is not None or runtime_guard is not None:
        target_threads = int(
            cpu_threads
            if cpu_threads is not None
            else (getattr(runtime_guard, "cpu_threads", MAX_CPU_THREADS))
        )
        enforce_cpu_thread_cap(target_threads, torch_mod=torch)

    resolved_format = prompt_format or SFT_FORMAT_VERSION
    resolved_sep = SFT_SEP if sep is None else sep

    rng = random.Random(cfg.seed)
    torch.manual_seed(cfg.seed)
    model.to(device)

    decay = [p for p in model.parameters() if p.requires_grad and p.dim() >= 2]
    no_decay = [p for p in model.parameters() if p.requires_grad and p.dim() < 2]
    optimizer = torch.optim.AdamW(
        [
            {"params": decay, "weight_decay": cfg.weight_decay},
            {"params": no_decay, "weight_decay": 0.0},
        ],
        lr=cfg.lr,
        betas=(0.9, 0.95),
    )

    amp_dtype_name = resolve_amp_dtype(device, cfg.mixed_precision, torch_mod=torch)
    amp_dtype = (
        getattr(torch, amp_dtype_name, None) if amp_dtype_name is not None else None
    )
    scaler = (
        torch.amp.GradScaler("cuda", enabled=True)
        if amp_dtype_name == "float16" and hasattr(torch, "amp")
        else None
    )

    ckpts = CheckpointManager(checkpoint_dir, keep_last=max(1, int(max_checkpoints)))
    monitor = TrainingMonitor(log_path)
    start_step = 0
    resumed = ckpts.load_latest()
    if resumed is not None:
        start_step, state = resumed
        validate_resume_identity(
            state,
            expected={
                "dataset_version": dataset_version,
                "dataset_content_sha256": dataset_content_sha256,
                "tokenizer_sha256": tokenizer_fingerprint,
                "model_config": model.cfg.to_dict(),
                "training_identity": _training_resume_identity(cfg),
                "prompt_format": resolved_format,
                "sep": resolved_sep,
            },
            required_fields=(
                "dataset_version", "dataset_content_sha256", "tokenizer_sha256",
                "model_config", "training_identity", "prompt_format", "sep",
            ),
        )
        if state.get("batch_rng") is None or state.get("rng") is None:
            raise ValueError("resume checkpoint is missing RNG state")
        model.load_state_dict(state["model"])
        optimizer.load_state_dict(state["optimizer"])
        restore_python_rng_state(rng, state["batch_rng"])
        restore_rng_state(state["rng"])

    initial_parameters = {
        name: parameter.detach().clone()
        for name, parameter in model.named_parameters()
    }

    def to_tensor(rows):
        return torch.tensor(rows, dtype=torch.long, device=device)

    def sample_sft_batch(pairs: list[tuple[list[int], list[int]]]):
        chosen = [pairs[rng.randrange(0, len(pairs))] for _ in range(cfg.batch_size)]
        return collate_sft_batch(chosen, pad_id=pad_id, max_seq_len=model.cfg.max_seq_len)

    @torch.no_grad()
    def evaluate() -> float:
        model.eval()
        losses = []
        max_eval = max(1, cfg.eval_batches)
        for idx in range(0, len(val_pairs), cfg.batch_size):
            if len(losses) >= max_eval:
                break
            chunk = val_pairs[idx : idx + cfg.batch_size]
            x, y = collate_sft_batch(chunk, pad_id=pad_id, max_seq_len=model.cfg.max_seq_len)
            losses.append(model(to_tensor(x), to_tensor(y))[1].item())
        model.train()
        return sum(losses) / len(losses)

    stopped_reason = None
    checkpoint_blocked = False
    checkpoint_saved = False

    def save(step: int) -> bool:
        nonlocal stopped_reason, checkpoint_blocked, checkpoint_saved
        if runtime_guard is not None:
            ok_guard, guard_reason, _ = runtime_guard.check_runtime(
                "before_checkpoint", step=step, checkpoint_write=True
            )
            if not ok_guard:
                checkpoint_blocked = True
                if stopped_reason is None:
                    stopped_reason = guard_reason
                return False
        elif disk_reserve_gb is not None:
            ok_disk, _ = check_disk_reserve(checkpoint_dir, reserve_gb=float(disk_reserve_gb))
            if not ok_disk:
                checkpoint_blocked = True
                if stopped_reason is None:
                    stopped_reason = "disk_reserve_violated"
                return False
        ckpts.save(
            step,
            {
                "model": model.state_dict(),
                "optimizer": optimizer.state_dict(),
                "step": step,
                "global_step_start": start_step,
                "experiment_steps": step - start_step,
                "stage_id": cfg.stage_id,
                "experiment_index": cfg.experiment_index,
                "batch_rng": serialize_python_rng_state(rng.getstate()),
                "rng": capture_rng_state(),
                "config": cfg.__dict__,
                "model_config": model.cfg.to_dict(),
                "training_identity": _training_resume_identity(cfg),
                "tokenizer_sha256": tokenizer_fingerprint,
                "dataset_version": dataset_version,
                "dataset_content_sha256": dataset_content_sha256,
                "prompt_format": resolved_format,
                "sep": resolved_sep,
            },
        )
        checkpoint_saved = True
        return True

    model.train()
    last_val = None
    last_train_loss = None
    if cost_controller is not None:
        cost_controller.start()
    if runtime_guard is not None:
        runtime_guard.start()
    step = start_step
    executed_steps = 0
    while step < cfg.max_steps and (
        segment_cap is None or executed_steps < segment_cap
    ):
        if cost_controller is not None and cost_controller.should_stop():
            stopped_reason = cost_controller.exceeded()
            break
        if runtime_guard is not None:
            ok_guard, guard_reason, _ = runtime_guard.check_runtime("before_step", step=step)
            if not ok_guard:
                stopped_reason = guard_reason
                break
        lr = lr_at(step, cfg)
        for group in optimizer.param_groups:
            group["lr"] = lr
        optimizer.zero_grad(set_to_none=True)
        total_loss = 0.0
        step_tokens = 0
        for _ in range(cfg.grad_accum_steps):
            x, y = sample_sft_batch(train_pairs)
            step_tokens += sum(len(row) for row in x)
            if amp_dtype is not None and hasattr(torch, "amp"):
                with torch.amp.autocast("cuda", dtype=amp_dtype):
                    loss = model(to_tensor(x), to_tensor(y))[1] / cfg.grad_accum_steps
            else:
                loss = model(to_tensor(x), to_tensor(y))[1] / cfg.grad_accum_steps
            if scaler is not None:
                scaler.scale(loss).backward()
            else:
                loss.backward()
            total_loss += loss.item()
        if not math.isfinite(total_loss):
            optimizer.zero_grad(set_to_none=True)
            monitor.log(step + 1, total_loss, lr, tokens=0)
            stopped_reason = "loss_diverged"
            break
        if cost_controller is not None and cost_controller.should_stop():
            optimizer.zero_grad(set_to_none=True)
            stopped_reason = cost_controller.exceeded()
            break
        if runtime_guard is not None:
            ok_guard, guard_reason, _ = runtime_guard.check_runtime("before_optimizer_step", step=step)
            if not ok_guard:
                optimizer.zero_grad(set_to_none=True)
                stopped_reason = guard_reason
                break
        if scaler is not None:
            scaler.unscale_(optimizer)
        torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.grad_clip)
        if scaler is not None:
            scaler.step(optimizer)
            scaler.update()
        else:
            optimizer.step()
        last_train_loss = total_loss
        step += 1
        executed_steps += 1
        segment_done = (
            segment_cap is not None and executed_steps >= segment_cap
        )

        if step % cfg.log_interval == 0 or step == cfg.max_steps or segment_done:
            rec = monitor.log(step, total_loss, lr, tokens=step_tokens)
            if rec["diverged"]:
                stopped_reason = "loss_diverged"
                break
        if step % cfg.eval_interval == 0 or step == cfg.max_steps or segment_done:
            last_val = evaluate()
        if step % cfg.checkpoint_interval == 0 or step == cfg.max_steps or segment_done:
            if not save(step):
                break

    if stopped_reason in (
        "loss_diverged",
        "ram_hard_limit",
        "disk_reserve_violated",
        "disk_budget_violated",
    ):
        pass
    elif stopped_reason is not None and step > start_step and not checkpoint_blocked:
        save(step)
    if cost_controller is not None:
        cost_controller.pause()
    if runtime_guard is not None:
        runtime_guard.pause()
    if last_val is None and stopped_reason is None:
        last_val = evaluate()
    parameter_changed = any(
        not torch.equal(initial_parameters[name], parameter.detach())
        for name, parameter in model.named_parameters()
    )
    return {
        "steps": step,
        "resumed_from": start_step,
        "global_step_start": start_step,
        "global_step_end": step,
        "experiment_steps": executed_steps,
        "stage_id": cfg.stage_id,
        "experiment_index": cfg.experiment_index,
        "stopped_reason": stopped_reason,
        "train_loss": last_train_loss,
        "parameter_changed": parameter_changed,
        "val_loss": last_val,
        "perplexity": perplexity(last_val) if last_val is not None else None,
        "prompt_format": resolved_format,
        "checkpoint_blocked": checkpoint_blocked,
        "checkpoint_saved": checkpoint_saved,
    }
