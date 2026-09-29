"""Elite natural reply composer — human answers, no JSON/debug fog.

Used by MockCommandProvider when Anthropic is unavailable, and by CommandAgent
short-circuit paths (identity remember / name recall).
"""
from __future__ import annotations

import json
import re
from typing import Any


def is_name_question(message: str) -> bool:
    return bool(re.search(
        r"(?i)ما\s*اسمي|من\s*أنا|what(?:'s|\s+is)\s+my\s+name|who\s+am\s+i",
        message or "",
    ))


def is_remember_turn(message: str) -> bool:
    return bool(re.search(
        r"(?i)\bremember\b|تذكّر|تذكر|احفظ\s*هذا|احفظ\s*أن|نادني|اسمي\s|my\s+name\s+is|call\s+me",
        message or "",
    ))


def empty_name_reply(language: str = "ar") -> str:
    if (language or "").startswith("en"):
        return (
            "I don't have your name stored yet. "
            "Tell me once — for example: my name is Fahad — and I'll remember it precisely."
        )
    return (
        "ما عندي اسمك محفوظاً بعد. "
        "قل لي مرة واحدة بوضوح — مثال: اسمي فهد — وأثبته في الذاكرة بدقة."
    )


def remember_confirm_reply(
    *,
    language: str,
    facts_stored: list[dict[str, Any]] | None = None,
    message: str = "",
) -> str:
    """Short confirmation after legendary ingest captured identity/prefs."""
    en = (language or "").startswith("en")
    name = None
    prefs: list[str] = []
    for f in facts_stored or []:
        pred = str(f.get("predicate") or "")
        obj = str(f.get("object") or "").strip()
        if pred in {"name_is", "named", "is_named", "الاسم"} and obj:
            name = obj
        elif pred.startswith("prefer") and obj:
            prefs.append(obj)
    if not name:
        # Fallback parse from message
        m = re.search(r"(?:اسمي|اسمِي)(?:\s+هو)?\s+([^\n،,.!\s]{2,40})", message or "")
        if not m:
            m = re.search(r"(?i)my\s+name\s+is\s+([^\n,!.\s]{2,40})", message or "")
        if m:
            name = m.group(1).strip(" .،,")
    if en:
        parts = []
        if name:
            parts.append(f"Got it — I'll remember your name as {name}.")
        else:
            parts.append("Saved. I'll keep that in legendary memory.")
        if prefs:
            parts.append("Preference noted: " + "; ".join(prefs[:2]) + ".")
        parts.append("Ask me anything — I'll answer from what I know, not invent.")
        return " ".join(parts)
    parts = []
    if name:
        parts.append(f"تم — اسمك عندي الآن: {name}.")
    else:
        parts.append("تم الحفظ في الذاكرة الأسطورية.")
    if prefs:
        parts.append("سجّلت تفضيلك: " + "؛ ".join(prefs[:2]) + ".")
    parts.append("اسألني مباشرة — أجيب مما أعرفه بدقة، بلا اختراع.")
    return " ".join(parts)


def memory_direct_reply(language: str, direct: str) -> str:
    """Conflict-free identity/preference answer — clean, no template fog."""
    en = (language or "").startswith("en")
    d = (direct or "").strip()
    if not d:
        return empty_name_reply(language)
    if en:
        return f"{d} If anything changed, just tell me and I'll update it."
    return f"{d} إذا تغيّر شيء، قل لي وأحدّث الذاكرة فوراً."


def _brief_text(obj: Any, limit: int = 220) -> str:
    if obj is None:
        return ""
    if isinstance(obj, str):
        s = re.sub(r"\s+", " ", obj).strip()
        return s if len(s) <= limit else s[: limit - 1] + "…"
    if isinstance(obj, (int, float, bool)):
        return str(obj)
    try:
        s = json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        s = str(obj)
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= limit else s[: limit - 1] + "…"


