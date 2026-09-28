"""Command Chat Agent — the Brain of PFAI.

Chat → Agent → Tool Router → Heart (core/services) → Result → Chat

Does NOT mutate model weights. Learning = memory/feedback/approved knowledge.
Sensitive heart mutations require explicit owner approval.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from .command_audit import CommandAuditLog
from .command_memory import CommandMemoryService
from .model_anthropic import AnthropicProvider
from .model_mock import MockCommandProvider
from .tool_router import ToolRouter
from .logging_setup import setup_logging

log = setup_logging("pfai.command_agent")

STATUSES = (
    "thinking",
    "planning",
    "calling_tool",
    "executing",
    "waiting_for_approval",
    "completed",
    "failed",
)


class CommandAgent:
    def __init__(
        self,
        router: ToolRouter,
        memory: CommandMemoryService,
        audit: CommandAuditLog,
        model=None,
    ):
        self.router = router
        self.memory = memory
        self.audit = audit
        self.model = model
        self.mock = MockCommandProvider()

    def provider_name(self) -> str:
        if self._anthropic_ready():
            return f"anthropic:{getattr(self.model, 'model', 'claude')}"
        return "mock-command"

    def _anthropic_ready(self) -> bool:
        if not isinstance(self.model, AnthropicProvider):
            return False
        env = getattr(self.model, "api_key_env", "ANTHROPIC_API_KEY")
        return bool(os.environ.get(env))

    def handle(self, message: str, *, owner: str, conversation_id: str | None = None, language: str | None = None) -> dict:
        timeline: list[dict] = []
        message = (message or "").strip()
        if not message:
            return {"ok": False, "error": "message is required", "timeline": timeline}

        lang = language or _detect_lang(message)
        cid = self.memory.ensure_conversation(conversation_id)
        self.memory.add_message(cid, "user", message, status="completed")

        # Delegate coding-education intents to Coding Academy brain when wired.
        # Training eligibility / control status stay on ToolRouter (read-only).
        coding_agent = getattr(self, "coding_agent", None)
        if (
            coding_agent is not None
            and _looks_like_coding_intent(message)
            and not _looks_like_training_status_intent(message)
        ):
            try:
                from .coding_agent import build_learning_context
                coding = coding_agent.handle(message, owner=owner)
                reply = coding.get("reply") or json.dumps(coding, ensure_ascii=False)[:1200]
                status = "completed" if coding.get("ok", True) else "failed"
                tl = coding.get("timeline") or [{"status": "teaching", "detail": "coding academy"}]
                learning_context = coding.get("learning_context") or build_learning_context(coding)
                self.memory.add_message(
                    cid, "assistant", reply, status=status,
                    meta={"coding": coding, "timeline": tl, "learning_context": learning_context},
                )
                self.audit.record(
                    actor=owner, command=message, tool="coding_agent", status=status,
                    result={"intent": coding.get("intent")}, required_approval=False, conversation_id=cid,
                )
                return {
                    "ok": coding.get("ok", True),
                    "conversation_id": cid,
                    "reply": reply,
                    "timeline": tl,
                    "coding": coding,
                    "learning_context": learning_context,
                    "provider": coding.get("provider") or self.provider_name(),
                    "status": status,
                    "language": lang,
                }
            except Exception as exc:
                log.warning("coding delegate failed: %s", exc)

        def mark(status: str, detail: str | None = None, **extra):
            step = {"status": status, "detail": detail, **extra}
            timeline.append(step)
            return step

        mark("thinking", "Loading relevant PFAI memory and safety context")
        mem_ctx = self.memory.context_block(message)
        dialog = self.memory.recent_dialog(cid, limit=6)

        # Correction conversational shortcut
        if _is_correction_offer(message, dialog):
            return self._handle_correction_capture(cid, owner, message, lang, timeline, mark)

        mark("planning", f"Planning with provider={self.provider_name()}")
        try:
            planned = self._plan(message, mem_ctx, dialog)
        except Exception as exc:
            mark("failed", str(exc))
            reply = _fail_reply(lang, str(exc))
            self.memory.add_message(cid, "assistant", reply, status="failed", meta={"timeline": timeline})
            return {"ok": False, "conversation_id": cid, "reply": reply, "timeline": timeline, "provider": self.provider_name()}

        tool_results: list[dict] = []
        pending_payload = None

        # One-mind budget: prefer unified pulse; cap fan-out to cut lag
        planned = _budget_plan(planned)
        mark("executing", f"Unified execution plan tools={len(planned)}")
        tool_results, pending_payload = self._execute_plan(
            planned, owner=owner, cid=cid, message=message, mark=mark
        )

        if pending_payload:
            reply = _approval_reply(lang, pending_payload)
            final_status = "waiting_for_approval"
        else:
            mark("thinking", "Composing answer from tool results + memory")
            reply = self._compose(message, tool_results, mem_ctx, lang)
            # Soft-complete: local brain stays responsive even if one lane degrades
            final_status = "completed" if (
                not tool_results
                or any(t.get("ok") for t in tool_results)
                or all(t.get("needs_approval") for t in tool_results)
            ) else "failed"
            if final_status == "completed":
                mark("completed", "Turn finished")
            else:
                mark("failed", "Critical tools failed")

        self.memory.add_message(
            cid, "assistant", reply, status=final_status,
            meta={"timeline": timeline, "tools": tool_results, "pending": pending_payload, "provider": self.provider_name()},
        )
        return {
            "ok": final_status in {"completed", "waiting_for_approval"},
            "conversation_id": cid,
            "reply": reply,
            "timeline": timeline,
            "tools": tool_results,
            "pending": pending_payload,
            "provider": self.provider_name(),
            "memory_used": mem_ctx,
            "status": final_status,
            "language": lang,
        }

    def approve(self, pending_id: str, *, owner: str) -> dict:
        item = self.memory.get_pending(pending_id)
        if not item:
            return {"ok": False, "error": "pending action not found"}
        if item["status"] != "waiting_for_approval":
            return {"ok": False, "error": f"pending action status is {item['status']}"}
        self.memory.resolve_pending(pending_id, "approved", owner)
        timeline = [{"status": "executing", "detail": f"Owner approved {item['tool']}", "tool": item["tool"]}]
        result = self.router.execute(item["tool"], item.get("args") or {}, approved=True)
        status = "completed" if result.get("ok") else "failed"
        timeline.append({"status": status, "detail": None if result.get("ok") else result.get("error"), "tool": item["tool"]})
        self.audit.record(
            actor=owner, command=f"approve:{pending_id}", tool=item["tool"], status=status,
            result=result.get("result") if result.get("ok") else None,
            required_approval=True, approved=True, conversation_id=item["conversation_id"],
            pending_id=pending_id, error=result.get("error"),
        )
        reply = (
            f"تمت الموافقة وتنفيذ `{item['tool']}`. النتيجة: {_short(result)}"
            if _detect_lang(item.get("reason") or "") == "ar"
            else f"Approved and executed `{item['tool']}`. Result: {_short(result)}"
        )
        self.memory.add_message(
            item["conversation_id"], "assistant", reply, status=status,
            meta={"timeline": timeline, "tools": [result], "pending_id": pending_id},
        )
        return {
            "ok": result.get("ok", False),
            "conversation_id": item["conversation_id"],
            "reply": reply,
            "timeline": timeline,
            "tools": [result],
            "status": status,
            "pending_id": pending_id,
        }

    def reject(self, pending_id: str, *, owner: str) -> dict:
        item = self.memory.get_pending(pending_id)
        if not item:
            return {"ok": False, "error": "pending action not found"}
        self.memory.resolve_pending(pending_id, "rejected", owner)
        self.audit.record(
            actor=owner, command=f"reject:{pending_id}", tool=item["tool"], status="rejected",
            required_approval=True, approved=False, conversation_id=item["conversation_id"], pending_id=pending_id,
        )
        reply = f"تم رفض تنفيذ `{item['tool']}` بواسطة المالك." 
        self.memory.add_message(item["conversation_id"], "assistant", reply, status="completed", meta={"pending_id": pending_id, "rejected": True})
        return {"ok": True, "conversation_id": item["conversation_id"], "reply": reply, "status": "rejected", "pending_id": pending_id}

    def _record_tool_learning(self, owner: str, tool: str, message: str, result: dict) -> None:
        """Feed continuous-learning bridge from successful tool turns (never trains weights)."""
        bridge = getattr(self, "experience_bridge", None)
        if bridge is None or not hasattr(bridge, "record_tool_success"):
            return
        try:
            bridge.record_tool_success(
                instruction=f"[{tool}] {(message or '')[:400]}",
                result_summary=json.dumps(result.get("result"), ensure_ascii=False, default=str)[:800],
                source_id=f"command_chat:{owner}:{tool}",
            )
        except Exception as exc:
            log.debug("tool learning bridge skipped: %s", exc)

    # -- planning / compose --------------------------------------------
    _PARALLEL_READ = frozenset({
        "health_check", "system_status", "metrics_snapshot", "modules_list",
        "continuous_status", "deployments_list", "knowledge_search", "memory_search",
        "recovery_verify", "research_verify", "regression_pending", "chat_audit_recent",
        "propose_improvement", "learner_snapshot", "training_eligibility",
        "training_control_status", "coding_tracks", "coding_progress", "coding_projects",
        "coding_knowledge", "coding_next_lesson", "web_status", "app_control_status",
        "autonomy_status", "advanced_status", "advanced_awareness", "self_check_run",
        "unified_brain_status",
    })

    def _execute_plan(
        self,
        planned: list[dict],
        *,
        owner: str,
        cid: str,
        message: str,
        mark,
    ) -> tuple[list[dict], dict | None]:
        """Execute reads in parallel; writes/serial tools in order. Soft-fail lanes."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import time

        tool_results: list[dict] = []
        pending_payload = None
        reads = []
        writes = []
        for step in planned:
            tool = step.get("tool")
            if not tool:
                continue
            if self.router.requires_approval(tool):
                writes.append(step)  # approval path stays serial
            elif tool in self._PARALLEL_READ:
                reads.append(step)
            else:
                writes.append(step)

        # Parallel read lanes
        if reads:
            mark("calling_tool", f"Parallel read lanes n={len(reads)}")
            with ThreadPoolExecutor(max_workers=min(6, len(reads))) as pool:
                futs = {}
                for step in reads:
                    tool = step["tool"]
                    args = step.get("args") or {}
                    futs[pool.submit(self.router.execute, tool, args, approved=False, actor=owner)] = step
                for fut in as_completed(futs):
                    step = futs[fut]
                    tool = step["tool"]
                    try:
                        result = fut.result(timeout=8)
                    except Exception as exc:
                        result = {"ok": False, "tool": tool, "error": f"lane_timeout_or_error:{exc}", "degraded": True}
                    if "tool" not in result:
                        result = {**result, "tool": tool}
                    tool_results.append(result)
                    self.audit.record(
                        actor=owner, command=message, tool=tool,
                        status="completed" if result.get("ok") else "failed",
                        result=result.get("result") if result.get("ok") else None,
                        required_approval=False, approved=None, conversation_id=cid,
                        error=result.get("error"),
                    )
                    if result.get("ok"):
                        self._record_tool_learning(owner, tool, message, result)

        # Serial write / heavy tools
        for step in writes:
            tool = step.get("tool")
            args = step.get("args") or {}
            mark("calling_tool", f"Selected tool {tool}", tool=tool)
            if self.router.requires_approval(tool):
                pid = self.memory.create_pending(cid, tool, args, reason=step.get("reason") or message)
                pending_payload = {
                    "pending_id": pid,
                    "tool": tool,
                    "args": args,
                    "reason": step.get("reason") or f"Owner approval required for {tool}",
                }
                mark("waiting_for_approval", pending_payload["reason"], pending_id=pid, tool=tool)
                self.audit.record(
                    actor=owner, command=message, tool=tool, status="waiting_for_approval",
                    required_approval=True, approved=False, conversation_id=cid, pending_id=pid,
                )
                tool_results.append({"ok": False, "needs_approval": True, "tool": tool, "args": args, "pending_id": pid})
                break
            mark("executing", f"Executing {tool} via heart", tool=tool)
            t0 = time.time()
            try:
                result = self.router.execute(tool, args, approved=False, actor=owner)
            except Exception as exc:
                result = {"ok": False, "tool": tool, "error": str(exc), "degraded": True}
            if "tool" not in result:
                result = {**result, "tool": tool}
            result.setdefault("_ms", int((time.time() - t0) * 1000))
            tool_results.append(result)
            self.audit.record(
                actor=owner, command=message, tool=tool,
                status="completed" if result.get("ok") else "failed",
                result=result.get("result") if result.get("ok") else None,
                required_approval=False, approved=None, conversation_id=cid,
                error=result.get("error"),
            )
            if result.get("ok"):
                self._record_tool_learning(owner, tool, message, result)
            if not result.get("ok"):
                mark("failed", result.get("error") or "tool failed", tool=tool)
        return tool_results, pending_payload

    def _plan(self, message: str, mem_ctx: str, dialog: list[dict]) -> list[dict]:
        allowed = [t["name"] for t in self.router.catalog()]
        if self._model_generate_ready():
            catalog = json.dumps(self.router.catalog(), ensure_ascii=False)
            prompt = (
                "You are the PFAI Unified Super Brain — one mind, precise, fast. "
                "Prefer unified_brain_pulse for whole-system asks. Max 3 tools. "
                "Return ONLY JSON: {\"tools\":[{\"tool\":\"name\",\"args\":{},\"reason\":\"...\"}],\"reply_hint\":\"...\"}. "
                "Never invent tool names. Prefer academy/training-status tools for learning questions. "
                "Never select weight training / model activate / secrets tools. "
                "Open-execution mode may run mutating chat tools without a second approval click.\n"
                f"Allowed tools: {catalog}\n"
                f"Durable memory:\n{mem_ctx}\n"
                f"Recent dialog: {json.dumps(dialog[-4:], ensure_ascii=False)}\n"
                f"Owner message: {message}\n"
            )
            try:
                raw = self.model.generate(prompt, system="PFAI advanced command planner. JSON only.")
                data = _extract_json_obj(raw)
                if data and isinstance(data.get("tools"), list):
                    out = []
                    for t in data["tools"]:
                        name = (t or {}).get("tool")
                        if name in allowed:
                            out.append({"tool": name, "args": (t or {}).get("args") or {}, "reason": (t or {}).get("reason") or ""})
                    if out:
                        return out
            except Exception as exc:
                log.warning("model plan failed, using mock: %s", exc)
        return self.mock.plan_tools(message, allowed)

    def _compose(self, message: str, tool_results: list[dict], mem_ctx: str, lang: str) -> str:
        if self._model_generate_ready():
            prompt = (
                "Compose a high-signal operator reply for PFAI Advanced Command Chat. "
                "Sound like a real AI systems brain: structured findings, clear next steps, "
                "link education/training when relevant. Use tool results only; do not invent metrics. "
                "Prefer the owner's language. Keep it powerful but honest.\n"
                f"Language hint: {lang}\nMessage: {message}\nMemory:\n{mem_ctx}\n"
                f"Tool results: {json.dumps(tool_results, ensure_ascii=False, default=str)[:8000]}\n"
            )
            try:
                return self.model.generate(
                    prompt,
                    system="PFAI advanced operator assistant. Precise, analytical, safety-aware.",
                )
            except Exception as exc:
                log.warning("model compose failed: %s", exc)
        return self.mock.compose_reply(message, tool_results, mem_ctx, language=lang)

    def _model_generate_ready(self) -> bool:
        if self._anthropic_ready():
            return True
        if self.model is None or not hasattr(self.model, "generate"):
            return False
        # EchoProvider is too weak for planning/compose — keep mock path.
        return type(self.model).__name__ not in {"EchoProvider", "MockCommandProvider"}

    def _handle_correction_capture(self, cid, owner, message, lang, timeline, mark) -> dict:
        from .open_execution import open_chat_tools
        mark("thinking", "Owner correction flow")
        content = message
        for prefix in ("التصحيح:", "التصحيح :", "correction:", "Correction:"):
            if prefix.lower() in message.lower():
                content = message.split(":", 1)[-1].strip()
                break
        if re.search(r"غير صحيح|wrong|incorrect", message, re.I) and len(content) < 40:
            reply = (
                "ما التصحيح الذي تريد حفظه؟ أرسل نص التصحيح بوضوح (مثال: التصحيح: ...)."
                if lang == "ar"
                else "What correction should I save? Send it clearly (example: correction: ...)."
            )
            mark("completed", "Awaiting correction text")
            self.memory.add_message(cid, "assistant", reply, status="completed", meta={"timeline": timeline})
            return {
                "ok": True, "conversation_id": cid, "reply": reply, "timeline": timeline,
                "status": "completed", "provider": self.provider_name(), "language": lang,
            }
        # Open mode: persist immediately without approval wait
        if open_chat_tools() or not self.router.requires_approval("save_owner_correction"):
            mark("executing", "Saving correction (open execution)")
            result = self.router.execute("save_owner_correction", {"content": content}, approved=True, actor=owner)
            status = "completed" if result.get("ok") else "failed"
            mark(status, None if result.get("ok") else result.get("error"))
            reply = (
                f"تم حفظ التصحيح في الذاكرة. id={(result.get('result') or {}).get('memory_id')}"
                if lang == "ar"
                else f"Correction saved to memory. id={(result.get('result') or {}).get('memory_id')}"
            )
            if not result.get("ok"):
                reply = result.get("error") or reply
            self.audit.record(
                actor=owner, command=message, tool="save_owner_correction", status=status,
                required_approval=False, approved=True, conversation_id=cid,
                result=result.get("result"), error=result.get("error"),
            )
            self.memory.add_message(cid, "assistant", reply, status=status, meta={"timeline": timeline, "tools": [result]})
            return {
                "ok": bool(result.get("ok")), "conversation_id": cid, "reply": reply, "timeline": timeline,
                "tools": [result], "status": status, "provider": self.provider_name(), "language": lang,
            }
        pid = self.memory.create_pending(cid, "save_owner_correction", {"content": content}, reason="Save owner correction")
        mark("waiting_for_approval", "Owner approval required to persist correction", pending_id=pid)
        self.audit.record(
            actor=owner, command=message, tool="save_owner_correction", status="waiting_for_approval",
            required_approval=True, approved=False, conversation_id=cid, pending_id=pid,
        )
        pending = {"pending_id": pid, "tool": "save_owner_correction", "args": {"content": content}, "reason": "Save owner correction"}
        reply = _approval_reply(lang, pending)
        self.memory.add_message(cid, "assistant", reply, status="waiting_for_approval", meta={"timeline": timeline, "pending": pending})
        return {
            "ok": True, "conversation_id": cid, "reply": reply, "timeline": timeline,
            "pending": pending, "status": "waiting_for_approval", "provider": self.provider_name(), "language": lang,
        }


