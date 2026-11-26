#!/usr/bin/env python3
"""
ZYRQUEN Ω∞ — Native Causal, Conditional & Categorical Syllogism Reasoning Engine
--------------------------------------------------------------------------------
100% Pure Python Standard Library (zero external LLM calls):
1. Conditional / Causal Forward-Chaining (Modus Ponens & Causal Graph)
   - Handles multi-rule chains (`ถ้า A แล้ว B และ ถ้า B แล้ว C หาก A จะเกิดอะไรขึ้น`)
   - Handles causal verbs (`A ทำให้เกิด B`, `B ส่งผลให้ C`)
   - Detects causal polarity contradictions (`C` vs `ไม่ C` -> CONTRADICTION / BLOCKED)
2. Categorical Syllogism & Set Inclusion Deduction
   - Universal affirmative (`ทุก X เป็น Y`, `All X are Y`)
   - Universal negative (`ไม่มี X เป็น Y`, `No X is Y`)
   - Membership (`Z เป็น X`) & query (`ดังนั้น Z เป็น Y หรือไม่`)
3. Backward Root-Cause Tracing over SQLite Knowledge Graph
   - Traces upstream causal triples (`ทำให้เกิด`, `ส่งผลให้`, `causes`, `leads to`)
"""

from __future__ import annotations

import collections
import re
import sqlite3
from typing import Any


_NEG_PREFIX_RE = re.compile(r"^(?:ไม่|ไม่ใช่|ไม่เป็น|ไม่เกิด|not\s+|no\s+)", re.IGNORECASE)


def _strip_clause(text: str) -> str:
    s = text.strip(" .,:;\"'?!()")
    s = re.sub(r"\s+", " ", s)
    return s


def _canonical_prop(text: str) -> tuple[str, bool]:
    """Return (normalized_base_proposition, is_negated)."""
    s = _strip_clause(text)
    s_clean = re.sub(r"^(?:จะเกิด|เกิด|จะ|ต้อง)\s+", "", s).strip()
    is_neg = False
    m = _NEG_PREFIX_RE.match(s_clean)
    if m:
        is_neg = True
        s_clean = s_clean[m.end() :].strip()
    s_clean = re.sub(r"^(?:เป็น|คือ|เกิด)\s+", "", s_clean).strip()
    base = (s_clean or s).lower()
    return base, is_neg


def _split_clauses(raw: str) -> list[str]:
    parts = re.split(
        r"(?:[;\n]+|,\s*(?=(?:ถ้า|หาก|เมื่อ|สมมติ|ทุก|ไม่มี|และ|ดังนั้น|if|given|all|no|when)\b)|\s+(?:และ|แล้วก็)\s+|\s+and\s+)",
        raw.strip(),
        flags=re.IGNORECASE,
    )
    return [_strip_clause(p) for p in parts if _strip_clause(p)]


def _parse_causal_rule(clause: str) -> tuple[str, str] | None:
    patterns = [
        re.compile(r"^(?:ถ้า|หาก|เมื่อ|สมมติว่า|สมมติ)\s*(.+?)\s*(?:แล้ว|จะทำให้|ส่งผลให้|ทำให้เกิด|ทำให้|ย่อม)\s*(.+)$", re.IGNORECASE),
        re.compile(r"^(?:if|when|given)\s+(.+?)\s*(?:then|,)\s*(.+)$", re.IGNORECASE),
        re.compile(r"^(.+?)\s*(?:ทำให้เกิด|ส่งผลให้|นำไปสู่|ก่อให้เกิด|causes|leads\s+to|implies|->|⇒)\s*(.+)$", re.IGNORECASE),
    ]
    for pat in patterns:
        m = pat.match(clause)
        if m:
            ant = _strip_clause(m.group(1))
            con = _strip_clause(m.group(2))
            if ant and con and ant.lower() != con.lower():
                return ant, con
    return None


