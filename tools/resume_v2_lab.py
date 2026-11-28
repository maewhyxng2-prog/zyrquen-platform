#!/usr/bin/env python3
"""Environment setup, checkpoint verification, reload check, and continuation trainer
for ZYRQUEN Native V2 (PureNativeTransformerLMV2 + PureContinualTrainerV2).

Policy:
- Native model only; zero pretrained third-party weights and zero external AI APIs.
- Auto-selects the highest verified checkpoint in OUT_DIR (preferring Step 6000 candidate
  `v2_teacher_transfer_run5000_step6000.json.gz`, with fallback to Step 5000 / Step 4025).
- Refuses to proceed on SHA-256 mismatch when a known manifest digest exists.
- Does not overwrite existing checkpoints and does not promote candidates automatically.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
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
from verify_checkpoints import verify_checkpoints  # noqa: E402

DEFAULT_OUT_DIR = Path("/content/zyrquen-resume/checkpoints")

# Recorded SHA-256 manifest (baselines + Step 5025..6000 continuation sequence)
KNOWN_CHECKPOINT_SHA256: Dict[str, str] = {
    "v2_continued_step4000.json.gz": "0ca27a632e85bc7fde764b9948ceb9ed16a53911d5773bd51b5cd7c722a5237d",
    "v2_continued_step4025.json.gz": "f4b33c82a27a0a3f05b468d2ff1cf297746f7a3aa85ecbc03ff0093f34c75314",
    "v2_teacher_transfer_step5000.json.gz": "76c85f56c615590906bee1f7893e22301f7be1d430130cd2b882e1921d9d72ed",
    "v2_teacher_transfer_run5000_step5025.json.gz": "1de745e95b02653a9dc4d9cd07a61c408553ac041256082e99fbbdf00e00e140",
    "v2_teacher_transfer_run5000_step5050.json.gz": "3755c25a2e3c7e42e86349f3e283bfe1bc0e53cb836e4bb9b4d9cb5ce288dda0",
    "v2_teacher_transfer_run5000_step5075.json.gz": "b289b0d6c588431b7a0443d6f5ef28cd99e8fe0dccfd70f4a560a17d5bd7b653",
    "v2_teacher_transfer_run5000_step5100.json.gz": "ceef223f2751f2031a4a92516d4f42a108e3e387bd9f78c869504ea3954498fc",
    "v2_teacher_transfer_run5000_step5125.json.gz": "4aa6ceab1132809647158b1b3ac0261c764217c744ec04c9e1df38611e3c0181",
    "v2_teacher_transfer_run5000_step5150.json.gz": "53a5095ee2b74fd1094919141e5cbd4ff5f3521b28d7a6e9612f66813347ac72",
    "v2_teacher_transfer_run5000_step5175.json.gz": "ff38aca43560457101fd5f0357f71767b42c717e86ba89366a3b665389399159",
    "v2_teacher_transfer_run5000_step5200.json.gz": "801f1c064173b480bd75cc707d1795ef194b9673b5006835a8b6eb0a0ddfccc9",
    "v2_teacher_transfer_run5000_step5225.json.gz": "499dfa5dc6e05dda0dc8ae04d160e645632b6dd146017c8c89e4733b08b4027e",
    "v2_teacher_transfer_run5000_step5250.json.gz": "a185f847cec9ae4a73cd48998c612917adbf3d45e3ee50b4fb2e2612bfa869d3",
    "v2_teacher_transfer_run5000_step5275.json.gz": "8b10636e775762cc1f4d7ee895baf5750f8850a1b7da9aaced90221dce050fc2",
    "v2_teacher_transfer_run5000_step5300.json.gz": "285a473675c630dca1ff9b147d3e54e510a9233e83e83d3ecbad3859e9358df2",
    "v2_teacher_transfer_run5000_step5325.json.gz": "56931475194b881be9e9d8c48007a764bf3a557e31702909af5bd8a21ed46294",
    "v2_teacher_transfer_run5000_step5350.json.gz": "5fdc2aefcf9f77b54ca4ba36bcf498f0c7dfd37617f74be325cf76200fb65839",
    "v2_teacher_transfer_run5000_step5375.json.gz": "a9c124e59116bf760aeab1273d6fe617b98c599258e2b9ed4c7450ef2a2e0b58",
    "v2_teacher_transfer_run5000_step5400.json.gz": "8f93f6a1f996e755febf427c74779c35489a0b13e66c9dd6ff962ed4308effc7",
    "v2_teacher_transfer_run5000_step5425.json.gz": "439a549e948c46a480a1aa1f465ba17dfc02e3a9b49c4e71b56e39977f75a09d",
    "v2_teacher_transfer_run5000_step5450.json.gz": "001164a3fdf834a958dfad45028d941dba714590e039e7eed65e8ec246946fce",
    "v2_teacher_transfer_run5000_step5475.json.gz": "eae1b6fa9798145bc4f77d566d2b1fdc8d0450addfa19e4cd80e5278a69691e7",
    "v2_teacher_transfer_run5000_step5500.json.gz": "6b37593ef67a24729f8de2ec9349f7b3ccb2eb8a9e6054430f289a26070207a2",
    "v2_teacher_transfer_run5000_step5525.json.gz": "bf1cc85e9e6221d8ec59bfcd182084735d4fa4792560d2c3ba89376d677d61fa",
    "v2_teacher_transfer_run5000_step5550.json.gz": "883fd165bea22121e5d66813cc3357425ac7206e75126b79f1f7db0a697568c0",
    "v2_teacher_transfer_run5000_step5575.json.gz": "b2f4e8575add3d5700b59c4d40b7bf1d64e10d7d27f1e5634a9ae6a296e21263",
    "v2_teacher_transfer_run5000_step5600.json.gz": "8ba6e33f6eaa7d60911ee9ba3d3449a95b23b93711deddd27e368a2bed0b12b4",
    "v2_teacher_transfer_run5000_step5625.json.gz": "8e52f2674096c054ccf6c846fcb3570232021ef9f11c58d9b685941bd0f7338e",
    "v2_teacher_transfer_run5000_step5650.json.gz": "4fdce60b3ad836bd9a63b371d8c610a3efb135e14a94b3588c2cff8fad50c20a",
    "v2_teacher_transfer_run5000_step5675.json.gz": "9fe00d7f6e73ff06cd18b65786b75109e7b3eacdcfb4f9a48ab415e3bb5441ad",
    "v2_teacher_transfer_run5000_step5700.json.gz": "e3bfb82ce41c07ea009ac19ade9b4dadb11d26fb58e68fe10c3b9acc2d54900b",
    "v2_teacher_transfer_run5000_step5725.json.gz": "adef12a38c715269bde139b88a20dba040501a7e05b8e03274f127ef48df36ed",
    "v2_teacher_transfer_run5000_step5750.json.gz": "55549e8f24c4b4dd62e43a898dc035aa5fa9275b779395e98d06179c13b52e69",
    "v2_teacher_transfer_run5000_step5775.json.gz": "cc4ccb15343175f32424fcca16b814996859ffb0c12d73412d0f06eab1b3f029",
    "v2_teacher_transfer_run5000_step5800.json.gz": "9d17996720e8c72a3eeae61761aefd0495188911a83d152e89f3d8f42605c6f1",
    "v2_teacher_transfer_run5000_step5825.json.gz": "ec0097e331167d81b13f92d6910962d68d7ba890cf21d925a6344b88310eec2f",
    "v2_teacher_transfer_run5000_step5850.json.gz": "fba66bb041aae9cca57b43372e2159a94eefcbd682a3f40314a8bbd2adcbe5a8",
    "v2_teacher_transfer_run5000_step5875.json.gz": "9ac2a73357d8a084e1a259c48a4b8eb3197415d9d29e585db2f5e4cf641f3a1f",
    "v2_teacher_transfer_run5000_step5900.json.gz": "0b6d0b0e88f007ad663f30ce9a86f556a72d807814e5821e10c16f98558c431c",
    "v2_teacher_transfer_run5000_step5925.json.gz": "6f078a01867a54545a24dede3fc4d982774c95a80fcb35111cfccf199f4034df",
    "v2_teacher_transfer_run5000_step5950.json.gz": "afad144ed48bec461e9e22bfd8a4b1a7513cffa945a8e3a4f48ae98e2bf6c854",
    "v2_teacher_transfer_run5000_step5975.json.gz": "abbc4c214d72a8f79339a89dc8c4b4ca97826a7df9e519d0f24c5bf4f7d6bd3a",
    "v2_teacher_transfer_run5000_step6000.json.gz": "3b7f0ed4de259a0b1db2135caf193c074409cadb3a599ae4656cfd4b3dffbca7",
}

_STEP_RE = re.compile(r"_step(\d+)\.json\.gz$", re.IGNORECASE)


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_step_from_name(path: Path) -> int:
    match = _STEP_RE.search(path.name)
    return int(match.group(1)) if match else -1


def resolve_expected_sha256(ckpt_path: Path) -> Optional[str]:
    if ckpt_path.name in KNOWN_CHECKPOINT_SHA256:
        return KNOWN_CHECKPOINT_SHA256[ckpt_path.name]
    sidecar = Path(f"{ckpt_path}.sha256")
    if sidecar.is_file():
        token = sidecar.read_text(encoding="utf-8").strip().split()[0]
        if re.fullmatch(r"[0-9a-fA-F]{64}", token):
            return token.lower()
    return None


def find_latest_checkpoint(out_dir: Path) -> Tuple[Path, Optional[str]]:
    if not out_dir.is_dir():
        raise FileNotFoundError(f"Checkpoint directory not found: {out_dir}")
    candidates = sorted(
        (p for p in out_dir.glob("*.json.gz") if p.is_file()),
        key=lambda p: (extract_step_from_name(p), p.name),
    )
    if not candidates:
        raise FileNotFoundError(f"No .json.gz checkpoints found in: {out_dir}")
    latest = candidates[-1]
    return latest, resolve_expected_sha256(latest)


def _extract_text_entry(item: Any) -> Optional[str]:
    if isinstance(item, str):
        return item if item.strip() else None
    if isinstance(item, dict):
        for key in ("full_text", "text", "content"):
            val = item.get(key)
            if isinstance(val, str) and val.strip():
                return val
        prompt = item.get("prompt") or item.get("instruction") or item.get("input")
        if isinstance(prompt, str):
            for ans_key in ("response", "completion", "reference_solution", "output", "answer", "target"):
                ans = item.get(ans_key)
                if isinstance(ans, str):
                    return f"{prompt}\n{ans}" if ans else prompt
    return None


def _read_text_maybe_gzip(path: Path) -> str:
    if path.name.lower().endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return fh.read()
    return path.read_text(encoding="utf-8")


def load_texts_from_file(path: Path, split: Optional[str] = None) -> List[str]:
    if not path.is_file():
        raise FileNotFoundError(f"Text dataset file not found: {path}")

    raw_text = _read_text_maybe_gzip(path)
    lower_name = path.name.lower()
    texts: List[str] = []

    if lower_name.endswith(".jsonl") or lower_name.endswith(".jsonl.gz"):
        for line in raw_text.splitlines():
            line = line.strip()
            if not line:
                continue
            extracted = _extract_text_entry(json.loads(line))
            if extracted is not None:
                texts.append(extracted)
    else:
        raw = json.loads(raw_text)
        entries: Any = raw
        if isinstance(raw, dict):
            if split is not None:
                if split not in raw:
                    raise KeyError(
                        f"Split '{split}' not found in {path.name}; available keys: {sorted(raw.keys())}"
                    )
                entries = raw[split]
            else:
                entries = None
                for key in ("texts", "examples", "samples", "items", "records", "data", "prompts", "corpus"):
                    if key in raw and isinstance(raw[key], list):
                        entries = raw[key]
                        break
                if entries is None:
                    list_keys = [k for k, v in raw.items() if isinstance(v, list)]
                    if len(list_keys) == 1:
                        entries = raw[list_keys[0]]
                    else:
                        raise ValueError(
                            f"Dict dataset {path.name} has keys {sorted(raw.keys())}; pass split explicitly."
                        )
        if isinstance(entries, list):
            for item in entries:
                extracted = _extract_text_entry(item)
                if extracted is not None:
                    texts.append(extracted)

    if not texts:
        raise ValueError(f"No usable training/validation text entries found in {path}")
    return texts


def verify_and_reload(
    ckpt_path: Path,
    expected_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    actual_sha = sha256_file(ckpt_path)
    if expected_sha256 is not None and actual_sha != expected_sha256:
        raise ValueError(
            f"SHA-256 mismatch for {ckpt_path.name}: actual={actual_sha} expected={expected_sha256}"
        )

    tokenizer = ByteTokenizer()
    trainer = PureContinualTrainerV2.load_checkpoint(
        ckpt_path,
        tokenizer,
        expected_sha256=expected_sha256,
        resume_optimizer=True,
        restore_continual_state=True,
    )
    expected_step = extract_step_from_name(ckpt_path)
    if expected_step >= 0 and trainer.global_step != expected_step:
        raise AssertionError(
            f"Reloaded global_step={trainer.global_step} != filename step={expected_step}"
        )
    if not trainer.m_state or not trainer.v_state:
        raise AssertionError("Optimizer m_state / v_state missing after checkpoint reload")

    return {
        "trainer": trainer,
        "tokenizer": tokenizer,
        "checkpoint": str(ckpt_path),
        "sha256": actual_sha,
        "size_bytes": ckpt_path.stat().st_size,
        "global_step": trainer.global_step,
        "replay_buffer_len": len(trainer.replay_buffer),
        "has_anchor_params": bool(trainer.anchor_params),
        "has_importance_diag": bool(trainer.importance_diag),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify, reload, evaluate, and continue training ZYRQUEN V2 from latest checkpoint."
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--checkpoint", type=Path, default=None, help="Explicit checkpoint path")
    parser.add_argument("--baseline", type=Path, default=None, help="Optional baseline checkpoint for held-out comparison")
    parser.add_argument("--val-file", type=Path, default=None, help="Held-out validation JSON/JSONL file")
    parser.add_argument("--train-file", type=Path, default=None, help="Training dataset JSON/JSONL file")
    parser.add_argument("--target-step", type=int, default=None, help="Target global step when continuing training")
    parser.add_argument("--chunk-steps", type=int, default=25, help="Steps per checkpoint save")
    parser.add_argument("--batch-size", type=int, default=3)
    parser.add_argument("--replay-ratio", type=float, default=0.5)
    parser.add_argument("--run-prefix", type=str, default=None, help="Output filename prefix")
    parser.add_argument("--verify-only", action="store_true", help="Only verify SHA-256 and fresh-runtime reload")
    args = parser.parse_args(argv)

    ckpt_path = args.checkpoint
    if ckpt_path is None:
        ckpt_path, expected_sha = find_latest_checkpoint(args.out_dir)
    else:
        expected_sha = resolve_expected_sha256(ckpt_path)

    print(f"[1/4] Selected checkpoint: {ckpt_path}")
    print(f"      Expected SHA-256  : {expected_sha or '(sidecar/manifest not recorded)'}")

    dir_report = verify_checkpoints(
        args.out_dir,
        expected_overrides={
            k: v for k, v in KNOWN_CHECKPOINT_SHA256.items() if (args.out_dir / k).exists()
        },
        allow_empty=False,
    )
    print(
        f"[2/4] Directory check   : total={dir_report['total']} matched={dir_report['matched']} failed={dir_report['failed']}"
    )

    reloaded = verify_and_reload(ckpt_path, expected_sha256=expected_sha)
    trainer: PureContinualTrainerV2 = reloaded["trainer"]
    tokenizer: ByteTokenizer = reloaded["tokenizer"]
    print(
        "[3/4] Reload verified   : "
        f"global_step={reloaded['global_step']} | "
        f"size={reloaded['size_bytes']} | "
        f"replay={reloaded['replay_buffer_len']} | "
        f"anchor={reloaded['has_anchor_params']} | "
        f"importance={reloaded['has_importance_diag']}"
    )

    if args.val_file is not None:
        val_texts = load_texts_from_file(args.val_file)
        cand_eval = trainer.model.evaluate_texts(tokenizer, val_texts)
        print(f"      Candidate eval    : {json.dumps(cand_eval)}")
        if args.baseline is not None and args.baseline.is_file():
            base_reloaded = verify_and_reload(
                args.baseline, expected_sha256=resolve_expected_sha256(args.baseline)
            )
            base_eval = base_reloaded["trainer"].model.evaluate_texts(tokenizer, val_texts)
            print(f"      Baseline eval     : {json.dumps(base_eval)}")

    if args.verify_only or args.train_file is None or args.target_step is None:
        print("[4/4] Training skipped  : pass --train-file and --target-step (without --verify-only) to continue training.")
        return 0

    train_texts = load_texts_from_file(args.train_file)
    start_step = trainer.global_step
    if args.target_step <= start_step:
        print(f"[4/4] Nothing to do     : current step {start_step} >= target {args.target_step}")
        return 0

    prefix = args.run_prefix or f"v2_teacher_transfer_run{start_step}"
    print(f"[4/4] Continuing training from step {start_step} -> {args.target_step} ({len(train_texts)} examples)")

    while trainer.global_step < args.target_step:
        step_budget = min(args.chunk_steps, args.target_step - trainer.global_step)
        stats = trainer.train_steps(
            train_texts,
            steps=step_budget,
            batch_size=args.batch_size,
            replay_ratio=args.replay_ratio,
        )
        out_ckpt = args.out_dir / f"{prefix}_step{trainer.global_step}.json.gz"
        _, digest = trainer.save_checkpoint(out_ckpt)
        print(
            f"STEP {trainer.global_step} | loss={stats['final_loss']:.4f} | file={out_ckpt.name} | sha256={digest}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
