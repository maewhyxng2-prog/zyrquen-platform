# ZYRQUEN Ω∞ — P11 Blockers and Remediation (`P11_BLOCKERS_AND_REMEDIATION.md`)

- **Mission:** Prioritized Blocker Register, Remediation Sequence & Gate Entry Checklist for P11
- **Mode:** `READINESS AUDIT + PREPARATION` (`EXECUTION AUTHORITY: NOT GRANTED`)
- **Current Verdict:** `P11_READINESS = BLOCKED`

---

## 1. Master Blocker & Remediation Register

| ID | Domain | File / Config Ref | Actual Evidence | Status | Required Remediation | Verification Method |
|---|---|---|---|---|---|---|
| **B-01** | Runtime Env | Host Python `3.11.2`, `/apps/api/requirements.txt` | `torch_spec: None`, `fastapi_spec: None`, `pytest_spec: None`, `pip_spec: None`. `apps/core/native/test_*.py` fails `unittest discover` with 6 `ModuleNotFoundError: No module named 'pytest'`. | `BLOCKED` | Install CPU-only PyTorch (`--index-url https://download.pytorch.org/whl/cpu`), `fastapi`, `pydantic`, `pytest` inside clean venv (zero paid GPU packages). | `python3 -c "import torch, fastapi, pytest"` + `pytest apps/core/native` |
| **B-02** | Governance / V10 Gate | `/apps/core/native/closure_audit.py`, `/docs/v11/V11_GATE_TRANSITION_DECISION.md` | `build_v10_closure_audit()` locally returns `overall_status: "BLOCKED"`, `v11_gate: {"unlocked": False, "status": "LOCKED"}` (6 missing V10/runtime artifacts). | `BLOCKED` | Either restore verified archived V10 `CLOSED_FAIL` report SHA-256 per `V10-GOV-DEC-01` OR obtain explicit human governance override for P11 Stage-2 pilot authorization (preserving V10 `CLOSED_FAIL`). | `build_v10_closure_audit()` / signed governance record |
| **B-03** | Dataset Artifacts | `/data/`, `/tools/`, `/apps/core/native/dataset_status.py` | No `data/nagi_v11/`, no `tokenizer.json`, no `tools/gen_nagi_v11.py`, no `tools/audit_leakage_v11.py`. `get_datasets_pipeline_status()` returns `configured: False`. | `BLOCKED` | Implement deterministic solver generator `tools/gen_nagi_v11.py` + `tools/audit_leakage_v11.py`, generate 4-split SFT dataset, train `zyrquen.tokenizer.v2` on train-only corpus. | `inspect_v11_training_dataset_readiness()["ready"] is True` |
| **B-04** | Leakage & Dedup Coverage | `/apps/core/native/dataset_v11.py`, `/apps/core/native/dataset.py:149-237`, `/apps/core/workflow/handlers/groups.py:250-315` | `TL-01` (template disjointness), `SL-01` (structural depth disjointness), `DL-01` (fuzzy dedup), and BPE token length check (`<=256`) are NOT implemented; `prepare_dataset()` only handles 3 raw-text splits. | `FAIL` | Add `TL-01`, `SL-01`, `DL-01`, and BPE length verifier to `dataset_v11.py` & `tools/audit_leakage_v11.py`; extend `prepare_dataset()` or dedicated V11 SFT builder. | Adversarial leakage injection unit tests (`TL-01`/`SL-01`/`DL-01`/`>256` tokens must FAIL). |
| **B-05** | Manifest & Orchestrator Schema Conflict | `/apps/core/training/orchestrator.py:137-153`, `/docs/v11/V11_DATASET_SPECIFICATION.md:214` | `TrainingOrchestrator.prepare()` requires `manifest["files"]["train.jsonl"]["documents"]`, rejects `"splits"`-only manifests, and omits `unseen`/`ood` & `DataAdapter.detect_leakage()`. | `FAIL` | Emit both `"files"` and `"splits"` in V11 `manifest.json`; update `TrainingOrchestrator.prepare()` to call `verify_dataset_manifest()` + `DataAdapter.detect_leakage()`. | Unit test `TrainingOrchestrator.prepare()` on canonical V11 manifest + leaked manifest. |
| **B-06** | Stage Curriculum & Slot Binding | `/apps/core/native/train.py:450-520`, `/apps/core/workflow/handlers/groups.py:551-553` | `handle_training_execute` loads full `train.jsonl` without `stage_tag` filtering and binds `<slot_k>` **once** statically before training. | `FAIL` | Implement `stage_id` + `stage_replay_weights` curriculum sampler and deterministic per-step dynamic slot binding `(seed, step, idx)`. | Unit tests verifying stage exclusivity, replay ratios, and dynamic slot variation across steps. |
| **B-07** | Checkpoint `weights_only=True` & Cross-Segment Resume | `/apps/core/native/train.py:303,560`, `/apps/core/training_infrastructure/recovery/checkpoint_recovery.py:16-39`, `/apps/core/workflow/handlers/groups.py:456-458` | Checkpoints store raw Python `rng.getstate()` tuples under `weights_only=True` (`NOT VERIFIED` on PyTorch `>=2.5`); cross-segment resume does not enforce `dataset_content_sha256` / `tokenizer_sha256` / `model_config` parity before stepping. | `NOT VERIFIED` / `FAIL` | Verify `torch.load(..., weights_only=True)` in real CPU PyTorch (serialize RNG state as `list[int]` if blocked); assert exact manifest/tokenizer/config SHA parity on segment resume. | `tests/native/test_checkpoint_resume.py` with real `torch.save` / `torch.load`. |
| **B-08** | Evaluation Schema & Runner Missing | `/apps/core/native/evaluation/engine.py`, `/apps/core/workflow/handlers/groups.py:1258-1467`, `/tools/` | `evaluate_native_model()` outputs `zyrquen.native_inference_evaluation.v1`, NOT `zyrquen.v11.evaluation_report.v1`; `tools/eval_nagi_v11.py` missing; `max_new_tokens=32` truncates 5–6-step plans; `exposure_gap` / `abstention` / `ar_inverse` / `near_miss_rejection` missing. | `FAIL` | Create `tools/eval_nagi_v11.py`, add missing 6-capability metrics + teacher-forced comparison + `max_new_tokens=64` to `engine.py`/`metrics.py`. | End-to-end eval schema test on random-init `ZyrquenModel` parsed cleanly by `handle_evaluation_gate()`. |
| **B-09** | Unfrozen Eval Thresholds | `/docs/v11/V11_EVALUATION_PLAN.md` (`OD-EP-01`), `/apps/core/workflow/handlers/groups.py:1258-1467` | Exact numeric PASS floors (`OD-EP-01`) remain TBD; `handle_evaluation_gate()` trusts report summary flags if numbers are finite. | `FAIL` | Freeze exact numeric thresholds in governance config & enforce them inside `handle_evaluation_gate()` independently of report summary strings. | Negative gate test confirming sub-threshold scores fail even when summary claims `"PASS"`. |
| **B-10** | Native-Only Repo Hygiene | `/apps/core/download_model.py`, `/apps/core/evaluation/engine.py` | Unused `download_model.py` (`Qwen/Qwen2.5-0.5B`) and unused legacy mock `apps/core/evaluation/engine.py` (`15.5 / 0.85`) remain in repo. | `FAIL` (Policy Hygiene) | Remove/quarantine both files with explicit human approval; ban `huggingface_hub`/`transformers` imports in `maintainer/policy.py`. | Clean `grep` + `tests/test_maintainer_bot.py`. |
| **B-11** | Compute Telemetry Unmeasured | Host (`torch` absent), `/apps/core/workflow/resource_guard.py` | Actual PyTorch base RSS, activation Peak RSS (`B=4, L=256`), CPU `sec/step`, and uncached 64-token `generate()` latency are `NOT VERIFIED`. | `NOT VERIFIED` | Run 10-step CPU training + 20-row decode benchmark post-`B-01`; tune segment cap or batch eval if step time > 1.5 s/step. | Recorded `TrainingMonitor` JSONL Peak RSS (`<1.5 GiB`) and `sec/step`. |
| **B-12** | Broken APIs (`evaluation`, `datasets`, `training`) | `/apps/api/routers/{evaluation,datasets,training}.py`, `/apps/api/evaluation_service.py`, `/apps/core/native/dataset_status.py` | `/v1/evaluation/runs` runs `run_inference=False` (-> 503) and drops DB persistence; `/v1/datasets` lacks audit/token-stats endpoints; `/v1/training/runs` lacks `cancel`, passes no `RamMonitor`, defaults to `128/100`. | `FAIL` | Fix `/v1/evaluation/runs` DB+inference wiring; add `/v1/datasets/{ver}/audit` & `/token-stats`; align `/v1/training/runs` with `tier0_v11()` + `cancel` endpoint. | FastAPI `TestClient` suite (`apps/api/test_*.py`). |

