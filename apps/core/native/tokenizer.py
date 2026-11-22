"""ZYRQUEN native tokenizer: byte-level BPE, pure standard library.

Vocabulary is learned from a real corpus via ``ZyrquenTokenizer.train``.
Byte-level base alphabet means any Unicode text (Thai, English, emoji, ...)
round-trips losslessly after NFC normalisation.
"""
import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Iterable

SCHEMA = "zyrquen.tokenizer.v1"
SCHEMA_V2 = "zyrquen.tokenizer.v2"
SPECIAL_TOKENS = ("<|pad|>", "<|bos|>", "<|eos|>", "<|unk|>")
SLOT_COUNT = 32
SLOT_TOKENS = tuple(f"<slot_{i}>" for i in range(SLOT_COUNT))
SPECIAL_TOKENS_V2 = SPECIAL_TOKENS + SLOT_TOKENS
N_SPECIAL = len(SPECIAL_TOKENS)
BYTE_OFFSET = N_SPECIAL          # byte b -> id BYTE_OFFSET + b
BASE_VOCAB = N_SPECIAL + 256
# A pre-token is an optional leading space + a run of non-space characters,
# or a run of whitespace. (Thai has no spaces, so runs can be long.)
_PRETOKEN = re.compile(r" ?\S+|\s+")
_SLOT_RE = re.compile("(" + "|".join(re.escape(t) for t in SLOT_TOKENS) + ")")


def normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _special_tokens_for_schema(schema: str) -> tuple[str, ...]:
    if schema == SCHEMA:
        return SPECIAL_TOKENS
    if schema == SCHEMA_V2:
        return SPECIAL_TOKENS_V2
    raise ValueError("unsupported tokenizer schema")


