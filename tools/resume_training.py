#!/usr/bin/env python3
"""Safe checkpoint verification and training resumption from Step 6000 -> 7000
for ZYRQUEN Native V2 (PureNativeTransformerLMV2 + PureContinualTrainerV2).

Policy:
- Native model only; zero pretrained third-party weights and zero external AI APIs.
- Verifies SHA-256 against the PR #56 manifest before loading any checkpoint.
- Restores full Optimizer (m_state, v_state, global_step) and Continual-Learning
  state (replay_buffer, anchor_params, importance_diag).
- Never overwrites existing checkpoints; writes .sha256 sidecars alongside outputs.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON_CORE = REPO_ROOT / "python_core"
if str(PYTHON_CORE) not in sys.path:
    sys.path.insert(0, str(PYTHON_CORE))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.zyrquen_v2_pure import PureContinualTrainerV2  # noqa: E402
from v2.zyrquen_v2_trainer import ByteTokenizer  # noqa: E402
from tools.tpu_probe import detect_runtime_accelerator, format_runtime_report  # noqa: E402

DEFAULT_OUT_DIR = Path("/content/zyrquen-resume/checkpoints")

# PR #56 Checkpoint Manifest: step -> (filename, sha256)
PR56_STEP_MANIFEST: Dict[int, Tuple[str, str]] = {
    4000: ("v2_continued_step4000.json.gz", "0ca27a632e85bc7fde764b9948ceb9ed16a53911d5773bd51b5cd7c722a5237d"),
    4025: ("v2_continued_step4025.json.gz", "f4b33c82a27a0a3f05b468d2ff1cf297746f7a3aa85ecbc03ff0093f34c75314"),
    5000: ("v2_teacher_transfer_step5000.json.gz", "76c85f56c615590906bee1f7893e22301f7be1d430130cd2b882e1921d9d72ed"),
    5025: ("v2_teacher_transfer_run5000_step5025.json.gz", "1de745e95b02653a9dc4d9cd07a61c408553ac041256082e99fbbdf00e00e140"),
    5050: ("v2_teacher_transfer_run5000_step5050.json.gz", "3755c25a2e3c7e42e86349f3e283bfe1bc0e53cb836e4bb9b4d9cb5ce288dda0"),
    5075: ("v2_teacher_transfer_run5000_step5075.json.gz", "b289b0d6c588431b7a0443d6f5ef28cd99e8fe0dccfd70f4a560a17d5bd7b653"),
    5100: ("v2_teacher_transfer_run5000_step5100.json.gz", "ceef223f2751f2031a4a92516d4f42a108e3e387bd9f78c869504ea3954498fc"),
    5125: ("v2_teacher_transfer_run5000_step5125.json.gz", "4aa6ceab1132809647158b1b3ac0261c764217c744ec04c9e1df38611e3c0181"),
    5150: ("v2_teacher_transfer_run5000_step5150.json.gz", "53a5095ee2b74fd1094919141e5cbd4ff5f3521b28d7a6e9612f66813347ac72"),
    5175: ("v2_teacher_transfer_run5000_step5175.json.gz", "ff38aca43560457101fd5f0357f71767b42c717e86ba89366a3b665389399159"),
    5200: ("v2_teacher_transfer_run5000_step5200.json.gz", "801f1c064173b480bd75cc707d1795ef194b9673b5006835a8b6eb0a0ddfccc9"),
    5225: ("v2_teacher_transfer_run5000_step5225.json.gz", "499dfa5dc6e05dda0dc8ae04d160e645632b6dd146017c8c89e4733b08b4027e"),
    5250: ("v2_teacher_transfer_run5000_step5250.json.gz", "a185f847cec9ae4a73cd48998c612917adbf3d45e3ee50b4fb2e2612bfa869d3"),
    5275: ("v2_teacher_transfer_run5000_step5275.json.gz", "8b10636e775762cc1f4d7ee895baf5750f8850a1b7da9aaced90221dce050fc2"),
    5300: ("v2_teacher_transfer_run5000_step5300.json.gz", "285a473675c630dca1ff9b147d3e54e510a9233e83e83d3ecbad3859e9358df2"),
    5325: ("v2_teacher_transfer_run5000_step5325.json.gz", "56931475194b881be9e9d8c48007a764bf3a557e31702909af5bd8a21ed46294"),
    5350: ("v2_teacher_transfer_run5000_step5350.json.gz", "5fdc2aefcf9f77b54ca4ba36bcf498f0c7dfd37617f74be325cf76200fb65839"),
    5375: ("v2_teacher_transfer_run5000_step5375.json.gz", "a9c124e59116bf760aeab1273d6fe617b98c599258e2b9ed4c7450ef2a2e0b58"),
    5400: ("v2_teacher_transfer_run5000_step5400.json.gz", "8f93f6a1f996e755febf427c74779c35489a0b13e66c9dd6ff962ed4308effc7"),
    5425: ("v2_teacher_transfer_run5000_step5425.json.gz", "439a549e948c46a480a1aa1f465ba17dfc02e3a9b49c4e71b56e39977f75a09d"),
    5450: ("v2_teacher_transfer_run5000_step5450.json.gz", "001164a3fdf834a958dfad45028d941dba714590e039e7eed65e8ec246946fce"),
    5475: ("v2_teacher_transfer_run5000_step5475.json.gz", "eae1b6fa9798145bc4f77d566d2b1fdc8d0450addfa19e4cd80e5278a69691e7"),
    5500: ("v2_teacher_transfer_run5000_step5500.json.gz", "6b37593ef67a24729f8de2ec9349f7b3ccb2eb8a9e6054430f289a26070207a2"),
    5525: ("v2_teacher_transfer_run5000_step5525.json.gz", "bf1cc85e9e6221d8ec59bfcd182084735d4fa4792560d2c3ba89376d677d61fa"),
    5550: ("v2_teacher_transfer_run5000_step5550.json.gz", "883fd165bea22121e5d66813cc3357425ac7206e75126b79f1f7db0a697568c0"),
    5575: ("v2_teacher_transfer_run5000_step5575.json.gz", "b2f4e8575add3d5700b59c4d40b7bf1d64e10d7d27f1e5634a9ae6a296e21263"),
    5600: ("v2_teacher_transfer_run5000_step5600.json.gz", "8ba6e33f6eaa7d60911ee9ba3d3449a95b23b93711deddd27e368a2bed0b12b4"),
    5625: ("v2_teacher_transfer_run5000_step5625.json.gz", "8e52f2674096c054ccf6c846fcb3570232021ef9f11c58d9b685941bd0f7338e"),
    5650: ("v2_teacher_transfer_run5000_step5650.json.gz", "4fdce60b3ad836bd9a63b371d8c610a3efb135e14a94b3588c2cff8fad50c20a"),
    5675: ("v2_teacher_transfer_run5000_step5675.json.gz", "9fe00d7f6e73ff06cd18b65786b75109e7b3eacdcfb4f9a48ab415e3bb5441ad"),
    5700: ("v2_teacher_transfer_run5000_step5700.json.gz", "e3bfb82ce41c07ea009ac19ade9b4dadb11d26fb58e68fe10c3b9acc2d54900b"),
    5725: ("v2_teacher_transfer_run5000_step5725.json.gz", "adef12a38c715269bde139b88a20dba040501a7e05b8e03274f127ef48df36ed"),
    5750: ("v2_teacher_transfer_run5000_step5750.json.gz", "55549e8f24c4b4dd62e43a898dc035aa5fa9275b779395e98d06179c13b52e69"),
    5775: ("v2_teacher_transfer_run5000_step5775.json.gz", "cc4ccb15343175f32424fcca16b814996859ffb0c12d73412d0f06eab1b3f029"),
    5800: ("v2_teacher_transfer_run5000_step5800.json.gz", "9d17996720e8c72a3eeae61761aefd0495188911a83d152e89f3d8f42605c6f1"),
    5825: ("v2_teacher_transfer_run5000_step5825.json.gz", "ec0097e331167d81b13f92d6910962d68d7ba890cf21d925a6344b88310eec2f"),
    5850: ("v2_teacher_transfer_run5000_step5850.json.gz", "fba66bb041aae9cca57b43372e2159a94eefcbd682a3f40314a8bbd2adcbe5a8"),
    5875: ("v2_teacher_transfer_run5000_step5875.json.gz", "9ac2a73357d8a084e1a259c48a4b8eb3197415d9d29e585db2f5e4cf641f3a1f"),
    5900: ("v2_teacher_transfer_run5000_step5900.json.gz", "0b6d0b0e88f007ad663f30ce9a86f556a72d807814e5821e10c16f98558c431c"),
    5925: ("v2_teacher_transfer_run5000_step5925.json.gz", "6f078a01867a54545a24dede3fc4d982774c95a80fcb35111cfccf199f4034df"),
    5950: ("v2_teacher_transfer_run5000_step5950.json.gz", "afad144ed48bec461e9e22bfd8a4b1a7513cffa945a8e3a4f48ae98e2bf6c854"),
    5975: ("v2_teacher_transfer_run5000_step5975.json.gz", "abbc4c214d72a8f79339a89dc8c4b4ca97826a7df9e519d0f24c5bf4f7d6bd3a"),
    6000: ("v2_teacher_transfer_run5000_step6000.json.gz", "3b7f0ed4de259a0b1db2135caf193c074409cadb3a599ae4656cfd4b3dffbca7"),
}

_SHA_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def compute_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_checkpoint_for_step(step: int, out_dir: Path) -> Tuple[Path, Optional[str]]:
    if step in PR56_STEP_MANIFEST:
        filename, expected_sha = PR56_STEP_MANIFEST[step]
        return out_dir / filename, expected_sha

    matches = sorted(p for p in out_dir.glob(f"*_step{step}.json.gz") if p.is_file())
    if not matches:
        raise FileNotFoundError(f"No checkpoint found for step {step} in {out_dir}")
    ckpt_path = matches[-1]
    sidecar = Path(f"{ckpt_path}.sha256")
    expected_sha: Optional[str] = None
    if sidecar.is_file():
        token = sidecar.read_text(encoding="utf-8").strip().split()[0]
        if _SHA_RE.fullmatch(token):
            expected_sha = token.lower()
    return ckpt_path, expected_sha


def verify_checkpoint_hash(step: int, out_dir: Path = DEFAULT_OUT_DIR) -> Tuple[Path, str]:
    """Read checkpoint for `step` and verify its SHA-256 against the PR #56 manifest (or sidecar)."""
    ckpt_path, expected_sha = _resolve_checkpoint_for_step(step, out_dir)
    if not ckpt_path.is_file():
        raise FileNotFoundError(f"Checkpoint not found for step {step}: {ckpt_path}")

    actual_sha = compute_sha256(ckpt_path)
    if expected_sha is not None and actual_sha != expected_sha:
        raise ValueError(
            f"SHA-256 mismatch at step {step} ({ckpt_path.name}): "
            f"actual={actual_sha} expected={expected_sha}"
        )
    return ckpt_path, actual_sha