---

## 2. Recommended Dependency Sequence (`Step 0 -> Gate Approval`)

Execute in strict topological order (do NOT start training until Step 5 passes):

1. **Step 0 — Governance & Hygiene Cleanup (`B-02`, `B-10`):**
   - Obtain human decision reconciling V10 `CLOSED_FAIL` archive (`V10-GOV-DEC-01`) vs Stage-2 P11 unlock.
   - With human approval, delete/quarantine `/apps/core/download_model.py` and `/apps/core/evaluation/engine.py`.
2. **Step 1 — CPU PyTorch Runtime & Micro-Benchmark (`B-01`, `B-07`, `B-11`):**
   - Install CPU-only `torch`, `fastapi`, `pydantic`, `pytest` (`$0`, no GPU).
   - Run full `pytest apps/core/native/` + `tests/native/test_checkpoint_resume.py` verifying `weights_only=True` reload.
   - Run 20-step `SmokeMini` + 10-step `Tier0-Default` CPU micro-benchmark (`Peak RSS` & `sec/step` telemetry).
3. **Step 2 — Dataset Generation & Zero-Leakage Certification (`B-03`, `B-04`, `B-05`):**
   - Build `tools/gen_nagi_v11.py` + `tools/audit_leakage_v11.py` (`EL-01..05`, `TL-01`, `SL-01`, `DL-01`, `<=256` length check).
   - Align `TrainingOrchestrator.prepare()` (`files` + `splits` + 4-split leakage guard).
   - Generate deterministic `data/nagi_v11/` + train `zyrquen.tokenizer.v2` (`train` split only) + verify `EL-05`.
