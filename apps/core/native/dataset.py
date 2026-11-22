"""Phase 3.3 dataset preparation (standard library only).

Pipeline: import -> clean -> PII redaction -> quality filter -> language label ->
exact de-duplication -> deterministic train/validation/test split -> versioned output
with a provenance manifest. Every source MUST declare a licence string; that is a
record of the user's declaration, not a legal check.
"""
import hashlib
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

SCHEMA = "zyrquen.dataset-manifest.v1"
SPLITS = ("train", "validation", "test")

_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"), None)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<!\d)(?:\+66|0)[\s\-]?\d{1,2}[\s\-]?\d{3}[\s\-]?\d{3,4}(?!\d)")
_THAI_ID = re.compile(r"(?<!\d)\d{1}[\s\-]?\d{4}[\s\-]?\d{5}[\s\-]?\d{2}[\s\-]?\d{1}(?!\d)")
_CARD = re.compile(r"(?<!\d)(?:\d[ \-]?){13,19}(?!\d)")


@dataclass(frozen=True)
class Source:
    path: str
    license: str
    name: str = ""

    def __post_init__(self):
        if not self.license or not self.license.strip():
            raise ValueError(f"source {self.path!r} must declare a licence")


@dataclass(frozen=True)
class PrepConfig:
    min_chars: int = 20
    max_chars: int = 200_000
    min_letter_ratio: float = 0.5
    max_line_repeat_ratio: float = 0.5
    val_fraction: float = 0.01
    test_fraction: float = 0.01
    redact_pii: bool = True
    allowed_languages: tuple[str, ...] = ("th", "en", "mixed")
    version: str = "0.1.0"

    def __post_init__(self):
        if not (0 <= self.val_fraction and 0 <= self.test_fraction
                and self.val_fraction + self.test_fraction < 1):
            raise ValueError("invalid split fractions")


@dataclass
class PrepReport:
    manifest: dict
    dropped: Counter = field(default_factory=Counter)


# ---- import ----
def iter_source(source: Source) -> Iterator[str]:
    path = Path(source.path)
    if path.suffix == ".jsonl":
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                text = json.loads(line).get("text")
            except (json.JSONDecodeError, AttributeError):
                continue
            if isinstance(text, str):
                yield text
    else:  # plain text: documents separated by blank-line-only separators "\n\n\n"
        for doc in re.split(r"\n{3,}", path.read_text(encoding="utf-8")):
            yield doc


# ---- cleaning ----
def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text).translate(_ZERO_WIDTH)
    text = _CONTROL.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def redact_pii(text: str) -> str:
    """Best-effort pattern redaction (emails, Thai/intl phones, Thai ID, card-like
    numbers). It does NOT catch names or addresses and is not a privacy guarantee."""
    text = _EMAIL.sub("[EMAIL]", text)
    text = _THAI_ID.sub("[ID]", text)
    text = _CARD.sub("[NUMBER]", text)
    return _PHONE.sub("[PHONE]", text)


# ---- quality / language ----
def letter_ratio(text: str) -> float:
    non_space = [c for c in text if not c.isspace()]
    if not non_space:
        return 0.0
    return sum(unicodedata.category(c).startswith(("L", "M")) for c in non_space) / len(non_space)


def line_repeat_ratio(text: str) -> float:
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if len(lines) < 2:
        return 0.0
    return 1.0 - len(set(lines)) / len(lines)


def detect_language(text: str) -> str:
    """Script-based heuristic: 'th', 'en' (Latin), 'mixed' or 'other'."""
    thai = latin = other = 0
    for c in text:
        if not c.isalpha():
            continue
        o = ord(c)
        if 0x0E00 <= o <= 0x0E7F:
            thai += 1
        elif c.isascii() or 0x00C0 <= o <= 0x024F:
            latin += 1
        else:
            other += 1
    total = thai + latin + other
    if total == 0 or other / total > 0.3:
        return "other"
    if thai / total > 0.8:
        return "th"
    if latin / total > 0.8:
        return "en"
    return "mixed"


def quality_reason(text: str, cfg: PrepConfig) -> str | None:
    if len(text) < cfg.min_chars:
        return "too_short"
    if len(text) > cfg.max_chars:
        return "too_long"
    if letter_ratio(text) < cfg.min_letter_ratio:
        return "low_letter_ratio"
    if line_repeat_ratio(text) > cfg.max_line_repeat_ratio:
        return "repeated_lines"
    return None


