"""Deep comprehension — extract intent, goals, constraints, latent need.

Deterministic, fast, offline. Feeds planning + elite reply composition.
"""
from __future__ import annotations

import re
from typing import Any


def comprehend(
    message: str,
    *,
    dialog: list[dict] | None = None,
    memory_hints: str = "",
    language: str | None = None,
) -> dict[str, Any]:
    text = (message or "").strip()
    ar = bool(re.search(r"[\u0600-\u06FF]", text))
    lang = language or ("ar" if ar else "en")
    blob = text.lower()

    intent = "general"
    goals: list[str] = []
    constraints: list[str] = []
    entities: list[str] = []
    emotion = "neutral"
    latent = ""
    strategy = "direct_answer"

    # Intent taxonomy
    if re.search(r"عقل\s*واحد|unified|سلاسة|سرعة", text, re.I):
        intent = "unify_system"
        goals.append("coherent_fast_system")
        strategy = "unified_pulse"
    elif re.search(r"أصلح\s*نفس|طور\s*نفس|self[_\s-]?heal|self[_\s-]?improve|مرحلة\s*متطورة|يبني\s*ال?اكواد", text, re.I):
        intent = "self_evolve"
        goals.append("autonomous_improvement")
        strategy = "multi_pass_action"
    elif re.search(r"علمني|teach|تمرين|أكاديمية|python|javascript", text, re.I):
        intent = "teach"
        goals.append("skill_growth")
        strategy = "teach_then_exercise"
    elif re.search(r"ابحث|search|web|ويب|إنترنت", text, re.I):
        intent = "research"
        goals.append("grounded_web_facts")
        strategy = "cite_then_synthesize"
    elif re.search(r"تدريب|training|continuous|تعلم\s*مستمر", text, re.I):
        intent = "train_learn"
        goals.append("continuous_capability")
        strategy = "status_then_next_step"
    elif re.search(r"ذاكرة|memory|تذكر|remember|افهم|فهم", text, re.I):
        intent = "memory_mind"
        goals.append("legendary_recall")
        strategy = "memory_first_answer"
    elif re.search(r"تحكم|status|صحة|health|نظام", text, re.I):
        intent = "ops_status"
        goals.append("accurate_ops_picture")
        strategy = "snapshot_precision"

    # Goals / desires
    if re.search(r"أريد|اريد|أريدك|اريدك|I want|make it|طور|حسّن|حسن", text, re.I):
        goals.append("user_desire_stated")
    if re.search(r"يتفوق|أقوى|اقوا|أفضل|افضل|legendary|أسطور|خارق", text, re.I):
        goals.append("elite_quality_bar")
        emotion = "ambitious"
        latent = "surpass frontier chat quality via memory+understanding+precision"
    if re.search(r"بدون\s*قيود|بدون\s*ا?خطاء|بلا\s*تأخير", text, re.I):
        constraints.append("minimize_friction")
        constraints.append("honest_about_hard_bounds")

    # Entities (lightweight)
    for pat, label in [
        (r"\bpython\b|بايثون", "python"),
        (r"\bjavascript\b|جافاسكربت", "javascript"),
        (r"PFAI|pfai", "pfai"),
        (r"Render|رندر", "render"),
        (r"شات|chat", "chat"),
        (r"تدريب|training", "training"),
        (r"ذاكرة|memory", "memory"),
    ]:
        if re.search(pat, text, re.I):
            entities.append(label)

    # Dialog continuity
    prior_user = [d.get("content") for d in (dialog or []) if d.get("role") == "user"][-3:]
    prior_assistant = [d.get("content") for d in (dialog or []) if d.get("role") == "assistant"][-2:]
    if prior_user and intent == "general":
        intent = "followup"
        strategy = "continue_thread"
        latent = latent or "continue prior desire with higher precision"

    # Memory influence
    mem_used = bool(memory_hints and "no durable" not in memory_hints.lower())
    if mem_used:
        goals.append("honor_durable_memory")

    understanding = {
        "surface": text[:280],
        "intent": intent,
        "goals": goals[:8],
        "constraints": constraints[:6],
        "entities": entities[:8],
        "emotion": emotion,
        "latent_need": latent or _default_latent(intent, lang),
        "reply_strategy": strategy,
        "language": lang,
        "memory_loaded": mem_used,
        "thread_user_turns": len(prior_user),
        "confidence": 0.72 if intent != "general" else 0.55,
    }
    return understanding


def _default_latent(intent: str, lang: str) -> str:
    ar = lang.startswith("ar")
    mapping = {
        "unify_system": ("منظومة متماسكة سريعة بلا تشتيت", "coherent fast system without fragmentation"),
        "self_evolve": ("ذكاء يطوّر نفسه بتحقق حقيقي", "self-improving intelligence with real verification"),
        "teach": ("تعلّم فعّال بخطوات واضحة", "effective learning with clear steps"),
        "research": ("حقائق موثوقة مع مصادر", "reliable facts with sources"),
        "train_learn": ("تعلّم/تدريب مستمر دقيق", "precise continuous learning/training"),
        "memory_mind": ("فهم عميق + ذاكرة لا تنسى المهم", "deep understanding + memory that keeps what matters"),
        "ops_status": ("صورة تشغيلية دقيقة الآن", "precise live operational picture"),
        "followup": ("إكمال الطلب السابق بدقة أعلى", "continue prior request with higher precision"),
        "general": ("إجابة قوية مفهومة وعملية", "strong, clear, actionable answer"),
    }
    pair = mapping.get(intent, mapping["general"])
    return pair[0] if ar else pair[1]


def comprehension_block(u: dict[str, Any], *, language: str = "ar") -> str:
    ar = language.startswith("ar")
    if ar:
        return (
            f"الفهم: النية={u.get('intent')} · الحاجة الكامنة={u.get('latent_need')} · "
            f"الأهداف={', '.join(u.get('goals') or []) or '—'} · "
            f"الكيانات={', '.join(u.get('entities') or []) or '—'} · "
            f"استراتيجية الرد={u.get('reply_strategy')} · ثقة={u.get('confidence')}"
        )
    return (
        f"Understanding: intent={u.get('intent')} · latent={u.get('latent_need')} · "
        f"goals={', '.join(u.get('goals') or []) or '—'} · "
        f"entities={', '.join(u.get('entities') or []) or '—'} · "
        f"strategy={u.get('reply_strategy')} · conf={u.get('confidence')}"
    )