class ZyrquenTokenizer:
    def __init__(
        self,
        merges: list[tuple[int, int]] | None = None,
        version: str = "0.1.0",
        *,
        schema: str = SCHEMA,
    ):
        self.schema = schema
        self.special_tokens = _special_tokens_for_schema(schema)
        self.n_special = len(self.special_tokens)
        self.byte_offset = self.n_special
        self.base_vocab = self.byte_offset + 256
        self.version = version
        self.merges: list[tuple[int, int]] = [tuple(m) for m in (merges or [])]
        self._rank = {pair: i for i, pair in enumerate(self.merges)}
        self._cache: dict[str, tuple[int, ...]] = {}
        # id -> bytes
        self._bytes: dict[int, bytes] = {self.byte_offset + b: bytes([b]) for b in range(256)}
        for i, (a, b) in enumerate(self.merges):
            self._bytes[self.base_vocab + i] = self._bytes[a] + self._bytes[b]
        self._special_ids = {tok: i for i, tok in enumerate(self.special_tokens)}
        self._control_ids = {tok: i for i, tok in enumerate(SPECIAL_TOKENS)}
        self._slot_ids = {
            tok: self._special_ids[tok]
            for tok in SLOT_TOKENS
            if tok in self._special_ids
        }
        self._special_re = re.compile(
            "(" + "|".join(re.escape(t) for t in self.special_tokens) + ")"
        )
        self._control_re = re.compile(
            "(" + "|".join(re.escape(t) for t in SPECIAL_TOKENS) + ")"
        )

    # ---- properties ----
    @property
    def vocab_size(self) -> int:
        return self.base_vocab + len(self.merges)

    @property
    def supports_atomic_slots(self) -> bool:
        return self.schema == SCHEMA_V2

    pad_id, bos_id, eos_id, unk_id = 0, 1, 2, 3

    def slot_id(self, index: int) -> int:
        if not self.supports_atomic_slots:
            raise ValueError("tokenizer schema does not reserve atomic slot IDs")
        if not 0 <= index < SLOT_COUNT:
            raise ValueError(f"slot index out of range: {index}")
        return self._slot_ids[f"<slot_{index}>"]

    # ---- training ----
    @classmethod
    def train(
        cls,
        texts: Iterable[str],
        vocab_size: int,
        version: str = "0.1.0",
        *,
        schema: str = SCHEMA,
    ) -> "ZyrquenTokenizer":
        special_tokens = _special_tokens_for_schema(schema)
        byte_offset = len(special_tokens)
        base_vocab = byte_offset + 256
        if vocab_size < base_vocab:
            raise ValueError(f"vocab_size must be >= {base_vocab}")
        word_counts: Counter = Counter()
        for text in texts:
            normalized = normalize(text)
            segments = _SLOT_RE.split(normalized) if schema == SCHEMA_V2 else [normalized]
            for seg in segments:
                if schema == SCHEMA_V2 and seg in SLOT_TOKENS:
                    continue  # slots are atomic special tokens; do not learn BPE merges for them
                for piece in _PRETOKEN.findall(seg):
                    word_counts[piece] += 1
        if not word_counts:
            raise ValueError("training corpus is empty")

        words = {
            tuple(byte_offset + b for b in w.encode("utf-8")): c for w, c in word_counts.items()
        }
        merges: list[tuple[int, int]] = []
        while base_vocab + len(merges) < vocab_size:
            pairs: Counter = Counter()
            for seq, c in words.items():
                for pair in zip(seq, seq[1:]):
                    pairs[pair] += c
            if not pairs:
                break
            best = max(pairs.items(), key=lambda kv: (kv[1], (-kv[0][0], -kv[0][1])))
            if best[1] < 2:
                break  # no pair repeats; further merges would just memorise
            pair = best[0]
            new_id = base_vocab + len(merges)
            merges.append(pair)
            words = {cls._merge_seq(seq, pair, new_id): c for seq, c in words.items()}
        return cls(merges, version, schema=schema)

    @staticmethod
    def _merge_seq(seq: tuple, pair: tuple, new_id: int) -> tuple:
        out, i = [], 0
        while i < len(seq):
            if i < len(seq) - 1 and (seq[i], seq[i + 1]) == pair:
                out.append(new_id)
                i += 2
            else:
                out.append(seq[i])
                i += 1
        return tuple(out)

    # ---- encode / decode ----
    def _encode_piece(self, piece: str) -> tuple[int, ...]:
        cached = self._cache.get(piece)
        if cached is not None:
            return cached
        seq = [self.byte_offset + b for b in piece.encode("utf-8")]
        while len(seq) > 1:
            ranked = [(self._rank.get(p, None), p) for p in zip(seq, seq[1:])]
            ranked = [r for r in ranked if r[0] is not None]
            if not ranked:
                break
            rank, pair = min(ranked)
            seq = list(self._merge_seq(tuple(seq), pair, self.base_vocab + rank))
        result = tuple(seq)
        if len(self._cache) < 100_000:
            self._cache[piece] = result
        return result

    def encode(
        self,
        text: str,
        add_bos: bool = False,
        add_eos: bool = False,
        allow_special: bool = False,
        allow_slots: bool | None = None,
    ) -> list[int]:
        ids: list[int] = [self.bos_id] if add_bos else []
        use_slots = self.supports_atomic_slots if allow_slots is None else (
            bool(allow_slots) and self.supports_atomic_slots
        )

        if allow_special and (use_slots or not self.supports_atomic_slots):
            splitter = self._special_re
            active_specials = self._special_ids
        elif allow_special:
            splitter = self._control_re
            active_specials = self._control_ids
        elif use_slots:
            splitter = _SLOT_RE
            active_specials = self._slot_ids
        else:
            splitter = None
            active_specials = {}

        parts = splitter.split(text) if splitter is not None else [text]
        for part in parts:
            if not part:
                continue
            if part in active_specials:
                ids.append(active_specials[part])
                continue
            for piece in _PRETOKEN.findall(normalize(part)):
                ids.extend(self._encode_piece(piece))
        if add_eos:
            ids.append(self.eos_id)
        return ids

    def decode(
        self,
        ids: Iterable[int],
        skip_special: bool = True,
        skip_slots: bool = False,
    ) -> str:
        buf = bytearray()
        out: list[str] = []
        for i in ids:
            if i < N_SPECIAL:
                if not skip_special:
                    out.append(buf.decode("utf-8", errors="replace"))
                    buf.clear()
                    out.append(self.special_tokens[i])
                continue
            if N_SPECIAL <= i < self.byte_offset:
                if not skip_slots:
                    out.append(buf.decode("utf-8", errors="replace"))
                    buf.clear()
                    out.append(self.special_tokens[i])
                continue
            if i not in self._bytes:
                raise ValueError(f"unknown token id: {i}")
            buf += self._bytes[i]
        out.append(buf.decode("utf-8", errors="replace"))
        return "".join(out)

    # ---- entity leakage verification (EL-05) ----
    def learned_pieces(self) -> set[str]:
        pieces: set[str] = set()
        for idx in range(self.base_vocab, self.vocab_size):
            raw = self._bytes.get(idx)
            if raw is not None:
                pieces.add(raw.decode("utf-8", errors="replace").strip())
        return pieces

    def find_entity_leakage(self, forbidden_entities: Iterable[str]) -> list[str]:
        forbidden = {e for e in forbidden_entities if isinstance(e, str) and e}
        if not forbidden:
            return []
        pieces = self.learned_pieces()
        leaked: list[str] = []
        for ent in sorted(forbidden):
            if ent in pieces or any(ent in p for p in pieces):
                leaked.append(ent)
        return leaked

    # ---- persistence / versioning ----
    def fingerprint(self) -> str:
        if self.schema == SCHEMA:
            payload = json.dumps(self.merges, separators=(",", ":")).encode()
        else:
            payload = json.dumps(
                {
                    "schema": self.schema,
                    "special_tokens": list(self.special_tokens),
                    "merges": self.merges,
                },
                separators=(",", ":"),
            ).encode()
        return hashlib.sha256(payload).hexdigest()

    def save(self, path: str | Path) -> None:
        data = {
            "schema": self.schema,
            "version": self.version,
            "normalization": "NFC",
            "special_tokens": list(self.special_tokens),
            "vocab_size": self.vocab_size,
            "merges": [list(m) for m in self.merges],
            "sha256": self.fingerprint(),
        }
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: str | Path) -> "ZyrquenTokenizer":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        schema = data.get("schema")
        expected_special = list(_special_tokens_for_schema(str(schema or "")))
        if data.get("special_tokens") != expected_special:
            raise ValueError("special token mismatch")
        tok = cls(
            [tuple(m) for m in data["merges"]],
            data.get("version", "0.0.0"),
            schema=schema,
        )
        if tok.fingerprint() != data.get("sha256") or tok.vocab_size != data.get("vocab_size"):
            raise ValueError("tokenizer integrity check failed")
        return tok

