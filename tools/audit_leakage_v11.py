#!/usr/bin/env python3
"""
ZYRQUEN Native Model v11 — Read-Only Leakage, Integrity, Schema & PII Auditor

Strictly read-only validator for `data/nagi_v11/` 4-split SFT corpora.
Verifies:
  1. INTEGRITY_MANIFEST  (zyrquen.dataset-manifest.v1, native origin/license,
                          both "files" & "splits", 4 splits SHA-256, content_sha256)
  2. SCHEMA_VALIDATION   (all required fields, capability set, split match, unique IDs)
  3. UNIQUE_ANSWER       (unique_answer_verified == True on 100% of records)
  4. EL_ENTITY_DISJOINTNESS (EL-01..04: zero entity overlap across all 6 split pairs
                             + strict split namespace prefix purity TR/VA/UN/OO)
  5. TL_TEMPLATE_DISJOINTNESS (TL-01: Family B unseen & Family C ood skeletons +
                               template_ids strictly disjoint from Family A train/val)
  6. SL_STRUCTURAL_DISJOINTNESS (SL-01: train/val hop<=3, plan<=4 vs ood hop>=4 or plan>=5)
  7. DL_DEDUP_AND_INPUT_DISJOINTNESS (DL-01: zero exact pair dups, zero cross-split input
                                      overlap, within-train shingle near-dup rate <= 1.0%)
  8. PII_SCAN            (zero emails, phones, national IDs, SSNs, cards, tokens, IPs, paths)
  9. TOKENIZER_EL05_AND_BUDGET (if tokenizer present/specified: EL-05 check + 100% of
                                slot-bound SFT pairs <= max_seq_len (256))
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
TOOLS_DIR = PROJECT_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from apps.core.native.dataset import (  # noqa: E402
    SCHEMA as MANIFEST_SCHEMA,
    V11_SPLITS,
    verify_dataset_manifest,
)
from apps.core.native.sft import (  # noqa: E402
    bind_ephemeral_slots,
    encode_sft_pair,
    extract_entities,
)
from apps.core.native.tokenizer import ZyrquenTokenizer  # noqa: E402

try:
    from gen_nagi_v11 import (  # noqa: E402
        CAPABILITIES,
        DATASET_ID,
        LICENSE_TAG,
        ORIGIN_TAG,
        scan_pii,
    )
except ImportError:  # pragma: no cover
    CAPABILITIES = (
        "abstract_reasoning",
        "relational_generalization",
        "ood_transfer",
        "multi_step_planning",
        "self_verification",
        "knowledge_integration",
    )
    DATASET_ID = "nagi_v11"
    ORIGIN_TAG = "native-deterministic-solver-v11"
    LICENSE_TAG = "synthetic-native-zyrquen-v11"
    scan_pii = None  # type: ignore

REQUIRED_RECORD_FIELDS = frozenset(
    {
        "id",
        "split",
        "capability",
        "stage_tag",
        "input",
        "target",
        "entities",
        "template_id",
        "structure_signature",
        "unique_answer_verified",
    }
)

EXPECTED_SPLIT_PREFIXES: dict[str, tuple[str, ...]] = {
    "train": ("TR_E", "node_tr_", "item_tr_", "step_tr_", "rec_tr_e"),
    "validation": ("VA_E", "node_va_", "item_va_", "step_va_", "rec_va_e"),
    "unseen": ("UN_E", "node_un_", "item_un_", "step_un_", "rec_un_e"),
    "ood": ("OO_E", "node_oo_", "item_oo_", "step_oo_", "rec_oo_e"),
}

_ENT_MASK_RE = re.compile(
    r"\b(?:(?:TR|VA|TE|UN|OO)_E[0-9A-Za-z_]+|(?:node|item|step)_(?:tr|va|te|un|oo)_[0-9A-Za-z_]+|rec_(?:tr|va|te|un|oo)_e[0-9A-Za-z_]+)\b"
)
_NUM_MASK_RE = re.compile(r"\b\d+\b")
_TAG_MASK_RE = re.compile(r"\b(?:k\d+|s\d+|val_\d+(?:_alt)?|cls_\d+|tier_\d+)\b")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_text(text: str) -> str:
    return " ".join(text.casefold().split())


def _template_skeleton(text: str) -> str:
    masked = _ENT_MASK_RE.sub("<ENT>", text)
    masked = _TAG_MASK_RE.sub("<TOK>", masked)
    masked = _NUM_MASK_RE.sub("<NUM>", masked)
    return _normalize_text(masked)


def _shingles(text: str, k: int = 5) -> set[str]:
    tokens = _normalize_text(text).split()
    if len(tokens) < k:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i : i + k]) for i in range(len(tokens) - k + 1)}


def run_audit(
    dataset_dir: Path | str,
    *,
    tokenizer_path: Path | str | None = None,
    max_seq_len: int = 256,
    require_tokenizer: bool = False,
    strict: bool | None = None,
    ngram_size: int = 5,
    max_ngram_overlap: float = 0.05,
) -> dict[str, Any]:
    root = Path(dataset_dir)
    gates: dict[str, dict[str, Any]] = {}

    # 1. INTEGRITY_MANIFEST
    manifest: dict[str, Any] | None = None
    manifest_errors: list[str] = []
    strict_mode = bool(strict) if strict is not None else False
    if root.is_symlink() or not root.is_dir():
        manifest_errors.append(f"Dataset directory missing or symlinked: {root}")
    else:
        resolved_root = root.resolve()
        try:
            manifest = verify_dataset_manifest(resolved_root, require_schema=True)
            if strict is None:
                strict_mode = manifest.get("origin") == ORIGIN_TAG
            if manifest.get("schema") != MANIFEST_SCHEMA:
                manifest_errors.append(f"Unexpected schema: {manifest.get('schema')!r}")
            if manifest.get("dataset") != DATASET_ID:
                manifest_errors.append(f"Unexpected dataset id: {manifest.get('dataset')!r}")
            if strict_mode:
                if manifest.get("origin") != ORIGIN_TAG:
                    manifest_errors.append(f"Missing or non-native origin: {manifest.get('origin')!r}")
                if manifest.get("license") != LICENSE_TAG:
                    manifest_errors.append(f"Missing or non-native license: {manifest.get('license')!r}")
                files_map = manifest.get("files")
                splits_map = manifest.get("splits")
                if not isinstance(files_map, dict) or not all(f"{s}.jsonl" in files_map for s in V11_SPLITS):
                    manifest_errors.append("Manifest missing complete 4-split 'files' contract.")
                if not isinstance(splits_map, dict) or not all(s in splits_map for s in V11_SPLITS):
                    manifest_errors.append("Manifest missing complete 4-split 'splits' contract.")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            manifest_errors.append(str(exc))

    gates["INTEGRITY_MANIFEST"] = {
        "passed": len(manifest_errors) == 0,
        "errors": manifest_errors[:20],
        "content_sha256": manifest.get("content_sha256") if manifest else None,
    }

    if manifest is None or manifest_errors:
        return {
            "schema": "zyrquen.v11.dataset_audit.v1",
            "dataset_dir": str(root),
            "overall_status": "FAIL",
            "status": "FAIL",
            "splits_verified": [],
            "split_counts": {},
            "total_examples": 0,
            "gates": gates,
        }

    # Load all 4 splits read-only
    records_by_split: dict[str, list[dict[str, Any]]] = {}
    schema_errors: list[str] = []
    seen_ids: set[str] = set()
    unique_ans_failures: list[str] = []
    split_counts: dict[str, int] = {}
    minimal_required = frozenset({"split", "capability", "input", "target", "unique_answer_verified"})

    for sp in V11_SPLITS:
        sp_path = root / f"{sp}.jsonl"
        rows: list[dict[str, Any]] = []
        for ln_no, raw_ln in enumerate(sp_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not raw_ln.strip():
                continue
            try:
                obj = json.loads(raw_ln)
            except json.JSONDecodeError as exc:
                schema_errors.append(f"{sp}:{ln_no} invalid json: {exc}")
                continue
            if not isinstance(obj, dict):
                schema_errors.append(f"{sp}:{ln_no} record is not an object")
                continue
            req_fields = REQUIRED_RECORD_FIELDS if strict_mode else minimal_required
            missing = req_fields - set(obj.keys())
            if missing:
                schema_errors.append(f"{sp}:{ln_no} missing fields {sorted(missing)}")
                continue
            if obj.get("split") != sp:
                schema_errors.append(f"{sp}:{ln_no} split mismatch {obj.get('split')!r}")
            if obj.get("capability") not in CAPABILITIES:
                schema_errors.append(f"{sp}:{ln_no} invalid capability {obj.get('capability')!r}")
            if not isinstance(obj.get("input"), str) or not obj["input"].strip():
                schema_errors.append(f"{sp}:{ln_no} empty input")
            if not isinstance(obj.get("target"), str) or not obj["target"].strip():
                schema_errors.append(f"{sp}:{ln_no} empty target")
            if strict_mode and not isinstance(obj.get("structure_signature"), dict):
                schema_errors.append(f"{sp}:{ln_no} invalid structure_signature")
            rec_id = str(obj.get("id") or obj.get("example_id") or "")
            if not rec_id or rec_id in seen_ids:
                schema_errors.append(f"{sp}:{ln_no} duplicate or empty id {rec_id!r}")
            else:
                seen_ids.add(rec_id)
            if obj.get("unique_answer_verified") is not True:
                unique_ans_failures.append(f"{sp}:{rec_id}")
            rows.append(obj)
        if not rows:
            schema_errors.append(f"{sp}.jsonl has 0 records")
        records_by_split[sp] = rows
        split_counts[sp] = len(rows)

    gates["SCHEMA_VALIDATION"] = {
        "passed": len(schema_errors) == 0,
        "error_count": len(schema_errors),
        "errors": schema_errors[:20],
    }
    gates["UNIQUE_ANSWER"] = {
        "passed": len(unique_ans_failures) == 0,
        "failure_count": len(unique_ans_failures),
        "failures": unique_ans_failures[:20],
    }

    # 4. EL_ENTITY_DISJOINTNESS (EL-01..04 + prefix purity)
    split_entities: dict[str, set[str]] = {}
    prefix_violations: list[str] = []
    for sp in V11_SPLITS:
        ents: set[str] = set()
        allowed_prefixes = EXPECTED_SPLIT_PREFIXES[sp]
        for row in records_by_split[sp]:
            row_ents = set(extract_entities(f"{row.get('input', '')}\n{row.get('target', '')}"))
            meta_ents = row.get("entities")
            if isinstance(meta_ents, list):
                row_ents.update(str(e) for e in meta_ents if e)
            for ent in row_ents:
                if not ent.startswith(allowed_prefixes):
                    prefix_violations.append(f"{sp}:{row.get('id')}:{ent}")
            ents.update(row_ents)
        split_entities[sp] = ents

    cross_entity_overlaps: list[dict[str, Any]] = []
    for i, s1 in enumerate(V11_SPLITS):
        for s2 in V11_SPLITS[i + 1 :]:
            overlap = sorted(split_entities[s1] & split_entities[s2])
            if overlap:
                cross_entity_overlaps.append(
                    {"pair": f"{s1}<->{s2}", "count": len(overlap), "samples": overlap[:10]}
                )

    gates["EL_ENTITY_DISJOINTNESS"] = {
        "passed": len(cross_entity_overlaps) == 0 and len(prefix_violations) == 0,
        "entity_counts": {sp: len(v) for sp, v in split_entities.items()},
        "cross_split_overlaps": cross_entity_overlaps,
        "prefix_violations": prefix_violations[:20],
    }

    # 5. TL_TEMPLATE_DISJOINTNESS (TL-01)
    if strict_mode:
        skeletons: dict[str, set[str]] = {}
        tpl_ids: dict[str, set[str]] = {}
        for sp in V11_SPLITS:
            skeletons[sp] = {_template_skeleton(str(r.get("input", ""))) for r in records_by_split[sp]}
            tpl_ids[sp] = {str(r.get("template_id") or "") for r in records_by_split[sp]}

        family_a_skel = skeletons["train"] | skeletons["validation"]
        family_a_tpl = tpl_ids["train"] | tpl_ids["validation"]

        tl_collisions: list[dict[str, Any]] = []
        for held_sp in ("unseen", "ood"):
            skel_ov = sorted(family_a_skel & skeletons[held_sp])
            tpl_ov = sorted(family_a_tpl & tpl_ids[held_sp])
            if skel_ov or tpl_ov:
                tl_collisions.append(
                    {
                        "pair": f"train|validation<->{held_sp}",
                        "skeleton_overlap": len(skel_ov),
                        "template_id_overlap": len(tpl_ov),
                        "samples": (tpl_ov + skel_ov)[:10],
                    }
                )
        unseen_ood_tpl = sorted(tpl_ids["unseen"] & tpl_ids["ood"])
        unseen_ood_skel = sorted(skeletons["unseen"] & skeletons["ood"])
        if unseen_ood_tpl or unseen_ood_skel:
            tl_collisions.append(
                {
                    "pair": "unseen<->ood",
                    "skeleton_overlap": len(unseen_ood_skel),
                    "template_id_overlap": len(unseen_ood_tpl),
                    "samples": (unseen_ood_tpl + unseen_ood_skel)[:10],
                }
            )

        gates["TL_TEMPLATE_DISJOINTNESS"] = {
            "passed": len(tl_collisions) == 0,
            "collisions": tl_collisions,
        }

        # 6. SL_STRUCTURAL_DISJOINTNESS (SL-01)
        sl_violations: list[str] = []
        for sp in ("train", "validation", "unseen"):
            for r in records_by_split[sp]:
                sig = r.get("structure_signature") or {}
                hop = int(sig.get("hop_depth") or 0)
                plen = int(sig.get("plan_len") or 0)
                if hop > 3 or plen > 4:
                    sl_violations.append(f"{sp}:{r.get('id')}:hop={hop},plan={plen} exceeds ID ceiling")
        for r in records_by_split["ood"]:
            sig = r.get("structure_signature") or {}
            hop = int(sig.get("hop_depth") or 0)
            plen = int(sig.get("plan_len") or 0)
            if hop < 4 and plen < 5:
                sl_violations.append(f"ood:{r.get('id')}:hop={hop},plan={plen} violates OOD depth (>=4 or plan>=5)")

        gates["SL_STRUCTURAL_DISJOINTNESS"] = {
            "passed": len(sl_violations) == 0,
            "violation_count": len(sl_violations),
            "violations": sl_violations[:20],
        }
    else:
        gates["TL_TEMPLATE_DISJOINTNESS"] = {
            "passed": True,
            "status": "NOT APPLICABLE (minimal fixture)",
            "collisions": [],
        }
        gates["SL_STRUCTURAL_DISJOINTNESS"] = {
            "passed": True,
            "status": "NOT APPLICABLE (minimal fixture)",
            "violation_count": 0,
            "violations": [],
        }

    # 7. DL_DEDUP_AND_INPUT_DISJOINTNESS (DL-01)
    norm_inputs_by_split: dict[str, set[str]] = {}
    pair_counts: dict[str, int] = {}
    exact_pair_dups: list[str] = []

    for sp in V11_SPLITS:
        inps: set[str] = set()
        for r in records_by_split[sp]:
            n_in = _normalize_text(str(r.get("input", "")))
            n_pair = f"{n_in}||{_normalize_text(str(r.get('target', '')))}"
            inps.add(n_in)
            pair_counts[n_pair] = pair_counts.get(n_pair, 0) + 1
            if pair_counts[n_pair] > 1:
                exact_pair_dups.append(f"{sp}:{r.get('id')}")
        norm_inputs_by_split[sp] = inps

    cross_input_overlaps: list[dict[str, Any]] = []
    for i, s1 in enumerate(V11_SPLITS):
        for s2 in V11_SPLITS[i + 1 :]:
            ov = norm_inputs_by_split[s1] & norm_inputs_by_split[s2]
            if ov:
                cross_input_overlaps.append({"pair": f"{s1}<->{s2}", "count": len(ov)})

    # Fast inverted 5-gram shingle check within train for true fuzzy duplicates (>=0.85 Jaccard)
    train_rows = records_by_split["train"]
    shingle_index: dict[str, list[int]] = defaultdict(list)
    row_shingles: list[set[str]] = []
    near_dup_indices: set[int] = set()
    for idx, r in enumerate(train_rows):
        sh = _shingles(f"{r.get('input', '')} {r.get('target', '')}", k=5)
        row_shingles.append(sh)
        candidates: set[int] = set()
        for gram in sh:
            candidates.update(shingle_index[gram])
        for cand in candidates:
            other = row_shingles[cand]
            union_sz = len(sh | other)
            if union_sz > 0 and (len(sh & other) / union_sz) >= 0.85:
                near_dup_indices.add(idx)
                break
        for gram in sh:
            if len(shingle_index[gram]) < 64:
                shingle_index[gram].append(idx)

    near_dup_rate = (len(near_dup_indices) / len(train_rows)) if train_rows else 0.0
    gates["DL_DEDUP_AND_INPUT_DISJOINTNESS"] = {
        "passed": (
            len(exact_pair_dups) == 0
            and len(cross_input_overlaps) == 0
            and near_dup_rate <= 0.01
        ),
        "exact_pair_duplicates": len(exact_pair_dups),
        "cross_split_input_overlaps": cross_input_overlaps,
        "within_train_near_dup_count": len(near_dup_indices),
        "within_train_near_dup_rate": round(near_dup_rate, 6),
    }

    # 7b. CROSS_SPLIT_NGRAM_OVERLAP (P11-B <= 5% ceiling across train/val/unseen(test)/ood)
    ngram_splits: dict[str, list[dict[str, Any]]] = dict(records_by_split)
    optional_test_path = root / "test.jsonl"
    if optional_test_path.is_file() and not optional_test_path.is_symlink():
        test_rows = [
            json.loads(ln)
            for ln in optional_test_path.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        if test_rows:
            ngram_splits["test"] = test_rows

    split_ngrams: dict[str, set[str]] = {}
    for sp_name, sp_rows in ngram_splits.items():
        ng_set: set[str] = set()
        for r in sp_rows:
            ng_set.update(_shingles(f"{r.get('input', '')} {r.get('target', '')}", k=ngram_size))
        split_ngrams[sp_name] = ng_set

    pairwise_ngram_stats: dict[str, dict[str, Any]] = {}
    max_pairwise_rate = 0.0
    heldout_union: set[str] = set()
    heldout_overlap_union: set[str] = set()
    ordered_sp = [s for s in ("train", "validation", "unseen", "test", "ood") if s in split_ngrams]

    for i, s1 in enumerate(ordered_sp):
        for s2 in ordered_sp[i + 1 :]:
            ng1, ng2 = split_ngrams[s1], split_ngrams[s2]
            denom = min(len(ng1), len(ng2))
            shared = ng1 & ng2
            rate = (len(shared) / denom) if denom > 0 else 0.0
            max_pairwise_rate = max(max_pairwise_rate, rate)
            pairwise_ngram_stats[f"{s1}<->{s2}"] = {
                "shared_ngrams": len(shared),
                "min_split_ngrams": denom,
                "overlap_rate": round(rate, 6),
                "overlap_percent": round(rate * 100.0, 4),
            }
            if s1 == "train" or s2 == "train":
                other_ng = ng2 if s1 == "train" else ng1
                heldout_union.update(other_ng)
                heldout_overlap_union.update(shared)

    overall_ngram_overlap_rate = (
        len(heldout_overlap_union) / len(heldout_union) if heldout_union else 0.0
    )
    ngram_passed = (
        (
            overall_ngram_overlap_rate <= max_ngram_overlap
            and max_pairwise_rate <= max_ngram_overlap
        )
        if strict_mode
        else True
    )
    gates["CROSS_SPLIT_NGRAM_OVERLAP"] = {
        "passed": ngram_passed,
        "ngram_size": ngram_size,
        "max_allowed_rate": max_ngram_overlap,
        "max_allowed_percent": round(max_ngram_overlap * 100.0, 2),
        "overall_overlap_rate": round(overall_ngram_overlap_rate, 6),
        "overall_overlap_percent": round(overall_ngram_overlap_rate * 100.0, 4),
        "max_pairwise_overlap_rate": round(max_pairwise_rate, 6),
        "max_pairwise_overlap_percent": round(max_pairwise_rate * 100.0, 4),
        "pairwise": pairwise_ngram_stats,
    }

    # 8. PII_SCAN
    pii_hits: list[dict[str, Any]] = []
    if scan_pii is not None:
        for sp in V11_SPLITS:
            for r in records_by_split[sp]:
                for field in ("input", "target"):
                    findings = scan_pii(str(r.get(field, "")))
                    if findings:
                        pii_hits.append(
                            {"split": sp, "id": r.get("id"), "field": field, "findings": findings[:3]}
                        )
    gates["PII_SCAN"] = {
        "passed": scan_pii is not None and len(pii_hits) == 0,
        "pii_match_count": len(pii_hits),
        "samples": pii_hits[:10],
    }

    # 9. TOKENIZER_EL05_AND_BUDGET (optional unless require_tokenizer=True or tokenizer.json present)
    tok_candidate = Path(tokenizer_path) if tokenizer_path else (root / "tokenizer.json")
    if tok_candidate.is_file() and not tok_candidate.is_symlink():
        tok_errors: list[str] = []
        max_bound_tokens = 0
        try:
            tok = ZyrquenTokenizer.load(tok_candidate)
            heldout_ents = sorted(
                split_entities["validation"] | split_entities["unseen"] | split_entities["ood"]
            )
            leaked_toks = tok.find_entity_leakage(heldout_ents)
            if leaked_toks:
                tok_errors.append(f"EL-05 leakage in tokenizer: {leaked_toks[:10]}")
            for sp in V11_SPLITS:
                for r in records_by_split[sp]:
                    bp, bt, _ = bind_ephemeral_slots(str(r["input"]), str(r["target"]), permute_slots=False)
                    assert bt is not None
                    x_ids, _ = encode_sft_pair(tok, bp, bt, max_seq_len=max_seq_len)
                    max_bound_tokens = max(max_bound_tokens, len(x_ids))
            tok_sha = tok.fingerprint()
            tok_vocab = tok.vocab_size
        except (OSError, ValueError, KeyError, TypeError) as exc:
            tok_errors.append(str(exc))
            tok_sha = None
            tok_vocab = None

        gates["TOKENIZER_EL05_AND_BUDGET"] = {
            "passed": len(tok_errors) == 0,
            "status": "PASS" if len(tok_errors) == 0 else "FAIL",
            "tokenizer_path": str(tok_candidate),
            "tokenizer_sha256": tok_sha,
            "vocab_size": tok_vocab,
            "max_slot_bound_sft_tokens": max_bound_tokens,
            "max_seq_len": max_seq_len,
            "errors": tok_errors[:20],
        }
    else:
        gates["TOKENIZER_EL05_AND_BUDGET"] = {
            "passed": not require_tokenizer,
            "status": "FAIL" if require_tokenizer else "NOT RUN",
            "detail": f"No tokenizer found at {tok_candidate}",
        }

    overall_ok = all(bool(g.get("passed")) for g in gates.values())
    status_str = "PASS" if overall_ok else "FAIL"
    return {
        "schema": "zyrquen.v11.dataset_audit.v1",
        "dataset_dir": str(root),
        "dataset_manifest_sha256": _sha256_file(root / "manifest.json"),
        "dataset_content_sha256": manifest.get("content_sha256"),
        "overall_status": status_str,
        "status": status_str,
        "splits_verified": list(V11_SPLITS),
        "split_counts": split_counts,
        "total_examples": sum(split_counts.values()),
        "gates": gates,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only V11 dataset integrity, leakage (EL/TL/SL/DL), n-gram overlap (<=5%), PII, and EL-05 tokenizer audit."
    )
    parser.add_argument("--dataset-dir", type=Path, default=PROJECT_ROOT / "data" / "nagi_v11")
    parser.add_argument("--tokenizer", type=Path, default=None)
    parser.add_argument("--max-seq-len", type=int, default=256)
    parser.add_argument("--ngram-size", type=int, default=5)
    parser.add_argument("--max-ngram-overlap", type=float, default=0.05)
    parser.add_argument("--require-tokenizer", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_audit(
        args.dataset_dir,
        tokenizer_path=args.tokenizer,
        max_seq_len=args.max_seq_len,
        require_tokenizer=args.require_tokenizer,
        strict=True,
        ngram_size=args.ngram_size,
        max_ngram_overlap=args.max_ngram_overlap,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["overall_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
