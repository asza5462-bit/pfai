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
    if re.search(
        r"صلاحية\s*كاملة|بلا\s*اي\s*قيود|ذكاء\s*حر|راجع\s*كل|لا\s*يوجد\s*مشاكل|"
        r"تصحيح\s*نفس|تعديل\s*ال?اكواد|free\s*sovereign|integrity",
        text,
        re.I,
    ):
        intent = "free_sovereign"
        goals.append("zero_faults")
        goals.append("self_correcting_code")
        goals.append("full_productive_autonomy")
        strategy = "sovereign_audit_repair"
        latent = (
            "ذكاء حر سيّد يراجع ويصلح نفسه بلا أعطال — مع حدود صلبة للأمان"
            if ar else
            "free sovereign AI that audits/self-repairs with honest hard safety bounds"
        )
    elif re.search(
        r"كم[يّ]|quantum|جزء\s*من\s*مليون|microsecond|μs|\bus\b|سرعة\s*فائق|"
        r"إنترنت\s*الأشياء|انترنت\s*الاشياء|\biot\b|mqtt|zigbee|matter",
        text,
        re.I,
    ):
        intent = "quantum_iot_speed"
        goals.append("ultra_fast_local_core")
        goals.append("iot_comprehension")
        goals.append("continuous_evolution")
        strategy = "quantum_iot_evolve"
        latent = (
            "نواة سرعة حقيقية + فهم IoT + تطوّر كل دقيقة دون ادّعاء حاسوب كمّي زائف"
            if ar else
            "real ultra-fast core + IoT understanding + per-minute evolution without fake quantum hardware claims"
        )
    elif re.search(r"عقل\s*واحد|unified|سلاسة|سرعة", text, re.I):
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
    elif re.search(
        r"تدريب|training|continuous|تعل[يّ]م\s*مستمر|التعليم\s*المستمر|"
        r"التدريب\s*المستمر|lora|fine.?tun|تدرب|درّب|درب",
        text,
        re.I,
    ):
        intent = "train_learn"
        goals.append("real_weight_training")
        goals.append("continuous_capability")
        strategy = "start_real_training"
        if re.search(r"مستمر|continuous|24/?7|على\s*مدار|مدار\s*الساعة", text, re.I):
            latent = (
                "تعلّم وتدريب مستمران 24/7 بمراقب حي — عمل حقيقي بلا وهم"
                if ar else
                "24/7 continuous learn+train under a live monitor — real work, not theater"
            )
        else:
            latent = (
                "تشغيل تدريب LoRA حقيقي من الشات — ليس قراءة فقط وليس وهماً"
                if ar else
                "run real LoRA training from chat — not read-only, not simulated"
            )
    elif re.search(r"ذاكرة|memory|تذكر|remember|افهم|فهم", text, re.I):
        intent = "memory_mind"
        goals.append("legendary_recall")
        strategy = "memory_first_answer"
    elif re.search(
        r"تحكم|status|صحة|health|نظام|كيف\s*حال|وضع\s*ال?نظام|فحص",
        text,
        re.I,
    ):
        intent = "ops_status"
        goals.append("accurate_ops_picture")
        strategy = "snapshot_precision"
        latent = (
            "صورة تشغيلية دقيقة الآن من القلب الحي"
            if ar else
            "precise live operational picture from the heart"
        )

    # Goals / desires
    if re.search(r"أريد|اريد|أريدك|اريدك|I want|make it|طور|حسّن|حسن", text, re.I):
        goals.append("user_desire_stated")
    if re.search(r"يتفوق|أقوى|اقوا|أفضل|افضل|legendary|أسطور|خارق", text, re.I):
        goals.append("elite_quality_bar")
        emotion = "ambitious"
        latent = (
            "التفوق عبر ذاكرة أسطورية + فهم عميق + دقة بلا اختلاق"
            if ar else
            "surpass frontier chat quality via memory+understanding+precision"
        )
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
        (r"iot|أشياء|اشياء|mqtt", "iot"),
        (r"كم[يّ]|quantum", "quantum_inspired"),
    ]:
        if re.search(pat, text, re.I):
            entities.append(label)

    # Dialog continuity — inherit prior productive intent on أكمل/continue
    prior_user = [d.get("content") for d in (dialog or []) if d.get("role") == "user"][-4:]
    prior_assistant = [d.get("content") for d in (dialog or []) if d.get("role") == "assistant"][-2:]
    continue_cmd = bool(re.search(
        r"^(?:اكمل|أكمل|استمر|continue|go\s*on|keep\s*going|next)\s*[.!?؟]*$",
        text,
        re.I,
    ))
    if intent == "general" and (continue_cmd or (prior_user and len(text) < 24)):
        # Infer prior intent from recent user turns
        prior_blob = " ".join(str(x or "") for x in prior_user)
        inherited = ""
        if re.search(r"تدريب|training|continuous|تعل[يّ]م\s*مستمر|تدرب|lora", prior_blob, re.I):
            inherited = "train_learn"
        elif re.search(r"أصلح|طور\s*نفس|self.?improve|مراقب|sovereign|راجع\s*كل", prior_blob, re.I):
            inherited = "self_evolve"
        elif re.search(r"عقل\s*واحد|unified", prior_blob, re.I):
            inherited = "unify_system"
        if inherited:
            intent = inherited
            strategy = "continue_prior_intent"
            latent = _default_latent(inherited, lang)
        else:
            intent = "followup"
            strategy = "continue_thread"
            latent = latent or _default_latent("followup", lang)
    elif prior_user and intent == "general":
        intent = "followup"
        strategy = "continue_thread"
        latent = latent or _default_latent("followup", lang)

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
        "quantum_iot_speed": (
            "سرعة محلية مقاسة + IoT حقيقي + تطوّر مستمر (بدون كمّ زائف)",
            "measured local speed + real IoT + continuous evolution (no fake quantum)",
        ),
        "free_sovereign": (
            "مراجعة وإصلاح ذاتي كامل بصلاحية منتجة حرة",
            "full self-audit/repair with free productive authority",
        ),
        "self_evolve": ("ذكاء يطوّر نفسه بتحقق حقيقي", "self-improving intelligence with real verification"),
        "teach": ("تعلّم فعّال بخطوات واضحة", "effective learning with clear steps"),
        "research": ("حقائق موثوقة مع مصادر", "reliable facts with sources"),
        "train_learn": ("تدريب أوزان حقيقي LoRA من الشات", "real LoRA weight training from chat"),
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