def humanize_tool(name: str, res: Any, *, en: bool) -> str | None:
    """Turn a tool result into one natural sentence. Skip audit/debug noise."""
    if name in {"memory_status", "memory_audit", "memory_search", "memory_heal"}:
        # Never dump JSON audits into the user-facing reply body.
        if not isinstance(res, dict):
            return None
        if name == "memory_heal":
            n = res.get("superseded") or 0
            if en:
                return f"Memory heal finished — superseded {n} conflicting fact(s)."
            return f"أتممت إصلاح الذاكرة — استبدلت {n} حقيقة متعارضة."
        if name == "memory_search":
            rows = res.get("results") or res.get("hits") or []
            n = len(rows) if isinstance(rows, list) else 0
            if en:
                return f"Memory search returned {n} hit(s)."
            return f"بحث الذاكرة أعاد {n} نتيجة."
        facts = res.get("active_facts")
        if facts is None and isinstance(res.get("audit"), dict):
            facts = res["audit"].get("active_facts")
        if facts is not None:
            if en:
                return f"Legendary memory holds {facts} active fact(s)."
            return f"الذاكرة الأسطورية تحتفظ بـ {facts} حقيقة نشطة."
        return None

    if not isinstance(res, dict):
        return f"{name}: {_brief_text(res, 120)}" if res not in (None, "") else None

    if name == "unified_brain_pulse":
        snap = res.get("snapshot") or res
        health = (snap.get("health") if isinstance(snap, dict) else None) or res.get("ok")
        ms = res.get("elapsed_ms")
        if en:
            return f"One-mind pulse OK (health={health}" + (f", {ms}ms" if ms is not None else "") + ")."
        return f"نبضة العقل الواحد سليمة (الصحة={health}" + (f"، {ms}ms" if ms is not None else "") + ")."

    if name == "app_control_status":
        ver = res.get("version") or "?"
        if en:
            return f"App control online — version {ver}."
        return f"التحكم بالتطبيق يعمل — الإصدار {ver}."

    if name in {"web_search", "web_research"}:
        n = len(res.get("results") or res.get("citations") or [])
        ans = res.get("answer") or res.get("summary")
        if ans:
            return _brief_text(ans, 280)
        if en:
            return f"Live web returned {n} source(s)."
        return f"الويب الحي أعاد {n} مصدر."

    if name == "quantum_pulse":
        hyp = (res.get("collapsed") or {}).get("hypothesis") if isinstance(res.get("collapsed"), dict) else None
        t = res.get("timing") or {}
        us = t.get("elapsed_us")
        if en:
            return f"Quantum route collapsed" + (f" → {hyp}" if hyp else "") + (f" in {us}µs" if us is not None else "") + "."
        return f"المسار الكمّي اكتمل" + (f" → {hyp}" if hyp else "") + (f" خلال {us}µs" if us is not None else "") + "."

    if name == "iot_understand":
        ans = res.get("answer")
        if ans:
            return _brief_text(ans, 260)
        cards = res.get("cards") or []
        titles = [c.get("title") for c in cards[:3] if isinstance(c, dict)]
        if titles:
            return ("IoT: " if en else "IoT: ") + " · ".join(str(x) for x in titles)
        return None

    if name == "evolution_status":
        if en:
            return (
                f"Evolution alive={res.get('alive')} · "
                f"minute={res.get('minute_ticks')} hour={res.get('hour_ticks')} day={res.get('day_ticks')}."
            )
        return (
            f"التطور يعمل={res.get('alive')} · "
            f"دقيقة={res.get('minute_ticks')} ساعة={res.get('hour_ticks')} يوم={res.get('day_ticks')}."
        )

    if name in {"smart_training_start", "training_cycle_start"}:
        cy = res.get("cycle") or res
        executed = cy.get("actual_training_executed") or res.get("actual_training_executed")
        status = cy.get("status") or res.get("status")
        if en:
            return f"Training {'executed' if executed else 'queued'} — status {status}."
        return f"التدريب {'نُفّذ فعلياً' if executed else 'في الطابور'} — الحالة {status}."

    if name in {"free_sovereign_cycle", "free_sovereign_repair", "free_sovereign_audit"}:
        improved = res.get("improved")
        if en:
            return f"Sovereign integrity cycle done" + (" — improvements applied." if improved else ".")
        return f"اكتملت دورة السيادة والسلامة" + (" — طُبّقت تحسينات." if improved else ".")

    if name == "free_ai_status":
        fr = res.get("freedom") or {}
        unlocked = len([x for x in (fr.get("unlocked_productive") or []) if x])
        if en:
            return f"Free AI status: {unlocked} productive lane(s) unlocked; weight promotion stays gated."
        return f"حالة الذكاء الحر: {unlocked} مسار منتج مفتوح؛ ترقية الأوزان تبقى مشروطة."

    if name in {"advanced_self_develop", "self_improve_tick"}:
        stage = res.get("stage") or (res.get("maturity") or {}).get("stage")
        if en:
            return f"Self-develop tick — stage {stage or '?'}."
        return f"نبضة التطوير الذاتي — المرحلة {stage or '؟'}."

    if name == "coding_teach":
        lesson = res.get("lesson_title") or res.get("title") or res.get("lesson_id")
        if en:
            return f"Teaching ready" + (f": {lesson}." if lesson else ".")
        return f"الدرس جاهز" + (f": {lesson}." if lesson else ".")

    if name in {"health_check", "system_status"}:
        ok = res.get("ok", res.get("status"))
        if en:
            return f"System check: {ok}."
        return f"فحص النظام: {ok}."

    if name in {"continuous_status", "smart_continuous_status"}:
        alive = res.get("worker_alive") or res.get("real_loop")
        pending = res.get("pending_examples")
        svc = (res.get("service") or {}).get("status") if isinstance(res.get("service"), dict) else res.get("service")
        if en:
            return (
                f"Continuous learn {'ALIVE 24/7' if alive else 'DOWN'} "
                f"(service={svc or '?'}, pending={pending})."
            )
        return (
            f"التعلّم المستمر {'يعمل 24/7' if alive else 'متوقف'} "
            f"(الخدمة={svc or '؟'}، معلّق={pending})."
        )

    if name == "continuous_start":
        alive = res.get("worker_alive")
        if en:
            return f"Continuous worker started — alive={alive}."
        return f"شغّلت عامل التعلّم المستمر — حي={alive}."

    if name == "continuous_tick":
        cy = res.get("cycle") or res
        if en:
            return f"Continuous tick done — cycle ok={cy.get('ok', res.get('ok'))}."
        return f"نفّذت دورة تعلّم مستمر — نجاح={cy.get('ok', res.get('ok'))}."

    if name in {"live_monitor_status", "live_monitor_pulse"}:
        if name == "live_monitor_status" and hasattr(res, "get"):
            alive = res.get("alive")
            pulses = res.get("pulses")
            cont = res.get("continuous") or {}
            if en:
                return (
                    f"Live monitor {'RUNNING' if alive else 'DOWN'} · pulses={pulses} · "
                    f"continuous_worker={cont.get('worker_alive')}."
                )
            return (
                f"المراقب الحي {'يعمل' if alive else 'متوقف'} · نبضات={pulses} · "
                f"عامل_مستمر={cont.get('worker_alive')}."
            )
        # pulse summary
        train = res.get("training") or {}
        if en:
            return (
                f"Live monitor pulse ok — continuous={res.get('continuous_alive')} · "
                f"evolution={res.get('evolution_alive')} · "
                f"train_triggered={train.get('triggered')} "
                f"(weights never auto-promoted)."
            )
        return (
            f"نبضة المراقب الحي تمت — مستمر={res.get('continuous_alive')} · "
            f"تطوّر={res.get('evolution_alive')} · "
            f"تدريب_مُشغَّل={train.get('triggered')} "
            f"(ترقية الأوزان لا تتم صامتة)."
        )

    if name in {"smart_training_status", "training_eligibility"}:
        elig = res.get("eligible")
        if elig is None and isinstance(res.get("eligibility"), dict):
            elig = res["eligibility"].get("eligible")
        status = res.get("status") or (res.get("last") or {}).get("status")
        if en:
            return f"Training eligibility={'YES' if elig else 'NO'}" + (f" · status {status}." if status else ".")
        return f"أهلية التدريب={'نعم' if elig else 'لا'}" + (f" · الحالة {status}." if status else ".")

    # Generic: prefer answer/message fields over raw JSON
    for key in ("answer", "message", "summary", "detail", "status"):
        if res.get(key) and not isinstance(res.get(key), (dict, list)):
            return f"{name}: {_brief_text(res.get(key), 160)}"
    return None  # skip opaque blobs


