"""Canonical SFT prompt/target boundary, ephemeral slot binding, and causal masking contract.

Shared single source of truth for both SFT training (`train_sft`) and native inference
(`NativeInferenceEngine`, `StreamingInferenceEngine`) so BOS, SEP, EOS, slot bindings,
and `-100` label masks match identically.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from apps.core.native.tokenizer import SCHEMA_V2, SLOT_COUNT, ZyrquenTokenizer

SFT_FORMAT_VERSION = "zyrquen.sft.v1"
SFT_SEP = "\n### Response:\n"
IGNORE_INDEX = -100

_V10_ENTITY_RE = re.compile(
    r"\b(?:(?:TR|VA|TE)_E[0-9A-Za-z_]+|(?:node|item|step)_(?:tr|va|te)_[0-9A-Za-z_]+|rec_(?:tr|va|te)_e[0-9A-Za-z_]+)\b"
)
_V11_ENTITY_RE = re.compile(
    r"\b(?:(?:TR|VA|TE|UN|OO)_E[0-9A-Za-z_]+|(?:node|item|step)_(?:tr|va|te|un|oo)_[0-9A-Za-z_]+|rec_(?:tr|va|te|un|oo)_e[0-9A-Za-z_]+)\b"
)
_ENTITY_RE = _V11_ENTITY_RE
_SLOT_TOKEN_RE = re.compile(r"<slot_(?:[0-9]|[12][0-9]|3[01])>")


def extract_entities(text: str) -> list[str]:
    """Return all deterministic dataset entity identifiers matched by `_ENTITY_RE` in order."""
    return _ENTITY_RE.findall(text)


@dataclass(frozen=True)
class SlotBinding:
    surface_to_slot: dict[str, str]
    slot_to_surface: dict[str, str]


def bind_ephemeral_slots(
    prompt: str,
    target: str | None = None,
    *,
    permute_slots: bool = False,
    rng: random.Random | None = None,
    max_slots: int = SLOT_COUNT,
) -> tuple[str, str | None, SlotBinding]:
    """Bind dataset entities (`TR_E*`, `VA_E*`, `TE_E*`, `UN_E*`, `OO_E*`) ephemerally to `<slot_0>`..`<slot_31>`.

    Only entities present in `prompt` (and `target` if passed during training) receive slots;
    no entity surface form ever needs to be stored in the static tokenizer vocabulary.
    """
    pool = list(range(max_slots))
    if permute_slots:
        (rng or random).shuffle(pool)

    surface_to_slot: dict[str, str] = {}
    slot_to_surface: dict[str, str] = {}
    cursor = 0

    texts = [prompt] + ([target] if target is not None else [])
    for txt in texts:
        for ent in _ENTITY_RE.findall(txt):
            if ent in surface_to_slot:
                continue
            if cursor >= max_slots:
                raise ValueError(f"example exceeds maximum ephemeral slot capacity ({max_slots})")
            slot = f"<slot_{pool[cursor]}>"
            cursor += 1
            surface_to_slot[ent] = slot
            slot_to_surface[slot] = ent

    def _sub(match: re.Match[str]) -> str:
        return surface_to_slot.get(match.group(0), match.group(0))

    bound_prompt = _ENTITY_RE.sub(_sub, prompt)
    bound_target = _ENTITY_RE.sub(_sub, target) if target is not None else None
    return bound_prompt, bound_target, SlotBinding(surface_to_slot, slot_to_surface)


def restore_ephemeral_slots(text: str, binding: SlotBinding | None) -> str:
    """Restore `<slot_k>` tokens in generated text back to surface entity names."""
    if not binding or not binding.slot_to_surface:
        return text
    return _SLOT_TOKEN_RE.sub(
        lambda m: binding.slot_to_surface.get(m.group(0), m.group(0)),
        text,
    )


def encode_sft_prompt(
    tokenizer: ZyrquenTokenizer,
    prompt: str,
    *,
    sep: str = SFT_SEP,
) -> list[int]:
    """Canonical SFT inference/training prefix: `[bos_id] + encode(prompt + sep)`."""
    if not isinstance(prompt, str) or not prompt:
        raise ValueError("prompt must be a non-empty string")
    body = tokenizer.encode(f"{prompt}{sep}", add_bos=False, add_eos=False)
    return [int(tokenizer.bos_id)] + [int(tok) for tok in body]


def encode_sft_pair(
    tokenizer: ZyrquenTokenizer,
    prompt: str,
    target: str,
    *,
    max_seq_len: int = 256,
    sep: str = SFT_SEP,
    ignore_index: int = IGNORE_INDEX,
) -> tuple[list[int], list[int]]:
    """Encode `(prompt, target)` into causal-shifted `(x, y)` with `-100` masking on prompt.

    Layout before shift:
      `full_ids    = [bos_id] + encode(prompt + sep) + encode(target) + [eos_id]`
      `full_labels = [-100] * len(prefix)           + encode(target) + [eos_id]`
    After causal shift (`x = full_ids[:-1]`, `y = full_labels[1:]`):
      - logit at `x[len(prefix) - 1]` (last SEP token) predicts `target[0]`
      - logit at last target token predicts `eos_id`
      - all prefix positions have label `-100`
    """
    if not isinstance(target, str) or target == "":
        raise ValueError("target must be a non-empty string")
    prefix_ids = encode_sft_prompt(tokenizer, prompt, sep=sep)
    target_ids = [int(tok) for tok in tokenizer.encode(target, add_bos=False, add_eos=False)]
    target_ids.append(int(tokenizer.eos_id))

    full_ids = prefix_ids + target_ids
    if len(full_ids) - 1 > max_seq_len:
        raise ValueError(
            f"SFT example input length {len(full_ids) - 1} exceeds max_seq_len={max_seq_len}"
        )

    full_labels = [ignore_index] * len(prefix_ids) + target_ids
    x = full_ids[:-1]
    y = full_labels[1:]
    return x, y


def build_sft_pairs(
    records: Iterable[dict],
    tokenizer: ZyrquenTokenizer,
    *,
    max_seq_len: int = 256,
    sep: str = SFT_SEP,
    use_slots: bool = False,
    permute_slots: bool = False,
    rng: random.Random | None = None,
) -> list[tuple[list[int], list[int]]]:
    """Convert SFT records (`input`/`target`) into `(x, y)` pairs ready for `collate_sft_batch`."""
    pairs: list[tuple[list[int], list[int]]] = []
    for row in records:
        prompt = str(row["input"])
        target = str(row["target"])
        if use_slots:
            prompt, bound_target, _ = bind_ephemeral_slots(
                prompt,
                target,
                permute_slots=permute_slots,
                rng=rng,
            )
            assert bound_target is not None
            target = bound_target
        pairs.append(
            encode_sft_pair(
                tokenizer,
                prompt,
                target,
                max_seq_len=max_seq_len,
                sep=sep,
            )
        )
    if not pairs:
        raise ValueError("no SFT examples available")
    return pairs


def collate_sft_batch(
    batch: Sequence[tuple[list[int], list[int]]],
    *,
    pad_id: int = 0,
    ignore_index: int = IGNORE_INDEX,
    max_seq_len: int | None = None,
) -> tuple[list[list[int]], list[list[int]]]:
    """Right-pad `(x, y)` sequences using `pad_id` for inputs and `-100` for targets."""
    if not batch:
        raise ValueError("cannot collate empty SFT batch")
    max_len = max(len(x) for x, _ in batch)
    if max_seq_len is not None and max_len > max_seq_len:
        raise ValueError(f"batch length {max_len} exceeds max_seq_len={max_seq_len}")
    xs: list[list[int]] = []
    ys: list[list[int]] = []
    for x, y in batch:
        if len(x) != len(y):
            raise ValueError("mismatched x and y sequence lengths")
        pad = max_len - len(x)
        xs.append(list(x) + [pad_id] * pad)
        ys.append(list(y) + [ignore_index] * pad)
    return xs, ys


def train_slot_safe_tokenizer(
    train_records: Iterable[dict],
    vocab_size: int,
    *,
    version: str = "0.1.0",
    use_slots: bool = True,
    schema: str = SCHEMA_V2,
    forbidden_entities: Iterable[str] = (),
) -> ZyrquenTokenizer:
    """Train native BPE tokenizer strictly on `train` split (never validation/test) and assert EL-05."""
    corpus: list[str] = []
    for row in train_records:
        prompt = str(row["input"])
        target = str(row["target"])
        if use_slots:
            prompt, bound_target, _ = bind_ephemeral_slots(prompt, target, permute_slots=False)
            assert bound_target is not None
            target = bound_target
        corpus.append(f"{prompt}{SFT_SEP}{target}")

    tok = ZyrquenTokenizer.train(corpus, vocab_size=vocab_size, version=version, schema=schema)
    leaked = tok.find_entity_leakage(forbidden_entities)
    if leaked:
        raise ValueError(f"EL-05 vocabulary entity leakage detected: {leaked[:10]}")
    return tok