def _try_causal_forward_chain(prompt: str) -> dict[str, Any] | None:
    cleaned = prompt.strip()
    # Look for conditional/causal trigger cues with at least one causal rule + query/observation
    has_question_cue = bool(
        re.search(
            r"(?:จะเกิดอะไรขึ้น|จะเกิดอะไร|เกิดอะไรขึ้น|ผลคืออะไร|ผลลัพธ์คืออะไร|สรุปได้ว่าอย่างไร|สรุปว่าอย่างไร|what\s+(?:happens|follows|results)|what\s+will\s+happen)",
            cleaned,
            re.IGNORECASE,
        )
    )
    if not has_question_cue:
        return None

    # Split question tail off
    q_split = re.split(
        r"\s*(?:จะเกิดอะไรขึ้น|จะเกิดอะไร|เกิดอะไรขึ้น|ผลคืออะไร|ผลลัพธ์คืออะไร|สรุปได้ว่าอย่างไร|สรุปว่าอย่างไร|what\s+(?:happens|follows|results)|what\s+will\s+happen)\??\s*$",
        cleaned,
        maxsplit=1,
        flags=re.IGNORECASE,
    )
    body = q_split[0].strip()
    if not body:
        return None

    # Check explicit trailing "หาก/ถ้า/สมมติ/เมื่อ/given <observed_fact>" segment right before question
    obs_facts: list[str] = []
    cue_iter = list(
        re.finditer(
            r"(?:^|[.;,\n]\s*|\s+)(?:หาก|ถ้า|สมมติว่า|สมมติ|เมื่อ|พบว่า|ปรากฏว่า|given(?:\s+that)?|suppose|if)\s+",
            body,
            flags=re.IGNORECASE,
        )
    )
    rules_raw = body
    for m_cue in reversed(cue_iter):
        tail = body[m_cue.end() :].strip()
        tail_clean = re.sub(r"\s*(?:เกิดขึ้น|เป็นจริง|occurred|happens)\s*$", "", tail, flags=re.IGNORECASE)
        tail_clean = _strip_clause(tail_clean)
        if not tail_clean:
            continue
        if "แล้ว" not in tail_clean and "then" not in tail_clean.lower() and not _parse_causal_rule(tail_clean):
            obs_facts.append(tail_clean)
            rules_raw = body[: m_cue.start()].strip()
            break

    clauses = _split_clauses(rules_raw)
    rules: list[tuple[str, str]] = []
    for cl in clauses:
        parsed = _parse_causal_rule(cl)
        if parsed:
            rules.append(parsed)
        elif not cl.startswith(("ถ้า", "หาก", "if", "when")) and len(cl) >= 2:
            obs_facts.append(cl)

    if not rules or not obs_facts:
        return None

    # Forward-chain BFS over causal rules
    steps: list[str] = []
    adj: dict[tuple[str, bool], list[tuple[str, bool, str, str]]] = collections.defaultdict(list)
    display_map: dict[tuple[str, bool], str] = {}

    for ant_raw, con_raw in rules:
        a_key = _canonical_prop(ant_raw)
        c_key = _canonical_prop(con_raw)
        display_map.setdefault(a_key, ant_raw)
        display_map.setdefault(c_key, con_raw)
        adj[a_key].append((c_key[0], c_key[1], ant_raw, con_raw))
        steps.append(f"กฎเหตุ-ผล: `{ant_raw}` ⇒ `{con_raw}`")

    known: dict[str, bool] = {}  # base_prop -> polarity (True=affirmative, False=negated)
    queue: collections.deque[tuple[str, bool]] = collections.deque()
    for fact in obs_facts:
        f_base, f_neg = _canonical_prop(fact)
        display_map.setdefault((f_base, f_neg), fact)
        steps.append(f"ข้อเท็จจริงตั้งต้น: `{fact}`")
        if f_base in known and known[f_base] != (not f_neg):
            steps.append(f"ตรวจพบข้อเท็จจริงตั้งต้นขัดแย้งกันเองที่ `{f_base}`")
            return {
                "engine": "causal_logic_native",
                "sub_type": "causal_forward_chain",
                "determined": False,
                "contradiction": True,
                "derived_conclusion": None,
                "conclusions": [],
                "steps": steps,
            }
        known[f_base] = not f_neg
        queue.append((f_base, f_neg))

    conclusions: list[str] = []
    seen_edges: set[tuple[tuple[str, bool], tuple[str, bool]]] = set()
    while queue:
        cur_state = queue.popleft()
        for nxt_base, nxt_neg, ant_disp, con_disp in adj.get(cur_state, []):
            edge_k = (cur_state, (nxt_base, nxt_neg))
            if edge_k in seen_edges:
                continue
            seen_edges.add(edge_k)
            expected_pol = not nxt_neg
            if nxt_base in known and known[nxt_base] != expected_pol:
                steps.append(f"ตรวจพบข้อขัดแย้งเชิงสาเหตุ: `{con_disp}` ขัดกับสถานะก่อนหน้าของ `{nxt_base}`")
                return {
                    "engine": "causal_logic_native",
                    "sub_type": "causal_forward_chain",
                    "determined": False,
                    "contradiction": True,
                    "derived_conclusion": None,
                    "conclusions": conclusions,
                    "steps": steps,
                }
            if nxt_base not in known:
                known[nxt_base] = expected_pol
                conclusions.append(con_disp)
                steps.append(f"อนุมานต่อเนื่อง (Modus Ponens): `{ant_disp}` ⇒ `{con_disp}`")
                queue.append((nxt_base, nxt_neg))

    if not conclusions:
        steps.append("ข้อเท็จจริงตั้งต้นไม่เข้าเงื่อนไขของกฎเหตุ-ผลที่มีอยู่")
        return {
            "engine": "causal_logic_native",
            "sub_type": "causal_forward_chain",
            "determined": False,
            "contradiction": False,
            "derived_conclusion": None,
            "conclusions": [],
            "steps": steps,
        }

    return {
        "engine": "causal_logic_native",
        "sub_type": "causal_forward_chain",
        "determined": True,
        "contradiction": False,
        "derived_conclusion": conclusions[-1],
        "conclusions": conclusions,
        "steps": steps,
    }


