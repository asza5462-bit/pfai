"""Deterministic Mock provider for Command Chat when Anthropic is unavailable.

Never claims to be Claude. Used for offline UI/agent/tool tests without secrets.
Produces structured, analytical operator replies from real tool results.
"""
from __future__ import annotations

import json
import re
from .model import ModelProvider


class MockCommandProvider(ModelProvider):
    """Rule/heuristic planner + high-signal reply composer for development and tests."""

    name = "mock-command"

    def generate(self, prompt: str, **kwargs) -> str:
        # Used only as a fallback composer; planning uses plan_tools().
        return (
            "[PFAI-MOCK] I can inspect system health, metrics, continuous status, "
            "academy progress, training eligibility, memory, and execute open tools. "
            f"Prompt summary: {prompt[:180]}"
        )

    def plan_tools(self, message: str, allowed_tools: list[str]) -> list[dict]:
        text = (message or "").strip().lower()
        ar = message or ""
        allowed = set(allowed_tools)
        picks: list[str] = []

        def add(name: str):
            if name in allowed and name not in picks:
                picks.append(name)

        web_intent = bool(re.search(
            r"ابحث\s*في\s*(الويب|الانترنت|الإنترنت)|search\s*(the\s*)?web|web\s*search|"
            r"web\s*research|deep\s*research|بحث\s*ويب|بحث\s*عميق|من\s*الإنترنت|"
            r"from\s*the\s*internet|look\s*up\s*online|on\s*the\s*web|"
            r"fetch\s*url|افتح\s*الرابط|https?://|web\s*status|حالة\s*الويب",
            text + ar,
            re.I,
        ))

        if re.search(
            r"كم[يّ]|quantum|جزء\s*من\s*مليون|microsecond|سرعة\s*فائق|"
            r"إنترنت\s*الأشياء|انترنت\s*الاشياء|\biot\b|mqtt|zigbee|matter|"
            r"يتطور\s*كل|تطور\s*كل\s*دقيقة|evolution\s*cadence",
            text + ar,
            re.I,
        ):
            add("quantum_pulse")
            add("iot_understand")
            add("evolution_status")
            add("quantum_status")
        if re.search(
            r"ابدأ\s*التدريب|شغ[ّل]\s*التدريب|درّب|درب\s*الان|run\s*training|"
            r"training_cycle|smart_training|تدريب\s*حقيقي|تدريب\s*فعلي|"
            r"ليس\s*وهم|بلا\s*حدود.*تدريب|تدريب.*بلا\s*حدود",
            text + ar,
            re.I,
        ):
            add("smart_training_start")
            add("training_cycle_start")
            add("smart_training_status")
            add("training_eligibility")
        elif re.search(
            r"eligib|أهلية|حالة\s*التدريب|training\s*status|جاهزية\s*التدريب|"
            r"هل\s*(التدريب|النموذج)|next\s*training|can\s*we\s*train|متى\s*نتدرب",
            text + ar,
            re.I,
        ):
            add("training_eligibility")
            add("smart_training_status")
            add("training_control_status")
            add("smart_training_start")
        elif re.search(r"continuous|تعلم\s*مستمر|continuous\s*learning", text + ar):
            add("continuous_status")
        elif re.search(r"\btraining\b|تدريب\s*النموذج|تدريب\s*النماذج|التدريب", text + ar):
            add("smart_training_start")
            add("training_cycle_start")
            add("smart_training_status")
            add("training_eligibility")
        if re.search(r"health|صح[ةه]|فحص.*صح", text + ar):
            add("health_check")
        if re.search(r"system|حال[ةه].*نظام|حل[ل].*نظام|status|حل[ل]\s*النظام", text + ar) and not web_intent:
            add("system_status")
        if re.search(r"metric|مؤشر|أخطاء|error|fail", text + ar) and not web_intent:
            add("metrics_snapshot")
            if "system_status" in allowed:
                add("system_status")
        if re.search(r"module|وحدات|مكون", text + ar):
            add("modules_list")
        if re.search(r"deploy|نشر", text + ar):
            add("deployments_list")
        if re.search(r"recover|استرداد", text + ar):
            add("recovery_verify")
        # Live web — one primary tool path (avoid stacking research+search+coding)
        if web_intent:
            add("web_status")
            if re.search(r"fetch|url|رابط|https?://", text + ar, re.I) and not re.search(r"ابحث|search|research", text + ar, re.I):
                add("web_fetch")
            elif re.search(r"web\s*status|حالة\s*الويب|internet\s*status", text + ar, re.I) and not re.search(r"ابحث|search|research", text + ar, re.I):
                pass  # status only
            elif re.search(r"research|بحث\s*عميق|تحليل\s*ويب|deep\s*research|synthesize", text + ar, re.I):
                add("web_research")
            else:
                # Simple "search the web" → fast search path (no page fetch pipeline)
                add("web_search")
        elif re.search(r"research_verify|ledger\s*research", text + ar, re.I):
            add("research_verify")
        if re.search(r"regression|انحدار", text + ar):
            add("regression_pending")
        if re.search(r"audit|تدقيق", text + ar):
            add("chat_audit_recent")
        if re.search(r"improv|تحسين|اقترح", text + ar):
            add("propose_improvement")
        if re.search(
            r"ال?تحكم\s*ال?كامل|master\s*control|حالة\s*التطبيق|app\s*control|لوحة\s*التحكم\s*ال?كاملة",
            text + ar,
            re.I,
        ):
            add("app_control_status")
            add("system_status")
            add("continuous_status")
            add("web_status")
        # Coding academy — skip when this turn is a web/internet request
        if not web_intent:
            if re.search(r"علمني|teach|learn|مبتدئ|تمرين|python|javascript|مسار\s*تعليمي|أكاديمية", text + ar):
                add("coding_teach")
                add("coding_tracks")
            if re.search(r"اختبر مستواي|assess|assessment", text + ar):
                add("coding_assess")
            if re.search(r"راجع.*كود|code review|review code", text + ar):
                add("coding_review")
            if re.search(r"مشروع|project", text + ar):
                add("coding_projects")
            if re.search(r"sandbox|نفذ الكود|run code", text + ar):
                add("run_sandbox")
            if re.search(r"تلميح|hint", text + ar, re.I):
                add("coding_hint")
            if re.search(r"أرسل الحل|submit (my )?(code|solution)|تحقق من حلي|submit_exercise", text + ar, re.I):
                add("coding_exercise_submit")
            if re.search(r"الدرس\s*التالي|next\s*lesson|تمرين\s*التالي", text + ar):
                add("coding_next_lesson")
                add("coding_progress")
            if re.search(r"تقدمي|learner\s*snapshot|لوحة\s*التعلم|skill\s*profile|مهاراتي", text + ar):
                add("learner_snapshot")
                add("coding_progress")
        if re.search(r"search knowledge|ابحث.*معرف|راجع.*بيانات|بيانات", text + ar) and not web_intent:
            add("knowledge_search")
            add("memory_search")
        if re.search(
            r"تدريب\s*مستمر|تدريب\s*بذكاء|بدون\s*قيود|فهم\s*عالي|تركيز\s*عالي|"
            r"دقيق\s*جدا|smart\s*continuous|high.?precision\s*train|continuous\s*without",
            text + ar,
            re.I,
        ):
            add("continuous_start")
            add("continuous_tick")
            add("smart_continuous_status")
            add("continuous_status")
        if re.search(r"start continuous|شغ[لّ].*تعلم|تشغيل.*continuous|ابدأ\s*التعلم\s*المستمر", text + ar):
            add("continuous_start")
            add("continuous_status")
            add("continuous_tick")
            add("smart_continuous_status")
        if re.search(r"tick continuous|دورة\s*تعلم|continuous\s*tick|نفّذ\s*دورة", text + ar):
            add("continuous_tick")
            add("continuous_status")
            add("smart_continuous_status")
        if re.search(r"smart\s*continuous|حالة\s*التدريب\s*الذكي|precision\s*train", text + ar, re.I):
            add("smart_continuous_status")
            add("continuous_status")
        if re.search(
            r"start\s*training\s*cycle|training_cycle|ابدأ\s*دورة\s*التدريب|شغّل\s*التدريب|run\s*training",
            text + ar,
            re.I,
        ):
            add("smart_training_start")
            add("training_cycle_start")
            add("training_eligibility")
        if re.search(r"stop continuous|أوقف.*تعلم|ايقاف.*تعلم", text + ar):
            add("continuous_stop")
        if re.search(r"resume continuous|استأنف.*تعلم", text + ar):
            add("continuous_resume")
        if re.search(r"pause continuous|إيقاف\s*مؤقت|ايقاف\s*مؤقت", text + ar):
            add("continuous_pause")
        if re.search(r"remember|احفظ|حفظ.*(معرف|تفضيل|قرار)", text + ar):
            add("remember_knowledge")
        if re.search(r"forget|انسَ|انسى|احذف.*ذاكر", text + ar):
            add("forget_memory")
        if re.search(r"correct|تصحيح|هذا التحليل غير صحيح", text + ar):
            add("save_owner_correction")
        # Legendary memory / deep understanding asks
        if re.search(
            r"ذاكرة\s*أسطور|legendary\s*memory|تذكر\s*هذا|احفظ\s*هذا|افهمني|فهم\s*عالي|"
            r"يتفوق|أقوى\s*الذكاء|memory\s*first|what\s*do\s*you\s*remember|"
            r"تعارض.*ذاكر|تسريب.*ذاكر|memory\s*audit|memory\s*heal|أصلح\s*(?:ال)?ذاكر|"
            r"افحص.*ذاكر|ذاكرة|ما\s*اسمي|ماذا\s*أفضل",
            text + ar,
            re.I,
        ):
            add("memory_status")
            add("memory_audit")
            add("memory_search")
            if re.search(r"أصلح|heal|تعارض|تسريب|conflict|افحص", text + ar, re.I):
                add("memory_heal")
        # Unified one-mind asks — single pulse (speed + coherence)
        elif re.search(
            r"عقل\s*واحد|unified\s*brain|كل\s*شيء\s*يعمل|سلاسة|سرعة\s*متناه|"
            r"بدون\s*ا?خطاء|بدون\s*تأخير|ذكاء\s*خارق|قوة\s*و\s*دقة|طوره|وطوره|"
            r"و\s*طوره|super\s*brain|one\s*mind",
            text + ar,
            re.I,
        ):
            add("unified_brain_pulse")
        # Free sovereign / full integrity review
        if re.search(
            r"راجع\s*كل|لا\s*يوجد\s*مشاكل|لا\s*بد\s*ان\s*لا\s*يوجد|"
            r"صلاحية\s*كاملة|بلا\s*اي\s*قيود|ذكاء\s*حر|free\s*sovereign|"
            r"تصحيح\s*نفس|تعديل\s*ال?اكواد|اعطال|متضارب|فحص\s*ذاتي|"
            r"free_ai|sovereign_cycle|integrity\s*audit",
            text + ar,
            re.I,
        ):
            add("free_sovereign_cycle")
            add("free_ai_status")
            add("self_heal_cycle")
            add("self_check_run")
            add("advanced_self_develop")
        if re.search(
            r"أصلح\s*نفس|صلح\s*نفس|self[_\s-]?heal|self[_\s-]?check|self[_\s-]?improve|"
            r"طور\s*نفس|حدّث\s*نفس|حدث\s*نفس|يطور\s*نفس|يصلح\s*نفس|يحل\s*مشاكل|"
            r"استقلال|autonom|فك\s*القيود|بدون\s*قيود|طور\s*ذات|تحسين\s*ذاتي|"
            r"يبني\s*ال?اكواد|يبني\s*الأكواد|self[_\s-]?develop|advanced_self|"
            r"يراجع\s*اكثر|يصحح\s*اكثر|واعي|بدون\s*الرجوع|مرحلة\s*متطورة|"
            r"شغ[ّل]\s*فحص|إصلاح\s*آمن|اصلاح\s*امن",
            text + ar,
            re.I,
        ):
            add("self_check_run")
            add("self_heal_cycle")
            add("advanced_awareness")
            add("advanced_status")
            add("advanced_self_develop")
            add("autonomy_status")
            add("self_improve_tick")
            add("free_sovereign_cycle")
            add("unified_brain_pulse")

        if not picks:
            add("unified_brain_pulse")
            add("app_control_status")
            add("system_status")
            add("learner_snapshot")

        tools = []
        for name in picks:
            args: dict = {}
            if name in {"knowledge_search", "memory_search"}:
                args = {"q": message, "limit": 8}
            if name in {"web_search", "web_research"}:
                args = {"query": message, "limit": 5}
            if name == "web_fetch":
                m = re.search(r"https?://\S+", message or "")
                args = {"url": m.group(0) if m else ""}
            if name == "propose_improvement":
                args = {"topic": message}
            if name == "remember_knowledge":
                args = {"kind": "approved_knowledge", "content": message}
            if name == "save_owner_correction":
                args = {"content": message}
            if name == "chat_audit_recent":
                args = {"limit": 20}
            if name == "coding_teach":
                args = {"track_id": "python", "goal": message}
            if name == "coding_next_lesson":
                args = {"track_id": "python"}
            if name == "coding_hint":
                args = {"track_id": "python"}
            if name == "coding_exercise_submit":
                code_m = re.search(r"```(?:python)?\n([\s\S]*?)```", message or "")
                args = {
                    "track_id": "python",
                    "lesson_id": "py-intro",
                    "code": (code_m.group(1) if code_m else message),
                }
            if name == "learner_snapshot":
                args = {}
            if name == "unified_brain_pulse":
                act = "status"
                if re.search(r"طور|develop|build|ibn|ابن", message or "", re.I):
                    act = "auto"
                elif re.search(r"أصلح|heal|improve|صلح", message or "", re.I):
                    act = "improve"
                args = {"action": act, "message": message, "include_action": act != "status"}
            if name in {"quantum_pulse", "quantum_hot_route", "iot_understand"}:
                args = {"message": message, "language": "ar" if re.search(r"[\u0600-\u06FF]", message or "") else "en"}
                if name != "iot_understand":
                    args.pop("language", None)
            if name == "evolution_tick":
                args = {"kind": "minute"}
            tools.append({"tool": name, "args": args})
        return tools

    def compose_reply(
        self,
        message: str,
        tool_results: list[dict],
        memory_context: str,
        language: str = "ar",
        understanding: dict | None = None,
    ) -> str:
        """Elite reply: understanding → memory → live findings → next move."""
        from .deep_comprehension import comprehend, comprehension_block

        ok = [t for t in tool_results if t.get("ok")]
        pending = [t for t in tool_results if t.get("needs_approval")]
        failed = [t for t in tool_results if not t.get("ok") and not t.get("needs_approval")]
        en = language.startswith("en")
        u = understanding or comprehend(message, memory_hints=memory_context or "", language=language)

        def _brief(obj, limit=360):
            try:
                s = json.dumps(obj, ensure_ascii=False, default=str)
            except Exception:
                s = str(obj)
            s = re.sub(r"\s+", " ", s).strip()
            return s if len(s) <= limit else s[: limit - 1] + "…"

        insights: list[str] = []
        for t in ok:
            name = t.get("tool") or "?"
            res = t.get("result") if isinstance(t.get("result"), dict) else t.get("result")
            if name == "unified_brain_pulse" and isinstance(res, dict):
                insights.append(("unified " if en else "العقل الواحد ") + _brief(res.get("snapshot") or res, 280))
            elif name == "app_control_status" and isinstance(res, dict):
                insights.append(("ops " if en else "التشغيل ") + _brief({
                    "version": res.get("version"), "continuous": res.get("continuous"),
                    "advanced": res.get("advanced"), "web": res.get("web"),
                }, 260))
            elif name in {"web_search", "web_research"} and isinstance(res, dict):
                n = len(res.get("results") or res.get("citations") or [])
                insights.append(f"web hits={n} status={res.get('WEB_FABRIC_STATUS') or res.get('error')}")
            elif name == "quantum_pulse" and isinstance(res, dict):
                t = res.get("timing") or {}
                insights.append(_brief({
                    "collapsed": (res.get("collapsed") or {}).get("hypothesis"),
                    "us": t.get("elapsed_us"), "band": t.get("target_band"),
                    "quantum_hardware": res.get("quantum_hardware"),
                }, 220))
            elif name == "iot_understand" and isinstance(res, dict):
                cards = res.get("cards") or []
                insights.append(("IoT: " if en else "IoT: ") + (res.get("answer") or _brief({
                    "confidence": res.get("confidence"), "cards": [c.get("title") for c in cards[:3]],
                }, 260))[:260])
            elif name == "evolution_status" and isinstance(res, dict):
                insights.append(_brief({
                    "alive": res.get("alive"), "minute": res.get("minute_ticks"),
                    "hour": res.get("hour_ticks"), "day": res.get("day_ticks"),
                }, 180))
            elif name in {"smart_training_start", "training_cycle_start"} and isinstance(res, dict):
                cy = res.get("cycle") or res
                insights.append(_brief({
                    "executed": cy.get("actual_training_executed") or res.get("actual_training_executed"),
                    "status": cy.get("status") or res.get("status"),
                    "reason": cy.get("reason") or res.get("reason"),
                    "read_only": res.get("read_only"),
                }, 220))
            elif name in {"free_sovereign_cycle", "free_sovereign_repair", "free_sovereign_audit"} and isinstance(res, dict):
                insights.append(_brief({
                    "ok": res.get("ok"), "improved": res.get("improved"),
                    "after": res.get("after"), "schema": (res.get("schema") or {}).get("current"),
                    "failures": ((res.get("after") or res.get("self_check") or {}).get("failures")),
                }, 260))
            elif name == "free_ai_status" and isinstance(res, dict):
                fr = (res.get("freedom") or {})
                insights.append(_brief({
                    "unlocked": len([x for x in (fr.get("unlocked_productive") or []) if x]),
                    "gated": fr.get("still_hard_gated"),
                    "weight_promotion": res.get("weight_promotion"),
                }, 220))
            elif name in {"advanced_self_develop", "self_improve_tick"} and isinstance(res, dict):
                insights.append(_brief({
                    "stage": res.get("stage") or (res.get("maturity") or {}).get("stage"),
                    "ran": res.get("ran"), "solved": (res.get("build") or {}).get("solved"),
                    "check_ok": res.get("check_ok"),
                }, 220))
            elif name == "coding_teach" and isinstance(res, dict):
                insights.append(("teach: " if en else "تعليم: ") + _brief(res, 220))
            elif isinstance(res, dict):
                insights.append(f"{name}: {_brief(res, 160)}")
            else:
                insights.append(f"{name}: {_brief(res, 120)}")

        mem_lines = []
        direct_answer = ""
        if memory_context and "no durable" not in memory_context.lower():
            for line in (memory_context or "").splitlines():
                line = line.strip()
                if line.startswith("DirectAnswer:"):
                    direct_answer = line.split(":", 1)[-1].strip()
                if line.startswith("-") or line.startswith("Thread") or line.startswith("Facts"):
                    mem_lines.append(line[:200])
                if len(mem_lines) >= 5:
                    break

        latent = u.get("latent_need") or ""
        intent = u.get("intent") or "general"
        # Memory-first: if we already have a conflict-free direct answer, lead with it.
        if direct_answer and intent in {"memory_mind", "followup", "general"}:
            if en:
                return "\n".join([
                    "From legendary memory (no conflicts):",
                    direct_answer,
                    *(["Supporting facts:", *[f"  {x}" for x in mem_lines[:4]]] if mem_lines else []),
                    "Tell me what else to remember or correct.",
                ])
            return "\n".join([
                "من الذاكرة الأسطورية (بدون تعارض):",
                direct_answer,
                *(["حقائق داعمة:", *[f"  {x}" for x in mem_lines[:4]]] if mem_lines else []),
                "قل لي ماذا أتذكر أيضاً أو ما الذي أصحّحه.",
            ])
        next_move = {
            "unify_system": ("اطلب نبضة عقل واحد أو راقب اللوحة الحية.", "Ask for a unified pulse or watch the live board."),
            "quantum_iot_speed": (
                "اطلب quantum_pulse أو سؤال MQTT/Zigbee — التطور يعمل كل دقيقة.",
                "Ask for quantum_pulse or an MQTT/Zigbee question — evolution ticks every minute.",
            ),
            "free_sovereign": (
                "اطلب free_sovereign_cycle لمراجعة وإصلاح كل شيء الآن.",
                "Ask for free_sovereign_cycle to audit and repair everything now.",
            ),
            "self_evolve": ("شغّل التطوير الذاتي المتقدم الآن.", "Run advanced self-develop now."),
            "teach": ("ابدأ درساً أو سلّم تمريناً للتحقق.", "Start a lesson or submit an exercise to verify."),
            "research": ("حدّد سؤالاً أدق للبحث الحي.", "Narrow the live research question."),
            "train_learn": ("شغّل smart_training_start الآن — تدريب حقيقي LoRA من الشات.", "Run smart_training_start now — real LoRA from chat."),
            "memory_mind": ("قل ما تريدني أن أتذكره للأبد.", "Tell me what to remember forever."),
            "ops_status": ("اطلب التحكم الكامل أو نبضة العقل.", "Ask for master control or a brain pulse."),
        }.get(intent, ("قل الخطوة التالية التي تريدها بدقة.", "State the exact next step you want."))
        nm = next_move[0] if not en else next_move[1]

        if en:
            parts = [
                "Understood.",
                f"You want: {latent}",
                comprehension_block(u, language="en"),
            ]
            if mem_lines:
                parts.append("From legendary memory:")
                parts.extend(f"  {x}" for x in mem_lines[:5])
            if insights:
                parts.append("Live findings:")
                parts.extend(f"• {x}" for x in insights[:8])
            if pending:
                parts.append("A sensitive action still awaits approval.")
            if failed and not insights:
                parts.append("Some tools degraded — answering from memory + remaining live lanes.")
            parts.append(f"Next: {nm}")
            parts.append("I stay precise: no invented metrics, no silent weight promotion.")
            return "\n".join(parts)

        parts = [
            "فهمتك.",
            f"ما تريده في العمق: {latent}",
            comprehension_block(u, language="ar"),
        ]
        if mem_lines:
            parts.append("من الذاكرة الأسطورية:")
            parts.extend(f"  {x}" for x in mem_lines[:5])
        if insights:
            parts.append("من الواقع الحي الآن:")
            parts.extend(f"• {x}" for x in insights[:8])
        if pending:
            parts.append("ما زال إجراء حسّاس بانتظار الموافقة.")
        if failed and not insights:
            parts.append("بعض المسارات تدهورت — أجيب من الذاكرة والمسارات الحية المتبقية.")
        parts.append(f"الخطوة التالية: {nm}")
        parts.append("أبقى دقيقاً: لا اختراع لمؤشرات، ولا ترقية أوزان صامتة.")
        return "\n".join(parts)
