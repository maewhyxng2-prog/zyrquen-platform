#!/usr/bin/env python3
"""
ZYRQUEN Native Cognitive Pipeline (Pure Python 3.11 Standard Library)
---------------------------------------------------------------------
Implements the multi-stage native cognitive cycle:
    Understand -> Interpret -> Retrieve -> Reason -> Evaluate -> Respond -> Learn

Design guarantees:
- Zero external LLMs and zero pretrained external model weights.
- Zero hardcoded per-emoji or single-greeting lookup tables.
- Separates communicative understanding from factual retrieval so ordinary human
  communication (greetings, courtesy, help/capability inquiries, affective
  expressions, contextual follow-ups, and compositional reasoning over known
  semantic primitives) succeeds cleanly even when the Knowledge Graph is empty
  and no trained checkpoint exists.
- Tracks internal cognitive states:
    UNDERSTOOD | INFERRED | UNCERTAIN | UNKNOWN | NEEDS_CLARIFICATION
  alongside system epistemic states:
    VERIFIED | UNCERTAIN | NOT_LEARNED | UNABLE_TO_INFER | UNKNOWN | BLOCKED | PENDING_APPROVAL | FAILED
- Never mutates neural model weights autonomously (model_weights_changed=False)
  and never bypasses approval or authorization gates.
"""

from __future__ import annotations

import collections
import json
import re
import sqlite3
import time
import unicodedata
import uuid
from typing import Any


COGNITIVE_STATES = (
    "UNDERSTOOD",
    "INFERRED",
    "UNCERTAIN",
    "UNKNOWN",
    "NEEDS_CLARIFICATION",
)

EPISTEMIC_STATES = (
    "VERIFIED",
    "UNCERTAIN",
    "NOT_LEARNED",
    "UNABLE_TO_INFER",
    "UNKNOWN",
    "BLOCKED",
    "PENDING_APPROVAL",
    "FAILED",
)

# General Unicode descriptor semantic axes (derived from official Unicode character names)
_AFFECT_AXIS_KEYWORDS: dict[str, set[str]] = {
    "joy_amusement": {
        "JOY", "LAUGH", "LAUGHING", "TEARS", "GRIN", "GRINNING", "SMILE",
        "SMILING", "CHUCKLE", "WINK", "WINKING", "ROFL", "ROLLING", "FLOOR",
        "SLIGHTLY", "BEAMING", "GLEE",
    },
    "sadness_concern": {
        "CRY", "CRYING", "SAD", "FROWNING", "PENSIVE", "DISAPPOINTED",
        "WORRIED", "WEARY", "TIRED", "SOB", "BROKEN", "PLEADING", "ANGUISHED",
        "DOWNCAST", "PERSEVERING", "CONFOUNDED",
    },
    "anger_frustration": {
        "ANGRY", "POUTING", "RAGE", "STEAM", "UNAMUSED", "SYMBOLS", "SWEARING",
        "EXPRESSIONLESS",
    },
    "curiosity_thinking": {
        "THINKING", "MONOCLE", "QUESTION", "CONFUSED", "RAISED", "EYEBROW",
        "MAGNIFYING", "SEARCH", "INSPECT",
    },
    "celebration_excitement": {
        "PARTY", "POPPER", "CONFETTI", "SPARKLES", "STAR", "FIRE", "CLAPPING",
        "TROPHY", "MEDAL", "FIREWORKS", "BALLOON", "CHEERS", "ROCKET",
    },
    "affection_support": {
        "HEART", "LOVE", "HUGGING", "KISS", "THUMBS", "CLAP", "FOLDED",
        "HANDS", "HUG", "SUPPORT", "WARM", "STAR-STRUCK",
    },
    "surprise_shock": {
        "EXPLODING", "ASTONISHED", "FLUSHED", "FEARFUL", "SCREAMING", "OPEN",
        "EXCLAMATION", "HUSHED", "DIZZY", "GASP",
    },
}

_THAI_INTERROGATIVE_CUES = (
    "คืออะไร", "ทำงานอย่างไร", "เกิดขึ้นได้อย่างไร", "ได้อย่างไร",
    "คือ", "อะไร", "อย่างไร", "ยังไง", "ทำไม", "ที่ไหน", "เมื่อไร",
    "เมื่อไหร่", "ใคร", "เท่าไร", "เท่าไหร่", "กี่", "หรือไม่", "หรือเปล่า",
    "หมายถึง", "อธิบาย", "ช่วยอธิบาย", "เล่าเรื่อง", "บอกเกี่ยวกับ", "ต่างกัน",
)

_EN_INTERROGATIVE_CUES = (
    "what", "why", "how", "who", "whom", "where", "when", "which",
    "explain", "describe", "define", "tell me about", "compare",
)

_AMBIGUOUS_INTERJECTIONS = {
    "อืม", "อือ", "เอ่อ", "hmm", "hm", "uh", "um",
    "งง", "งงเลย", "จริงหรอ", "จริงเหรอ", "ว่าไง",
}

_FOLLOWUP_CUES_TH = (
    "มัน", "อันนั้น", "อันนี้", "สิ่งนั้น", "สิ่งนี้", "เรื่องนี้", "เรื่องนั้น",
    "แบบนั้น", "แบบนี้", "แล้วไงต่อ", "ยังไงต่อ", "ต่อเลย", "อธิบายเพิ่ม",
    "ขยายความ", "ดียังไง", "ข้อดี", "ข้อเสีย", "ทำไมล่ะ", "ทำไมถึง",
    "หมายความว่าไง", "แล้วยังไง",
)

_FOLLOWUP_CUES_EN = (
    "it", "that", "this", "they", "them", "those", "these",
    "why", "how so", "tell me more", "elaborate", "continue", "more details",
)

_THAI_POLITE_PARTICLES = (
    "นะครับ", "นะคะ", "นะฮะ", "จ้า", "จ๊ะ", "ครับผม", "ครับ", "ค่ะ", "คะ",
    "ฮะ", "นะ", "เลย", "ด้วย", "สิ", "ซิ",
)

_THAI_GREETING_STEMS = (
    "สวัสดีตอนเช้า", "สวัสดีตอนสาย", "สวัสดีตอนเที่ยง", "สวัสดีตอนบ่าย",
    "สวัสดีตอนเย็น", "สวัสดีตอนค่ำ", "อรุณสวัสดิ์", "สายัณห์สวัสดิ์",
    "สวัสดี", "หวัดดี", "ทักทาย", "ดีจ้า", "ดีครับ", "ดีค่ะ",
)

_EN_GREETING_STEMS = (
    "good morning", "good afternoon", "good evening",
    "nice to meet you", "pleased to meet you",
    "greetings", "hello", "howdy", "hey", "hi", "yo",
)

_THAI_WELLBEING_FILLERS = (
    "สบายดีไหม", "สบายดีมั้ย", "เป็นไงบ้าง", "เป็นยังไงบ้าง",
    "มีใครอยู่ไหม", "อยู่ไหม", "พร้อมไหม", "ยินดีที่ได้รู้จัก",
)

_EN_WELLBEING_FILLERS = (
    "there", "how are you", "how's it going", "how are things",
    "are you there", "nice to meet you",
)

_THANKS_CUES_TH = ("ขอบคุณมาก", "ขอบคุณ", "ขอบใจ")
_THANKS_CUES_EN = ("thank you", "thanks", "thx", "appreciate it")

_FAREWELL_CUES_TH = ("ราตรีสวัสดิ์", "ฝันดี", "ลาก่อน", "บ๊ายบาย", "เจอกันใหม่", "ไปก่อน")
_FAREWELL_CUES_EN = ("good night", "goodnight", "goodbye", "bye", "see you", "farewell")

_ACK_CUES_TH = ("โอเค", "รับทราบ", "เข้าใจแล้ว", "ตกลง", "เยี่ยมเลย", "ยอดเยี่ยม", "ดีเลย")
_ACK_CUES_EN = ("ok", "okay", "got it", "understood", "alright", "sounds good", "great", "cool")

_OPEN_HELP_CUES_TH = ("ช่วยหน่อย", "ช่วยด้วย", "ขอความช่วยเหลือ", "แนะนำหน่อย", "เริ่มต้นยังไง")
_OPEN_HELP_CUES_EN = ("help", "help me", "assist me", "can you help")

_CAPABILITY_CUES_TH = (
    "ทำอะไรได้บ้าง", "ช่วยอะไรได้บ้าง", "ความสามารถอะไรบ้าง",
    "คุณคือใคร", "เธอคือใคร", "zyrquen คืออะไร", "แนะนำตัวหน่อย",
)
_CAPABILITY_CUES_EN = (
    "what can you do", "what are your capabilities", "how can you help",
    "who are you", "introduce yourself",
)

_EXPLICIT_CMD_RE = re.compile(
    r"^(?:ภารกิจ|ปฏิบัติการ(?:อัตโนมัติ)?|mission|autonomous|วางแผน|แผนงาน|plan|"
    r"สอน|จำว่า|จำ|เรียนรู้|teach|learn|remember|เชื่อมโยง|หาเส้นทาง|เส้นทาง|path|connect|trace|"
    r"แก้สมการ|สมการ|คำนวณ|หาค่า|คิดเลข|สถิติ|วิเคราะห์ตัวเลข|ค่าเฉลี่ย|มัธยฐาน|"
    r"solve|equation|calculate|compute|eval|evaluate|stats|statistics|ค้นคว้า|ค้นหาเว็บ|web_search|doc_fetch)\b",
    re.IGNORECASE,
)

