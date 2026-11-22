#!/usr/bin/env python3
"""
ZYRQUEN Ω∞ — NAGI v10 Training Controller

Purpose:
Perform a strict pre-training readiness check for NAGI v10.

Current implementation:
- Dataset and manifest validation.
- Independent leakage auditor invocation.
- CPU/RAM/Disk resource inspection.
- Locked training budget enforcement.
- Explicit training-hook readiness gate.
- Explicit Tier-2 approval gate.
- Machine-readable readiness report.

IMPORTANT:
This file does NOT claim to train a model.
Actual training remains BLOCKED until the native training hook,
architecture, objective, and approval integration are implemented.

Safety:
- CPU only.
- No paid GPU.
- No v7/v8/v9 modifications.
- No checkpoint overwrite.
- No dataset modification.
- No automatic commit, push, or deployment.
- No fabricated training or evaluation metrics.

Exit codes:
0 = PREFLIGHT PASS, TRAINING NOT STARTED
1 = PREFLIGHT FAILED
2 = INVALID ARGUMENTS
3 = TRAINING BLOCKED
"""

from future import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(file).resolve().parents[1]

DEFAULT_DATASET_DIR = PROJECT_ROOT / "data" / "nagi_v10"
DEFAULT_AUDITOR = PROJECT_ROOT / "tools" / "audit_leakage_v10.py"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "eval" / "nagi_v10"

---------------------------------------------------------

Locked resource budget

---------------------------------------------------------

MAX_CPU_CORES = 2
MAX_PARAMETERS = 5_000_000
MAX_SEQUENCE_LENGTH = 256
MAX_BATCH_SIZE = 4
MAX_TRAINING_STEPS = 500

RAM_SOFT_LIMIT_BYTES = int(3.0 * 10243)
RAM_HARD_LIMIT_BYTES = int(3.5 * 10243)

MIN_FREE_DISK_BYTES = int(2.0 * 10243)
MAX_NEW_DISK_BYTES = int(1.0 * 10243)

EXPERIMENT_TIMEOUT_SECONDS = 20 * 60

---------------------------------------------------------

Authorization and implementation status

---------------------------------------------------------

These are deliberately locked.

Do not change these constants to simulate authorization.

TRAINING_HOOK_IMPLEMENTED = False
TIER2_APPROVAL_AVAILABLE = False
PAID_GPU_ALLOWED = False

TRAINING_IMPLEMENTATION_STATUS = (
"training_hook_not_implemented"
)

APPROVAL_STATUS = "tier2_token_not_issued"

No model architecture or objective is declared as implemented.

MODEL_ARCHITECTURE_STATUS = "pending_review"
TRAINING_OBJECTIVE_STATUS = "pending_review"

@dataclass
class ResourceSnapshot:
cpu_cores: int
ram_total_bytes: int | None
ram_available_bytes: int | None
process_ram_bytes: int | None
disk_free_bytes: int
gpu_available: bool
platform: str

@dataclass
class TrainingConfig:
seed: int = 42
batch_size: int = 4
sequence_length: int = 256
training_steps: int = 500
learning_rate: float = 0.0003
weight_decay: float = 0.01
max_parameters: int = MAX_PARAMETERS
device: str = "cpu"
timeout_seconds: int = EXPERIMENT_TIMEOUT_SECONDS

class PreflightError(Exception):
"""Raised when a required readiness check fails."""

def utc_now() -> str:
return datetime.now(timezone.utc).isoformat()

def read_int(path: Path) -> int | None:
try:
return int(path.read_text(encoding="utf-8").strip())
except (OSError, ValueError):
return None

def read_meminfo() -> dict[str, int]:
result: dict[str, int] = {}
path = Path("/proc/meminfo")

if not path.is_file():
    return result

try:
    for line in path.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition(":")
        parts = value.strip().split()

        if parts:
            result[key] = int(parts[0]) * 1024
except (OSError, ValueError):
    return {}

return result

def process_memory_bytes() -> int | None:
"""
Read current process resident memory from /proc.
Returns None when the platform does not expose this information.
"""

