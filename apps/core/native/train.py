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

    def __post_init__(self):
        if self.block_size < 2 or self.batch_size < 1 or self.grad_accum_steps < 1 or self.max_steps < 1:
            raise ValueError("invalid training sizes")
        if not (0 < self.min_lr <= self.lr) or not (0 <= self.warmup_steps < self.max_steps):
            raise ValueError("invalid learning-rate settings")


# ---- pure-python helpers ----
def lr_at(step: int, cfg: TrainConfig) -> float:
    """Linear warm-up then cosine decay to min_lr. `step` is 0-based."""
    if step < cfg.warmup_steps:
        return cfg.lr * (step + 1) / cfg.warmup_steps
    if step >= cfg.max_steps:
        return cfg.min_lr
    progress = (step - cfg.warmup_steps) / max(1, cfg.max_steps - cfg.warmup_steps)
    return cfg.min_lr + 0.5 * (1 + math.cos(math.pi * progress)) * (cfg.lr - cfg.min_lr)


def build_token_stream(texts: Iterable[str], tokenizer) -> list[int]:
    """Concatenate documents, each followed by <|eos|>."""
    ids: list[int] = []
    for text in texts:
        ids.extend(tokenizer.encode(text, add_eos=True))
    return ids


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


# ---- torch training loop (not run in authoring environment) ----
def train(model, train_ids: list[int], val_ids: list[int], cfg: TrainConfig,
          checkpoint_dir: str | Path, log_path: str | Path, device: str = "cpu",
          cost_controller=None, tokenizer_fingerprint: str | None = None,
          dataset_version: str | None = None) -> dict:
    import torch

    from apps.core.training_infrastructure.monitoring.training_monitor import TrainingMonitor
    from apps.core.training_infrastructure.recovery.checkpoint_recovery import (
        CheckpointManager, capture_rng_state, restore_rng_state)

    rng = random.Random(cfg.seed)
    torch.manual_seed(cfg.seed)
    model.to(device)

    decay = [p for p in model.parameters() if p.requires_grad and p.dim() >= 2]
    no_decay = [p for p in model.parameters() if p.requires_grad and p.dim() < 2]
    optimizer = torch.optim.AdamW(
        [{"params": decay, "weight_decay": cfg.weight_decay},
         {"params": no_decay, "weight_decay": 0.0}], lr=cfg.lr, betas=(0.9, 0.95))

    ckpts = CheckpointManager(checkpoint_dir)
    monitor = TrainingMonitor(log_path)
    start_step = 0
    resumed = ckpts.load_latest()
    if resumed is not None:
        start_step, state = resumed
        model.load_state_dict(state["model"])
        optimizer.load_state_dict(state["optimizer"])
        rng.setstate(state["batch_rng"])
        restore_rng_state(state["rng"])

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

    def save(step: int) -> None:
        ckpts.save(step, {
            "model": model.state_dict(), "optimizer": optimizer.state_dict(),
            "step": step, "batch_rng": rng.getstate(), "rng": capture_rng_state(),
            "config": cfg.__dict__, "model_config": model.cfg.to_dict(),
            "tokenizer_sha256": tokenizer_fingerprint, "dataset_version": dataset_version,
        })

    model.train()
    last_val = None
    stopped_reason = None
    if cost_controller is not None:
        cost_controller.start()
    step = start_step
    while step < cfg.max_steps:
        if cost_controller is not None and cost_controller.should_stop():
            stopped_reason = cost_controller.exceeded()
            break
        lr = lr_at(step, cfg)
        for group in optimizer.param_groups:
            group["lr"] = lr
        optimizer.zero_grad(set_to_none=True)
        total_loss = 0.0
        for _ in range(cfg.grad_accum_steps):
            x, y = sample_batch(train_ids, cfg.block_size, cfg.batch_size, rng)
            loss = model(to_tensor(x), to_tensor(y))[1] / cfg.grad_accum_steps
            loss.backward()
            total_loss += loss.item()
        torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.grad_clip)
        optimizer.step()
        step += 1

        if step % cfg.log_interval == 0 or step == cfg.max_steps:
            tokens = cfg.batch_size * cfg.block_size * cfg.grad_accum_steps * cfg.log_interval
            rec = monitor.log(step, total_loss, lr, tokens=tokens)
            if rec["diverged"]:
                stopped_reason = "loss_diverged"
                break
        if step % cfg.eval_interval == 0 or step == cfg.max_steps:
            last_val = evaluate()
        if step % cfg.checkpoint_interval == 0 or step == cfg.max_steps:
            save(step)

    if stopped_reason in ("loss_diverged",):
        pass  # do not checkpoint a diverged state
    elif stopped_reason is not None and step > start_step:
        save(step)  # budget stop: keep progress so the run can resume
    if cost_controller is not None:
        cost_controller.pause()
    if last_val is None and stopped_reason is None:
        last_val = evaluate()
    return {"steps": step, "resumed_from": start_step, "stopped_reason": stopped_reason,
            "val_loss": last_val, "perplexity": perplexity(last_val) if last_val is not None else None}
