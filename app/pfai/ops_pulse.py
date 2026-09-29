"""Natural ops / system-status answers from live heart signals."""
from __future__ import annotations

from typing import Any


def ops_status_reply(
    *,
    language: str = "ar",
    health: dict[str, Any] | None = None,
    continuous: dict[str, Any] | None = None,
    monitor: dict[str, Any] | None = None,
    evolution: dict[str, Any] | None = None,
    unified: dict[str, Any] | None = None,
    version: str = "",
) -> str:
    """Claude-grade concise system status — facts only, no JSON fog."""
    en = (language or "").startswith("en")
    h = health or {}
    c = continuous or {}
    m = monitor or {}
    e = evolution or {}
    u = unified or {}

    status = h.get("status") or h.get("runtime") or "unknown"
    ver = version or h.get("version") or "?"
    cont_alive = bool(c.get("worker_alive") or c.get("real_loop"))
    cont_pending = c.get("pending_examples")
    mon_alive = bool(m.get("alive"))
    mon_pulses = m.get("pulses")
    evo_alive = bool(e.get("alive"))
    evo_min = e.get("minute_ticks")
    u_cycles = u.get("cycles")
    u_hb = u.get("heartbeat_alive")
    u_elig = (u.get("training") or {}).get("eligible") if isinstance(u.get("training"), dict) else None
    u_async = (u.get("training") or {}).get("async_running") if isinstance(u.get("training"), dict) else None

    if en:
        lines = [
            f"System is {status} — PFAI {ver}.",
            f"Continuous learn worker: {'ALIVE 24/7' if cont_alive else 'DOWN'}"
            + (f" (pending={cont_pending})" if cont_pending is not None else "") + ".",
            f"Unified learn+train: cycles={u_cycles if u_cycles is not None else '—'} · "
            f"heartbeat={'ON' if u_hb else 'off'}"
            + (f" · eligible={u_elig}" if u_elig is not None else "")
            + (f" · LoRA_running={u_async}" if u_async is not None else "") + ".",
            f"Live monitor: {'RUNNING' if mon_alive else 'DOWN'}"
            + (f" · pulses={mon_pulses}" if mon_pulses is not None else "") + ".",
            f"Evolution cadence: {'alive' if evo_alive else 'down'}"
            + (f" · minute_ticks={evo_min}" if evo_min is not None else "") + ".",
            "Weight promotion stays owner-gated — never silent.",
        ]
        return " ".join(lines)

    lines = [
        f"النظام {('سليم' if str(status).lower() in {'ok', 'healthy'} else status)} — PFAI {ver}.",
        f"عامل التعلّم المستمر: {'يعمل 24/7' if cont_alive else 'متوقف'}"
        + (f" (معلّق={cont_pending})" if cont_pending is not None else "") + ".",
        f"الحلقة الموحّدة: دورات={u_cycles if u_cycles is not None else '—'} · "
        f"نبض={'يعمل' if u_hb else 'متوقف'}"
        + (f" · أهلية={u_elig}" if u_elig is not None else "")
        + (f" · LoRA_يعمل={u_async}" if u_async is not None else "") + ".",
        f"المراقب الحي: {'يعمل' if mon_alive else 'متوقف'}"
        + (f" · نبضات={mon_pulses}" if mon_pulses is not None else "") + ".",
        f"إيقاع التطوّر: {'حي' if evo_alive else 'متوقف'}"
        + (f" · دقائق={evo_min}" if evo_min is not None else "") + ".",
        "ترقية الأوزان تبقى بموافقة المالك — بلا تفعيل صامت.",
    ]
    return " ".join(lines)


def is_ops_status_question(message: str) -> bool:
    import re
    return bool(re.search(
        r"(?i)كيف\s*حال[ةه]?\s*ال?نظام|حال[ةه]\s*ال?نظام|system\s*status|"
        r"هل\s*ال?نظام\s*يعمل|status\s*now|health\s*check|فحص\s*ال?صحة|"
        r"ما\s*وضع\s*ال?نظام|الوضع\s*الان|الوضع\s*الآن",
        message or "",
    ))