status = Path("/proc/self/status")

if not status.is_file():
    return None

try:
    for line in status.read_text(encoding="utf-8").splitlines():
        if line.startswith("VmRSS:"):
            value = line.split()[1]
            return int(value) * 1024
except (OSError, ValueError, IndexError):
    return None

return None

def detect_cpu_cores() -> int:
try:
return max(1, len(os.sched_getaffinity(0)))
except (AttributeError, OSError):
return max(1, os.cpu_count() or 1)

def detect_gpu() -> bool:
"""
Detect NVIDIA CUDA visibility without importing or initializing CUDA.

This project is currently CPU-only. A detected GPU does not authorize
GPU usage.
"""

cuda_visible = os.environ.get("CUDA_VISIBLE_DEVICES")

if cuda_visible is not None:
    if cuda_visible.strip() in ("", "-1"):
        return False

return shutil.which("nvidia-smi") is not None

def detect_resources(dataset_dir: Path) -> ResourceSnapshot:
meminfo = read_meminfo()

ram_total = meminfo.get("MemTotal")
ram_available = meminfo.get("MemAvailable")

if ram_total is None:
    try:
        import os as os_module
        page_size = os_module.sysconf("SC_PAGE_SIZE")
        total_pages = os_module.sysconf("SC_PHYS_PAGES")
        ram_total = page_size * total_pages
    except (ValueError, OSError, AttributeError):
        ram_total = None

disk_target = dataset_dir

while not disk_target.exists() and disk_target != disk_target.parent:
    disk_target = disk_target.parent

disk_free = shutil.disk_usage(disk_target).free

return ResourceSnapshot(
    cpu_cores=detect_cpu_cores(),
    ram_total_bytes=ram_total,
    ram_available_bytes=ram_available,
    process_ram_bytes=process_memory_bytes(),
    disk_free_bytes=disk_free,
    gpu_available=detect_gpu(),
    platform=platform.platform(),
)

def validate_config(config: TrainingConfig) -> None:
if config.device != "cpu":
raise PreflightError("Only CPU execution is permitted")

if config.batch_size < 1 or config.batch_size > MAX_BATCH_SIZE:
    raise PreflightError(
        f"Batch size exceeds locked limit: {MAX_BATCH_SIZE}"
    )

if (
    config.sequence_length < 1
    or config.sequence_length > MAX_SEQUENCE_LENGTH
):
    raise PreflightError(
        f"Sequence length exceeds locked limit: "
        f"{MAX_SEQUENCE_LENGTH}"
    )

if (
    config.training_steps < 1
    or config.training_steps > MAX_TRAINING_STEPS
):
    raise PreflightError(
        f"Training steps exceed locked limit: "
        f"{MAX_TRAINING_STEPS}"
    )

if config.max_parameters < 1:
    raise PreflightError("Invalid parameter budget")

if config.max_parameters > MAX_PARAMETERS:
    raise PreflightError(
        f"Parameter budget exceeds {MAX_PARAMETERS}"
    )

if config.timeout_seconds < 1:
    raise PreflightError("Invalid timeout")

if config.timeout_seconds > EXPERIMENT_TIMEOUT_SECONDS:
    raise PreflightError(
        "Experiment timeout exceeds locked limit"
    )

if config.learning_rate <= 0:
    raise PreflightError("Learning rate must be positive")

if config.weight_decay < 0:
    raise PreflightError("Weight decay cannot be negative")

def validate_resources(
resources: ResourceSnapshot,
) -> list[str]:

blockers: list[str] = []

if resources.cpu_cores < 1:
    blockers.append("CPU_UNAVAILABLE")

if resources.cpu_cores > MAX_CPU_CORES:
    blockers.append(
        f"CPU_LIMIT_EXCEEDED:{resources.cpu_cores}"
    )

if resources.ram_available_bytes is not None:
    if resources.ram_available_bytes < RAM_SOFT_LIMIT_BYTES:
        blockers.append("INSUFFICIENT_AVAILABLE_RAM")