def compose_elite(
    message: str,
    tool_results: list[dict],
    memory_context: str,
    *,
    language: str = "ar",
    understanding: dict | None = None,
) -> str:
    """Frontier-style natural reply from understanding + memory + live tools."""
    en = (language or "").startswith("en")
    u = understanding or {}
    intent = u.get("intent") or "general"
    latent = (u.get("latent_need") or "").strip()

    ok = [t for t in tool_results if t.get("ok")]
    pending = [t for t in tool_results if t.get("needs_approval")]
    failed = [t for t in tool_results if not t.get("ok") and not t.get("needs_approval")]

    # Extract DirectAnswer + short fact lines from memory context
    direct_answer = ""
    mem_bits: list[str] = []
    if memory_context and "no durable" not in memory_context.lower():
        for line in (memory_context or "").splitlines():
            line = line.strip()
            if line.startswith("DirectAnswer:"):
                direct_answer = line.split(":", 1)[-1].strip()
            elif line.startswith("- (") and "→" in line:
                # (- (user) name_is → فهد) → natural
                m = re.match(r"-\s*\(([^)]+)\)\s+(\S+)\s*→\s*(.+)", line)
                if m:
                    pred, obj = m.group(2), m.group(3).strip()
                    if pred in {"name_is", "named", "is_named"}:
                        mem_bits.append(("اسمك: " if not en else "Your name: ") + obj)
                    else:
                        mem_bits.append(f"{pred}: {obj}")
                else:
                    mem_bits.append(line[:160])
            if len(mem_bits) >= 4:
                break

    if direct_answer and intent in {"memory_mind", "followup", "general"}:
        return memory_direct_reply(language, direct_answer)

    if is_name_question(message) and not direct_answer:
        return empty_name_reply(language)

    insights: list[str] = []
    for t in ok:
        name = t.get("tool") or "?"
        res = t.get("result") if isinstance(t.get("result"), dict) else t.get("result")
        line = humanize_tool(name, res, en=en)
        if line:
            insights.append(line)

    # Intent-specific lead
    lead = _lead_for_intent(intent, latent, message, en=en)

    parts: list[str] = [lead] if lead else []
    if mem_bits:
        if en:
            parts.append("From what I remember: " + " · ".join(mem_bits[:4]) + ".")
        else:
            parts.append("مما أتذكره: " + " · ".join(mem_bits[:4]) + ".")
    if insights:
        parts.extend(insights[:5])
    if pending:
        parts.append(
            "A sensitive action still needs your approval."
            if en else
            "ما زال إجراء حسّاس بانتظار موافقتك."
        )
    if failed and not insights:
        parts.append(
            "One live lane degraded — answering from memory and remaining signals."
            if en else
            "مسار حيّ تدهور — أجيب من الذاكرة والإشارات المتبقية."
        )

    next_line = _next_move(intent, en=en)
    if next_line and intent not in {"general", "followup"}:
        parts.append(next_line)

    # Guarantee substance
    body = "\n".join(p for p in parts if p and str(p).strip())
    if not body.strip():
        return (
            "I'm with you — say the exact outcome you want and I'll execute it precisely."
            if en else
            "أنا معك — حدّد النتيجة التي تريدها بدقة وأنفّذها بلا لفّ."
        )
    return body