def _dedup_key(text: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", text).casefold().encode("utf-8")).hexdigest()


def assign_split(doc_id: str, cfg: PrepConfig) -> str:
    """Deterministic: the same document always lands in the same split."""
    bucket = int(doc_id[:8], 16) / 0x100000000
    if bucket < cfg.test_fraction:
        return "test"
    if bucket < cfg.test_fraction + cfg.val_fraction:
        return "validation"
    return "train"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---- main entry ----
def prepare_dataset(sources: Iterable[Source], out_dir: str | Path,
                    cfg: PrepConfig | None = None) -> PrepReport:
    cfg = cfg or PrepConfig()
    sources = list(sources)
    if not sources:
        raise ValueError("at least one source is required")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    dropped: Counter = Counter()
    seen: set[str] = set()
    rows: dict[str, list[dict]] = {s: [] for s in SPLITS}
    per_source: dict[str, dict] = {}
    langs: Counter = Counter()

    for src in sources:
        name = src.name or Path(src.path).name
        stat = {"path": src.path, "license": src.license, "read": 0, "kept": 0,
                "sha256": _sha256_file(Path(src.path))}
        for raw in iter_source(src):
            stat["read"] += 1
            text = clean_text(raw)
            if cfg.redact_pii:
                text = redact_pii(text)
            reason = quality_reason(text, cfg)
            if reason:
                dropped[reason] += 1
                continue
            lang = detect_language(text)
            if lang not in cfg.allowed_languages:
                dropped["language_not_allowed"] += 1
                continue
            key = _dedup_key(text)
            if key in seen:
                dropped["duplicate"] += 1
                continue
            seen.add(key)
            split = assign_split(key, cfg)
            rows[split].append({"id": key[:16], "text": text, "lang": lang, "source": name})
            langs[lang] += 1
            stat["kept"] += 1
        per_source[name] = stat

    files = {}
    for split in SPLITS:
        p = out / f"{split}.jsonl"
        with p.open("w", encoding="utf-8") as f:
            for row in rows[split]:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        files[f"{split}.jsonl"] = {"documents": len(rows[split]), "sha256": _sha256_file(p)}

    content_hash = hashlib.sha256(
        "".join(files[f"{s}.jsonl"]["sha256"] for s in SPLITS).encode()).hexdigest()
    manifest = {
        "schema": SCHEMA,
        "version": cfg.version,
        "content_sha256": content_hash,
        "config": cfg.__dict__ | {"allowed_languages": list(cfg.allowed_languages)},
        "sources": per_source,
        "files": files,
        "languages": dict(langs),
        "dropped": dict(dropped),
        "notes": "Licences are user declarations. PII redaction is pattern-based only.",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return PrepReport(manifest, dropped)


def _verify_and_open_split(dataset_dir: str | Path, split: str) -> Path:
    d = Path(dataset_dir)
    manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    name = f"{split}.jsonl"
    if name not in manifest["files"]:
        raise ValueError(f"unknown split: {split}")
    if _sha256_file(d / name) != manifest["files"][name]["sha256"]:
        raise ValueError(f"dataset integrity check failed: {name}")
    return d / name


def load_split(dataset_dir: str | Path, split: str) -> Iterator[str]:
    """Reads one split and verifies its SHA-256 against the manifest first."""
    split_path = _verify_and_open_split(dataset_dir, split)
    with split_path.open(encoding="utf-8") as split_file:
        for line in split_file:
            if line.strip():
                yield json.loads(line)["text"]


def load_split_records(dataset_dir: str | Path, split: str) -> Iterator[dict]:
    """Reads structured JSONL records from a SHA-256 verified split."""
    split_path = _verify_and_open_split(dataset_dir, split)
    with split_path.open(encoding="utf-8") as split_file:
        for line in split_file:
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError(f"invalid record type in {split}.jsonl")
                yield row


def load_sft_split(dataset_dir: str | Path, split: str) -> Iterator[dict]:
    """Reads verified SFT `(input, target)` records from `train`, `validation`, or `test`."""
    for row in load_split_records(dataset_dir, split):
        if "input" not in row or "target" not in row:
            raise ValueError(f"SFT record in {split}.jsonl missing 'input' or 'target'")
        yield row


def detect_dataset_format(dataset_dir: str | Path) -> str:
    """Inspect verified `train.jsonl` first record to distinguish 'sft' vs 'text' datasets."""
    for row in load_split_records(dataset_dir, "train"):
        if "input" in row and "target" in row:
            return "sft"
        if "text" in row:
            return "text"
        raise ValueError("unrecognized record schema in train.jsonl")
    raise ValueError("train.jsonl contains no records")