REQUIRED_STATE_KEYS = {
    "params",
    "m_state",
    "v_state",
    "replay_buffer",
    "anchor_params",
    "importance_diag",
    "trainer_hparams",
}


def _all_finite(tree: Any) -> bool:
    if isinstance(tree, (int, float)):
        return math.isfinite(float(tree))
    if isinstance(tree, list):
        return all(_all_finite(item) for item in tree)
    if isinstance(tree, dict):
        return all(_all_finite(val) for val in tree.values())
    return True


def verify_trainer_can_continue(
    trainer: PureContinualTrainerV2,
    expected_step: int = 6000,
) -> Dict[str, Any]:
    """Ensure restored optimizer, replay buffer, importance weights, and forward/backward pass can safely continue training."""
    if trainer.global_step != expected_step:
        raise AssertionError(
            f"Restored global_step={trainer.global_step} != expected step={expected_step}"
        )
    if not trainer.m_state or not trainer.v_state:
        raise AssertionError("Optimizer m_state / v_state failed to restore from checkpoint")
    if set(trainer.m_state.keys()) != set(trainer.model.params.keys()):
        raise AssertionError("Optimizer m_state parameter keys do not match model.params")
    if set(trainer.v_state.keys()) != set(trainer.model.params.keys()):
        raise AssertionError("Optimizer v_state parameter keys do not match model.params")
    if not isinstance(trainer.replay_buffer, list):
        raise AssertionError("Continual-learning replay_buffer did not restore as a list")
    if not isinstance(trainer.importance_diag, dict) or not isinstance(trainer.anchor_params, dict):
        raise AssertionError("Continual-learning importance_diag / anchor_params failed to restore")
    if not _all_finite(trainer.model.params):
        raise AssertionError("Non-finite parameter weights detected in restored model")
    if not _all_finite(trainer.m_state) or not _all_finite(trainer.v_state):
        raise AssertionError("Non-finite optimizer moment buffers detected")
    if trainer.importance_diag and not _all_finite(trainer.importance_diag):
        raise AssertionError("Non-finite values detected in importance_diag")

    # Non-mutating forward/backward loss probe to verify gradient flow before resuming
    probe_text = (
        trainer.replay_buffer[0]
        if trainer.replay_buffer
        else "zyrquen native continuation safety probe"
    )
    probe_ids = trainer.tokenizer.encode(probe_text, add_eos=True)[: trainer.model.cfg.max_seq_len]
    if len(probe_ids) < 2:
        probe_ids = [65, 66, 67, trainer.tokenizer.eos_token_id]
    probe_loss, _, probe_grads = trainer.model.forward_loss_and_backward(
        probe_ids[:-1], probe_ids[1:]
    )
    if not math.isfinite(probe_loss) or not _all_finite(probe_grads):
        raise AssertionError(f"Continuation safety probe produced non-finite loss/grads: {probe_loss}")

    return {
        "can_continue_safely": True,
        "global_step": trainer.global_step,
        "probe_loss": round(float(probe_loss), 4),
        "optimizer_restored": True,
        "replay_buffer_len": len(trainer.replay_buffer),
        "has_anchor_params": bool(trainer.anchor_params),
        "has_importance_diag": bool(trainer.importance_diag),
    }


