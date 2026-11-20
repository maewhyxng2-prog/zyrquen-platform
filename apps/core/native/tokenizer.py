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
SPECIAL_TOKENS = ("<|pad|>", "<|bos|>", "<|eos|>", "<|unk|>")
N_SPECIAL = len(SPECIAL_TOKENS)
BYTE_OFFSET = N_SPECIAL          # byte b -> id BYTE_OFFSET + b
BASE_VOCAB = N_SPECIAL + 256
# A pre-token is an optional leading space + a run of non-space characters,
# or a run of whitespace. (Thai has no spaces, so runs can be long.)
_PRETOKEN = re.compile(r" ?\S+|\s+")


def normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text)


class ZyrquenTokenizer:
    def __init__(self, merges: list[tuple[int, int]] | None = None, version: str = "0.1.0"):
        self.version = version
        self.merges: list[tuple[int, int]] = [tuple(m) for m in (merges or [])]
        self._rank = {pair: i for i, pair in enumerate(self.merges)}
        self._cache: dict[str, tuple[int, ...]] = {}
        # id -> bytes
        self._bytes: dict[int, bytes] = {BYTE_OFFSET + b: bytes([b]) for b in range(256)}
        for i, (a, b) in enumerate(self.merges):
            self._bytes[BASE_VOCAB + i] = self._bytes[a] + self._bytes[b]
        self._special_ids = {tok: i for i, tok in enumerate(SPECIAL_TOKENS)}
        self._special_re = re.compile("(" + "|".join(re.escape(t) for t in SPECIAL_TOKENS) + ")")

    # ---- properties ----
    @property
    def vocab_size(self) -> int:
        return BASE_VOCAB + len(self.merges)

    pad_id, bos_id, eos_id, unk_id = 0, 1, 2, 3

    # ---- training ----
    @classmethod
    def train(cls, texts: Iterable[str], vocab_size: int, version: str = "0.1.0") -> "ZyrquenTokenizer":
        if vocab_size < BASE_VOCAB:
            raise ValueError(f"vocab_size must be >= {BASE_VOCAB}")
        word_counts: Counter = Counter()
        for text in texts:
            for piece in _PRETOKEN.findall(normalize(text)):
                word_counts[piece] += 1
        if not word_counts:
            raise ValueError("training corpus is empty")

        words = {
            tuple(BYTE_OFFSET + b for b in w.encode("utf-8")): c for w, c in word_counts.items()
        }
        merges: list[tuple[int, int]] = []
        while BASE_VOCAB + len(merges) < vocab_size:
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
            new_id = BASE_VOCAB + len(merges)
            merges.append(pair)
            words = {cls._merge_seq(seq, pair, new_id): c for seq, c in words.items()}
        return cls(merges, version)

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
        seq = [BYTE_OFFSET + b for b in piece.encode("utf-8")]
        while len(seq) > 1:
            ranked = [(self._rank.get(p, None), p) for p in zip(seq, seq[1:])]
            ranked = [r for r in ranked if r[0] is not None]
            if not ranked:
                break
            rank, pair = min(ranked)
            seq = list(self._merge_seq(tuple(seq), pair, BASE_VOCAB + rank))
        result = tuple(seq)
        if len(self._cache) < 100_000:
            self._cache[piece] = result
        return result

    def encode(self, text: str, add_bos: bool = False, add_eos: bool = False,
               allow_special: bool = False) -> list[int]:
        ids: list[int] = [self.bos_id] if add_bos else []
        parts = self._special_re.split(text) if allow_special else [text]
        for part in parts:
            if allow_special and part in self._special_ids:
                ids.append(self._special_ids[part])
                continue
            for piece in _PRETOKEN.findall(normalize(part)):
                ids.extend(self._encode_piece(piece))
        if add_eos:
            ids.append(self.eos_id)
        return ids

    def decode(self, ids: Iterable[int], skip_special: bool = True) -> str:
        buf = bytearray()
        out: list[str] = []
        for i in ids:
            if i < N_SPECIAL:
                if not skip_special:
                    out.append(buf.decode("utf-8", errors="replace"))
                    buf.clear()
                    out.append(SPECIAL_TOKENS[i])
                continue
            if i not in self._bytes:
                raise ValueError(f"unknown token id: {i}")
            buf += self._bytes[i]
        out.append(buf.decode("utf-8", errors="replace"))
        return "".join(out)

    # ---- persistence / versioning ----
    def fingerprint(self) -> str:
        payload = json.dumps(self.merges, separators=(",", ":")).encode()
        return hashlib.sha256(payload).hexdigest()

    def save(self, path: str | Path) -> None:
        data = {
            "schema": SCHEMA,
            "version": self.version,
            "normalization": "NFC",
            "special_tokens": list(SPECIAL_TOKENS),
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
        if data.get("schema") != SCHEMA:
            raise ValueError("unsupported tokenizer schema")
        if data.get("special_tokens") != list(SPECIAL_TOKENS):
            raise ValueError("special token mismatch")
        tok = cls([tuple(m) for m in data["merges"]], data.get("version", "0.0.0"))
        if tok.fingerprint() != data.get("sha256") or tok.vocab_size != data.get("vocab_size"):
            raise ValueError("tokenizer integrity check failed")
        return tok