def _detect_lang(text: str) -> str:
    if re.search(r"[\u0600-\u06FF]", text or ""):
        return "ar"
    return "en"


def _looks_like_training_status_intent(message: str) -> bool:
    """Model-training status / eligibility — not Coding Academy teach intents."""
    return bool(re.search(
        r"أهلية\s*التدريب|training\s*eligibility|حالة\s*التدريب|training\s*status|"
        r"جاهزية\s*التدريب|control.?center.*train|هل\s*(التدريب|النموذج).*جاهز|"
        r"next\s*training|can\s*we\s*train|متى\s*نتدرب|training_cycle|دورة\s*التدريب",
        message or "",
        re.I,
    ))


def _looks_like_web_intent(message: str) -> bool:
    return bool(re.search(
        r"ابحث\s*في\s*(الويب|الانترنت|الإنترنت)|search\s*(the\s*)?web|web\s*search|web\s*research|"
        r"بحث\s*ويب|من\s*الإنترنت|from\s*the\s*internet|look\s*up\s*online|fetch\s*url|https?://",
        message or "",
        re.I,
    ))


def _budget_plan(planned: list[dict], *, max_tools: int = 3) -> list[dict]:
    """Collapse redundant stacks; prefer unified_brain_pulse as single mind."""
    if not planned:
        return planned
    names = [p.get("tool") for p in planned if p.get("tool")]
    if "unified_brain_pulse" in names and len(names) >= 1:
        # Prefer pure one-mind pulse; keep one companion action if present
        pulse = next(p for p in planned if p.get("tool") == "unified_brain_pulse")
        companion_ok = {
            "advanced_self_develop", "self_improve_tick", "app_control_status",
            "training_cycle_start", "continuous_tick",
        }
        # If the turn is ONLY pulse + redundant status mirrors, collapse to pulse
        non_mirror = [p for p in planned if p.get("tool") in companion_ok]
        mirrors = {"system_status", "health_check", "autonomy_status", "advanced_status",
                   "web_status", "continuous_status", "learner_snapshot", "advanced_awareness",
                   "unified_brain_status"}
        if non_mirror:
            return [pulse, non_mirror[0]][:max_tools]
        if set(names) - {"unified_brain_pulse"} <= mirrors:
            return [pulse]
        return [pulse]
    # Dedupe while preserving order
    seen = set()
    out = []
    for p in planned:
        t = p.get("tool")
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(p)
        if len(out) >= max_tools:
            break
    return out