# Compositional semantic primitives (pure domain/structural concept stems, not full responses)
_SEMANTIC_PRIMITIVES: dict[str, dict[str, Any]] = {
    "verification_evidence": {
        "cues": (
            "ตรวจสอบ", "ยืนยัน", "หลักฐาน", "พิสูจน์", "ประเมิน", "ความถูกต้อง",
            "verify", "verification", "evidence", "validate", "validation", "audit", "evaluate",
        ),
        "label_th": "การตรวจสอบและอ้างอิงหลักฐาน",
        "label_en": "evidence-based verification",
        "role": "epistemic_guard",
    },
    "training_data": {
        "cues": (
            "ข้อมูลฝึก", "ชุดข้อมูล", "ชุดทดสอบ", "ข้อมูลซ้ำ", "รั่วไหล", "leakage",
            "ความจำ", "การเรียนรู้", "การฝึก", "training", "dataset", "test split",
            "memorization", "memorize", "duplicate", "memory", "data",
        ),
        "label_th": "ข้อมูลและการเรียนรู้จากตัวอย่าง",
        "label_en": "training data & generalization hygiene",
        "role": "knowledge_substrate",
    },
    "reasoning_inference": {
        "cues": (
            "อนุมาน", "ตรรกะ", "เหตุผล", "วิเคราะห์", "เหตุและผล", "สรุปผล",
            "reasoning", "logic", "inference", "deduction", "generalization", "infer",
        ),
        "label_th": "การอนุมานและให้เหตุผลเชิงโครงสร้าง",
        "label_en": "structured logical inference",
        "role": "reasoning_engine",
    },
    "planning_execution": {
        "cues": (
            "วางแผน", "ขั้นตอน", "ลำดับ", "พึ่งพา", "ล้มเหลว", "ดำเนินการ", "เวิร์กโฟลว์",
            "plan", "planning", "step", "dependency", "failure", "execution", "workflow",
        ),
        "label_th": "การวางแผนลำดับขั้นและการจัดการความเสี่ยง",
        "label_en": "dependency-aware planning & execution",
        "role": "orchestration",
    },
    "security_governance": {
        "cues": (
            "ความปลอดภัย", "สิทธิ์", "อนุมัติ", "ขอบเขต", "ควบคุม", "ความเสี่ยง",
            "security", "permission", "approval", "governance", "safety", "boundary", "gate",
        ),
        "label_th": "การควบคุมสิทธิ์และขอบเขตความปลอดภัย",
        "label_en": "governance & safety boundaries",
        "role": "safety_control",
    },
    "system_architecture": {
        "cues": (
            "ระบบ", "โครงสร้าง", "สถาปัตยกรรม", "กลไก", "ความน่าเชื่อถือ", "เสถียรภาพ",
            "system", "architecture", "structure", "reliability", "mechanism", "trust",
        ),
        "label_th": "โครงสร้างและความน่าเชื่อถือของระบบ",
        "label_en": "system structure & reliability",
        "role": "system_property",
    },
    "hypothesis_guessing": {
        "cues": (
            "คาดเดา", "เดา", "สมมติ", "แต่งคำตอบ", "จำคำตอบ",
            "guess", "guessing", "fabricate", "hallucination", "assumption",
        ),
        "label_th": "การคาดเดาโดยไม่มีหลักฐานรองรับ",
        "label_en": "ungrounded guessing",
        "role": "anti_pattern",
    },
}

_KNOWN_STRUCTURAL_LEXICON = frozenset({
    "ถ้า", "หาก", "เมื่อ", "ไม่มี", "มี", "ซ้ำ", "กับ", "และ", "หรือ", "ระหว่าง", "ต่างกัน",
    "เปรียบเทียบ", "เทียบกับ", "ส่งผล", "ทำให้", "กระทบ", "ต่อ", "อย่างไร", "ยังไง", "อะไร",
    "ควร", "หยุด", "ทำงาน", "ความ", "การ", "ใน", "ของ", "ที่", "ได้", "เป็น", "จะ", "เกิดผล",
    "เกิด", "ผล", "อย่าง", "เพียง", "เดียว", "ก่อน", "หลัง", "มาก", "น้อย", "ไม่", "ใช่",
    "if", "when", "without", "with", "and", "or", "between", "compare", "comparison",
    "difference", "different", "vs", "versus", "affect", "effect", "impact", "cause",
    "lead", "leads", "to", "how", "why", "what", "should", "stop", "continue", "missing",
    "absent", "only", "alone", "before", "after", "reliable", "accuracy", "quality",
    "ในระบบ", "ของระบบ", "ความสามารถ", "ผลลัพธ์",
})

_VOWELS = set("aeiouy")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _analyze_unicode_semantics(text: str) -> dict[str, Any]:
    """
    Analyze arbitrary Unicode symbols/characters via stdlib unicodedata decomposition.
    Zero per-emoji canned response lookup: composes affective axes directly from
    official Unicode character categories and name descriptors.
    """
    axis_scores: dict[str, int] = collections.Counter()
    symbol_descriptors: list[str] = []
    symbol_count = 0
    thai_chars = 0
    latin_chars = 0
    digit_chars = 0
    punct_chars = 0
    other_letters = 0

    for ch in text:
        if ch.isspace():
            continue
        cat = unicodedata.category(ch)
        code = ord(ch)

        if 0x0E00 <= code <= 0x0E7F:
            thai_chars += 1
            continue
        if ("a" <= ch <= "z") or ("A" <= ch <= "Z"):
            latin_chars += 1
            continue
        if cat.startswith("N"):
            digit_chars += 1
            continue
        if cat in ("Cf", "Mn", "Sk"):
            continue

        uname = unicodedata.name(ch, "")
        is_expressive_symbol = (
            cat in ("So", "Sm")
            or 0x1F000 <= code <= 0x1FAFF
            or 0x2600 <= code <= 0x27BF
            or ("QUESTION" in uname and cat == "Po" and code > 0x00FF)
            or ("EXCLAMATION" in uname and cat == "Po" and code > 0x00FF)
        )
        if is_expressive_symbol:
            symbol_count += 1
            if uname:
                symbol_descriptors.append(uname)
                name_tokens = {tok for tok in re.split(r"[\s\-]+", uname.upper()) if tok}
                for axis, keywords in _AFFECT_AXIS_KEYWORDS.items():
                    hits = len(name_tokens & keywords)
                    if hits:
                        axis_scores[axis] += hits
            continue

        if cat.startswith("P"):
            punct_chars += 1
        elif cat.startswith("L"):
            other_letters += 1

    total_alpha = thai_chars + latin_chars + other_letters
    dominant_axis = None
    if axis_scores:
        dominant_axis = max(axis_scores.items(), key=lambda kv: kv[1])[0]

    if axis_scores.get("joy_amusement", 0) > 0 and axis_scores.get("sadness_concern", 0) > 0:
        if any("JOY" in d or "LAUGH" in d or "ROFL" in d for d in symbol_descriptors):
            dominant_axis = "joy_amusement"

    return {
        "symbol_count": symbol_count,
        "symbol_descriptors": symbol_descriptors[:8],
        "axis_scores": dict(axis_scores),
        "dominant_axis": dominant_axis,
        "has_facial_cue": any("FACE" in d or "HEAD" in d or "EYES" in d for d in symbol_descriptors),
        "thai_chars": thai_chars,
        "latin_chars": latin_chars,
        "digit_chars": digit_chars,
        "punct_chars": punct_chars,
        "other_letters": other_letters,
        "total_alpha": total_alpha,
    }


def _is_plausible_latin_word(word: str) -> bool:
    w = word.lower()
    if len(w) <= 1:
        return True
    if len(w) <= 4:
        return not bool(re.search(r"(.)\1{3,}", w))
    if re.search(r"(.)\1{3,}", w):
        return False
    if re.search(r"[^aeiouy]{5,}", w):
        return False
    vowel_count = sum(1 for c in w if c in _VOWELS)
    if vowel_count == 0:
        return False
    vowel_ratio = vowel_count / len(w)
    if len(w) >= 8 and vowel_ratio < 0.16:
        return False
    return True


def _is_plausible_thai_span(span: str) -> bool:
    if len(span) < 2:
        return False
    if re.search(r"(.)\1{3,}", span):
        return False
    has_consonant = any(0x0E01 <= ord(c) <= 0x0E2E for c in span)
    if not has_consonant:
        return False
    consonants = sum(1 for c in span if 0x0E01 <= ord(c) <= 0x0E2E)
    if len(span) >= 6 and consonants < len(span) * 0.3:
        return False
    return True


def _detect_opaque_noise(
    text: str,
    unicode_sem: dict[str, Any],
    *,
    kg_matched_any: bool = False,
) -> tuple[bool, str | None]:
    stripped = text.strip()
    if not stripped:
        return True, "empty_input"

    if unicode_sem["symbol_count"] > 0:
        return False, None

    if unicode_sem["total_alpha"] == 0 and unicode_sem["digit_chars"] == 0:
        return True, "punctuation_or_symbol_noise"

    if kg_matched_any:
        return False, None

    latin_words = re.findall(r"[A-Za-z]+", stripped)
    thai_spans = re.findall(r"[\u0E00-\u0E7F]+", stripped)

    if thai_spans:
        if not any(_is_plausible_thai_span(sp) for sp in thai_spans) and not latin_words:
            return True, "implausible_thai_noise"

    if latin_words and not thai_spans:
        plausible_count = sum(1 for w in latin_words if _is_plausible_latin_word(w))
        if plausible_count == 0:
            return True, "implausible_latin_noise"
        if len(latin_words) >= 2 and plausible_count / len(latin_words) < 0.4:
            return True, "mostly_implausible_tokens"

    if (
        unicode_sem["thai_chars"] == 0
        and unicode_sem["latin_chars"] == 0
        and unicode_sem["other_letters"] == 0
        and unicode_sem["digit_chars"] > 0
        and unicode_sem["punct_chars"] > 0
    ):
        if not re.search(r"[+\-*/^=]", stripped):
            return True, "unstructured_digits_and_punctuation"

    return False, None


def _strip_polite_particles_th(text: str) -> tuple[str, str]:
    """Strip Thai trailing polite particles and detect politeness register."""
    cur = text.strip()
    register = "polite"
    changed = True
    while changed and cur:
        changed = False
        for p in _THAI_POLITE_PARTICLES:
            if cur.endswith(p):
                if p in ("จ้า", "จ๊ะ"):
                    register = "casual"
                cur = cur[: -len(p)].strip(" ,.!?\t")
                changed = True
                break
    return cur, register


