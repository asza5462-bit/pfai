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
            r"web\s*research|بحث\s*ويب|من\s*الإنترنت|from\s*the\s*internet|look\s*up\s*online|"
            r"fetch\s*url|افتح\s*الرابط|https?://|web\s*status|حالة\s*الويب",
            text + ar,
            re.I,
        ))

        if re.search(
            r"eligib|أهلية|حالة\s*التدريب|training\s*status|جاهزية\s*التدريب|"
            r"هل\s*(التدريب|النموذج)|next\s*training|can\s*we\s*train|متى\s*نتدرب",
            text + ar,
            re.I,
        ):
            add("training_eligibility")
            add("training_control_status")
        elif re.search(r"continuous|تعلم\s*مستمر|continuous\s*learning", text + ar):
            add("continuous_status")
        elif re.search(r"\btraining\b|تدريب\s*النموذج|تدريب\s*النماذج", text + ar):
            add("training_control_status")
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
            r"تحكم\s*كامل|master\s*control|حالة\s*التطبيق|app\s*control|لوحة\s*التحكم\s*الكاملة",
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
        if re.search(r"start continuous|شغ[لّ].*تعلم|تشغيل.*continuous|ابدأ\s*التعلم\s*المستمر", text + ar):
            add("continuous_start")
            add("continuous_status")
            add("continuous_tick")
        if re.search(r"tick continuous|دورة\s*تعلم|continuous\s*tick|نفّذ\s*دورة", text + ar):
            add("continuous_tick")
            add("continuous_status")
        if re.search(
            r"start\s*training\s*cycle|training_cycle|ابدأ\s*دورة\s*التدريب|شغّل\s*التدريب|run\s*training",
            text + ar,
            re.I,
        ):
            add("training_eligibility")
            add("training_cycle_start")
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

        if not picks:
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
            tools.append({"tool": name, "args": args})
        return tools

    def compose_reply(self, message: str, tool_results: list[dict], memory_context: str, language: str = "ar") -> str:
        ok = [t for t in tool_results if t.get("ok")]
        pending = [t for t in tool_results if t.get("needs_approval")]
        failed = [t for t in tool_results if not t.get("ok") and not t.get("needs_approval")]
        en = language.startswith("en")

        def _brief(obj, limit=420):
            try:
                s = json.dumps(obj, ensure_ascii=False, default=str)
            except Exception:
                s = str(obj)
            s = re.sub(r"\s+", " ", s).strip()
            return s if len(s) <= limit else s[: limit - 1] + "…"

        insights: list[str] = []
        for t in ok:
            name = t.get("tool") or "?"
            res = t.get("result")
            if name == "health_check":
                st = (res or {}).get("status") if isinstance(res, dict) else res
                insights.append(f"health={st}" if en else f"الصحة={st}")
            elif name == "system_status" and isinstance(res, dict):
                h = (res.get("health") or {}).get("status") if isinstance(res.get("health"), dict) else res.get("health")
                insights.append(f"system health={h}" if en else f"حالة النظام={h}")
            elif name == "metrics_snapshot" and isinstance(res, dict):
                insights.append(("metrics: " if en else "المؤشرات: ") + _brief(res, 220))
            elif name == "training_eligibility" and isinstance(res, dict):
                elig = res.get("eligible")
                insights.append(
                    f"training eligible={elig} (use training_cycle_start; no silent promote)"
                    if en else
                    f"أهلية التدريب={elig} (استخدم training_cycle_start — بدون تفعيل صامت)"
                )
            elif name in {"web_search", "web_research"} and isinstance(res, dict):
                n = len(res.get("results") or res.get("citations") or [])
                st = res.get("WEB_FABRIC_STATUS") or ("ok" if res.get("ok") else res.get("error"))
                insights.append(
                    f"web {name}: status={st} hits={n} fabricated={res.get('fabricated_results')}"
                    if en else
                    f"الويب {name}: حالة={st} نتائج={n} ملفّق={res.get('fabricated_results')}"
                )
            elif name == "web_fetch" and isinstance(res, dict):
                insights.append(("web fetch: " if en else "جلب ويب: ") + _brief(res, 220))
            elif name == "web_status" and isinstance(res, dict):
                insights.append(f"WEB_FABRIC_STATUS={res.get('WEB_FABRIC_STATUS')}")
            elif name == "coding_exercise_submit" and isinstance(res, dict):
                insights.append(
                    f"exercise {'PASSED' if res.get('passed') else 'FAILED'} · {res.get('teaching') or res.get('message') or ''}"
                )
            elif name == "coding_hint" and isinstance(res, dict):
                insights.append(f"hint L{res.get('level')}: {(res.get('hint') or res.get('message') or '')[:160]}")
            elif name == "app_control_status" and isinstance(res, dict):
                insights.append(("master control: " if en else "التحكم الكامل: ") + _brief({
                    "version": res.get("version"),
                    "continuous": res.get("continuous"),
                    "web": res.get("web"),
                }, 260))
            elif name == "training_control_status" and isinstance(res, dict):
                insights.append(("training control: " if en else "مركز التدريب: ") + _brief({
                    "paused": res.get("paused"),
                    "autonomous_enabled": res.get("autonomous_enabled"),
                    "can_start_from_chat": res.get("can_start_from_chat"),
                }, 200))
            elif name == "learner_snapshot" and isinstance(res, dict):
                prof = res.get("profile") or {}
                insights.append(
                    f"academy level={prof.get('display_level')} mode={prof.get('mode')} done={prof.get('completed_lessons')}"
                    if en else
                    f"الأكاديمية مستوى={prof.get('display_level')} وضع={prof.get('mode')} دروس={prof.get('completed_lessons')}"
                )
            elif name == "continuous_status" and isinstance(res, dict):
                insights.append(("continuous: " if en else "التعلم المستمر: ") + _brief(res, 220))
            elif name in {"continuous_start", "continuous_resume", "continuous_pause", "continuous_stop"}:
                insights.append(f"{name} → {_brief(res, 160)}")
            elif name in {"coding_teach", "coding_tracks", "coding_progress", "coding_next_lesson", "coding_assess"}:
                insights.append(f"{name}: {_brief(res, 240)}")
            elif name in {"remember_knowledge", "save_owner_correction", "correct_memory", "forget_memory"}:
                insights.append(f"{name}: {_brief(res, 160)}")
            else:
                insights.append(f"{name}: {_brief(res, 180)}")

        if en:
            parts = [
                "PFAI Advanced Brain — analytical summary from live tools:",
            ]
            if insights:
                parts.append("Findings:")
                parts.extend(f"• {x}" for x in insights[:10])
            if ok:
                parts.append("Executed: " + ", ".join(t.get("tool", "?") for t in ok) + ".")
            if pending:
                parts.append("Sensitive action(s) still await approval (locked mode).")
            if failed:
                parts.append("Some tools failed — see timeline for detail.")
            if memory_context and "no durable" not in memory_context.lower():
                parts.append("Durable memory considered: " + memory_context[:220])
            parts.append(
                "Education & training: academy tools teach; eligibility is read-only; "
                "model promotion never auto-starts from chat."
            )
            return "\n".join(parts)

        parts = ["عقل PFAI المتقدم — ملخص تحليلي من أدوات حية:"]
        if insights:
            parts.append("النتائج:")
            parts.extend(f"• {x}" for x in insights[:10])
        if ok:
            parts.append("الأدوات المنفذة: " + ", ".join(t.get("tool", "?") for t in ok))
        if pending:
            parts.append("ما زال هناك إجراء بانتظار الموافقة (وضع الأقفال).")
        if failed:
            parts.append("بعض الأدوات فشلت — راجع المخطط الزمني.")
        if memory_context and "no durable" not in memory_context.lower():
            parts.append("تم أخذ الذاكرة الدائمة بالاعتبار.")
        parts.append(
            "التعليم والتدريب: أدوات الأكاديمية تعلّم؛ الأهلية للقراءة فقط؛ "
            "ترقية أوزان النموذج لا تبدأ تلقائيًا من الشات."
        )
        return "\n".join(parts)