def _lead_for_intent(intent: str, latent: str, message: str, *, en: bool) -> str:
    if intent == "memory_mind":
        if en:
            return "I'll keep what matters and answer from verified memory — nothing invented."
        return "سأحتفظ بما يهم وأجيب من ذاكرة موثّقة — بلا اختراع."
    if intent == "train_learn":
        if re.search(r"مستمر|continuous|24/?7|مدار|مراقب", message or "", re.I):
            if en:
                return "Continuous learn+train is supervised 24/7 by the live monitor — real ticks, real LoRA when eligible."
            return "التعلّم والتدريب المستمران تحت المراقب الحي 24/7 — دورات حقيقية وLoRA عند الأهلية."
        if en:
            return "Real training path is open from chat — LoRA runs when eligible, never silent weight promotion."
        return "مسار التدريب الحقيقي مفتوح من الشات — LoRA يعمل عند الأهلية، بلا ترقية أوزان صامتة."
    if intent == "free_sovereign":
        if en:
            return "Full integrity review: audit, repair productive lanes, keep hard safety bounds."
        return "مراجعة سيادة كاملة: تدقيق، إصلاح المسارات المنتجة، مع حدود السلامة الصلبة."
    if intent == "self_evolve":
        if en:
            return "Self-develop engaged — I'll improve carefully and report what actually changed."
        return "التطوير الذاتي مفعّل — أحسّن بحذر وأبلّغ بما تغيّر فعلاً."
    if intent == "quantum_iot_speed":
        if en:
            return "Ultra-fast quantum-inspired + IoT mind path ready."
        return "مسار السرعة الكمّية المستوحاة + عقل IoT جاهز."
    if intent == "unify_system":
        if en:
            return "One mind, parallel lanes — coherence over noise."
        return "عقل واحد ومسارات متوازية — تماسك بدل ضوضاء."
    if intent == "teach":
        if en:
            return "Teaching mode — clear steps, real checks, no fluff."
        return "وضع التعليم — خطوات واضحة وفحص حقيقي بلا حشو."
    if intent == "research":
        if en:
            return "Live research — I'll cite what the web actually returns."
        return "بحث حي — أستند إلى ما يعيده الويب فعلاً."
    if intent == "ops_status":
        if en:
            return "Ops pulse — real status only."
        return "نبضة التشغيل — حالة حقيقية فقط."
    if intent == "followup":
        # Never echo English boilerplate into Arabic replies
        if latent and not re.search(r"continue prior|higher precision", latent, re.I):
            return (f"Continuing — {latent}." if en else f"نكمل — {latent}.")
        return ("Continuing the productive loop now." if en else "نكمل الحلقة الإنتاجية الآن.")
    # general — answer the ask, don't dump internals
    if latent and latent not in {"general help", "مساعدة عامة"}:
        if not en and re.search(r"[A-Za-z]{4,}", latent) and not re.search(r"[\u0600-\u06FF]", latent):
            return "فهمت — أنفّذ بدقة."
        return (f"Understood — {latent}." if en else f"فهمت — {latent}.")
    return ("Understood." if en else "فهمت.")


