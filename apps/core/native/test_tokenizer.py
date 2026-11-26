import pytest

from apps.core.native.tokenizer import BASE_VOCAB, ZyrquenTokenizer

CORPUS = [
    "สวัสดีครับ วันนี้อากาศดีมาก ไปกินข้าวกันไหม",
    "ZYRQUEN is an independent AI platform with its own native model.",
    "การฝึกโมเดลภาษาต้องใช้ข้อมูลจำนวนมากและทรัพยากรการคำนวณ",
    "The quick brown fox jumps over the lazy dog. The model learns language.",
] * 20


@pytest.fixture(scope="module")
def tok():
    return ZyrquenTokenizer.train(CORPUS, vocab_size=BASE_VOCAB + 120, version="test")


def test_learns_merges(tok):
    assert 0 < len(tok.merges) <= 120
    assert tok.vocab_size == BASE_VOCAB + len(tok.merges)


@pytest.mark.parametrize("text", [
    "สวัสดีครับ", "Hello, world!", "ผสม mixed ไทย English 123", "emoji 😀🚀 ok",
    "  leading and  double  spaces\n\tnewline", "", "ก",
])
def test_roundtrip(tok, text):
    assert tok.decode(tok.encode(text)) == text


def test_compresses_seen_text(tok):
    text = "The model learns language."
    assert len(tok.encode(text)) < len(text.encode("utf-8"))


def test_unseen_text_roundtrips(tok):
    text = "คำที่ไม่เคยเห็นมาก่อน xyzzy 漢字"
    assert tok.decode(tok.encode(text)) == text


def test_deterministic_training():
    a = ZyrquenTokenizer.train(CORPUS, BASE_VOCAB + 50)
    b = ZyrquenTokenizer.train(CORPUS, BASE_VOCAB + 50)
    assert a.merges == b.merges and a.fingerprint() == b.fingerprint()


def test_special_tokens(tok):
    ids = tok.encode("hi", add_bos=True, add_eos=True)
    assert ids[0] == tok.bos_id and ids[-1] == tok.eos_id
    assert tok.decode(ids) == "hi"
    ids = tok.encode("a<|eos|>b", allow_special=True)
    assert tok.eos_id in ids
    assert tok.eos_id not in tok.encode("a<|eos|>b")  # plain text by default


def test_save_load_and_tamper(tok, tmp_path):
    p = tmp_path / "tokenizer.json"
    tok.save(p)
    loaded = ZyrquenTokenizer.load(p)
    text = "สวัสดี ZYRQUEN"
    assert loaded.encode(text) == tok.encode(text)
    assert loaded.version == "test"
    p.write_text(p.read_text(encoding="utf-8").replace('"version": "test"', '"version": "test"').replace("[[", "[[9,", 1), encoding="utf-8")
    with pytest.raises(ValueError):
        ZyrquenTokenizer.load(p)


def test_invalid_inputs(tok):
    with pytest.raises(ValueError):
        ZyrquenTokenizer.train([], BASE_VOCAB + 10)
    with pytest.raises(ValueError):
        ZyrquenTokenizer.train(CORPUS, 10)
    with pytest.raises(ValueError):
        tok.decode([10**9])
