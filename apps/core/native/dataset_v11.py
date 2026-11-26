"""ZYRQUEN V11 4-split DataAdapter and leakage detection (pure stdlib)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from apps.core.native.dataset import (
    V11_SPLITS,
    load_split_records,
    resolve_dataset_splits,
    verify_dataset_manifest,
)
try:
    from apps.core.native.sft import extract_entities
except ModuleNotFoundError:
    _V11_ENTITY_FALLBACK_RE = re.compile(
        r"\b(?:(?:TR|VA|TE|UN|OO)_E[0-9A-Za-z_]+|(?:node|item|step)_(?:tr|va|te|un|oo)_[0-9A-Za-z_]+|rec_(?:tr|va|te|un|oo)_e[0-9A-Za-z_]+)\b"
    )

    def extract_entities(text: str) -> list[str]:
        return _V11_ENTITY_FALLBACK_RE.findall(text)


class DatasetLeakageError(ValueError):
    """Raised when V11 dataset split validation or leakage detection fails."""


@dataclass(frozen=True)
class LeakageReport:
    passed: bool
    split_counts: dict[str, int]
    text_overlaps: list[dict[str, Any]] = field(default_factory=list)
    entity_overlaps: list[dict[str, Any]] = field(default_factory=list)
    split_label_mismatches: list[dict[str, Any]] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "status": "PASS" if self.passed else "FAIL",
            "split_counts": dict(self.split_counts),
            "text_overlaps": list(self.text_overlaps),
            "entity_overlaps": list(self.entity_overlaps),
            "split_label_mismatches": list(self.split_label_mismatches),
            "violations": list(self.violations),
        }


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _record_fingerprint_text(row: dict[str, Any]) -> str:
    if "input" in row:
        return _normalize_text(str(row["input"]))
    if "text" in row:
        return _normalize_text(str(row["text"]))
    return _normalize_text(str(row))


def _record_entities(row: dict[str, Any]) -> set[str]:
    parts: list[str] = []
    for key in ("input", "target", "text"):
        val = row.get(key)
        if isinstance(val, str) and val:
            parts.append(val)
    return set(extract_entities("\n".join(parts)))


class DataAdapter:
    """V11 4-split dataset adapter (`train`, `validation`, `unseen`, `ood`) with leakage detection."""

    REQUIRED_SPLITS: tuple[str, ...] = V11_SPLITS

    def __init__(self, dataset_dir: str | Path, *, verify_on_init: bool = True) -> None:
        self.dataset_dir = Path(dataset_dir)
        self.manifest: dict[str, Any] = {}
        if verify_on_init:
            self.verify_manifest()

    def verify_manifest(self) -> dict[str, Any]:
        manifest = verify_dataset_manifest(self.dataset_dir)
        splits = resolve_dataset_splits(manifest)
        if tuple(splits) != self.REQUIRED_SPLITS:
            raise DatasetLeakageError(
                f"V11 DataAdapter requires 4 splits {self.REQUIRED_SPLITS}, got {splits}"
            )
        self.manifest = manifest
        return manifest

    def load_split(self, split: str) -> list[dict[str, Any]]:
        if split not in self.REQUIRED_SPLITS:
            raise ValueError(
                f"invalid V11 split {split!r}; expected one of {self.REQUIRED_SPLITS}"
            )
        records = list(load_split_records(self.dataset_dir, split))
        if not records:
            raise DatasetLeakageError(f"V11 split {split!r} is empty")
        return records

    def load_all_splits(self) -> dict[str, list[dict[str, Any]]]:
        if not self.manifest:
            self.verify_manifest()
        return {split: self.load_split(split) for split in self.REQUIRED_SPLITS}

    def detect_leakage(self, *, raise_on_leakage: bool = False) -> LeakageReport:
        splits_data = self.load_all_splits()
        split_counts = {sp: len(rows) for sp, rows in splits_data.items()}

        text_index: dict[str, dict[str, list[int]]] = {sp: {} for sp in self.REQUIRED_SPLITS}
        entity_index: dict[str, set[str]] = {sp: set() for sp in self.REQUIRED_SPLITS}
        split_label_mismatches: list[dict[str, Any]] = []

        for split_name, rows in splits_data.items():
            for idx, row in enumerate(rows):
                declared_split = row.get("split")
                if declared_split is not None and str(declared_split) != split_name:
                    split_label_mismatches.append(
                        {
                            "split_file": split_name,
                            "row_index": idx,
                            "declared_split": str(declared_split),
                        }
                    )
                norm = _record_fingerprint_text(row)
                if norm:
                    digest = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]
                    text_index[split_name].setdefault(digest, []).append(idx)
                entity_index[split_name].update(_record_entities(row))

        text_overlaps: list[dict[str, Any]] = []
        entity_overlaps: list[dict[str, Any]] = []
        violations: list[str] = []

        if split_label_mismatches:
            violations.append(
                f"split_label_mismatch:{len(split_label_mismatches)}"
            )

        for i, split_a in enumerate(self.REQUIRED_SPLITS):
            for split_b in self.REQUIRED_SPLITS[i + 1 :]:
                shared_hashes = sorted(
                    set(text_index[split_a]).intersection(text_index[split_b])
                )
                if shared_hashes:
                    text_overlaps.append(
                        {
                            "split_a": split_a,
                            "split_b": split_b,
                            "overlap_count": len(shared_hashes),
                            "sample_hashes": shared_hashes[:5],
                        }
                    )
                    violations.append(
                        f"text_overlap:{split_a}<->{split_b}:{len(shared_hashes)}"
                    )

                shared_entities = sorted(
                    entity_index[split_a].intersection(entity_index[split_b])
                )
                if shared_entities:
                    entity_overlaps.append(
                        {
                            "split_a": split_a,
                            "split_b": split_b,
                            "overlap_count": len(shared_entities),
                            "sample_entities": shared_entities[:10],
                        }
                    )
                    violations.append(
                        f"entity_leakage:{split_a}<->{split_b}:{len(shared_entities)}"
                    )

        passed = not violations
        report = LeakageReport(
            passed=passed,
            split_counts=split_counts,
            text_overlaps=text_overlaps,
            entity_overlaps=entity_overlaps,
            split_label_mismatches=split_label_mismatches,
            violations=violations,
        )
        if raise_on_leakage and not passed:
            raise DatasetLeakageError(
                f"V11 dataset leakage detected: {', '.join(violations)}"
            )
        return report

    def validate_no_leakage(self) -> LeakageReport:
        return self.detect_leakage(raise_on_leakage=True)

    def prepare_splits(self) -> tuple[dict[str, list[dict[str, Any]]], LeakageReport]:
        report = self.validate_no_leakage()
        return self.load_all_splits(), report
