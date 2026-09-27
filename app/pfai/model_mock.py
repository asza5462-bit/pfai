"""Deterministic Mock provider for Command Chat when Anthropic is unavailable.

Never claims to be Claude. Used for offline UI/agent/tool tests without secrets.
"""
from __future__ import annotations

import json
import re
from .model import ModelProvider


class MockCommandProvider(ModelProvider):
    """Rule/heuristic planner + reply composer for development and tests."""

    name = "mock-command"

    def generate(self, prompt: str, **kwargs) -> str:
        # Used only as a fallback composer; planning uses plan_tools().
        return (
            "[PFAI-MOCK] I can inspect system health, metrics, continuous status, "
            "memory, and request owner approval for sensitive actions. "
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

        # bilingual keyword routing
        if re.search(r"health|صح[ةه]|فحص.*صح", text + ar):
            add("health_check")
        if re.search(r"system|حال[ةه].*نظام|حل[ل].*نظام|status", text + ar):
            add("system_status")
        if re.search(r"metric|مؤشر|أخطاء|error|fail", text + ar):
            add("metrics_snapshot")
            if "system_status" in allowed:
                add("system_status")
        if re.search(r"module|وحدات|مكون", text + ar):
            add("modules_list")
        if re.search(r"continuous|تعلم|training|تدريب", text + ar):
            add("continuous_status")
        if re.search(r"deploy|نشر", text + ar):
            add("deployments_list")
        if re.search(r"recover|استرداد", text + ar):
            add("recovery_verify")
        if re.search(r"research|بحث", text + ar):
            add("research_verify")
        if re.search(r"regression|انحدار", text + ar):
            add("regression_pending")
        if re.search(r"audit|تدقيق", text + ar):
            add("chat_audit_recent")
        if re.search(r"improv|تحسين|اقترح", text + ar):
            add("propose_improvement")
        if re.search(r"search knowledge|ابحث.*معرف|راجع.*بيانات|بيانات", text + ar):
            add("knowledge_search")
            add("memory_search")
        if re.search(r"start continuous|شغ[لّ].*تعلم|تشغيل.*continuous", text + ar):
            add("continuous_start")
        if re.search(r"stop continuous|أوقف.*تعلم|ايقاف.*تعلم", text + ar):
            add("continuous_stop")
        if re.search(r"remember|احفظ|حفظ.*(معرف|تفضيل|قرار)", text + ar):
            add("remember_knowledge")
        if re.search(r"forget|انسَ|انسى|احذف.*ذاكر", text + ar):
            add("forget_memory")
        if re.search(r"correct|تصحيح|هذا التحليل غير صحيح", text + ar):
            add("save_owner_correction")

        if not picks:
            add("system_status")

        tools = []
        for name in picks:
            args: dict = {}
            if name in {"knowledge_search", "memory_search"}:
                args = {"q": message, "limit": 5}
            if name == "propose_improvement":
                args = {"topic": message}
            if name == "remember_knowledge":
                args = {"kind": "approved_knowledge", "content": message}
            if name == "save_owner_correction":
                args = {"content": message}
            if name == "chat_audit_recent":
                args = {"limit": 20}
            tools.append({"tool": name, "args": args})
        return tools

    def compose_reply(self, message: str, tool_results: list[dict], memory_context: str, language: str = "ar") -> str:
        ok = [t for t in tool_results if t.get("ok")]
        pending = [t for t in tool_results if t.get("needs_approval")]
        failed = [t for t in tool_results if not t.get("ok") and not t.get("needs_approval")]
        if language.startswith("en"):
            parts = ["PFAI Command Agent (mock brain) summary:"]
            if ok:
                parts.append(f"Completed tools: {', '.join(t.get('tool','?') for t in ok)}.")
            if pending:
                parts.append("Sensitive action(s) await your owner approval before execution.")
            if failed:
                parts.append("Some tools failed — see timeline/details.")
            parts.append("Memory context considered: " + (memory_context[:240] if memory_context else "none"))
            return "\n".join(parts)
        parts = ["ملخص عقل PFAI (وضع Mock للتطوير):"]
        if ok:
            parts.append("الأدوات المنفذة: " + ", ".join(t.get("tool", "?") for t in ok))
        if pending:
            parts.append("هناك إجراء حسّاس بانتظار موافقة المالك قبل التنفيذ.")
        if failed:
            parts.append("بعض الأدوات فشلت — راجع التفاصيل في المخطط الزمني.")
        if memory_context and "no durable" not in memory_context:
            parts.append("تم أخذ الذاكرة ذات الصلة بالاعتبار.")
        return "\n".join(parts)
