import shutil
import logging
import logging
import json
import math
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


# ---- torch training loop (not run in authoring environment) ----
def train(model, train_ids: list[int], val_ids: list[int], cfg: TrainConfig,
          checkpoint_dir: str | Path, log_path: str | Path, device: str = "cpu",
          cost_controller=None, tokenizer_fingerprint: str | None = None,
          dataset_version: str | None = None,
          runtime_guard=None, disk_reserve_gb: float | None = None,
          cpu_threads: int | None = None, max_checkpoints: int = 3) -> dict:
    import torch

    from apps.core.training_infrastructure.monitoring.training_monitor import TrainingMonitor
    from apps.core.training_infrastructure.recovery.checkpoint_recovery import (
        CheckpointManager, capture_rng_state, restore_rng_state)
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

    ckpts = CheckpointManager(checkpoint_dir, keep_last=max(1, int(max_checkpoints)))
    monitor = TrainingMonitor(log_path)
    start_step = 0
    resumed = ckpts.load_latest()
    if resumed is not None:
        start_step, state = resumed
        model.load_state_dict(state["model"])
        optimizer.load_state_dict(state["optimizer"])
        rng.setstate(state["batch_rng"])
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
            "step": step, "batch_rng": rng.getstate(), "rng": capture_rng_state(),
            "config": cfg.__dict__, "model_config": model.cfg.to_dict(),
            "tokenizer_sha256": tokenizer_fingerprint, "dataset_version": dataset_version,
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
    while step < cfg.max_steps:
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
            loss = model(to_tensor(x), to_tensor(y))[1] / cfg.grad_accum_steps
            # --- V9 Minimal Observability ---
            loss_val = loss.item()
            if step % cfg.log_interval == 0:
                log_data = {
                    "step": step,
                    "loss": loss_val if math.isfinite(loss_val) else None,
                    "learning_rate": optimizer.param_groups[0]["lr"],
                    "is_finite": math.isfinite(loss_val)
                }
                logging.info(json.dumps(log_data))
            # ---------------------------------
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
        # --- V9 Parameter Delta Observability ---
        old_weight = next(model.parameters()).detach().clone()
        torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.grad_clip)
        optimizer.step()
        param_delta = (next(model.parameters()) - old_weight).norm().item()
        if param_delta == 0.0:
            logging.warning(f'Step {step}: Parameter delta is 0.0!')
        # ----------------------------------------
        last_train_loss = total_loss
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
            # --- V9 Disk Space Check ---
            try:
                _, _, free = shutil.disk_usage('./checkpoints')
                if free / (1024**3) < 1.0:
                    logging.error('Disk space critically low. Aborting.')
                    break
            except Exception as e:
                logging.warning(f'Could not check disk: {e}')
            # ---------------------------
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
    prompt_format: str | None = None,
    sep: str | None = None,
    pad_id: int = 0,
    runtime_guard=None,
    disk_reserve_gb: float | None = None,
    cpu_threads: int | None = None,
    max_checkpoints: int = 3,
) -> dict:
    """Supervised fine-tuning / native SFT training over `(x, y)` pairs with `-100` label masking."""
    import torch

    from apps.core.native.sft import SFT_FORMAT_VERSION, SFT_SEP, collate_sft_batch
    from apps.core.training_infrastructure.monitoring.training_monitor import TrainingMonitor
    from apps.core.training_infrastructure.recovery.checkpoint_recovery import (
        CheckpointManager,
        capture_rng_state,
        restore_rng_state,
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

    ckpts = CheckpointManager(checkpoint_dir, keep_last=max(1, int(max_checkpoints)))
    monitor = TrainingMonitor(log_path)
    start_step = 0
    resumed = ckpts.load_latest()
    if resumed is not None:
        start_step, state = resumed
        model.load_state_dict(state["model"])
        optimizer.load_state_dict(state["optimizer"])
        rng.setstate(state["batch_rng"])
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
                "batch_rng": rng.getstate(),
                "rng": capture_rng_state(),
                "config": cfg.__dict__,
                "model_config": model.cfg.to_dict(),
                "tokenizer_sha256": tokenizer_fingerprint,
                "dataset_version": dataset_version,
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
    while step < cfg.max_steps:
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
            loss = model(to_tensor(x), to_tensor(y))[1] / cfg.grad_accum_steps
            # --- V9 Minimal Observability ---
            loss_val = loss.item()
            if step % cfg.log_interval == 0:
                log_data = {
                    "step": step,
                    "loss": loss_val if math.isfinite(loss_val) else None,
                    "learning_rate": optimizer.param_groups[0]["lr"],
                    "is_finite": math.isfinite(loss_val)
                }
                logging.info(json.dumps(log_data))
            # ---------------------------------
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
        torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.grad_clip)
        optimizer.step()
        last_train_loss = total_loss
        step += 1

        if step % cfg.log_interval == 0 or step == cfg.max_steps:
            rec = monitor.log(step, total_loss, lr, tokens=step_tokens)
            if rec["diverged"]:
                stopped_reason = "loss_diverged"
                break
        if step % cfg.eval_interval == 0 or step == cfg.max_steps:
            last_val = evaluate()
        if step % cfg.checkpoint_interval == 0 or step == cfg.max_steps:
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
        "stopped_reason": stopped_reason,
        "train_loss": last_train_loss,
        "parameter_changed": parameter_changed,
        "val_loss": last_val,
        "perplexity": perplexity(last_val) if last_val is not None else None,
        "prompt_format": resolved_format,
        "checkpoint_blocked": checkpoint_blocked,
        "checkpoint_saved": checkpoint_saved,
    }