def _decompose_utterance(prompt: str) -> dict[str, Any]:
    """
    Decompose greetings, time-of-day modifiers, polite particles, vocatives,
    and courtesy/help phrases without a static phrase-to-reply lookup table.
    """
    raw = unicodedata.normalize("NFC", prompt).strip()
    stripped_punct = raw.strip(" \t\r\n!?.~…")
    low = stripped_punct.lower()

    time_of_day: str | None = None
    if any(t in low for t in ("ตอนเช้า", "อรุณสวัสดิ์", "good morning", "morning")):
        time_of_day = "morning"
    elif any(t in low for t in ("ตอนบ่าย", "ตอนสาย", "ตอนเที่ยง", "good afternoon", "afternoon")):
        time_of_day = "afternoon"
    elif any(t in low for t in ("ตอนเย็น", "ตอนค่ำ", "สายัณห์สวัสดิ์", "good evening", "evening")):
        time_of_day = "evening"
    elif any(t in low for t in ("ราตรีสวัสดิ์", "ฝันดี", "good night", "goodnight")):
        time_of_day = "night"

    addressed_by_name = bool(re.search(r"(?:zyrquen|เซอร์เควน)", low))

    leading_salutation: str | None = None
    register = "polite"
    remainder = stripped_punct

    # 1. Check Thai greeting stems at start of utterance
    for stem in sorted(_THAI_GREETING_STEMS, key=len, reverse=True):
        if low.startswith(stem):
            after = stripped_punct[len(stem):].strip(" ,.!?:-\t")
            after_clean, reg = _strip_polite_particles_th(after)
            # Strip optional time-of-day modifier right after "สวัสดี"
            for tod in ("ตอนเช้า", "ตอนสาย", "ตอนเที่ยง", "ตอนบ่าย", "ตอนเย็น", "ตอนค่ำ"):
                if after_clean.startswith(tod):
                    after_clean = after_clean[len(tod):].strip(" ,.!?\t")
                    after_clean, reg = _strip_polite_particles_th(after_clean)
            leading_salutation = stem
            register = "casual" if stem in ("หวัดดี", "ดีจ้า") else reg
            remainder = after_clean
            break

    # 2. Check English greeting stems at start of utterance
    if leading_salutation is None:
        for stem in sorted(_EN_GREETING_STEMS, key=len, reverse=True):
            m = re.match(rf"^{re.escape(stem)}(?:\b|$)[\s,!?:.-]*(.*)$", stripped_punct, re.IGNORECASE)
            if m:
                leading_salutation = stem
                register = "casual" if stem in ("hey", "hi", "yo") else "polite"
                remainder = m.group(1).strip(" ,.!?\t")
                if remainder.lower().startswith("there"):
                    after_there = remainder[5:].strip(" ,.!?\t")
                    remainder = after_there
                break

    # 3. Check if remainder after salutation is ONLY a vocative ("ZYRQUEN") or wellbeing filler
    asks_wellbeing = False
    pure_greeting = False
    effective_prompt = raw

    if leading_salutation is not None:
        rem_no_name = re.sub(r"\b(?:zyrquen|เซอร์เควน)\b", "", remainder, flags=re.IGNORECASE).strip(" ,.!?\t")
        rem_no_name, _ = _strip_polite_particles_th(rem_no_name)
        rem_l = rem_no_name.lower()

        if not rem_l:
            pure_greeting = True
            effective_prompt = ""
        else:
            for wf in _THAI_WELLBEING_FILLERS + _EN_WELLBEING_FILLERS:
                if rem_l == wf or rem_l.startswith(wf + " "):
                    leftover = rem_l[len(wf):].strip(" ,.!?\t")
                    leftover, _ = _strip_polite_particles_th(leftover)
                    if not leftover:
                        asks_wellbeing = True
                        pure_greeting = True
                        effective_prompt = ""
                        break
            if not pure_greeting:
                # Substantive follow-on task after greeting (e.g. "สวัสดีครับ คำนวณ 2+2" or "สวัสดี ZYRQUEN ใช้งานอะไร")
                # Keep ZYRQUEN in remainder if remainder contains an entity/predicate query!
                effective_prompt = remainder if remainder else raw

    return {
        "normalized": raw,
        "leading_salutation": leading_salutation,
        "pure_greeting": pure_greeting,
        "asks_wellbeing": asks_wellbeing,
        "time_of_day": time_of_day,
        "register": register,
        "addressed_by_name": addressed_by_name,
        "remainder": remainder,
        "effective_prompt": effective_prompt,
    }


def _extract_topic_focus(prompt: str, query_terms: list[str]) -> str:
    cleaned = prompt.strip()
    for pat in (
        r"^(?:explain|describe|define|tell me about|what is|who is|how does|where is|analyze|analyse)\s+",
        r"^(?:ช่วยอธิบาย|อธิบาย|ช่วยวิเคราะห์|วิเคราะห์|เล่าเรื่อง|บอกเกี่ยวกับ)\s*",
    ):
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE).strip()
    for suf in (
        "คืออะไร", "ทำงานอย่างไร", "เกิดขึ้นได้อย่างไร", "ได้อย่างไร",
        "หมายถึงอะไร", "อยู่ที่ไหน", "อย่างไร", "ยังไง", "ให้หน่อย", "?", "ครับ", "ค่ะ",
    ):
        if cleaned.endswith(suf) and len(cleaned) > len(suf) + 1:
            cleaned = cleaned[: -len(suf)].strip()
    if 2 <= len(cleaned) <= 72:
        return cleaned
    if query_terms:
        return ", ".join(query_terms[:3])
    return prompt.strip()[:60]


def _extract_conversation_context(conn: sqlite3.Connection, conversation_id: str | None) -> dict[str, Any]:
    recent_turns: list[dict[str, str]] = []
    if not conversation_id:
        return {
            "recent_turns": [],
            "last_user_prompt": "",
            "last_assistant_reply": "",
            "last_assistant_status": "",
            "active_topic": "",
            "last_substantive_user": "",
        }
    try:
        rows = conn.execute(
            """
            SELECT role, content, status
            FROM messages
            WHERE conversation_id=?
            ORDER BY created_at DESC, rowid DESC
            LIMIT 8
            """,
            (str(conversation_id),),
        ).fetchall()
        recent_turns = [
            {
                "role": str(r["role"]),
                "content": str(r["content"])[:220],
                "status": str(r["status"]),
            }
            for r in reversed(rows)
        ]
    except sqlite3.Error:
        recent_turns = []

    last_user_prompt = ""
    last_substantive_user = ""
    last_assistant_reply = ""
    last_assistant_status = ""
    active_topic = ""

    for t in reversed(recent_turns):
        if t["role"] == "assistant" and not last_assistant_reply:
            last_assistant_reply = t["content"]
            last_assistant_status = t["status"]
        elif t["role"] == "user":
            if not last_user_prompt:
                last_user_prompt = t["content"]
            dec = _decompose_utterance(t["content"])
            low_t = t["content"].strip().lower()
            is_followup_only = any(cue in low_t for cue in _FOLLOWUP_CUES_TH) and len(t["content"]) <= 36
            if not dec["pure_greeting"] and not is_followup_only and not last_substantive_user:
                last_substantive_user = t["content"]

    if last_substantive_user:
        # Clean command prefixes like "สอน:" or "คำนวณ" lightly for readable referent
        cleaned_topic = re.sub(
            r"^(?:สอน|จำว่า|วางแผน|คำนวณ|อธิบาย|ช่วยอธิบาย|ช่วยวิเคราะห์)\s*:?\s*",
            "",
            last_substantive_user.strip(),
            flags=re.IGNORECASE,
        ).strip()
        active_topic = cleaned_topic[:80] if cleaned_topic else last_substantive_user[:80]

    return {
        "recent_turns": recent_turns,
        "last_user_prompt": last_user_prompt,
        "last_substantive_user": last_substantive_user,
        "last_assistant_reply": last_assistant_reply,
        "last_assistant_status": last_assistant_status,
        "active_topic": active_topic,
    }


def _extract_semantic_primitives(prompt: str, query_terms: list[str]) -> dict[str, Any]:
    low = prompt.lower()
    matched_primitives: list[dict[str, str]] = []
    matched_cues_flat: set[str] = set()

    for pid, spec in _SEMANTIC_PRIMITIVES.items():
        hits = []
        for cue in spec["cues"]:
            if cue.isascii():
                if re.search(rf"\b{re.escape(cue)}\b", low):
                    hits.append(cue)
            elif cue in low:
                hits.append(cue)
        if hits:
            matched_primitives.append(
                {
                    "id": pid,
                    "label_th": spec["label_th"],
                    "label_en": spec["label_en"],
                    "role": spec["role"],
                    "matched_cue": hits[0],
                }
            )
            matched_cues_flat.update(hits)

    operators: list[str] = []
    if any(c in low for c in ("ต่างกัน", "เปรียบเทียบ", "เทียบกับ")) or re.search(
        r"\b(?:compare|comparison|difference|different|vs|versus)\b", low
    ):
        operators.append("comparison")
    if any(c in low for c in ("ถ้า", "หาก", "ส่งผล", "ทำให้เกิด", "กระทบ", "โดยไม่")) or re.search(
        r"\b(?:if|when|without|affect|effect|impact|lead to)\b", low
    ):
        operators.append("conditional_consequence")
    if any(c in low for c in ("ควร", "ดีกว่า")) or re.search(r"\b(?:should|better)\b", low):
        operators.append("tradeoff")

    # Detect unfamiliar / novel technical tokens not covered by primitives or common lexicon
    unfamiliar_terms: list[str] = []
    for tok in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}", prompt):
        tl = tok.lower()
        if tl in _KNOWN_STRUCTURAL_LEXICON or tl in matched_cues_flat or tl == "zyrquen":
            continue
        if any(tl in spec["cues"] for spec in _SEMANTIC_PRIMITIVES.values()):
            continue
        # Mixed case, digits/hyphens (e.g. XenoFlux-9), or domain-specific English term
        if (
            "-" in tok
            or "_" in tok
            or any(c.isdigit() for c in tok)
            or any(c.isupper() for c in tok[1:])
            or len(tok) >= 5
        ):
            unfamiliar_terms.append(tok)

    # Check if Thai spans contain unknown domain nouns outside structural lexicon & primitives
    thai_unfamiliar = False
    for span in re.findall(r"[\u0E00-\u0E7F]+", low):
        rem = span
        for cue in sorted(list(matched_cues_flat) + list(_KNOWN_STRUCTURAL_LEXICON) + list(_THAI_INTERROGATIVE_CUES), key=len, reverse=True):
            if not cue.isascii():
                rem = rem.replace(cue, " ")
        leftover_th = [s for s in rem.split() if len(s) >= 4]
        if leftover_th:
            thai_unfamiliar = True
            break

    return {
        "primitives": matched_primitives,
        "primitive_ids": [p["id"] for p in matched_primitives],
        "operators": operators,
        "unfamiliar_terms": list(dict.fromkeys(unfamiliar_terms))[:5],
        "has_ungrounded_domain_terms": bool(unfamiliar_terms) or thai_unfamiliar,
    }


def _detect_courtesy_or_help(prompt: str, decomposition: dict[str, Any]) -> tuple[str | None, str | None]:
    """Detect thank-yous, farewells, acknowledgements, capability inquiries, or help requests."""
    cleaned_th, _ = _strip_polite_particles_th(decomposition["normalized"])
    cleaned_th = re.sub(r"\b(?:zyrquen|เซอร์เควน)\b", "", cleaned_th, flags=re.IGNORECASE).strip(" ,.!?\t")
    cleaned_th, _ = _strip_polite_particles_th(cleaned_th)
    low = cleaned_th.lower()
    raw_low = decomposition["normalized"].lower().strip(" ,.!?\t")

    if any(low == c or low.startswith(c + " ") or raw_low.startswith(c) for c in _CAPABILITY_CUES_TH) or any(
        re.search(rf"\b{re.escape(c)}\b", raw_low) for c in _CAPABILITY_CUES_EN
    ):
        return "capability_or_help_request", "capability_inquiry"

    if any(low == c or low.startswith(c + " ") for c in _OPEN_HELP_CUES_TH) or any(
        raw_low == c or re.match(rf"^{re.escape(c)}[\s!?.]*$", raw_low) for c in _OPEN_HELP_CUES_EN
    ):
        return "capability_or_help_request", "open_help"

    if any(low == c or low.startswith(c) for c in _THANKS_CUES_TH) and len(low) <= 40:
        return "acknowledgement_or_courtesy", "thanks"
    if any(re.match(rf"^{re.escape(c)}(?:\s+(?:very\s+much|so\s+much|a\s+lot|zyrquen))?[!.\s]*$", raw_low) for c in _THANKS_CUES_EN):
        return "acknowledgement_or_courtesy", "thanks"

    if any(low == c or low.startswith(c + " ") for c in _FAREWELL_CUES_TH) and len(low) <= 40:
        return "acknowledgement_or_courtesy", "farewell"
    if any(re.match(rf"^{re.escape(c)}(?:\s+zyrquen)?[!.\s]*$", raw_low) for c in _FAREWELL_CUES_EN):
        return "acknowledgement_or_courtesy", "farewell"

    if low in _ACK_CUES_TH or raw_low in _ACK_CUES_EN:
        return "acknowledgement_or_courtesy", "ack"

    return None, None