if resources.process_ram_bytes is not None:
    if resources.process_ram_bytes >= RAM_HARD_LIMIT_BYTES:
        blockers.append("PROCESS_RAM_HARD_LIMIT_REACHED")

if resources.disk_free_bytes < MIN_FREE_DISK_BYTES:
    blockers.append("DISK_FREE_RESERVE_NOT_MET")

if resources.gpu_available and not PAID_GPU_ALLOWED:
    # GPU detection alone does not mean it will be used.
    # CPU remains the only permitted device.
    pass

return blockers

def run_leakage_audit(
auditor: Path,
dataset_dir: Path,
) -> dict[str, Any]:

if not auditor.is_file():
    raise PreflightError(
        f"Leakage auditor not found: {auditor}"
    )

if not dataset_dir.is_dir():
    raise PreflightError(
        f"Dataset directory not found: {dataset_dir}"
    )

command = [
    sys.executable,
    str(auditor),
    "--dataset-dir",
    str(dataset_dir),
]

try:
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
except subprocess.TimeoutExpired as exc:
    raise PreflightError(
        "Leakage audit timed out"
    ) from exc

if result.returncode != 0:
    raise PreflightError(
        "Leakage audit did not pass. "
        f"Exit code: {result.returncode}. "
        f"Output: {result.stderr[-2000:]}"
    )

try:
    report = json.loads(result.stdout)
except json.JSONDecodeError as exc:
    raise PreflightError(
        "Leakage auditor did not return valid JSON"
    ) from exc

if report.get("status") != "PASS":
    raise PreflightError(
        "Leakage auditor did not report PASS"
    )

if report.get("read_only") is not True:
    raise PreflightError(
        "Leakage auditor did not confirm read-only operation"
    )

return {
    "status": "PASS",
    "return_code": result.returncode,
    "dataset": report.get("dataset"),
    "total_examples": report.get("total_examples"),
    "split_counts": report.get("split_counts"),
    "reasoning_operators": report.get("reasoning_operators"),
    "unseen_abstract_operator_generalization": report.get(
        "unseen_abstract_operator_generalization"
    ),
}

def check_dataset_manifest(dataset_dir: Path) -> dict[str, Any]:
manifest_path = dataset_dir / "manifest.json"

if not manifest_path.is_file():
    raise PreflightError("Dataset manifest is missing")

try:
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
except (OSError, json.JSONDecodeError) as exc:
    raise PreflightError(
        f"Cannot read dataset manifest: {exc}"
    ) from exc

if manifest.get("dataset") != "nagi_v10":
    raise PreflightError("Unexpected dataset identifier")

digest = hashlib.sha256(manifest_bytes).hexdigest()

return {
    "status": "PRESENT",
    "manifest_sha256": digest,
    "total_examples": manifest.get("total_examples"),
    "seed": manifest.get("seed"),
}

def build_readiness_report(
config: TrainingConfig,
resources: ResourceSnapshot,
dataset_result: dict[str, Any] | None,
audit_result: dict[str, Any] | None,
blockers: list[str],
) -> dict[str, Any]:

return {
    "project": "ZYRQUEN Ω∞",
    "model": "NAGI v10",
    "created_at_utc": utc_now(),
    "status": (
        "BLOCKED" if blockers else "PREFLIGHT_PASS"
    ),
    "training_started": False,
    "training_hook": {
        "implemented": TRAINING_HOOK_IMPLEMENTED,
        "status": TRAINING_IMPLEMENTATION_STATUS,
    },
    "tier2_approval": {
        "available": TIER2_APPROVAL_AVAILABLE,
        "status": APPROVAL_STATUS,
    },
    "architecture": MODEL_ARCHITECTURE_STATUS,
    "training_objective": TRAINING_OBJECTIVE_STATUS,
    "config": asdict(config),
    "resources": asdict(resources),
    "dataset": dataset_result,
    "leakage_audit": audit_result,
    "blockers": blockers,
    "checkpoint_created": False,
    "evaluation_performed": False,
    "promotion": "NOT AUTHORIZED",
    "limitations": [
        "This controller is not a model trainer.",
        "No native model architecture has been connected.",
        "No training objective has been approved.",
        "No actual training metrics are available.",
        "No checkpoint has been created.",
    ],
}

