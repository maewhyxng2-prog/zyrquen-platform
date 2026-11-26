import json

import pytest

from apps.core.native.dataset import (
    PrepConfig, Source, assign_split, clean_text, detect_language, load_split,
    prepare_dataset, redact_pii)


def test_clean_text():
    assert clean_text("a\u200bb  c\r\n\r\n\r\n\r\nd\x00") == "ab c\n\nd"


def test_redact_pii():
    t = redact_pii("ติดต่อ somchai@example.com หรือ 081-234-5678 บัตร 1-2345-67890-12-3")
    assert "[EMAIL]" in t and "[PHONE]" in t and "[ID]" in t
    assert "somchai" not in t and "081" not in t


@pytest.mark.parametrize("text,lang", [
    ("สวัสดีครับวันนี้อากาศดีมาก", "th"),
    ("The weather is very nice today", "en"),
    ("วันนี้ I went to the market and bought อาหาร", "mixed"),
    ("今日は天気がいいですね。散歩に行きましょう", "other"),
])
def test_language(text, lang):
    assert detect_language(text) == lang


def test_source_requires_license():
    with pytest.raises(ValueError):
        Source("x.txt", license="  ")


def _make_sources(tmp_path):
    a = tmp_path / "a.jsonl"
    docs = [{"text": f"This is English document number {i} about language models and data."} for i in range(300)]
    docs += [{"text": "วันนี้อากาศดีมาก เราไปกินข้าวกันที่ร้านอาหารใกล้บ้าน ครั้งที่ %d" % i} for i in range(300)]
    docs += [{"text": docs[0]["text"]}, {"text": "short"}, {"text": "!!! ??? ### $$$ %%% ^^^ &&& *** ((( )))"},
             {"text": "mail me at a@b.com about the dataset project please thanks a lot"}]
    a.write_text("\n".join(json.dumps(d, ensure_ascii=False) for d in docs), encoding="utf-8")
    b = tmp_path / "b.txt"
    b.write_text("A plain text document that is long enough to pass the filter.\n\n\n"
                 "Another plain text document, also long enough to be kept here.", encoding="utf-8")
    return [Source(str(a), "CC0-declared", "a"), Source(str(b), "MIT-declared", "b")]


def test_prepare_dataset(tmp_path):
    cfg = PrepConfig(val_fraction=0.1, test_fraction=0.1)
    rep = prepare_dataset(_make_sources(tmp_path), tmp_path / "out", cfg)
    m = rep.manifest
    assert rep.dropped["duplicate"] == 1 and rep.dropped["too_short"] == 1
    assert rep.dropped["low_letter_ratio"] == 1
    total = sum(f["documents"] for f in m["files"].values())
    assert total == 603 and m["files"]["validation.jsonl"]["documents"] > 0
    assert m["files"]["test.jsonl"]["documents"] > 0
    assert m["sources"]["a"]["license"] == "CC0-declared"
    train = list(load_split(tmp_path / "out", "train"))
    assert train and not any("a@b.com" in t for t in train)


def test_split_is_deterministic_and_stable(tmp_path):
    srcs = _make_sources(tmp_path)
    cfg = PrepConfig(val_fraction=0.1, test_fraction=0.1)
    m1 = prepare_dataset(srcs, tmp_path / "o1", cfg).manifest
    m2 = prepare_dataset(srcs, tmp_path / "o2", cfg).manifest
    assert m1["content_sha256"] == m2["content_sha256"]
    assert assign_split("00000000" + "0" * 56, cfg) == "test"


def test_integrity_check(tmp_path):
    prepare_dataset(_make_sources(tmp_path), tmp_path / "out", PrepConfig())
    p = tmp_path / "out" / "train.jsonl"
    p.write_text(p.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        list(load_split(tmp_path / "out", "train"))


def test_requires_sources(tmp_path):
    with pytest.raises(ValueError):
        prepare_dataset([], tmp_path / "o")