def _detect_followup_reference(prompt: str, query_terms: list[str], ctx: dict[str, Any]) -> bool:
    low = prompt.strip().lower()
    if len(low) > 72:
        return False
    has_th_anaphora = any(cue in low for cue in _FOLLOWUP_CUES_TH)
    has_en_anaphora = any(re.search(rf"\b{re.escape(cue)}\b", low) for cue in _FOLLOWUP_CUES_EN)
    if not (has_th_anaphora or has_en_anaphora):
        return False
    # Exclude explicit math/logic/teaching/planning commands
    if _EXPLICIT_CMD_RE.match(prompt.strip()):
        return False
    # If the prompt is short/dependent and refers anaphorically, treat as contextual followup.
    # Thai syllable segmentation can expand one short phrase into >5 syllable tokens, so bound by surface words/length.
    ascii_words = re.findall(r"[a-z0-9_]+", low)
    if ascii_words:
        return len(ascii_words) <= 6 and len(low) <= 48
    return len(low) <= 48 and len(prompt.split()) <= 5


def understand_input(
    conn: sqlite3.Connection,
    prompt: str,
    *,
    attachment: str = "",
    mode: str = "auto",
    conversation_id: str | None = None,
    tokenize_fn=None,
    extract_terms_fn=None,
    query_kg_fn=None,
) -> dict[str, Any]:
    """
    Stage 1 (Understand): Parse linguistic cues, salutations, Unicode semantics,
    semantic primitives, conversational context, episodic memory, and KG neighborhood clues.
    """
    norm_prompt = unicodedata.normalize("NFC", prompt).strip()
    unicode_sem = _analyze_unicode_semantics(norm_prompt)
    decomposition = _decompose_utterance(norm_prompt)
    effective_prompt = decomposition["effective_prompt"] or norm_prompt

    tokens = tokenize_fn(effective_prompt) if tokenize_fn else re.findall(r"\w+", effective_prompt.lower())
    query_terms = extract_terms_fn(effective_prompt) if extract_terms_fn else list(dict.fromkeys(tokens))

    conv_ctx = _extract_conversation_context(conn, conversation_id)
    recent_turns = conv_ctx["recent_turns"]
    semantics = _extract_semantic_primitives(effective_prompt, query_terms)

    # Episodic experience lookup
    episodic_hits: list[dict[str, Any]] = []
    if query_terms and not decomposition["pure_greeting"]:
        try:
            ep_rows = conn.execute(
                """
                SELECT id, goal, outcome_status, gap_type, hypothesis_json, created_at
                FROM episodic_experiences
                ORDER BY created_at DESC
                LIMIT 40
                """
            ).fetchall()
            q_set = {t.lower() for t in query_terms}
            for er in ep_rows:
                g_l = str(er["goal"] or "").lower()
                overlap = [t for t in q_set if len(t) >= 2 and t in g_l]
                if overlap:
                    episodic_hits.append(
                        {
                            "id": er["id"],
                            "goal": str(er["goal"])[:100],
                            "outcome_status": er["outcome_status"],
                            "gap_type": er["gap_type"],
                            "overlap_terms": overlap[:4],
                        }
                    )
                if len(episodic_hits) >= 3:
                    break
        except sqlite3.Error:
            episodic_hits = []

    # Analogical KG neighborhood probe
    kg_related: list[dict[str, str]] = []
    probe_terms = list(query_terms)
    if conv_ctx["active_topic"] and _detect_followup_reference(norm_prompt, query_terms, conv_ctx):
        topic_terms = extract_terms_fn(conv_ctx["active_topic"]) if extract_terms_fn else re.findall(r"\w+", conv_ctx["active_topic"].lower())
        for tt in topic_terms:
            if tt not in probe_terms:
                probe_terms.append(tt)

    if probe_terms and not decomposition["pure_greeting"]:
        try:
            all_triples = conn.execute(
                "SELECT subject, relation, object, source FROM knowledge_triples LIMIT 250"
            ).fetchall()
            for tr in all_triples:
                subj_l = str(tr["subject"]).lower()
                obj_l = str(tr["object"]).lower()
                for qt in probe_terms:
                    if len(qt) >= 3 and (qt in subj_l or qt in obj_l or subj_l in qt):
                        kg_related.append(
                            {
                                "subject": str(tr["subject"]),
                                "relation": str(tr["relation"]),
                                "object": str(tr["object"]),
                                "matched_term": qt,
                            }
                        )
                        break
                if len(kg_related) >= 3:
                    break
        except sqlite3.Error:
            kg_related = []

    is_opaque, opaque_reason = _detect_opaque_noise(
        norm_prompt,
        unicode_sem,
        kg_matched_any=bool(kg_related),
    )

    topic_focus = _extract_topic_focus(effective_prompt, query_terms)
    language = (
        "symbolic"
        if unicode_sem["symbol_count"] > 0 and unicode_sem["total_alpha"] == 0
        else (
            "thai"
            if unicode_sem["thai_chars"] >= unicode_sem["latin_chars"] and unicode_sem["thai_chars"] > 0
            else ("english" if unicode_sem["latin_chars"] > 0 else "unknown")
        )
    )

    understanding: dict[str, Any] = {
        "prompt": norm_prompt,
        "effective_prompt": effective_prompt,
        "mode": mode,
        "language": language,
        "topic_focus": topic_focus,
        "tokens": tokens[:24],
        "query_terms": query_terms[:12],
        "unicode_semantics": unicode_sem,
        "decomposition": decomposition,
        "semantics": semantics,
        "is_opaque": is_opaque,
        "opaque_reason": opaque_reason,
        "conversation_context": conv_ctx,
        "recent_turns": recent_turns,
        "episodic_hits": episodic_hits,
        "kg_related": kg_related,
        "has_attachment": bool(attachment),
    }
    interpretation = interpret_intent(understanding)
    understanding["speech_act"] = interpretation["speech_act"]
    understanding["interpretation"] = interpretation
    return understanding


def interpret_intent(understanding: dict[str, Any]) -> dict[str, Any]:
    """
    Stage 2 (Interpret): Classify communicative intent and routing policy cleanly
    before retrieval or generative checkpoints can hijack social/pragmatic turns.
    """
    norm_prompt = understanding["prompt"]
    effective_prompt = understanding["effective_prompt"]
    mode = understanding["mode"]
    unicode_sem = understanding["unicode_semantics"]
    decomposition = understanding["decomposition"]
    semantics = understanding["semantics"]
    conv_ctx = understanding["conversation_context"]
    has_attachment = understanding["has_attachment"]

    lower_eff = effective_prompt.lower()
    lower_p = norm_prompt.lower()

    has_thai_q = any(cue in lower_eff for cue in _THAI_INTERROGATIVE_CUES)
    has_en_q = any(re.search(rf"\b{re.escape(cue)}\b", lower_eff) for cue in _EN_INTERROGATIVE_CUES)
    has_q_mark = "?" in norm_prompt
    is_conditional = bool(re.search(r"(?:^|\s)(?:ถ้า|หาก|ทุก|ไม่มี|if\b|all\b)", lower_eff))
    is_explicit_cmd = bool(_EXPLICIT_CMD_RE.match(effective_prompt.strip()))

    courtesy_act, courtesy_subtype = _detect_courtesy_or_help(norm_prompt, decomposition)
    is_followup = _detect_followup_reference(norm_prompt, understanding["query_terms"], conv_ctx)

    intent_subtype: str | None = None
    requires_retrieval = True
    early_communicative_route = False

    if understanding["is_opaque"]:
        speech_act = "opaque_noise"
        requires_retrieval = False
        early_communicative_route = mode == "auto" and not has_attachment
    elif unicode_sem["symbol_count"] > 0 and unicode_sem["total_alpha"] == 0 and unicode_sem["digit_chars"] == 0:
        speech_act = "affective_expression"
        requires_retrieval = False
        early_communicative_route = mode == "auto" and not has_attachment
    elif decomposition["pure_greeting"] and not is_explicit_cmd and not has_attachment:
        speech_act = "greeting"
        intent_subtype = decomposition["time_of_day"] or "general"
        requires_retrieval = False
        early_communicative_route = mode == "auto"
    elif courtesy_act is not None and not is_explicit_cmd and not has_attachment:
        speech_act = courtesy_act
        intent_subtype = courtesy_subtype
        requires_retrieval = False
        early_communicative_route = mode == "auto"
    elif is_explicit_cmd:
        speech_act = "explicit_task_or_command"
        requires_retrieval = True
    elif is_followup and not semantics["unfamiliar_terms"]:
        speech_act = "contextual_followup"
        intent_subtype = "anchored" if conv_ctx["active_topic"] else "unanchored"
        requires_retrieval = bool(conv_ctx["active_topic"])
    elif lower_p in _AMBIGUOUS_INTERJECTIONS or (
        unicode_sem["symbol_count"] > 0 and len(understanding["query_terms"]) <= 1 and not (has_thai_q or has_en_q)
    ):
        speech_act = "ambiguous_fragment"
        requires_retrieval = False
        early_communicative_route = mode == "auto" and not has_attachment
    elif is_conditional and (has_thai_q or has_q_mark or "แล้ว" in lower_eff or "ดังนั้น" in lower_eff) and not semantics["primitives"]:
        speech_act = "conditional_or_logic"
        requires_retrieval = True
    elif (
        len(semantics["primitive_ids"]) >= 2
        and bool(semantics["operators"])
        and not semantics["has_ungrounded_domain_terms"]
    ):
        speech_act = "compositional_reasoning_query"
        intent_subtype = semantics["operators"][0]
        requires_retrieval = True
    elif (
        semantics["unfamiliar_terms"]
        and not (
            re.match(r"^(?:explain|define|what is|describe)\b", lower_eff)
            and len(semantics["unfamiliar_terms"]) == 0
        )
        and any(c in lower_eff for c in ("ช่วยวิเคราะห์", "ควรเลือก", "ควรใช้", "เอาไง", "analyze", "choose", "which one"))
    ):
        speech_act = "unfamiliar_term_or_ambiguous"
        intent_subtype = "novel_term_clarification"
        requires_retrieval = True
    elif has_thai_q or has_en_q or has_q_mark:
        speech_act = "conceptual_question"
        requires_retrieval = True
    elif len(understanding["query_terms"]) <= 1 and len(norm_prompt) <= 10 and not has_attachment and unicode_sem["symbol_count"] > 0:
        speech_act = "ambiguous_fragment"
        requires_retrieval = False
    else:
        speech_act = "general_utterance"
        requires_retrieval = True

    return {
        "speech_act": speech_act,
        "intent_subtype": intent_subtype,
        "requires_retrieval": requires_retrieval,
        "early_communicative_route": early_communicative_route,
        "effective_prompt": effective_prompt,
        "is_explicit_command": is_explicit_cmd,
        "is_followup": is_followup,
        "resolved_referent": conv_ctx["active_topic"] if is_followup else "",
    }