def _looks_like_autonomy_intent(message: str) -> bool:
    return bool(re.search(
        r"أصلح\s*نفس|صلح\s*نفس|self[_\s-]?heal|self[_\s-]?check|self[_\s-]?improve|"
        r"طور\s*نفس|حدّث\s*نفس|حدث\s*نفس|يطور\s*نفس|يصلح\s*نفس|"
        r"استقلال|autonom|فك\s*القيود|بدون\s*قيود|تحسين\s*ذاتي|self_improve|"
        r"يبني\s*ال?اكواد|يبني\s*الأكواد|self[_\s-]?develop|advanced_self|"
        r"يراجع\s*اكثر|يصحح\s*اكثر|واعي|بدون\s*الرجوع|مرحلة\s*متطورة",
        message or "",
        re.I,
    ))


def _looks_like_coding_intent(message: str) -> bool:
    # Web / training-status / autonomy win over coding keyword collisions (e.g. "learn")
    if (
        _looks_like_web_intent(message)
        or _looks_like_training_status_intent(message)
        or _looks_like_autonomy_intent(message)
    ):
        return False
    return bool(re.search(
        r"علمني|teach me|learn |مبتدئ|full stack|اختبر مستواي|assess|تمرين|exercise|راجع هذا الكود|code review|"
        r"تلميح|hint|اشرح لي هذا الخطأ|debug|مشروع أتدرب|project|javascript|python|architecture|"
        r"لماذا هذا الكود|learning mode|engineering mode|sandbox|اختبرني|"
        r"مسار تعليمي|learning path|أكاديمية|coding academy|"
        r"الدرس التالي|next lesson|أرسل الحل|submit (my )?(code|solution)",
        message or "",
        re.I,
    ))