def _next_move(intent: str, *, en: bool) -> str:
    moves = {
        "unify_system": ("اطلب نبضة عقل واحد إن أردت إعادة التزامن.", "Ask for a unified pulse to resync."),
        "quantum_iot_speed": ("اطلب سؤالاً أدق عن MQTT/Zigbee أو نبضة كمّية.", "Ask a sharper MQTT/Zigbee question or a quantum pulse."),
        "free_sovereign": ("قل «راجع كل شيء» لتشغيل دورة السيادة الآن.", "Say “audit everything” to run the sovereign cycle now."),
        "self_evolve": ("قل «طوّر نفسك» لنبضة تطوير ذاتي.", "Say “self-develop” for a self-improve tick."),
        "teach": ("اختر درساً أو أرسل حلاً للتحقق.", "Pick a lesson or submit a solution to verify."),
        "research": ("ضيّق سؤال البحث بجملة واحدة.", "Narrow the research question to one sentence."),
        "train_learn": (
            "قل «أكمل» لنبضة مراقب أخرى، أو «ابدأ التدريب» لـ LoRA فوري.",
            "Say “continue” for another monitor pulse, or “start training” for immediate LoRA.",
        ),
        "memory_mind": ("قل ما تريدني أن أتذكره بوضوح.", "Tell me clearly what to remember."),
        "ops_status": ("اطلب التحكم الكامل أو نبضة العقل.", "Ask for master control or a brain pulse."),
    }
    pair = moves.get(intent)
    if not pair:
        return ""
    return pair[1] if en else pair[0]