def resume_from_checkpoint(
    step: int = 6000,
    out_dir: Path = DEFAULT_OUT_DIR,
) -> Dict[str, Any]:
    """Verify SHA-256 and restore full Optimizer + Continual-Learning state."""
    ckpt_path, verified_sha = verify_checkpoint_hash(step, out_dir=out_dir)

    with gzip.open(ckpt_path, "rt", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid checkpoint JSON payload in {ckpt_path.name}")
    missing_keys = REQUIRED_STATE_KEYS - set(payload.keys())
    if missing_keys:
        raise ValueError(
            f"Missing required checkpoint state keys in {ckpt_path.name}: {sorted(missing_keys)}"
        )

    tokenizer = ByteTokenizer()
    trainer = PureContinualTrainerV2.load_checkpoint(
        ckpt_path,
        tokenizer,
        expected_sha256=verified_sha,
        resume_optimizer=True,
        restore_continual_state=True,
    )
    safety = verify_trainer_can_continue(trainer, expected_step=step)

    return {
        "trainer": trainer,
        "tokenizer": tokenizer,
        "checkpoint_path": ckpt_path,
        "sha256": verified_sha,
        "size_bytes": ckpt_path.stat().st_size,
        **safety,
    }


def load_texts(path: Path) -> List[str]:
    if not path.is_file():
        raise FileNotFoundError(f"Dataset file not found: {path}")
    texts: List[str] = []
    if path.suffix.lower() == ".jsonl":
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if isinstance(obj, str):
                texts.append(obj)
            elif isinstance(obj, dict):
                if isinstance(obj.get("text"), str):
                    texts.append(obj["text"])
                elif isinstance(obj.get("prompt"), str) and isinstance(obj.get("response"), str):
                    texts.append(f"{obj['prompt']}\n{obj['response']}")
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, str):
                    texts.append(item)
                elif isinstance(item, dict) and isinstance(item.get("text"), str):
                    texts.append(item["text"])
    if not texts:
        raise ValueError(f"No usable text entries found in {path}")
    return texts


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify SHA-256 against PR #56 manifest, restore Step 6000 Optimizer/Trainer state, and resume training to Step 7000."
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--step", type=int, default=6000, help="Checkpoint step to resume from (default: 6000)")
    parser.add_argument("--target-step", type=int, default=7000, help="Target global step (default: 7000)")
    parser.add_argument("--chunk-steps", type=int, default=25, help="Checkpoint save interval in steps")
    parser.add_argument("--batch-size", type=int, default=3)
    parser.add_argument("--replay-ratio", type=float, default=0.5)
    parser.add_argument("--train-file", type=Path, default=None, help="Training dataset JSON/JSONL path")
    parser.add_argument("--val-file", type=Path, default=None, help="Optional held-out validation JSON/JSONL path")
    parser.add_argument("--run-prefix", type=str, default=None, help="Output checkpoint filename prefix")
    parser.add_argument("--verify-only", action="store_true", help="Only verify SHA-256 and state restoration")
    parser.add_argument("--check-tpu", action="store_true", help="Only print Colab TPU / TorchTPU / CPU runtime diagnostics")
    args = parser.parse_args(argv)

    runtime_info = detect_runtime_accelerator()
    if args.check_tpu:
        print(format_runtime_report(runtime_info))
        return 0

    print(
        f"[0/3] Runtime           : python={runtime_info['python_version']} | "
        f"torch={runtime_info['torch_version'] or 'none'} | "
        f"accelerator={runtime_info['accelerator']} | "
        f"devices={runtime_info['device_count']} | "
        f"tpu_addr={runtime_info['tpu_address']}"
    )

    restored = resume_from_checkpoint(step=args.step, out_dir=args.out_dir)
    trainer: PureContinualTrainerV2 = restored["trainer"]
    tokenizer: ByteTokenizer = restored["tokenizer"]

    print(f"[1/3] Verified SHA-256  : {restored['checkpoint_path'].name}")
    print(f"      sha256            : {restored['sha256']}")
    print(
        "[2/3] State restored    : "
        f"global_step={restored['global_step']} | "
        f"optimizer={restored['optimizer_restored']} | "
        f"replay={restored['replay_buffer_len']} | "
        f"anchor={restored['has_anchor_params']} | "
        f"importance={restored['has_importance_diag']}"
    )

    if args.val_file is not None:
        val_texts = load_texts(args.val_file)
        pre_eval = trainer.model.evaluate_texts(tokenizer, val_texts)
        print(f"      Pre-resume eval   : {json.dumps(pre_eval)}")

    if args.verify_only or args.train_file is None:
        print("[3/3] Resume skipped    : pass --train-file (without --verify-only) to train toward --target-step.")
        return 0

    if trainer.global_step >= args.target_step:
        print(f"[3/3] Nothing to do     : global_step={trainer.global_step} >= target_step={args.target_step}")
        return 0

    train_texts = load_texts(args.train_file)
    prefix = args.run_prefix or f"v2_teacher_transfer_run{trainer.global_step}"
    print(
        f"[3/3] Training started  : step {trainer.global_step} -> {args.target_step} "
        f"(chunk={args.chunk_steps}, examples={len(train_texts)})"
    )

    while trainer.global_step < args.target_step:
        step_budget = min(args.chunk_steps, args.target_step - trainer.global_step)
        stats = trainer.train_steps(
            train_texts,
            steps=step_budget,
            batch_size=args.batch_size,
            replay_ratio=args.replay_ratio,
        )
        out_ckpt = args.out_dir / f"{prefix}_step{trainer.global_step}.json.gz"
        _, new_digest = trainer.save_checkpoint(out_ckpt)
        print(
            f"STEP {trainer.global_step} | loss={stats['final_loss']:.4f} | "
            f"file={out_ckpt.name} | sha256={new_digest}"
        )

    if args.val_file is not None:
        post_eval = trainer.model.evaluate_texts(tokenizer, load_texts(args.val_file))
        print(f"      Post-resume eval  : {json.dumps(post_eval)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