def write_report(
report: dict[str, Any],
report_dir: Path,
) -> Path:

report_dir.mkdir(parents=True, exist_ok=True)

timestamp = datetime.now(
    timezone.utc
).strftime("%Y%m%dT%H%M%SZ")

report_path = report_dir / (
    f"v10_training_preflight_{timestamp}.json"
)

# Exclusive creation prevents accidental overwrite.
with report_path.open(
    "x",
    encoding="utf-8",
) as file:
    json.dump(
        report,
        file,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    file.write("\n")

return report_path

def parse_args() -> argparse.Namespace:
parser = argparse.ArgumentParser(
description="NAGI v10 CPU-only training readiness controller."
)

parser.add_argument(
    "--dataset-dir",
    type=Path,
    default=DEFAULT_DATASET_DIR,
)

parser.add_argument(
    "--auditor",
    type=Path,
    default=DEFAULT_AUDITOR,
)

parser.add_argument(
    "--report-dir",
    type=Path,
    default=DEFAULT_REPORT_DIR,
)

parser.add_argument("--seed", type=int, default=42)
parser.add_argument("--batch-size", type=int, default=4)
parser.add_argument("--sequence-length", type=int, default=256)
parser.add_argument("--training-steps", type=int, default=500)
parser.add_argument("--learning-rate", type=float, default=0.0003)
parser.add_argument("--weight-decay", type=float, default=0.01)

return parser.parse_args()

def main() -> int:
args = parse_args()

config = TrainingConfig(
    seed=args.seed,
    batch_size=args.batch_size,
    sequence_length=args.sequence_length,
    training_steps=args.training_steps,
    learning_rate=args.learning_rate,
    weight_decay=args.weight_decay,
)

try:
    validate_config(config)

    resources = detect_resources(
        args.dataset_dir.resolve()
    )

    blockers = validate_resources(resources)

    dataset_result = None
    audit_result = None

    if not blockers:
        dataset_result = check_dataset_manifest(
            args.dataset_dir.resolve()
        )

        audit_result = run_leakage_audit(
            args.auditor.resolve(),
            args.dataset_dir.resolve(),
        )

    if not TRAINING_HOOK_IMPLEMENTED:
        blockers.append("TRAINING_HOOK_NOT_IMPLEMENTED")

    if not TIER2_APPROVAL_AVAILABLE:
        blockers.append("TIER2_APPROVAL_NOT_ISSUED")

    if MODEL_ARCHITECTURE_STATUS != "APPROVED":
        blockers.append("MODEL_ARCHITECTURE_NOT_APPROVED")

    if TRAINING_OBJECTIVE_STATUS != "APPROVED":
        blockers.append("TRAINING_OBJECTIVE_NOT_APPROVED")

    report = build_readiness_report(
        config=config,
        resources=resources,
        dataset_result=dataset_result,
        audit_result=audit_result,
        blockers=blockers,
    )

    report_path = write_report(
        report,
        args.report_dir.resolve(),
    )

    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )

    print(f"\nPreflight report: {report_path}")

    if blockers:
        print("\nTRAINING STATUS: BLOCKED")
        print("Training started: NO")
        print("Checkpoint created: NO")

        for blocker in blockers:
            print(f"BLOCKER: {blocker}")

        return 3

    print("\nPREFLIGHT: PASS")
    print("Training started: NO")
    print("Training hook invocation: NOT IMPLEMENTED")

    return 0

except PreflightError as exc:
    print(
        f"PREFLIGHT FAILED: {exc}",
        file=sys.stderr,
    )
    print("Training started: NO", file=sys.stderr)
    return 1

except (OSError, ValueError) as exc:
    print(
        f"ERROR: {type(exc).__name__}: {exc}",
        file=sys.stderr,
    )
    print("Training started: NO", file=sys.stderr)
    return 1

if name == "main":
raise SystemExit(main())