def _describe_affective_state(unicode_sem: dict[str, Any], language: str) -> tuple[str, str]:
    axis = unicode_sem.get("dominant_axis")
    descriptors = unicode_sem.get("symbol_descriptors") or []
    is_en = language == "english"

    if axis == "joy_amusement":
        return (
            "อารมณ์ขัน ความสนุก หรือความรู้สึกดีใจ",
            "amusement, laughter, or a positive mood",
        ) if is_en else (
            "อารมณ์ขัน ความขบขัน หรือความรู้สึกยินดี",
            "amusement or positive joy",
        )
    if axis == "sadness_concern":
        return (
            "ความรู้สึกเศร้า กังวล หรือไม่สบายใจ",
            "sadness, concern, or distress",
        )
    if axis == "anger_frustration":
        return (
            "ความรู้สึกหงุดหงิด โกรธ หรือไม่พอใจ",
            "frustration or anger",
        )
    if axis == "curiosity_thinking":
        return (
            "ความสงสัย กำลังครุ่นคิด หรือมีคำถามในใจ",
            "thoughtfulness, curiosity, or a question",
        )
    if axis == "celebration_excitement":
        return (
            "ความตื่นเต้น การแสดงความยินดี หรือพลังงานเชิงบวก",
            "celebration or excitement",
        )
    if axis == "affection_support":
        return (
            "ความรู้สึกดี การสนับสนุน หรือความเห็นด้วย",
            "appreciation, warmth, or agreement",
        )
    if axis == "surprise_shock":
        return (
            "ความประหลาดใจ หรือตกใจกับบางเรื่อง",
            "surprise or astonishment",
        )
    if descriptors:
        cleaned_desc = descriptors[0].lower().replace("_", " ")
        return (
            f"สัญลักษณ์สื่อความหมายเชิงภาพ ({cleaned_desc})",
            f"a visual symbol ({cleaned_desc})",
        )
    return ("การแสดงออกเชิงสัญลักษณ์", "a symbolic expression")


def _synthesize_compositional_reasoning(
    understanding: dict[str, Any],
    language: str,
) -> dict[str, Any]:
    """
    Pure native symbolic/conceptual reasoning over unseen combinations of known
    semantic primitives, separating facts, structural inferences, and assumptions.
    """
    sem = understanding["semantics"]
    primitives = sem["primitives"]
    pids = set(sem["primitive_ids"])
    operators = sem["operators"]
    is_en = language == "english"

    facts = [
        (
            f"Identified concepts: {', '.join(p['label_en'] for p in primitives)}"
            if is_en
            else f"แนวคิดหลักที่ระบุในคำถาม: {', '.join(p['label_th'] for p in primitives)}"
        )
    ]
    inferences: list[str] = []
    assumptions: list[str] = []
    unknowns: list[str] = []

    if "training_data" in pids and "verification_evidence" in pids:
        if "conditional_consequence" in operators or "ซ้ำ" in understanding["prompt"].lower() or "duplicate" in understanding["prompt"].lower():
            inferences.append(
                "Overlap or unverified duplication between training and evaluation sets inflates apparent accuracy via memorization while failing true generalization on unseen inputs."
                if is_en
                else "หากชุดข้อมูลฝึกซ้ำซ้อนหรือไม่ผ่านการแยกตรวจสอบกับชุดทดสอบ ค่าความแม่นยำอาจสูงลวงจากการจำคำตอบ แต่ความสามารถในการอนุมานกับข้อมูลที่ไม่เคยพบจริงจะลดลง"
            )
        else:
            inferences.append(
                "Verification acts as an independent check on learned patterns so memorization is not mistaken for reliable capability."
                if is_en
                else "การตรวจสอบและหลักฐานช่วยคัดกรองว่าการเรียนรู้ใช้งานได้จริงกับข้อมูลใหม่ ไม่ใช่เพียงการจำรูปแบบเดิมซ้ำ"
            )

    if "verification_evidence" in pids and "hypothesis_guessing" in pids:
        inferences.append(
            "Verification grounds conclusions in checkable premises or records, whereas guessing bridges missing evidence with unverified claims that introduce false confidence."
            if is_en
            else "การอ้างอิงหลักฐานจำกัดข้อสรุปให้อยู่บนเงื่อนไขที่ตรวจสอบได้จริง ส่วนการคาดเดาเป็นการเติมช่องว่างโดยไม่มีหลักฐาน ทำให้เสี่ยงต่อการให้ข้อมูลผิดพลาดอย่างมั่นใจเกินจริง"
        )

    if "reasoning_inference" in pids and "hypothesis_guessing" in pids:
        inferences.append(
            "Structured inference separates premises, derived conclusions, and gaps, while ungrounded guessing hides uncertainty."
            if is_en
            else "การอนุมานเชิงตรรกะแยกข้อตั้ง ข้อสรุป และขอบเขตที่ไม่ทราบออกจากกันอย่างชัดเจน ต่างจากการจำหรือเดาคำตอบซึ่งไม่รู้ขอบเขตความไม่แน่นอนของตนเอง"
        )

    if "planning_execution" in pids and ("verification_evidence" in pids or "system_architecture" in pids):
        inferences.append(
            "When an upstream step lacks verification or fails silently, dependent downstream steps propagate unverified state and undermine overall system reliability."
            if is_en
            else "หากขั้นตอนต้นทางล้มเหลวหรือขาดการตรวจสอบ ขั้นตอนที่พึ่งพาต่อจากนั้นจะรับสถานะที่ผิดพลาดไปใช้ต่อ ควรหยุดตรวจสอบหรือแยกกู้คืนก่อนดำเนินการขั้นถัดไป"
        )

    if "security_governance" in pids:
        inferences.append(
            "Explicit permission and approval boundaries prevent unverified automated paths from mutating protected state."
            if is_en
            else "การมีขอบเขตสิทธิ์และ Approval Gate ช่วยป้องกันไม่ให้เส้นทางอัตโนมัติที่ยังไม่ผ่านการตรวจยืนยันไปเปลี่ยนแปลงสถานะสำคัญของระบบ"
        )

    if not inferences:
        joined = ", ".join(p["label_en"] if is_en else p["label_th"] for p in primitives)
        inferences.append(
            f"Combining {joined} requires checking dependencies first and keeping unverified conclusions explicit."
            if is_en
            else f"เมื่อเชื่อมโยงเรื่อง {joined} เข้าด้วยกัน จำเป็นต้องตรวจความสัมพันธ์เชิงเงื่อนไขก่อนสรุปผล และระบุส่วนที่ยังไม่ยืนยันให้ชัดเจน"
        )

    assumptions.append(
        "This analysis derives strictly from the structural concepts stated in your prompt without claiming empirical measurements from external data."
        if is_en
        else "ข้อสรุปนี้อนุมานจากความสัมพันธ์เชิงโครงสร้างของแนวคิดในคำถาม โดยไม่ได้อ้างผลการวัดเชิงประจักษ์จากข้อมูลภายนอกที่ยังไม่ได้นำเข้า"
    )
    unknowns.append(
        "Specific quantitative metrics, implementation parameters, or real dataset distributions are not included in this prompt."
        if is_en
        else "ตัวเลขชี้วัดจริง บริบทของงานเฉพาะ หรือรายละเอียดพารามิเตอร์เฉพาะทางยังไม่ได้ถูกระบุในคำถามนี้"
    )

    return {
        "facts": facts,
        "inferences": inferences,
        "assumptions": assumptions,
        "unknowns": unknowns,
    }