def _try_categorical_syllogism(prompt: str) -> dict[str, Any] | None:
    cleaned = prompt.strip()
    m_q = re.search(
        r"(?:ดังนั้น|สรุปว่า|ถามว่า|therefore|so)\s*,?\s*(.+?)\s*(?:หรือไม่|ใช่หรือไม่|ไหม|จริงหรือไม่|\?)*\s*$",
        cleaned,
        re.IGNORECASE,
    )
    if not m_q:
        return None
    premise_text = cleaned[: m_q.start()].strip()
    query_clause = _strip_clause(m_q.group(1))
    if not premise_text or not query_clause:
        return None

    # Parse query membership: "<target> เป็น/คือ/ต้อง/is/are <category>"
    qm = re.match(
        r"^(.+?)\s+(?:เป็น|คือ|ต้อง|จัดเป็น|มีสถานะ|is(?:\s+an?)?|are)\s+(.+)$",
        query_clause,
        re.IGNORECASE,
    )
    if not qm:
        return None
    q_subj = _strip_clause(qm.group(1))
    q_pred = _strip_clause(qm.group(2))
    if not q_subj or not q_pred:
        return None

    clauses = _split_clauses(premise_text)
    if len(clauses) < 2:
        return None

    isa_edges: dict[str, set[str]] = collections.defaultdict(set)  # sub_l -> set[super_l]
    disjoint_edges: dict[str, set[str]] = collections.defaultdict(set)  # class_l <-> negated class_l
    canon: dict[str, str] = {}
    steps: list[str] = []
    parsed_any_universal = False

    def _norm_cat(txt: str) -> str:
        t = _strip_clause(txt)
        t = re.sub(r"^(?:a|an|the|ทุก|ทั้งหมด)\s+", "", t, flags=re.IGNORECASE).strip()
        return t

    for cl in clauses:
        # Universal negative: "ไม่มี A เป็น B" / "No A is B"
        m_no = re.match(
            r"^(?:ไม่มี|ไม่พบ)\s*(.+?)\s*(?:เป็น|คือ|ต้อง|ใดๆ?\s*เป็น|ที่?เป็น)\s+(.+)$",
            cl,
            re.IGNORECASE,
        ) or re.match(r"^no\s+(.+?)\s+(?:is|are)\s+(.+)$", cl, re.IGNORECASE)
        if m_no:
            parsed_any_universal = True
            a_disp = _norm_cat(m_no.group(1))
            b_disp = _norm_cat(m_no.group(2))
            al, bl = a_disp.lower(), b_disp.lower()
            canon.setdefault(al, a_disp)
            canon.setdefault(bl, b_disp)
            disjoint_edges[al].add(bl)
            disjoint_edges[bl].add(al)
            steps.append(f"ข้อตั้งปฏิเสธสากล: `ไม่มี {a_disp} ที่เป็น {b_disp}`")
            continue

        # Universal affirmative: "ทุก A เป็น/คือ/ต้อง B" / "All A are B"
        m_all = re.match(
            r"^(?:ทุก(?:ๆ)?|ทั้งหมดของ|สิ่งที่เป็น)\s*(.+?)\s+(?:เป็น|คือ|ต้อง|จะ|ย่อมเป็น|ย่อม)\s+(.+)$",
            cl,
            re.IGNORECASE,
        ) or re.match(r"^(?:all|every)\s+(.+?)\s+(?:is|are|must\s+be)\s+(.+)$", cl, re.IGNORECASE)
        if m_all:
            parsed_any_universal = True
            a_disp = _norm_cat(m_all.group(1))
            b_disp = _norm_cat(m_all.group(2))
            al, bl = a_disp.lower(), b_disp.lower()
            canon.setdefault(al, a_disp)
            canon.setdefault(bl, b_disp)
            isa_edges[al].add(bl)
            steps.append(f"ข้อตั้งสากล: `ทุก {a_disp} ⊆ {b_disp}`")
            continue

        # Membership / instance fact: "X เป็น/คือ/ต้อง A" / "X is A"
        m_mem = re.match(
            r"^(.+?)\s+(?:ไม่เป็น|ไม่ใช่|ไม่ได้เป็น|is\s+not|are\s+not)\s+(.+)$",
            cl,
            re.IGNORECASE,
        )
        if m_mem:
            x_disp = _norm_cat(m_mem.group(1))
            a_disp = _norm_cat(m_mem.group(2))
            xl, al = x_disp.lower(), a_disp.lower()
            canon.setdefault(xl, x_disp)
            canon.setdefault(al, a_disp)
            disjoint_edges[xl].add(al)
            steps.append(f"ข้อเท็จจริงปฏิเสธ: `{x_disp} ∉ {a_disp}`")
            continue

        m_inst = re.match(
            r"^(.+?)\s+(?:เป็น|คือ|ต้อง|จัดเป็น|is(?:\s+an?)?|are)\s+(.+)$",
            cl,
            re.IGNORECASE,
        )
        if m_inst:
            x_disp = _norm_cat(m_inst.group(1))
            a_disp = _norm_cat(m_inst.group(2))
            xl, al = x_disp.lower(), a_disp.lower()
            canon.setdefault(xl, x_disp)
            canon.setdefault(al, a_disp)
            isa_edges[xl].add(al)
            steps.append(f"ข้อเท็จจริงสมาชิก: `{x_disp} ∈ {a_disp}`")
            continue

    if not parsed_any_universal:
        return None

    ql = _norm_cat(q_subj).lower()
    pl = _norm_cat(q_pred).lower()

    # BFS closure of all inherited superclasses of q_subj
    reachable: dict[str, list[str]] = {ql: [_norm_cat(q_subj)]}
    q = collections.deque([ql])
    while q:
        cur = q.popleft()
        for sup in isa_edges.get(cur, ()):
            if sup not in reachable:
                reachable[sup] = reachable[cur] + [canon.get(sup, sup)]
                q.append(sup)

    # Check contradictions across inherited classes
    for cls_a in reachable:
        for neg_b in disjoint_edges.get(cls_a, ()):
            if neg_b in reachable:
                steps.append(
                    f"ตรวจพบข้อขัดแย้งทางตรรกศาสตร์: `{q_subj}` สังกัดทั้ง `{canon.get(cls_a, cls_a)}` และขัดแย้งกับ `{canon.get(neg_b, neg_b)}`"
                )
                return {
                    "engine": "causal_logic_native",
                    "sub_type": "categorical_syllogism",
                    "determined": False,
                    "contradiction": True,
                    "derived_conclusion": None,
                    "steps": steps,
                }

    if pl in reachable:
        chain_str = " ⊆ ".join(reachable[pl])
        conclusion = f"{q_subj} เป็น {q_pred}"
        steps.append(f"อนุมานตรรกศาสตร์แบบ Syllogism: `{chain_str}` ⇒ ยืนยันว่า `{conclusion}`")
        return {
            "engine": "causal_logic_native",
            "sub_type": "categorical_syllogism",
            "determined": True,
            "contradiction": False,
            "verdict": "YES",
            "derived_conclusion": conclusion,
            "steps": steps,
        }

    # Check explicit universal negative exclusion
    for cls_a in reachable:
        if pl in disjoint_edges.get(cls_a, ()):
            conclusion = f"{q_subj} ไม่เป็น {q_pred}"
            steps.append(
                f"อนุมานการแยกกลุ่ม: `{q_subj} ∈ {canon.get(cls_a, cls_a)}` และไม่มี `{canon.get(cls_a, cls_a)}` ที่เป็น `{q_pred}` ⇒ `{conclusion}`"
            )
            return {
                "engine": "causal_logic_native",
                "sub_type": "categorical_syllogism",
                "determined": True,
                "contradiction": False,
                "verdict": "NO",
                "derived_conclusion": conclusion,
                "steps": steps,
            }

    steps.append(f"ไม่สามารถพิสูจน์จากข้อตั้งได้ว่า `{q_subj}` เป็น `{q_pred}` หรือไม่")
    return {
        "engine": "causal_logic_native",
        "sub_type": "categorical_syllogism",
        "determined": False,
        "contradiction": False,
        "verdict": "UNDETERMINED",
        "derived_conclusion": None,
        "steps": steps,
    }