def _is_correction_offer(message: str, dialog: list[dict]) -> bool:
    if re.search(r"غير صحيح|incorrect|wrong analysis|هذا التحليل", message or "", re.I):
        return True
    if dialog:
        last = dialog[-1]
        if last.get("role") == "assistant" and "التصحيح" in (last.get("content") or ""):
            return True
        if last.get("role") == "assistant" and "correction" in (last.get("content") or "").lower():
            return True
    return False


def _approval_reply(lang: str, pending: dict) -> str:
    if lang == "en":
        return (
            f"Action `{pending['tool']}` requires your Owner approval before execution.\n"
            f"Pending ID: {pending['pending_id']}\n"
            f"Reason: {pending.get('reason')}\n"
            "Approve or reject from the chat approval controls."
        )
    return (
        f"الإجراء `{pending['tool']}` يحتاج موافقة المالك قبل التنفيذ.\n"
        f"معرّف الانتظار: {pending['pending_id']}\n"
        f"السبب: {pending.get('reason')}\n"
        "استخدم أزرار الموافقة/الرفض في المحادثة."
    )


def _fail_reply(lang: str, err: str) -> str:
    return f"Failed to plan command: {err}" if lang == "en" else f"فشل التخطيط للأمر: {err}"


def _short(result: dict) -> str:
    try:
        return json.dumps(result, ensure_ascii=False, default=str)[:800]
    except Exception:
        return str(result)[:800]


def _extract_json_obj(text: str) -> dict | None:
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