def reason_with_evidence(
    understanding: dict[str, Any],
    *,
    attempted_engines: list[str] | None = None,
    failure_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Stage 4 (Reason): Synthesize communicative, contextual, compositional, or
    premise-gap reasoning without equating lookup misses to inability to think.
    """
    speech_act = understanding["speech_act"]
    interpretation = understanding.get("interpretation") or {}
    unicode_sem = understanding["unicode_semantics"]
    conv_ctx = understanding.get("conversation_context") or {}
    failure_context = failure_context or {}
    engines = list(attempted_engines or [])
    language = understanding.get("language", "thai")

    if failure_context.get("unable_reason"):
        gap = str(failure_context["unable_reason"])
        return {
            "can_infer_conclusion": False,
            "inference_gap": gap,
            "facts": [failure_context.get("detail")] if failure_context.get("detail") else [],
            "inferences": [],
            "assumptions": [],
            "unknowns": ["Missing premise or rule required for valid deduction"],
            "hypothesis": failure_context.get("detail")
            or "ข้อตั้งหรือเงื่อนไขที่ให้มายังไม่เพียงพอสำหรับการสรุปผลอย่างถูกต้อง",
            "attempted_inferences": engines + ["premise_gap_analysis"],
            "clarification_needed": True,
        }

    if speech_act == "opaque_noise":
        return {
            "can_infer_conclusion": False,
            "inference_gap": "no_signal",
            "facts": [],
            "inferences": [],
            "assumptions": [],
            "unknowns": ["No recognizable linguistic or symbolic structure"],
            "hypothesis": "ข้อความไม่มีโครงสร้างภาษา สัญลักษณ์สื่ออารมณ์ หรือความหมายที่ตีความได้",
            "attempted_inferences": engines + ["lexical_plausibility", "unicode_semantics"],
            "clarification_needed": True,
        }

    if speech_act == "greeting":
        dec = understanding["decomposition"]
        return {
            "can_infer_conclusion": True,
            "inference_gap": "none_communicative",
            "facts": [
                f"Detected salutation ({dec['leading_salutation']})",
                f"Language={language}, time_of_day={dec['time_of_day']}, has_prior_turns={bool(conv_ctx.get('recent_turns'))}",
            ],
            "inferences": ["User initiated or continued a conversational greeting directed to ZYRQUEN"],
            "assumptions": [],
            "unknowns": ["User's specific task or topic has not been stated yet"],
            "hypothesis": "เข้าใจว่าเป็นคำทักทายทั่วไปและพร้อมตอบกลับอย่างเป็นธรรมชาติตามบริบทภาษาและช่วงเวลา",
            "attempted_inferences": engines + ["morphological_salutation_parse", "pragmatic_register_analysis"],
            "clarification_needed": False,
        }

    if speech_act == "acknowledgement_or_courtesy":
        subtype = interpretation.get("intent_subtype") or "ack"
        return {
            "can_infer_conclusion": True,
            "inference_gap": "none_communicative",
            "facts": [f"Detected pragmatic courtesy ({subtype})"],
            "inferences": ["User expressed thanks, farewell, or acknowledgement cleanly"],
            "assumptions": [],
            "unknowns": [],
            "hypothesis": f"เข้าใจเจตนาเชิงมารยาทและการตอบรับ ({subtype})",
            "attempted_inferences": engines + ["pragmatic_courtesy_parse"],
            "clarification_needed": False,
        }

    if speech_act == "capability_or_help_request":
        subtype = interpretation.get("intent_subtype") or "open_help"
        return {
            "can_infer_conclusion": True,
            "inference_gap": "needs_task_detail" if subtype == "open_help" else "none_communicative",
            "facts": [f"User requested {subtype}"],
            "inferences": ["User is asking what ZYRQUEN can do or requesting assistance"],
            "assumptions": [],
            "unknowns": ["Specific problem/domain not yet specified"] if subtype == "open_help" else [],
            "hypothesis": "เข้าใจว่าผู้ใช้ขอความช่วยเหลือหรือสอบถามความสามารถจริงของ ZYRQUEN",
            "attempted_inferences": engines + ["capability_intent_parse"],
            "clarification_needed": subtype == "open_help",
        }

    if speech_act == "affective_expression":
        th_desc, en_desc = _describe_affective_state(unicode_sem, language)
        ctx_topic = conv_ctx.get("active_topic") or ""
        return {
            "can_infer_conclusion": False,
            "inference_gap": "affective_or_ambiguous_intent",
            "affective_summary_th": th_desc,
            "affective_summary_en": en_desc,
            "previous_topic": ctx_topic,
            "facts": [f"Unicode descriptors: {', '.join(unicode_sem.get('symbol_descriptors') or [])}"],
            "inferences": [f"Affective axis indicates {en_desc}"],
            "assumptions": [],
            "unknowns": ["User's intended next action or topic is unstated"],
            "hypothesis": f"ผู้ใช้อาจกำลังสื่อถึง{th_desc} แต่ยังไม่ระบุจุดประสงค์หรือคำสั่งที่ชัดเจน",
            "attempted_inferences": engines + ["unicode_affect_decomposition", "conversational_pragmatics"],
            "clarification_needed": True,
        }

    if speech_act == "contextual_followup":
        referent = conv_ctx.get("active_topic") or ""
        last_status = conv_ctx.get("last_assistant_status") or ""
        last_reply = conv_ctx.get("last_assistant_reply") or ""
        if not referent:
            return {
                "can_infer_conclusion": False,
                "inference_gap": "unanchored_context",
                "previous_topic": "",
                "facts": [],
                "inferences": [],
                "assumptions": [],
                "unknowns": ["No prior turn in this conversation establishes what the pronoun refers to"],
                "hypothesis": "ข้อความอ้างอิงถึงหัวข้อก่อนหน้า แต่ยังไม่มีบริบทก่อนหน้าในบทสนทนานี้",
                "attempted_inferences": engines + ["anaphora_resolution", "conversation_context_lookup"],
                "clarification_needed": True,
            }

        # Context exists! Check if prior topic was grounded or itself unlearned
        if last_status == "NOT_LEARNED":
            return {
                "can_infer_conclusion": False,
                "inference_gap": "context_unlearned_topic",
                "previous_topic": referent,
                "facts": [f"Resolved follow-up topic from prior turn: {referent}"],
                "inferences": ["Follow-up question refers to the unverified topic from the previous turn"],
                "assumptions": [],
                "unknowns": [f"Verified factual details about '{referent}' are not yet available"],
                "hypothesis": f"เข้าใจว่าถามต่อจากเรื่อง '{referent}' แต่ยังไม่มีข้อมูลยืนยันเพียงพอในหัวข้อนี้",
                "attempted_inferences": engines + ["anaphora_resolution", "context_epistemic_carryover"],
                "clarification_needed": True,
            }

        return {
            "can_infer_conclusion": True,
            "inference_gap": "none_contextual",
            "previous_topic": referent,
            "last_assistant_reply": last_reply,
            "facts": [f"Resolved referent from prior conversation: {referent}"],
            "inferences": [f"Follow-up elaborates on prior verified context regarding '{referent}'"],
            "assumptions": ["Assuming user continues asking about the immediately preceding topic"],
            "unknowns": ["Any additional external aspects not covered in earlier turns remain unverified"],
            "hypothesis": f"เชื่อมโยงคำถามต่อเนื่องเข้ากับหัวข้อก่อนหน้า '{referent}' สำเร็จ",
            "attempted_inferences": engines + ["anaphora_resolution", "contextual_synthesis"],
            "clarification_needed": False,
        }

    if speech_act == "compositional_reasoning_query":
        comp = _synthesize_compositional_reasoning(understanding, language)
        return {
            "can_infer_conclusion": True,
            "inference_gap": "none_compositional",
            "facts": comp["facts"],
            "inferences": comp["inferences"],
            "assumptions": comp["assumptions"],
            "unknowns": comp["unknowns"],
            "hypothesis": "วิเคราะห์ความสัมพันธ์จากโครงสร้างแนวคิดและเงื่อนไขในคำถามโดยไม่ต้องพึ่งข้อมูลที่ไม่ได้ยืนยัน",
            "attempted_inferences": engines + ["semantic_primitive_decomposition", "compositional_structural_reasoning"],
            "clarification_needed": False,
        }

    if speech_act == "ambiguous_fragment":
        prev_topic = conv_ctx.get("active_topic") or ""
        return {
            "can_infer_conclusion": False,
            "inference_gap": "affective_or_ambiguous_intent",
            "previous_topic": prev_topic,
            "facts": [f"Prior topic: {prev_topic}"] if prev_topic else [],
            "inferences": [],
            "assumptions": [],
            "unknowns": ["Input is too brief to determine exact goal"],
            "hypothesis": (
                f"ข้อความสั้นและยังมีบริบทไม่พอ (อาจเชื่อมโยงกับเรื่อง '{prev_topic}')"
                if prev_topic
                else "เข้าใจลักษณะข้อความเกริ่นนำ แต่ยังไม่ทราบเป้าหมายเฉพาะที่ผู้ใช้ต้องการ"
            ),
            "attempted_inferences": engines + ["conversational_pragmatics", "conversation_context_lookup"],
            "clarification_needed": True,
        }

    if speech_act == "unfamiliar_term_or_ambiguous":
        terms = understanding["semantics"].get("unfamiliar_terms") or []
        preserved = ", ".join(terms) if terms else understanding["topic_focus"]
        return {
            "can_infer_conclusion": False,
            "inference_gap": "unfamiliar_term_clarification",
            "preserved_terms": terms,
            "topic_focus": preserved,
            "facts": [f"Preserved unfamiliar term(s): {preserved}"],
            "inferences": ["Term has plausible structure but no verified definition in current memory"],
            "assumptions": [],
            "unknowns": [f"Domain, context, or definition for '{preserved}'"],
            "hypothesis": f"ตรวจพบคำหรือบริบทเฉพาะทาง '{preserved}' ที่ยังไม่มีข้อมูลยืนยัน จึงควรถามบริบทเพิ่มแทนการคาดเดา",
            "attempted_inferences": engines + ["unfamiliar_term_preservation", "clarification_generation"],
            "clarification_needed": True,
        }

    # Conceptual question / general utterance where KG & native models had no verified facts
    kg_related = understanding.get("kg_related") or []
    episodic_hits = understanding.get("episodic_hits") or []
    topic = understanding["topic_focus"]
    analogy_hint = ""
    if kg_related:
        sample = kg_related[0]
        analogy_hint = f"มีข้อมูลที่เกี่ยวข้องบางส่วนเกี่ยวกับ '{sample['subject']}' แต่ยังไม่ครอบคลุมคำถามนี้โดยตรง"

    return {
        "can_infer_conclusion": False,
        "inference_gap": "unlearned_knowledge",
        "topic_focus": topic,
        "analogy_hint": analogy_hint,
        "episodic_overlap_count": len(episodic_hits),
        "facts": [f"Question topic identified: {topic}"],
        "inferences": [],
        "assumptions": [],
        "unknowns": [f"Verified factual knowledge for '{topic}' is unavailable"],
        "hypothesis": f"เข้าใจว่าผู้ใช้กำลังสอบถามเกี่ยวกับ '{topic}' แต่ยังไม่มีข้อมูลที่ยืนยันได้ในหัวข้อนี้",
        "attempted_inferences": engines + ["linguistic_intent_parse", "kg_analogical_probe", "episodic_context_lookup"],
        "clarification_needed": False,
    }


def evaluate_cognition(
    understanding: dict[str, Any],
    reasoning: dict[str, Any],
    *,
    explicit_status: str | None = None,
) -> dict[str, Any]:
    """
    Stage 5 (Evaluate): Calibrate epistemic confidence and emit both:
    - cognitive_state: UNDERSTOOD | INFERRED | UNCERTAIN | UNKNOWN | NEEDS_CLARIFICATION
    - epistemic_state: VERIFIED | UNCERTAIN | NOT_LEARNED | UNABLE_TO_INFER | UNKNOWN | BLOCKED | PENDING_APPROVAL | FAILED
    """
    speech_act = understanding.get("speech_act")
    gap = reasoning.get("inference_gap")

    if explicit_status in {"VERIFIED", "BLOCKED", "PENDING_APPROVAL", "FAILED"}:
        return {
            "cognitive_state": "UNDERSTOOD" if explicit_status == "VERIFIED" else "UNCERTAIN",
            "epistemic_state": explicit_status,
            "understood": True,
            "confidence": 1.0 if explicit_status == "VERIFIED" else 0.0,
            "evidence_grounded": explicit_status == "VERIFIED",
            "contradictions_detected": explicit_status == "BLOCKED",
            "uncertainty_reason": None,
        }

    if explicit_status == "UNABLE_TO_INFER" or gap in {
        "missing_premise_or_rule",
        "division_by_zero",
        "underdetermined",
        "incompatible_attributes",
        "fallacy",
    }:
        return {
            "cognitive_state": "NEEDS_CLARIFICATION",
            "epistemic_state": "UNABLE_TO_INFER",
            "understood": True,
            "confidence": 0.15,
            "evidence_grounded": False,
            "contradictions_detected": False,
            "uncertainty_reason": reasoning.get("hypothesis"),
        }

    if gap == "no_signal":
        return {
            "cognitive_state": "UNKNOWN",
            "epistemic_state": "UNKNOWN",
            "understood": False,
            "confidence": 0.0,
            "evidence_grounded": False,
            "contradictions_detected": False,
            "uncertainty_reason": understanding.get("opaque_reason") or "unintelligible_input",
        }

    if gap == "none_communicative":
        return {
            "cognitive_state": "UNDERSTOOD",
            "epistemic_state": "VERIFIED",
            "understood": True,
            "confidence": 0.96,
            "evidence_grounded": True,
            "contradictions_detected": False,
            "uncertainty_reason": None,
        }

    if gap == "needs_task_detail":
        return {
            "cognitive_state": "NEEDS_CLARIFICATION",
            "epistemic_state": "VERIFIED",
            "understood": True,
            "confidence": 0.85,
            "evidence_grounded": True,
            "contradictions_detected": False,
            "uncertainty_reason": None,
        }

    if gap in {"none_compositional", "none_contextual"}:
        return {
            "cognitive_state": "INFERRED",
            "epistemic_state": "VERIFIED",
            "understood": True,
            "confidence": 0.82,
            "evidence_grounded": True,
            "contradictions_detected": False,
            "uncertainty_reason": None,
        }

    if gap in {"unfamiliar_term_clarification", "unanchored_context"}:
        return {
            "cognitive_state": "NEEDS_CLARIFICATION",
            "epistemic_state": "UNCERTAIN",
            "understood": True,
            "confidence": 0.35,
            "evidence_grounded": False,
            "contradictions_detected": False,
            "uncertainty_reason": reasoning.get("hypothesis"),
        }

    if gap == "context_unlearned_topic":
        return {
            "cognitive_state": "UNDERSTOOD",
            "epistemic_state": "NOT_LEARNED",
            "understood": True,
            "confidence": 0.1,
            "evidence_grounded": False,
            "contradictions_detected": False,
            "uncertainty_reason": reasoning.get("hypothesis"),
        }

    if gap == "affective_or_ambiguous_intent":
        has_affect = bool(understanding["unicode_semantics"].get("dominant_axis"))
        conf = 0.52 if has_affect else 0.38
        return {
            "cognitive_state": "UNCERTAIN" if speech_act == "affective_expression" else "NEEDS_CLARIFICATION",
            "epistemic_state": "UNCERTAIN",
            "understood": True,
            "confidence": conf,
            "evidence_grounded": False,
            "contradictions_detected": False,
            "uncertainty_reason": reasoning.get("hypothesis"),
        }

    # Clear query/topic understood, but factual/model knowledge is absent
    return {
        "cognitive_state": "UNDERSTOOD",
        "epistemic_state": "NOT_LEARNED",
        "understood": True,
        "confidence": 0.0,
        "evidence_grounded": False,
        "contradictions_detected": False,
        "uncertainty_reason": f"Missing verified factual basis for '{understanding['topic_focus']}'",
    }


def _compose_greeting_reply(understanding: dict[str, Any]) -> str:
    dec = understanding["decomposition"]
    lang = understanding.get("language", "thai")
    tod = dec.get("time_of_day")
    asks_wellbeing = dec.get("asks_wellbeing", False)
    has_prior = bool((understanding.get("conversation_context") or {}).get("recent_turns"))

    if lang == "english":
        salute_map = {
            "morning": "Good morning!",
            "afternoon": "Good afternoon!",
            "evening": "Good evening!",
        }
        opening = salute_map.get(tod or "", "Hello!")
        if asks_wellbeing:
            body = "I'm doing well and ready to work with you."
        elif has_prior:
            body = "Good to continue our conversation."
        else:
            body = "Welcome."
        offer = "How can I help you today?"
        return f"{opening} {body} {offer}"

    # Thai compositional greeting assembly
    tod_prefix = {
        "morning": "สวัสดีตอนเช้าครับ",
        "afternoon": "สวัสดีตอนบ่ายครับ",
        "evening": "สวัสดีตอนเย็นครับ",
    }
    opening = tod_prefix.get(tod or "", "สวัสดีครับ")
    if asks_wellbeing:
        middle = "ผมพร้อมช่วยงานตามปกติเลยครับ"
        offer = "วันนี้อยากให้ช่วยเรื่องอะไรดีครับ"
    elif has_prior:
        middle = "ยินดีที่ได้คุยกันต่อครับ"
        offer = "มีอะไรให้ช่วยเพิ่มเติมไหมครับ"
    else:
        middle = "ยินดีต้อนรับ"
        offer = "มีอะไรให้ช่วยวันนี้ครับ"
    return f"{opening} {middle} {offer}"


def _compose_courtesy_reply(understanding: dict[str, Any]) -> str:
    lang = understanding.get("language", "thai")
    subtype = (understanding.get("interpretation") or {}).get("intent_subtype") or "ack"
    tod = (understanding.get("decomposition") or {}).get("time_of_day")
    is_en = lang == "english"

    if subtype == "thanks":
        if is_en:
            return "You're welcome! Let me know whenever you'd like help with anything else."
        return "ยินดีครับ หากมีเรื่องอะไรให้ช่วยเพิ่มเติม บอกได้เสมอเลยนะครับ"

    if subtype == "farewell":
        if is_en:
            if tod == "night":
                return "Good night! Feel free to come back anytime."
            return "Goodbye! Feel free to return whenever you need assistance."
        if tod == "night":
            return "ราตรีสวัสดิ์ครับ พักผ่อนให้เต็มที่นะครับ แล้วพบกันใหม่เมื่อคุณต้องการความช่วยเหลือ"
        return "สวัสดีครับ แล้วพบกันใหม่เมื่อคุณพร้อมให้ช่วยงานนะครับ"

    if is_en:
        return "Got it. Let me know what topic or task you'd like to focus on next."
    return "รับทราบครับ อยากให้ช่วยเรื่องไหนหรือคุยประเด็นอะไรต่อ บอกได้เลยครับ"


def _compose_capability_reply(understanding: dict[str, Any]) -> str:
    lang = understanding.get("language", "thai")
    subtype = (understanding.get("interpretation") or {}).get("intent_subtype") or "open_help"
    is_en = lang == "english"

    if subtype == "capability_inquiry":
        if is_en:
            return (
                "I am ZYRQUEN, a native reasoning and structured assistance system. "
                "I can help you with symbolic math, algebra, statistics, logical and causal reasoning, "
                "structured task planning, and answering from verified knowledge you record—while clearly "
                "telling you when information is uncertain or unavailable instead of guessing."
            )
        return (
            "สวัสดีครับ ผมคือ ZYRQUEN ระบบช่วยวิเคราะห์และให้เหตุผลภายใน "
            "ผมสามารถช่วยคิดคำนวณทางคณิตศาสตร์ แก้สมการ วิเคราะห์สถิติ ไล่เหตุผลเชิงตรรกะและเหตุ-ผล "
            "วางแผนงานเป็นขั้นตอน รวมถึงค้นหาและเชื่อมโยงข้อมูลที่บันทึกไว้ได้ครับ "
            "และหากเรื่องใดยังไม่แน่ใจหรือยังไม่มีข้อมูลยืนยัน ผมจะแจ้งตรงไปตรงมาโดยไม่เดาคำตอบขึ้นมาเองครับ"
        )

    if is_en:
        return (
            "I'm here to help. Tell me what you'd like to work on—for example, a math or logic problem, "
            "analyzing trade-offs, planning steps, or exploring a specific question."
        )
    return (
        "ยินดีช่วยเลยครับ ตอนนี้อยากให้ผมช่วยเรื่องอะไรเป็นพิเศษครับ "
        "เช่น ช่วยคิดคำนวณ วิเคราะห์เหตุผล เปรียบเทียบแนวคิด หรือวางแผนงานเป็นขั้นตอน บอกรายละเอียดมาได้เลยครับ"
    )


def compose_honest_response(
    understanding: dict[str, Any],
    reasoning: dict[str, Any],
    evaluation: dict[str, Any],
) -> str:
    """
    Stage 6 (Respond): Generate natural, professional user-facing ZYRQUEN replies
    without leaking internal jargon ("Not Learned", "0 records", "checkpoint", "AST").
    """
    state = evaluation["epistemic_state"]
    speech_act = understanding.get("speech_act")
    gap = reasoning.get("inference_gap")
    lang = understanding.get("language", "thai")
    is_en = lang == "english"

    if speech_act == "greeting":
        return _compose_greeting_reply(understanding)

    if speech_act == "acknowledgement_or_courtesy":
        return _compose_courtesy_reply(understanding)

    if speech_act == "capability_or_help_request":
        return _compose_capability_reply(understanding)

    if speech_act == "compositional_reasoning_query" and state == "VERIFIED":
        facts = reasoning.get("facts") or []
        inferences = reasoning.get("inferences") or []
        unknowns = reasoning.get("unknowns") or []
        if is_en:
            parts = []
            if facts:
                parts.append(f"**What's clear from your question:** {facts[0]}")
            if inferences:
                parts.append("**Structural reasoning:**\n" + "\n".join(f"- {inf}" for inf in inferences))
            if unknowns:
                parts.append(f"**Boundary / missing specifics:** {unknowns[0]}")
            return "\n\n".join(parts)
        parts_th = []
        if facts:
            parts_th.append(f"**ประเด็นตั้งต้นที่เข้าใจ:** {facts[0]}")
        if inferences:
            parts_th.append("**การวิเคราะห์เชิงโครงสร้าง:**\n" + "\n".join(f"- {inf}" for inf in inferences))
        if unknowns:
            parts_th.append(f"**ขอบเขตและสมมติฐาน:** {unknowns[0]}")
        return "\n\n".join(parts_th)

    if speech_act == "contextual_followup" and gap == "none_contextual" and state == "VERIFIED":
        ref = reasoning.get("previous_topic") or ""
        last_reply = reasoning.get("last_assistant_reply") or ""
        snippet = last_reply.strip().splitlines()[0][:160] if last_reply else ""
        if is_en:
            base = f"Following up on **{ref}**, here is what we have established so far"
            if snippet:
                base += f": {snippet}"
            else:
                base += "."
            return (
                f"{base}\n\n"
                "If you'd like to explore a specific angle—such as advantages, trade-offs, or next steps—let me know which part you want to focus on."
            )
        base_th = f"ต่อเนื่องจากเรื่อง **{ref}** ก่อนหน้านี้"
        if snippet:
            base_th += f" สิ่งที่ได้วิเคราะห์ไว้คือ: {snippet}"
        return (
            f"{base_th}\n\n"
            "หากต้องการเจาะลึกมุมมองไหนเป็นพิเศษ เช่น ข้อดี ข้อจำกัด หรือขั้นตอนถัดไป บอกเพิ่มเติมได้เลยครับ"
        )

    if state == "UNKNOWN":
        if is_en:
            return (
                "I couldn't make out a clear meaning from this message yet, so I don't want to guess. "
                "Could you rephrase it or share a bit more context?"
            )
        return (
            "ผมยังไม่เข้าใจความหมายของข้อความนี้ครับ จึงไม่อยากเดาคำตอบไปเอง "
            "รบกวนพิมพ์ใหม่หรืออธิบายเพิ่มเติมอีกนิดนะครับ"
        )

    if state == "UNCERTAIN":
        if speech_act == "affective_expression":
            th_desc = reasoning.get("affective_summary_th") or "อารมณ์หรือสัญลักษณ์บางอย่าง"
            en_desc = reasoning.get("affective_summary_en") or "an emotional or symbolic reaction"
            prev_topic = reasoning.get("previous_topic")
            if is_en:
                ctx_bit = f" regarding \"{prev_topic}\"" if prev_topic else ""
                return (
                    f"It looks like you're expressing {en_desc}{ctx_bit}. "
                    f"Is there something on your mind or a topic you'd like to talk through?"
                )
            ctx_bit_th = f"เกี่ยวกับเรื่อง \"{prev_topic}\" " if prev_topic else ""
            return (
                f"ดูเหมือนคุณกำลังสื่อถึง{th_desc} {ctx_bit_th}"
                f"มีเรื่องอะไรเล่าให้ฟังหรืออยากให้ผมช่วยเรื่องไหน บอกได้เลยนะครับ"
            )

        if gap == "unanchored_context":
            if is_en:
                return (
                    "It sounds like you're referring to a specific topic or item, but I don't see earlier context in this chat yet. "
                    "Could you tell me which subject you mean?"
                )
            return (
                "ดูเหมือนคุณกำลังพูดถึงเรื่องหรือสิ่งใดสิ่งหนึ่งต่อจากบริบทก่อนหน้า แต่ในบทสนทนานี้ยังไม่มีหัวข้อตั้งต้นครับ "
                "รบกวนระบุเพิ่มเติมอีกนิดว่าหมายถึงเรื่องอะไรครับ"
            )

        if gap == "unfamiliar_term_clarification":
            preserved = reasoning.get("topic_focus") or understanding["prompt"][:60]
            if is_en:
                return (
                    f"I noticed the term \"{preserved}\", which I don't have verified background on yet. "
                    f"Could you share what domain or context \"{preserved}\" belongs to, and what outcome you're aiming for?"
                )
            return (
                f"ผมเห็นคำว่า \"{preserved}\" ในข้อความของคุณ ซึ่งยังไม่มีข้อมูลยืนยันในเรื่องนี้ครับ "
                f"รบกวนช่วยบอกบริบทหรือเป้าหมายเพิ่มเติมอีกนิดว่า \"{preserved}\" เกี่ยวข้องกับด้านใด เพื่อจะได้ช่วยวิเคราะห์ได้ตรงจุดครับ"
            )

        prev_topic = reasoning.get("previous_topic")
        if prev_topic:
            if is_en:
                return (
                    f"I want to make sure I follow you correctly—are you referring back to \"{prev_topic}\", "
                    f"or asking about something new?"
                )
            return (
                f"เพื่อไม่ให้เข้าใจคลาดเคลื่อน ไม่ทราบว่าคุณหมายถึงเรื่อง \"{prev_topic}\" ที่คุยกันก่อนหน้า "
                f"หรือต้องการให้ช่วยเรื่องใหม่ครับ"
            )
        if is_en:
            return (
                "I want to be sure I understand what you're looking for. "
                "Could you share a little more detail about what you'd like to explore or solve?"
            )
        return (
            "ผมอยากช่วยตอบให้ตรงจุดครับ รบกวนบอกรายละเอียดเพิ่มเติมอีกนิดว่าคุณต้องการให้ช่วยเรื่องอะไรครับ"
        )

    if state == "UNABLE_TO_INFER":
        reason_detail = reasoning.get("hypothesis") or "ข้อมูลหรือเงื่อนไขที่ให้มายังไม่เพียงพอที่จะสรุปผลได้"
        if is_en:
            return (
                f"I understood the problem structure, but I cannot draw a valid conclusion from the given premises: {reason_detail}"
            )
        return (
            f"ไม่สามารถสรุปคำตอบจากเงื่อนไขที่ให้มาได้ครับ: {reason_detail} "
            f"หากมีข้อมูลหรือเงื่อนไขเพิ่มเติม สามารถส่งมาให้ช่วยวิเคราะห์ใหม่ได้เลยนะครับ"
        )

    # NOT_LEARNED (factual/encyclopedic topic understood, verified knowledge unavailable)
    topic = reasoning.get("previous_topic") or understanding.get("topic_focus") or understanding["prompt"][:60]
    analogy = reasoning.get("analogy_hint")
    if is_en:
        extra = f" ({analogy})" if analogy else ""
        return (
            f"I understand you're asking about \"{topic}\", but I don't have verified information on this topic yet "
            f"and don't want to guess{extra}. If you'd like to share relevant context or details, I can help analyze it with you."
        )
    extra_th = f"\n\n({analogy})" if analogy else ""
    return (
        f"ผมเข้าใจว่าคุณกำลังถามเกี่ยวกับเรื่อง \"{topic}\" ครับ แต่ตอนนี้ผมยังไม่มีข้อมูลที่ยืนยันได้เพียงพอในเรื่องนี้ "
        f"จึงไม่อยากคาดเดาคำตอบขึ้นมาเอง{extra_th}\n"
        f"หากคุณมีรายละเอียดหรือบริบทเพิ่มเติม ส่งมาให้ผมช่วยวิเคราะห์ร่วมกันได้เลยครับ"
    )


def learn_from_experience(
    conn: sqlite3.Connection,
    understanding: dict[str, Any],
    reasoning: dict[str, Any],
    evaluation: dict[str, Any],
) -> dict[str, Any]:
    """
    Stage 7 (Learn): Persist epistemic experience to `episodic_experiences`
    without mutating model weights autonomously (model_weights_changed=False).
    """
    prompt = understanding.get("prompt", "").strip()
    state = evaluation["epistemic_state"]
    if not prompt:
        return {"recorded": False, "model_weights_changed": False}

    gap_type = str(reasoning.get("inference_gap") or state.lower())
    hypothesis_payload = {
        "speech_act": understanding.get("speech_act"),
        "cognitive_state": evaluation.get("cognitive_state"),
        "epistemic_state": state,
        "confidence": evaluation.get("confidence"),
        "understood": evaluation.get("understood"),
        "topic_focus": understanding.get("topic_focus"),
        "dominant_affect": understanding.get("unicode_semantics", {}).get("dominant_axis"),
        "model_weights_changed": False,
    }
    exp_id = str(uuid.uuid4())
    try:
        existing = conn.execute(
            """
            SELECT id FROM episodic_experiences
            WHERE goal=? AND outcome_status=?
            ORDER BY created_at DESC LIMIT 1
            """,
            (prompt[:240], state),
        ).fetchone()
        if not existing:
            with conn:
                conn.execute(
                    """
                    INSERT INTO episodic_experiences (
                        id, mission_id, goal, outcome_status, gap_type,
                        hypothesis_json, verified_delta, created_at
                    )
                    VALUES (?, NULL, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        exp_id,
                        prompt[:240],
                        state,
                        gap_type,
                        json.dumps(hypothesis_payload, ensure_ascii=False),
                        0.0,
                        _now_iso(),
                    ),
                )
            return {
                "recorded": True,
                "experience_id": exp_id,
                "model_weights_changed": False,
            }
        return {
            "recorded": False,
            "deduplicated": True,
            "model_weights_changed": False,
        }
    except sqlite3.Error:
        return {"recorded": False, "model_weights_changed": False}