4. **Step 3 — Training Pipeline Curriculum & Resume Parity (`B-06`, `B-07`, `B-12`):**
   - Freeze open config decisions (`OD-MS-01`, `OD-MS-02`, `OD-TP-01`, `OD-TP-02`).
   - Patch `train_sft`, `handle_training_execute`, `TrainingOrchestrator`, and `/v1/training/runs` (`stage_tags` sampler, dynamic per-step slot binding, resume SHA-256 verification, `cancel` endpoint).
5. **Step 4 — Evaluation Runner & API Wiring (`B-08`, `B-09`, `B-12`):**
   - Freeze `OD-EP-01` numeric thresholds in code.
   - Implement `tools/eval_nagi_v11.py` (`zyrquen.v11.evaluation_report.v1` + teacher-forced comparison + `max_new_tokens=64`) and wire `/v1/evaluation/runs` + `/v1/datasets/{ver}/audit`.
6. **Step 5 — Untrained Random-Init Baseline Run & Human Tier-2 Gate Submission:**
   - Run `tools/eval_nagi_v11.py` on freshly initialized random weights (`ZyrquenModel`).
   - Confirm `unseen` / `ood` capability metrics score at guessing floor (`< 5%`, `overall_status = FAIL`), while report schema + anti-leakage checks report `PASS`.
   - Submit complete evidence packet for explicit human Tier-2 training approval.

---

## 3. Mandatory Evidence Checklist Before Any Training Authorization

- [ ] `pytest` suite (`apps/core/native/test_*.py` + `tests/native/test_checkpoint_resume.py` + `tests/test_v11_stage1_readiness.py` + `apps/api/test_*.py`): `100% PASS` (excluding explicit GPU tests).
- [ ] Clean Native-Only `maintainer.audit.v1` (`0` external models, `download_model.py` & mock `evaluation/engine.py` removed/quarantined).
- [ ] Measured CPU micro-benchmark: `Peak RSS < 1.5 GiB` (`< 3.0 GiB` soft cap) and `sec/step` fitting `500`-step segment inside `1200s` soft timeout.
- [ ] Generated `data/nagi_v11/manifest.json` SHA-256 + `leakage_audit_report.json` (`EL-01..05`, `TL-01`, `SL-01`, `DL-01`, `max_tokens <= 256` all `PASS`).
- [ ] Random-init baseline `zyrquen.v11.evaluation_report.v1` verified (`schema=PASS`, `capability=FAIL`, proving zero data leakage / zero fabricated metrics).
- [ ] Signed single-use Tier-2 HMAC `approval_id` bound to exact dataset SHA-256, `ZyrquenConfig`, `max_steps=500`, and `seed=1337`.