def _try_kg_root_cause(prompt: str, conn: sqlite3.Connection | None) -> dict[str, Any] | None:
    if conn is None:
        return None
    cleaned = prompt.strip()
    m = re.match(
        r"^(?:สาเหตุ(?:ของ)?|ทำไม(?:เกิด)?|เหตุใด(?:จึงเกิด)?|root\s*cause(?:\s+of)?|what\s+causes)\s*:?\s*(.+?)\??$",
        cleaned,
        re.IGNORECASE,
    )
    if not m:
        return None
    target = _strip_clause(m.group(1))
    if not target:
        return None

    causal_rels = {"ทำให้เกิด", "ส่งผลให้", "ก่อให้เกิด", "นำไปสู่", "สาเหตุของ", "causes", "leads to"}
    rows = conn.execute("SELECT subject, relation, object, source FROM knowledge_triples").fetchall()
    rev_adj: dict[str, list[tuple[str, str, str]]] = collections.defaultdict(list)
    for r in rows:
        rel_l = r["relation"].strip().lower()
        if rel_l in causal_rels:
            rev_adj[r["object"].strip().lower()].append((r["subject"], r["relation"], r["source"]))

    t_l = target.lower()
    if t_l not in rev_adj:
        return None

    chains: list[str] = []
    root_causes: list[str] = []
    visited: set[str] = {t_l}
    q: collections.deque[tuple[str, list[str]]] = collections.deque([(t_l, [target])])
    while q:
        cur, path = q.popleft()
        parents = rev_adj.get(cur, [])
        if not parents and len(path) > 1:
            chains.append(" → ".join(reversed(path)))
            root_causes.append(path[-1])
            continue
        if len(path) >= 6:
            chains.append(" → ".join(reversed(path)))
            continue
        for subj, rel, _src in parents:
            sl = subj.lower()
            if sl not in visited:
                visited.add(sl)
                q.append((sl, path + [f"{subj} ({rel})"]))

    if not chains:
        return None

    return {
        "engine": "causal_logic_native",
        "sub_type": "kg_root_cause",
        "determined": True,
        "contradiction": False,
        "derived_conclusion": root_causes[0] if root_causes else chains[0],
        "root_causes": root_causes,
        "steps": [f"สายโซ่สาเหตุจากกราฟความรู้: {ch}" for ch in chains[:4]],
    }


def try_causal_logic_reasoning(prompt: str, conn: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    """Unified entrypoint for causal forward-chaining, categorical syllogisms, and KG root-cause tracing."""
    return (
        _try_causal_forward_chain(prompt)
        or _try_categorical_syllogism(prompt)
        or _try_kg_root_cause(prompt, conn)
    )