def run_cognitive_fallback_pipeline(
    conn: sqlite3.Connection,
    *,
    prompt: str,
    attachment: str = "",
    mode: str = "auto",
    conversation_id: str | None = None,
    attempted_engines: list[str] | None = None,
    failure_context: dict[str, Any] | None = None,
    explicit_status: str | None = None,
    understanding: dict[str, Any] | None = None,
    tokenize_fn=None,
    extract_terms_fn=None,
    query_kg_fn=None,
) -> dict[str, Any]:
    """Execute full Understand -> Interpret -> Reason -> Evaluate -> Respond -> Learn cycle."""
    if understanding is None:
        understanding = understand_input(
            conn,
            prompt,
            attachment=attachment,
            mode=mode,
            conversation_id=conversation_id,
            tokenize_fn=tokenize_fn,
            extract_terms_fn=extract_terms_fn,
            query_kg_fn=query_kg_fn,
        )
    interpretation = understanding.get("interpretation") or interpret_intent(understanding)
    reasoning = reason_with_evidence(
        understanding,
        attempted_engines=attempted_engines,
        failure_context=failure_context,
    )
    evaluation = evaluate_cognition(
        understanding,
        reasoning,
        explicit_status=explicit_status,
    )
    response_text = compose_honest_response(understanding, reasoning, evaluation)
    learning = learn_from_experience(conn, understanding, reasoning, evaluation)

    return {
        "status": evaluation["epistemic_state"],
        "epistemic_state": evaluation["epistemic_state"],
        "cognitive_state": evaluation["cognitive_state"],
        "response": response_text,
        "pipeline_trace": {
            "understand": {
                "language": understanding["language"],
                "speech_act": understanding["speech_act"],
                "intent_subtype": interpretation.get("intent_subtype"),
                "topic_focus": understanding["topic_focus"],
                "has_followup_reference": bool(interpretation.get("is_followup")),
                "resolved_referent": interpretation.get("resolved_referent"),
                "semantic_primitives": understanding["semantics"]["primitive_ids"],
                "symbol_count": understanding["unicode_semantics"]["symbol_count"],
                "dominant_affect": understanding["unicode_semantics"]["dominant_axis"],
                "symbol_descriptors": understanding["unicode_semantics"]["symbol_descriptors"],
                "episodic_hits": len(understanding["episodic_hits"]),
                "kg_related_hints": len(understanding["kg_related"]),
            },
            "interpret": {
                "speech_act": interpretation.get("speech_act"),
                "requires_retrieval": interpretation.get("requires_retrieval"),
                "early_communicative_route": interpretation.get("early_communicative_route"),
                "leading_salutation": understanding["decomposition"].get("leading_salutation"),
            },
            "reason": {
                "inference_gap": reasoning["inference_gap"],
                "facts": reasoning.get("facts", []),
                "inferences": reasoning.get("inferences", []),
                "assumptions": reasoning.get("assumptions", []),
                "unknowns": reasoning.get("unknowns", []),
                "hypothesis": reasoning["hypothesis"],
                "attempted_inferences": reasoning["attempted_inferences"],
                "clarification_needed": reasoning["clarification_needed"],
            },
            "evaluate": evaluation,
            "respond": {
                "strategy": evaluation["cognitive_state"].lower(),
                "epistemic_status": evaluation["epistemic_state"],
                "internal_jargon_suppressed": True,
            },
            "learn": learning,
        },
    }
