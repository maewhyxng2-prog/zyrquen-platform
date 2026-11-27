"""Native training package unifying the training pipeline and stage-aware sampler."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import importlib.util
import json
import math
import random
from pathlib import Path
from typing import Any, Iterable, Sequence

from apps.core.native.train.StageAwareSampler import (
    StageAwareSampler,
    StageSamplerConfig,
    validate_stage_weights,
)
from apps.core.training_infrastructure.recovery.checkpoint_recovery import CheckpointManager


class TokenStreamLimitExceeded(RuntimeError):
    """Raised when a tokenized corpus exceeds configured CPU/memory token bounds."""


@dataclass
class TrainConfig:
    block_size: int = 256
    batch_size: int = 4
    grad_accum_steps: int = 1
    max_steps: int = 100
    warmup_steps: int = 10
    lr: float = 1e-3
    min_lr: float = 1e-4
    weight_decay: float = 0.01
    eval_interval: int = 50
    eval_batches: int = 10
    checkpoint_interval: int = 50
    log_interval: int = 10
    device: str = "cpu"
    use_paid_gpu: bool = False
    max_parameters: int = 5_000_000
    seed: int = 42

    def __post_init__(self) -> None:
        if self.block_size <= 0:
            raise ValueError("block_size must be positive")
        if self.batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if self.grad_accum_steps <= 0:
            raise ValueError("grad_accum_steps must be positive")
        if self.max_steps <= 0:
            raise ValueError("max_steps must be positive")
        if self.warmup_steps < 0:
            raise ValueError("warmup_steps cannot be negative")
        if self.warmup_steps >= self.max_steps:
            raise ValueError("warmup_steps cannot be >= max_steps")
        if self.lr <= 0 or self.min_lr < 0:
            raise ValueError("learning rates must be non-negative with lr > 0")
        if self.min_lr > self.lr:
            raise ValueError("min_lr cannot be greater than lr")
        if self.eval_interval <= 0 or self.eval_batches <= 0:
            raise ValueError("eval_interval and eval_batches must be positive")
        if self.checkpoint_interval <= 0 or self.log_interval <= 0:
            raise ValueError("checkpoint_interval and log_interval must be positive")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def lr_at(step: int, cfg: TrainConfig) -> float:
    """Linear warmup up to warmup_steps-1 followed by cosine decay down to min_lr at max_steps."""
    if step <= 0:
        return float(cfg.min_lr if cfg.warmup_steps > 1 else cfg.lr)
    if step < cfg.warmup_steps:
        if cfg.warmup_steps <= 1:
            return float(cfg.lr)
        frac = float(step) / float(cfg.warmup_steps - 1)
        return float(cfg.min_lr + (cfg.lr - cfg.min_lr) * frac)
    if step >= cfg.max_steps:
        return float(cfg.min_lr)
    decay_steps = max(1, cfg.max_steps - cfg.warmup_steps)
    progress = float(step - cfg.warmup_steps) / float(decay_steps)
    cosine = 0.5 * (1.0 + math.cos(math.pi * progress))
    return float(cfg.min_lr + (cfg.lr - cfg.min_lr) * cosine)


def perplexity(loss: float) -> float:
    return math.exp(min(float(loss), 20.0))


def sample_batch(
    ids: Sequence[int],
    block_size: int,
    batch_size: int,
    rng: random.Random,
) -> tuple[list[list[int]], list[list[int]]]:
    if len(ids) < block_size + 1:
        raise ValueError(
            f"token stream length {len(ids)} is shorter than block_size + 1 ({block_size + 1})"
        )
    max_start = len(ids) - block_size - 1
    xs: list[list[int]] = []
    ys: list[list[int]] = []
    for _ in range(batch_size):
        start = rng.randint(0, max_start)
        xs.append(list(ids[start : start + block_size]))
        ys.append(list(ids[start + 1 : start + 1 + block_size]))
    return xs, ys


def build_token_stream(
    texts: Iterable[str],
    tok: Any,
    *,
    max_tokens: int | None = None,
) -> list[int]:
    stream: list[int] = []
    eos_id = int(getattr(tok, "eos_id", 2))
    for text in texts:
        encoded = tok.encode(str(text))
        stream.extend(encoded)
        stream.append(eos_id)
        if max_tokens is not None and len(stream) > max_tokens:
            raise TokenStreamLimitExceeded(
                f"token stream length {len(stream)} exceeded max_tokens={max_tokens}"
            )
    return stream


def _require_torch():
    if importlib.util.find_spec("torch") is None:
        raise RuntimeError("torch_not_installed")
    import torch  # type: ignore

    return torch


def _param_fingerprint(torch_mod: Any, model: Any) -> str:
    h = hashlib.sha256()
    with torch_mod.no_grad():
        for name in sorted(model.state_dict().keys()):
            tensor = model.state_dict()[name].detach().cpu().contiguous()
            h.update(name.encode("utf-8"))
            h.update(str(tuple(tensor.shape)).encode("utf-8"))
            h.update(tensor.numpy().tobytes() if hasattr(tensor, "numpy") else repr(tensor.tolist()).encode("utf-8"))
    return h.hexdigest()


def _append_metric_log(log_path: Path, log_data: dict[str, Any]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(log_data) + "\n")


def _check_runtime_guard(runtime_guard: Any, phase: str, *, step: int, checkpoint_write: bool = False) -> str | None:
    if runtime_guard is None:
        return None
    res = runtime_guard.check_runtime(phase, step=step, checkpoint_write=checkpoint_write)
    if isinstance(res, tuple):
        ok, reason = res[0], res[1]
        return None if ok else (str(reason) if reason else "runtime_guard_stopped")
    if isinstance(res, dict) and not res.get("ok", True):
        return str(res.get("reason") or "runtime_guard_stopped")
    return None


def _evaluate_batches(
    torch_mod: Any,
    model: Any,
    val_ids: Sequence[int],
    cfg: TrainConfig,
    rng: random.Random,
    device: str,
) -> float:
    was_training = bool(getattr(model, "training", False))
    model.eval()
    losses: list[float] = []
    with torch_mod.no_grad():
        for _ in range(max(1, int(cfg.eval_batches))):
            vx, vy = sample_batch(val_ids, cfg.block_size, cfg.batch_size, rng)
            x_t = torch_mod.tensor(vx, dtype=torch_mod.long, device=device)
            y_t = torch_mod.tensor(vy, dtype=torch_mod.long, device=device)
            logits = model(x_t)
            if isinstance(logits, tuple):
                logits = logits[0]
            loss = torch_mod.nn.functional.cross_entropy(
                logits.reshape(-1, logits.size(-1)),
                y_t.reshape(-1),
            )
            losses.append(float(loss.item()))
    if was_training:
        model.train()
    return sum(losses) / max(1, len(losses))


def train(
    model: Any,
    train_ids: Sequence[int],
    val_ids: Sequence[int],
    cfg: TrainConfig,
    checkpoint_dir: str | Path,
    log_path: str | Path,
    *,
    tokenizer_fingerprint: str | None = None,
    dataset_version: str | None = None,
    dataset_content_sha256: str | None = None,
    cost_controller: Any | None = None,
    runtime_guard: Any | None = None,
    device: str = "cpu",
) -> dict[str, Any]:
    """Run native pre-training loop on CPU/device with checkpoint recovery and NaN guards."""
    torch = _require_torch()
    if cfg.use_paid_gpu or str(device).lower().startswith("cuda"):
        raise PermissionError("Paid GPU training is blocked by default governance policy.")

    if runtime_guard is not None and hasattr(runtime_guard, "start"):
        runtime_guard.start()

    rng = random.Random(cfg.seed)
    torch.manual_seed(cfg.seed)
    model.to(device)
    model.train()

    ckpt_dir = Path(checkpoint_dir)
    log_file = Path(log_path)
    checkpoints = CheckpointManager(ckpt_dir)

    optimizer = torch.optim.AdamW(model.parameters(), lr=lr_at(0, cfg), weight_decay=cfg.weight_decay)

    start_step = 0
    resumed_from: int | None = None
    latest = checkpoints.load_latest()
    if latest is not None:
        loaded_step, state = latest
        if isinstance(state, dict) and "model" in state:
            model.load_state_dict(state["model"])
            if "optimizer" in state:
                try:
                    optimizer.load_state_dict(state["optimizer"])
                except Exception:
                    pass
            start_step = int(loaded_step)
            resumed_from = start_step

    initial_fp = _param_fingerprint(torch, model)
    last_train_loss: float | None = None
    last_val_loss: float | None = None
    stopped_reason: str | None = None
    completed_steps = start_step

    for step in range(start_step + 1, cfg.max_steps + 1):
        guard_stop = _check_runtime_guard(runtime_guard, "before_step", step=step)
        if guard_stop is not None:
            stopped_reason = guard_stop
            break
        if cost_controller is not None and hasattr(cost_controller, "check"):
            cost_controller.check(step=step)

        current_lr = lr_at(step - 1, cfg)
        for group in optimizer.param_groups:
            group["lr"] = current_lr

        optimizer.zero_grad(set_to_none=True)
        total_loss = 0.0
        for _ in range(cfg.grad_accum_steps):
            xb, yb = sample_batch(train_ids, cfg.block_size, cfg.batch_size, rng)
            x_t = torch.tensor(xb, dtype=torch.long, device=device)
            y_t = torch.tensor(yb, dtype=torch.long, device=device)
            logits = model(x_t)
            if isinstance(logits, tuple):
                logits = logits[0]
            loss = torch.nn.functional.cross_entropy(
                logits.reshape(-1, logits.size(-1)),
                y_t.reshape(-1),
            )
            loss_val = loss.item()
            if cfg.grad_accum_steps > 1:
                loss = loss / float(cfg.grad_accum_steps)
            loss.backward()
            total_loss += float(loss_val) / float(cfg.grad_accum_steps)

        if not math.isfinite(total_loss):
            stopped_reason = "loss_diverged"
            _append_metric_log(
                log_file,
                {"step": step, "loss": total_loss, "learning_rate": current_lr, "is_finite": False},
            )
            break

        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        completed_steps = step
        last_train_loss = total_loss

        if step % cfg.log_interval == 0 or step == cfg.max_steps:
            log_data = {
                "step": step,
                "loss": round(total_loss, 6),
                "learning_rate": current_lr,
                "is_finite": True,
            }
            _append_metric_log(log_file, log_data)

        if step % cfg.eval_interval == 0 or step == cfg.max_steps:
            last_val_loss = _evaluate_batches(torch, model, val_ids, cfg, rng, device)

        if step % cfg.checkpoint_interval == 0 or step == cfg.max_steps:
            guard_ckpt = _check_runtime_guard(runtime_guard, "before_checkpoint", step=step, checkpoint_write=True)
            if guard_ckpt is not None:
                stopped_reason = guard_ckpt
                break
            model_cfg_dict = model.cfg.to_dict() if hasattr(getattr(model, "cfg", None), "to_dict") else {}
            state_payload = {
                "step": step,
                "model": {k: v.detach().cpu() for k, v in model.state_dict().items()},
                "optimizer": optimizer.state_dict(),
                "model_config": model_cfg_dict,
                "config": cfg.to_dict(),
                "tokenizer_sha256": tokenizer_fingerprint,
                "dataset_version": dataset_version,
                "dataset_content_sha256": dataset_content_sha256,
                "val_loss": last_val_loss,
            }
            checkpoints.save(step, state_payload)

    if last_val_loss is None and completed_steps > start_step and stopped_reason is None:
        last_val_loss = _evaluate_batches(torch, model, val_ids, cfg, rng, device)

    final_fp = _param_fingerprint(torch, model)
    return {
        "steps": completed_steps,
        "resumed_from": resumed_from,
        "stopped_reason": stopped_reason,
        "train_loss": last_train_loss,
        "val_loss": last_val_loss,
        "perplexity": perplexity(last_val_loss) if last_val_loss is not None and math.isfinite(last_val_loss) else None,
        "parameter_changed": final_fp != initial_fp,
    }


def _sample_sft_batch(
    pairs: Sequence[tuple[Sequence[int], Sequence[int]]],
    batch_size: int,
    max_seq_len: int,
    pad_id: int,
    rng: random.Random,
) -> tuple[list[list[int]], list[list[int]]]:
    if not pairs:
        raise ValueError("SFT pairs sequence cannot be empty")
    chosen = [pairs[rng.randrange(len(pairs))] for _ in range(batch_size)]
    width = min(max_seq_len, max(len(x) for x, _ in chosen))
    width = max(2, width)
    xs: list[list[int]] = []
    ys: list[list[int]] = []
    for x_raw, y_raw in chosen:
        x_seq = list(x_raw)[:width]
        y_seq = list(y_raw)[:width]
        if len(x_seq) < width:
            pad_len = width - len(x_seq)
            x_seq = x_seq + [pad_id] * pad_len
            y_seq = y_seq + [-100] * pad_len
        xs.append(x_seq)
        ys.append(y_seq)
    return xs, ys


def _evaluate_sft_batches(
    torch_mod: Any,
    model: Any,
    val_pairs: Sequence[tuple[Sequence[int], Sequence[int]]],
    cfg: TrainConfig,
    pad_id: int,
    rng: random.Random,
    device: str,
) -> float:
    was_training = bool(getattr(model, "training", False))
    model.eval()
    losses: list[float] = []
    with torch_mod.no_grad():
        for _ in range(max(1, int(cfg.eval_batches))):
            vx, vy = _sample_sft_batch(val_pairs, cfg.batch_size, cfg.block_size, pad_id, rng)
            x_t = torch_mod.tensor(vx, dtype=torch_mod.long, device=device)
            y_t = torch_mod.tensor(vy, dtype=torch_mod.long, device=device)
            logits = model(x_t)
            if isinstance(logits, tuple):
                logits = logits[0]
            loss = torch_mod.nn.functional.cross_entropy(
                logits[:, :-1, :].reshape(-1, logits.size(-1)),
                y_t[:, 1:].reshape(-1),
                ignore_index=-100,
            )
            losses.append(float(loss.item()))
    if was_training:
        model.train()
    return sum(losses) / max(1, len(losses))


def train_sft(
    model: Any,
    train_pairs: Sequence[tuple[Sequence[int], Sequence[int]]],
    val_pairs: Sequence[tuple[Sequence[int], Sequence[int]]],
    cfg: TrainConfig,
    checkpoint_dir: str | Path,
    log_path: str | Path,
    *,
    tokenizer_fingerprint: str | None = None,
    dataset_version: str | None = None,
    dataset_content_sha256: str | None = None,
    prompt_format: str = "zyrquen.sft.v1",
    cost_controller: Any | None = None,
    runtime_guard: Any | None = None,
    device: str = "cpu",
    pad_id: int = 0,
) -> dict[str, Any]:
    """Run native supervised fine-tuning loop with masked prompt loss and NaN guards."""
    torch = _require_torch()
    if cfg.use_paid_gpu or str(device).lower().startswith("cuda"):
        raise PermissionError("Paid GPU training is blocked by default governance policy.")

    if runtime_guard is not None and hasattr(runtime_guard, "start"):
        runtime_guard.start()

    rng = random.Random(cfg.seed)
    torch.manual_seed(cfg.seed)
    model.to(device)
    model.train()

    ckpt_dir = Path(checkpoint_dir)
    log_file = Path(log_path)
    checkpoints = CheckpointManager(ckpt_dir)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr_at(0, cfg), weight_decay=cfg.weight_decay)

    start_step = 0
    resumed_from: int | None = None
    latest = checkpoints.load_latest()
    if latest is not None:
        loaded_step, state = latest
        if isinstance(state, dict) and "model" in state:
            model.load_state_dict(state["model"])
            start_step = int(loaded_step)
            resumed_from = start_step

    initial_fp = _param_fingerprint(torch, model)
    last_train_loss: float | None = None
    last_val_loss: float | None = None
    stopped_reason: str | None = None
    completed_steps = start_step

    for step in range(start_step + 1, cfg.max_steps + 1):
        guard_stop = _check_runtime_guard(runtime_guard, "before_step", step=step)
        if guard_stop is not None:
            stopped_reason = guard_stop
            break
        if cost_controller is not None and hasattr(cost_controller, "check"):
            cost_controller.check(step=step)

        current_lr = lr_at(step - 1, cfg)
        for group in optimizer.param_groups:
            group["lr"] = current_lr

        optimizer.zero_grad(set_to_none=True)
        total_loss = 0.0
        for _ in range(cfg.grad_accum_steps):
            xb, yb = _sample_sft_batch(train_pairs, cfg.batch_size, cfg.block_size, pad_id, rng)
            x_t = torch.tensor(xb, dtype=torch.long, device=device)
            y_t = torch.tensor(yb, dtype=torch.long, device=device)
            logits = model(x_t)
            if isinstance(logits, tuple):
                logits = logits[0]
            loss = torch.nn.functional.cross_entropy(
                logits[:, :-1, :].reshape(-1, logits.size(-1)),
                y_t[:, 1:].reshape(-1),
                ignore_index=-100,
            )
            loss_val = loss.item()
            if cfg.grad_accum_steps > 1:
                loss = loss / float(cfg.grad_accum_steps)
            loss.backward()
            total_loss += float(loss_val) / float(cfg.grad_accum_steps)

        if not math.isfinite(total_loss):
            stopped_reason = "loss_diverged"
            _append_metric_log(
                log_file,
                {"step": step, "loss": total_loss, "learning_rate": current_lr, "is_finite": False},
            )
            break

        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        completed_steps = step
        last_train_loss = total_loss

        if step % cfg.log_interval == 0 or step == cfg.max_steps:
            log_data = {
                "step": step,
                "loss": round(total_loss, 6),
                "learning_rate": current_lr,
                "is_finite": True,
            }
            _append_metric_log(log_file, log_data)

        if step % cfg.eval_interval == 0 or step == cfg.max_steps:
            last_val_loss = _evaluate_sft_batches(torch, model, val_pairs, cfg, pad_id, rng, device)

        if step % cfg.checkpoint_interval == 0 or step == cfg.max_steps:
            guard_ckpt = _check_runtime_guard(runtime_guard, "before_checkpoint", step=step, checkpoint_write=True)
            if guard_ckpt is not None:
                stopped_reason = guard_ckpt
                break
            model_cfg_dict = model.cfg.to_dict() if hasattr(getattr(model, "cfg", None), "to_dict") else {}
            state_payload = {
                "step": step,
                "model": {k: v.detach().cpu() for k, v in model.state_dict().items()},
                "optimizer": optimizer.state_dict(),
                "model_config": model_cfg_dict,
                "config": cfg.to_dict(),
                "tokenizer_sha256": tokenizer_fingerprint,
                "dataset_version": dataset_version,
                "dataset_content_sha256": dataset_content_sha256,
                "prompt_format": prompt_format,
                "val_loss": last_val_loss,
            }
            checkpoints.save(step, state_payload)

    if last_val_loss is None and completed_steps > start_step and stopped_reason is None:
        last_val_loss = _evaluate_sft_batches(torch, model, val_pairs, cfg, pad_id, rng, device)

    final_fp = _param_fingerprint(torch, model)
    return {
        "steps": completed_steps,
        "resumed_from": resumed_from,
        "stopped_reason": stopped_reason,
        "train_loss": last_train_loss,
        "val_loss": last_val_loss,
        "perplexity": perplexity(last_val_loss) if last_val_loss is not None and math.isfinite(last_val_loss) else None,
        "parameter_changed": final_fp != initial_fp,
        "prompt_format": prompt_format,
    }


__all__ = [
    "StageAwareSampler",
    "StageSamplerConfig",
    "TokenStreamLimitExceeded",
    "TrainConfig",
    "build_token_stream",
    "lr_at",
    "perplexity",
    "sample_batch",
    "train",
    "train_sft",
    "validate_stage_weights",
]
