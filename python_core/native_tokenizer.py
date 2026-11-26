#!/usr/bin/env python3
"""
ZYRQUEN Ω∞ — Native Subword BPE Tokenizer (P2)
-----------------------------------------------
Pure Python 3.11 Byte-Pair Encoding (BPE) subword tokenizer supporting:
- Mixed Thai (\u0E00-\u0E7F), English, numbers, and code punctuation/operators
- Byte-level fallback for lossless encode/decode on unseen OOV symbols
- Versioned vocabulary artifacts and honest coverage/compression metrics
"""

from __future__ import annotations

import collections
import json
import re
from pathlib import Path
from typing import Any


SPECIAL_TOKENS = ["<PAD>", "<UNK>", "<BOS>", "<EOS>"]

_PRETOKEN_RE = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+(?:\.[0-9]+)?|[\u0E00-\u0E7F]+|[^\sA-Za-z0-9\u0E00-\u0E7F]|[\s]+"
)


def _byte_to_sym(b: int) -> str:
    return f"<0x{b:02X}>"


def _sym_to_byte(tok: str) -> int | None:
    if len(tok) == 6 and tok.startswith("<0x") and tok.endswith(">"):
        try:
            return int(tok[3:5], 16)
        except ValueError:
            return None
    return None


def pretokenize(text: str) -> list[str]:
    if not text:
        return []
    return _PRETOKEN_RE.findall(text)


