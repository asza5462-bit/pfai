"""Local elite brain provider for Command Chat when Anthropic is unavailable.

Never claims to be Claude. Used for offline UI/agent/tool tests without secrets.
Plans real tools and composes natural, precise replies from live results.
"""
from __future__ import annotations

import re
from .model import ModelProvider


class MockCommandProvider(ModelProvider):
    """Rule/heuristic planner + elite natural reply composer."""

    name = "pfai-brain"

    def generate(self, prompt: str, **kwargs) -> str:
        # Used only as a fallback composer; planning uses plan_tools().
        return (
            "[PFAI Brain] I inspect health, training, memory, and execute open tools with precision. "
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
        # Continuous 24/7 first — must beat bare "هل التدريب" eligibility branch
        early_continuous = bool(re.search(
            r"ال?تدريب\s*ال?مستمر|ال?تعل[يّ]م\s*ال?مستمر|continuous\s*(training|learning)|"
            r"على\s*مدار\s*ال?ساعة|24/?7|مراقب\s*حي|live\s*monitor",
            text + ar,
            re.I,
        ))
        if early_continuous:
            add("live_monitor_pulse")
            add("continuous_start")
            add("continuous_tick")
            add("live_monitor_status")
            add("continuous_status")
            add("smart_continuous_status")
            add("evolution_status")
        elif re.search(
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
            add("continuous_start")
            add("live_monitor_pulse")
        elif re.search(
            r"eligib|أهلية|حالة\s*التدريب(?!\s*ال?مستمر)|training\s*status|جاهزية\s*التدريب|"
            r"هل\s*(?:ال)?(?:تدريب|نموذج)(?!\s*ال?مستمر)|next\s*training|can\s*we\s*train|متى\s*نتدرب",
            text + ar,
            re.I,
        ):
            add("training_eligibility")
            add("smart_training_status")
            add("training_control_status")
            add("smart_training_start")
        elif re.search(r"continuous|تعلم\s*مستمر|continuous\s*learning", text + ar):
            add("continuous_status")
            add("live_monitor_status")
            add("continuous_start")
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
        # Continuous learn/train 24/7 — match الـdefinite article forms
        continuous_ask = bool(re.search(
            r"ال?تدريب\s*ال?مستمر|ال?تعل[يّ]م\s*ال?مستمر|continuous\s*(training|learning)|"
            r"تدريب\s*بذكاء|smart\s*continuous|high.?precision\s*train|"
            r"على\s*مدار\s*ال?ساعة|24/?7|مراقب\s*حي|live\s*monitor|"
            r"هل\s*(?:ال)?تدريب|هل\s*(?:ال)?تعل[يّ]م",
            text + ar,
            re.I,
        ))
        if continuous_ask:
            add("live_monitor_pulse")
            add("continuous_start")
            add("continuous_tick")
            add("live_monitor_status")
            add("continuous_status")
            add("smart_continuous_status")
            add("evolution_status")
        if re.search(r"start continuous|شغ[لّ].*تعلم|تشغيل.*continuous|ابدأ\s*ال?تعلم\s*ال?مستمر", text + ar):
            add("continuous_start")
            add("live_monitor_pulse")
            add("continuous_status")
            add("continuous_tick")
            add("smart_continuous_status")
        if re.search(r"tick continuous|دورة\s*تعلم|continuous\s*tick|نفّذ\s*دورة", text + ar):
            add("continuous_tick")
            add("continuous_status")
            add("smart_continuous_status")
        if re.search(r"smart\s*continuous|حالة\s*ال?تدريب\s*ال?ذكي|precision\s*train", text + ar, re.I):
            add("smart_continuous_status")
            add("continuous_status")
            add("live_monitor_status")
        if re.search(
            r"start\s*training\s*cycle|training_cycle|ابدأ\s*دورة\s*ال?تدريب|شغّل\s*ال?تدريب|"
            r"run\s*training|ابدأ\s*ال?تدريب|تدرب|درّب|درب\s*على|تدرب\s*على",
            text + ar,
            re.I,
        ):
            add("smart_training_start")
            add("continuous_start")
            add("live_monitor_pulse")
            add("training_cycle_start")
            add("training_eligibility")
        # Continue / أكمل — keep productive loops moving
        if re.search(r"^(?:اكمل|أكمل|استمر|continue|go\s*on|keep\s*going)\b", text + ar, re.I):
            add("live_monitor_pulse")
            add("continuous_tick")
            add("smart_training_start")
            add("evolution_tick")
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
        # Legendary memory — audit/heal only when explicitly asked; simple
        # name/preference recall is answered from facts (no JSON dump tools).
        mem_audit = bool(re.search(
            r"تعارض.*ذاكر|تسريب.*ذاكر|memory\s*audit|memory\s*heal|أصلح\s*(?:ال)?ذاكر|"
            r"افحص.*ذاكر|تدقيق\s*(?:ال)?ذاكر|سلامة\s*(?:ال)?ذاكر",
            text + ar,
            re.I,
        ))
        mem_ask = bool(re.search(
            r"ذاكرة\s*أسطور|legendary\s*memory|تذكر\s*هذا|احفظ\s*هذا|افهمني|فهم\s*عالي|"
            r"يتفوق|أقوى\s*الذكاء|memory\s*first|what\s*do\s*you\s*remember|"
            r"ماذا\s*تذكر|ما\s*الذي\s*تتذكر|ذاكرة",
            text + ar,
            re.I,
        ))
        if mem_audit:
            add("memory_heal")
            add("memory_audit")
            add("memory_status")
            add("memory_search")
        elif mem_ask:
            add("memory_search")
            add("memory_status")
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
            if name == "live_monitor_pulse":
                args = {"deep": bool(re.search(r"عميق|deep|أصلح|طور|sovereign", message or "", re.I))}
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
        """Elite natural reply — no JSON dumps, no comprehension fog."""
        from .deep_comprehension import comprehend
        from .elite_reply import compose_elite

        u = understanding or comprehend(message, memory_hints=memory_context or "", language=language)
        return compose_elite(
            message,
            tool_results,
            memory_context,
            language=language,
            understanding=u,
        )
