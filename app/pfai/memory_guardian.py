"""Memory Guardian — conflict resolution, leak prevention, integrity audit.

Hard rules:
- Same subject+predicate with a new object ⇒ supersede old (no dual truths).
- Owner-scoped recall when owner is known (no cross-user bleed in public mode).
- Coding memories stay out of general legendary context unless coding query.
- Secrets never enter durable memory.
- Digests store user intent, not assistant boilerplate.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

SECRET_RE = re.compile(
    r"(?i)("
    r"(?:api[_-]?key|password|passwd|secret|token|bearer)\s*[:=]\s*\S+"
    r"|sk-[a-z0-9]{10,}"
    r"|ghp_[a-z0-9]{20,}"
    r"|(?:api[_-]?key|password|passwd|secret|token|bearer)"
    r")"
)

CODING_KIND_PREFIX = "coding_"

IDENTITY_PREDICATES = {
    "name_is", "named", "is_named", "الاسم",
}

CONFLICT_PREDICATES = IDENTITY_PREDICATES | {
    "desires", "prefers", "prefers_language", "timezone", "role",
}


def redact_secrets(text: str) -> tuple[str, bool]:
    raw = text or ""
    if not SECRET_RE.search(raw):
        return raw, False
    cleaned = SECRET_RE.sub("[REDACTED]", raw)
    return cleaned, True


def is_coding_kind(kind: str | None) -> bool:
    return str(kind or "").startswith(CODING_KIND_PREFIX)


def is_coding_query(query: str) -> bool:
    return bool(re.search(
        r"(?i)python|javascript|كود|coding|academy|تمرين|sandbox|درس|lesson|debug|bug",
        query or "",
    ))


def extract_identity_and_prefs(message: str) -> list[dict[str, Any]]:
    """Pull structured facts from a user turn (name, language, preferences)."""
    text = (message or "").strip()
    out: list[dict[str, Any]] = []
    if not text:
        return out

    # Name: اسمي X / my name is X — stop at connectors (و، وأنني، and, …)
    for pat, pred in (
        (r"(?:اسمي|اسمِي)\s+([^\n،,.!\s]{2,40})", "name_is"),
        (r"(?i)my\s+name\s+is\s+([^\n,!.\s]{2,40})", "name_is"),
        (r"(?:نادني|call\s+me)\s+([^\n،,.!\s]{2,40})", "name_is"),
    ):
        m = re.search(pat, text)
        if m:
            name = re.sub(r"\s+", " ", m.group(1)).strip(" .،,")
            # Trim trailing Arabic connective particles if glued
            name = re.split(r"(?:^و)|(?:وأنني)|(?:وأنا)|(?:\band\b)", name)[0].strip()
            if name and 1 < len(name) <= 40:
                out.append({
                    "subject": "user",
                    "predicate": pred,
                    "object": name,
                    "kind": "identity",
                    "confidence": 0.95,
                })
            break

    # Language preference
    if re.search(r"(?i)بالعربية|عربي(?:ة)?|arabic", text) and re.search(
        r"(?i)فضّل|prefer|أفضل|افضل|أرد|ارد|دائماً|always|مختصر", text
    ):
        out.append({
            "subject": "user",
            "predicate": "prefers_language",
            "object": "ar_concise" if re.search(r"مختصر|قصير|concise|short", text, re.I) else "ar",
            "kind": "preference",
            "confidence": 0.9,
        })
    if re.search(r"(?i)in\s+english|بالإنجليزية|بالانجليزية", text) and re.search(
        r"(?i)prefer|فضّل|أفضل|افضل", text
    ):
        out.append({
            "subject": "user",
            "predicate": "prefers_language",
            "object": "en",
            "kind": "preference",
            "confidence": 0.9,
        })

    return out


def find_fact_conflicts(facts: Iterable[dict]) -> list[dict]:
    """Group active facts that share subject+predicate with different objects."""
    buckets: dict[tuple[str, str], list[dict]] = {}
    for f in facts:
        if (f.get("status") or "active") != "active":
            continue
        key = (str(f.get("subject") or ""), str(f.get("predicate") or ""))
        if not key[0] or not key[1]:
            continue
        buckets.setdefault(key, []).append(f)
    conflicts = []
    for (subj, pred), rows in buckets.items():
        objects = {str(r.get("object") or "") for r in rows}
        if len(objects) > 1:
            conflicts.append({
                "subject": subj,
                "predicate": pred,
                "objects": sorted(objects),
                "ids": [r.get("id") for r in rows],
                "count": len(rows),
            })
    return conflicts


def pick_winner_fact(rows: list[dict]) -> dict | None:
    """Prefer highest confidence, then newest last_seen/id."""
    if not rows:
        return None
    return sorted(
        rows,
        key=lambda r: (
            float(r.get("confidence") or 0),
            str(r.get("last_seen") or ""),
            int(r.get("id") or 0),
        ),
        reverse=True,
    )[0]


def filter_durable_for_context(rows: list[dict], query: str) -> list[dict]:
    """Drop coding noise from general legendary context; keep corrections/identity."""
    coding_q = is_coding_query(query)
    out = []
    for r in rows:
        kind = str(r.get("kind") or "")
        if is_coding_kind(kind) and not coding_q:
            continue
        out.append(r)
    return out


def digest_from_dialog(dialog: list[dict], *, max_chars: int = 1400) -> str:
    """Compress dialog without assistant template spam."""
    bits: list[str] = []
    for m in dialog[-16:]:
        role = (m.get("role") or "?").strip()
        content = re.sub(r"\s+", " ", (m.get("content") or "")).strip()
        if not content:
            continue
        if role == "assistant":
            # Keep only a short non-template gist
            content = _assistant_gist(content)
            if not content:
                continue
            bits.append(f"assistant: {content[:160]}")
        else:
            bits.append(f"{role}: {content[:280]}")
    digest = " | ".join(bits)
    return digest[:max_chars]


def _assistant_gist(text: str) -> str:
    t = text or ""
    # Strip known elite template prefixes
    t = re.sub(r"^(فهمتك\.|Understood\.)\s*", "", t.strip())
    t = re.sub(r"(?m)^(ما تريده في العمق:|You want:|الفهم:|Understanding:|من الذاكرة الأسطورية:|From legendary memory:|من الواقع الحي الآن:|Live findings:|الخطوة التالية:|Next:).*$", "", t)
    t = re.sub(r"(?m)^أبقى دقيقاً:.*$", "", t)
    t = re.sub(r"(?m)^I stay precise:.*$", "", t)
    t = re.sub(r"\s+", " ", t).strip(" ·|-")
    # Prefer a concrete memory answer line if present
    m = re.search(r"(?:اسمك|your name|أتذكر|I remember)[^\n.]{0,120}", t, re.I)
    if m:
        return m.group(0).strip()[:160]
    return t[:160]


def answer_from_facts(facts: list[dict], query: str, *, language: str = "ar") -> str | None:
    """Direct, conflict-free answer for identity/preference questions."""
    ar = language.startswith("ar")
    q = query or ""
    active = [f for f in facts if (f.get("status") or "active") == "active"]
    if not active:
        return None

    # Name questions
    if re.search(r"(?i)ما\s*اسمي|من\s*أنا|what(?:'s|\s+is)\s+my\s+name|who\s+am\s+i", q):
        names = [f for f in active if f.get("predicate") in IDENTITY_PREDICATES]
        winner = pick_winner_fact(names)
        if winner:
            name = winner.get("object")
            return f"اسمك الذي أتذكره هو: {name}." if ar else f"Your name on record is: {name}."

    # Preference / language
    if re.search(r"(?i)ماذا\s*أفضل|ما\s*تفضيلي|what\s+do\s+i\s+prefer|my\s+preference", q):
        prefs = [f for f in active if str(f.get("predicate") or "").startswith("prefer")]
        if prefs:
            lines = []
            # Collapse by predicate
            by_pred: dict[str, list] = {}
            for p in prefs:
                by_pred.setdefault(str(p.get("predicate")), []).append(p)
            for pred, rows in by_pred.items():
                w = pick_winner_fact(rows)
                if w:
                    lines.append(f"{pred} → {w.get('object')}")
            if lines:
                body = "؛ ".join(lines)
                return (f"تفضيلاتك المسجّلة: {body}." if ar else f"Your recorded preferences: {body}.")
    return None


def integrity_report(
    *,
    facts: list[dict],
    durable: list[dict],
    owner: str = "",
) -> dict[str, Any]:
    conflicts = find_fact_conflicts(facts)
    dup_content = {}
    for d in durable:
        key = (d.get("kind"), (d.get("content") or "").strip())
        dup_content[key] = dup_content.get(key, 0) + 1
    duplicates = [
        {"kind": k[0], "content": (k[1] or "")[:120], "count": n}
        for k, n in dup_content.items() if n > 1 and k[1]
    ]
    secret_hits = [
        {"id": d.get("id"), "kind": d.get("kind")}
        for d in durable
        if SECRET_RE.search(d.get("content") or "")
    ]
    coding_bleed = [
        {"id": d.get("id"), "kind": d.get("kind"), "content": (d.get("content") or "")[:80]}
        for d in durable if is_coding_kind(d.get("kind"))
    ]
    return {
        "ok": not conflicts and not secret_hits,
        "owner_scope": owner or "(global)",
        "active_facts": len([f for f in facts if (f.get("status") or "active") == "active"]),
        "conflicts": conflicts,
        "duplicates": duplicates[:20],
        "secret_hits": secret_hits[:20],
        "coding_rows": len(coding_bleed),
        "note": (
            "Conflicts are same subject+predicate with multiple objects. "
            "Guardian supersede keeps only the winner."
        ),
    }