class NativeBPETokenizer:
    def __init__(
        self,
        vocab: dict[str, int] | None = None,
        merges: list[tuple[str, str]] | None = None,
        version: int = 1,
    ) -> None:
        self.version = int(version)
        self.merges: list[tuple[str, str]] = list(merges or [])
        self.merge_ranks: dict[tuple[str, str], int] = {
            pair: idx for idx, pair in enumerate(self.merges)
        }
        if vocab is not None:
            self.vocab: dict[str, int] = dict(vocab)
        else:
            self.vocab = {tok: idx for idx, tok in enumerate(SPECIAL_TOKENS)}
            for b in range(256):
                sym = _byte_to_sym(b)
                if sym not in self.vocab:
                    self.vocab[sym] = len(self.vocab)
        self.id_to_token: dict[int, str] = {idx: tok for tok, idx in self.vocab.items()}

    @property
    def vocab_size(self) -> int:
        return len(self.vocab)

    @property
    def pad_id(self) -> int:
        return self.vocab["<PAD>"]

    @property
    def unk_id(self) -> int:
        return self.vocab["<UNK>"]

    @property
    def bos_id(self) -> int:
        return self.vocab["<BOS>"]

    @property
    def eos_id(self) -> int:
        return self.vocab["<EOS>"]

    @classmethod
    def train(
        cls,
        corpus_lines: list[str],
        *,
        target_vocab_size: int = 384,
        min_pair_freq: int = 2,
        version: int = 1,
    ) -> "NativeBPETokenizer":
        vocab: dict[str, int] = {tok: idx for idx, tok in enumerate(SPECIAL_TOKENS)}
        for b in range(256):
            vocab[_byte_to_sym(b)] = len(vocab)

        word_freqs: collections.Counter[tuple[str, ...]] = collections.Counter()
        for line in corpus_lines:
            for chunk in pretokenize(line):
                bs = chunk.encode("utf-8")
                if not bs:
                    continue
                syms = tuple(_byte_to_sym(b) for b in bs)
                word_freqs[syms] += 1

        merges: list[tuple[str, str]] = []
        max_merges = max(0, int(target_vocab_size) - len(vocab))

        for _ in range(max_merges):
            pair_counts: collections.Counter[tuple[str, str]] = collections.Counter()
            for syms, freq in word_freqs.items():
                if len(syms) < 2:
                    continue
                for i in range(len(syms) - 1):
                    pair_counts[(syms[i], syms[i + 1])] += freq
            if not pair_counts:
                break
            best_pair, best_freq = max(
                pair_counts.items(),
                key=lambda kv: (kv[1], kv[0]),
            )
            if best_freq < min_pair_freq:
                break

            merged_sym = f"{best_pair[0]}::{best_pair[1]}" if len(merges) < 0 else best_pair[0] + best_pair[1]
            # Keep deterministic unambiguous joined token representation
            merges.append(best_pair)
            if merged_sym not in vocab:
                vocab[merged_sym] = len(vocab)

            new_word_freqs: collections.Counter[tuple[str, ...]] = collections.Counter()
            a, b = best_pair
            for syms, freq in word_freqs.items():
                if len(syms) < 2:
                    new_word_freqs[syms] += freq
                    continue
                out: list[str] = []
                i = 0
                n = len(syms)
                while i < n:
                    if i < n - 1 and syms[i] == a and syms[i + 1] == b:
                        out.append(merged_sym)
                        i += 2
                    else:
                        out.append(syms[i])
                        i += 1
                new_word_freqs[tuple(out)] += freq
            word_freqs = new_word_freqs

        return cls(vocab=vocab, merges=merges, version=version)

    def _encode_chunk(self, chunk: str) -> list[int]:
        syms = [_byte_to_sym(b) for b in chunk.encode("utf-8")]
        if not syms:
            return []
        while len(syms) >= 2:
            best_rank: int | None = None
            best_idx = -1
            for i in range(len(syms) - 1):
                pair = (syms[i], syms[i + 1])
                rank = self.merge_ranks.get(pair)
                if rank is not None and (best_rank is None or rank < best_rank):
                    best_rank = rank
                    best_idx = i
            if best_rank is None or best_idx < 0:
                break
            merged = syms[best_idx] + syms[best_idx + 1]
            syms = syms[:best_idx] + [merged] + syms[best_idx + 2 :]
        return [self.vocab.get(s, self.unk_id) for s in syms]

    def encode(self, text: str, *, add_bos: bool = False, add_eos: bool = False) -> list[int]:
        ids: list[int] = [self.bos_id] if add_bos else []
        for chunk in pretokenize(text):
            ids.extend(self._encode_chunk(chunk))
        if add_eos:
            ids.append(self.eos_id)
        return ids

    def decode(self, ids: list[int], *, skip_special: bool = True) -> str:
        byte_buf = bytearray()
        extra_chars: list[str] = []
        raw_parts: list[bytes] = []

        def _flush_bytes() -> None:
            if byte_buf:
                raw_parts.append(bytes(byte_buf))
                byte_buf.clear()

        for tid in ids:
            tok = self.id_to_token.get(int(tid), "<UNK>")
            if tok in SPECIAL_TOKENS:
                if skip_special:
                    continue
                _flush_bytes()
                raw_parts.append(tok.encode("utf-8"))
                continue
            # Expand concatenated <0x..><0x..> symbols cleanly back to exact UTF-8 bytes
            hex_matches = re.findall(r"<0x[0-9A-F]{2}>", tok)
            if hex_matches and "".join(hex_matches) == tok:
                for hm in hex_matches:
                    bv = _sym_to_byte(hm)
                    if bv is not None:
                        byte_buf.append(bv)
            else:
                _flush_bytes()
                extra_chars.append(tok)
                raw_parts.append(tok.encode("utf-8"))

        _flush_bytes()
        return b"".join(raw_parts).decode("utf-8", errors="replace")

    def evaluate_corpus(self, lines: list[str]) -> dict[str, Any]:
        total_bytes = 0
        total_tokens = 0
        unk_count = 0
        roundtrip_ok = 0
        for ln in lines:
            bs = ln.encode("utf-8")
            total_bytes += len(bs)
            ids = self.encode(ln)
            total_tokens += len(ids)
            unk_count += sum(1 for tid in ids if tid == self.unk_id)
            if self.decode(ids) == ln:
                roundtrip_ok += 1
        compression = round(total_bytes / max(1, total_tokens), 4) if lines else 0.0
        return {
            "vocab_size": self.vocab_size,
            "num_merges": len(self.merges),
            "lines": len(lines),
            "total_bytes": total_bytes,
            "total_tokens": total_tokens,
            "compression_bytes_per_token": compression,
            "oov_rate": round(unk_count / max(1, total_tokens), 6),
            "roundtrip_exact_rate": round(roundtrip_ok / max(1, len(lines)), 4) if lines else 1.0,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "native_bpe_v1",
            "version": self.version,
            "vocab": self.vocab,
            "merges": [list(p) for p in self.merges],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NativeBPETokenizer":
        merges = [(str(p[0]), str(p[1])) for p in data.get("merges", []) if len(p) == 2]
        vocab = {str(k): int(v) for k, v in (data.get("vocab") or {}).items()}
        return cls(vocab=vocab, merges=merges, version=int(data.get("version", 1)))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False)

    @classmethod
    def load(cls, path: Path) -> "NativeBPETokenizer":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
