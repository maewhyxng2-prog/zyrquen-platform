# ZYRQUEN Versioned Verification Matrix

This matrix separates evidence by version. A passing test in one version does not
authorize training or establish capability in another version.

## Status matrix

| Version | Governance status | Verification scope | Current disposition |
|---|---|---|---|
| V7 | Frozen historical baseline | Historical regression only; do not modify or treat as current capability evidence | Preserve baseline; test inventory must be mapped before claiming a full pass |
| V8 | Frozen historical baseline | Historical regression only; do not modify or treat as current capability evidence | Preserve baseline; test inventory must be mapped before claiming a full pass |
| V9 | CLOSED_FAIL | Reproduce its leakage/evaluation audit and retain the recorded baseline | Closed; do not reopen by changing thresholds or substituting newer tests |
| V10-D | Active closure verification | Resume identity, RNG serialization, real CPU checkpoint load, API/JWT/HMAC cross-process governance, forward probe, read-only preflight | Targeted Colab regression PASS (19/19); fresh preflight and authenticated Tier-2 approval still pending; training NOT RUN |
| V11 | LOCKED | Static/readiness verification only until its gate and required implementation are present | Blocked: `apps/core/native/dataset_v11.py` is absent on main, while `tests/native/test_checkpoint_resume.py` imports it |

## V10-D commands (Colab)

Run from the repository root after pulling the latest main:

```bash
git pull --ff-only

python -m compileall -q \
  apps/core/native/train.py \
  apps/core/training_infrastructure/recovery/checkpoint_recovery.py \
  apps/core/workflow/handlers/groups.py \
  tests/test_v10d_resume_integrity.py

python -m unittest discover -s tests -p "test_v10d_resume_integrity.py" -v
python -m unittest discover -s tests -p "test_v10d_*.py" -v
```

Expected acceptance criteria:
- Resume identity mismatch and legacy/missing fingerprint cases reject.
- Python RNG state round-trip reproduces the exact next random value.
- A real CPU PyTorch checkpoint saves and reloads through the default
  `weights_only=True` path.
- All V10-D API, JWT/admin, shared HMAC, cross-process resume, forward-probe
  contract, read-only preflight, and Tier-2 governance tests pass.

The V10-D glob is intentionally scoped to `tests/test_v10d_*.py`. Do not use
`unittest discover -s tests` as a substitute: it also discovers version-specific
tests under subpackages, including the currently blocked V11-dependent test.

## V11 blocker handling

Do not mark `tests/native/test_checkpoint_resume.py` as passed or silently skip
its missing dependency. It is blocked until the actual V11 `DataAdapter`
implementation is restored/implemented and reviewed. A placeholder module or
test suppression is not an acceptable fix.

## Training gate

Passing this matrix is verification evidence, not training authorization.
V10-D training must remain fail-closed until the authenticated admin approval,
valid shared HMAC approval, and resource guard all succeed. No test in this
matrix may issue approval, consume a real approval, start training, or write a
training checkpoint unless that test is explicitly an authorized integration
test using isolated temporary resources.
