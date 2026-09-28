"""PHASE 23 — Real web research pipeline with provenance and injection defense.

Does not fabricate URLs/citations/search results. When providers are unavailable,
reports WEB_FABRIC_STATUS=NOT_CONFIGURED explicitly.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from pfai.authorized_execution import sanitize_args
from pfai.elite.prompt_injection_guard import sanitize_external_content, scan_untrusted_text
from pfai.elite.types import new_id
from pfai.elite.web_fabric import (
    ClaimKind,
    WebInformationFabric,
    WebPolicyGate,
    WebResearchSession,
    redact_secrets,
    web_config_report,
)


class WebResearchProvider:
    """Provider-neutral research façade over WebInformationFabric / WebResearchSession."""

    provider_id = "web_research_pipeline"

    def __init__(self, fabric: WebInformationFabric | None = None, *, policy: WebPolicyGate | None = None) -> None:
        self.fabric = fabric or WebInformationFabric()
        self.policy = policy or WebPolicyGate()
        self.session = WebResearchSession(self.fabric, policy=self.policy)

    def readiness(self) -> dict[str, Any]:
        st = self.fabric.status()
        return {
            "ok": st.get("WEB_FABRIC_STATUS") == "READY",
            "provider": self.provider_id,
            "WEB_FABRIC_STATUS": st.get("WEB_FABRIC_STATUS"),
            "production_ready": st.get("WEB_FABRIC_STATUS") == "READY",
        }

    def research(self, query: str, **kwargs: Any) -> dict[str, Any]:
        return WebResearchPipeline(fabric=self.fabric, policy=self.policy).run(query, **kwargs)


class WebResearchPipeline:
    """
    user request → planner → query gen → provider → normalize → extract →
    dedupe → validate → evidence → synthesis → citations → response
    """

    VERSION = "23.0.0"

    def __init__(
        self,
        fabric: WebInformationFabric | None = None,
        *,
        policy: WebPolicyGate | None = None,
        audit_path: str = "data/longevity/elite/web_research_audit.jsonl",
    ) -> None:
        self.fabric = fabric or WebInformationFabric()
        self.policy = policy or WebPolicyGate()
        self.session = WebResearchSession(self.fabric, policy=self.policy)
        self.audit_path = Path(audit_path)
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)

    def _audit(self, event: str, **detail: Any) -> None:
        row = {"ts": time.time(), "event": event, **sanitize_args(detail)}
        with self.audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def run(
        self,
        query: str,
        *,
        limit: int = 5,
        fetch_top: int = 1,
        approved: bool = False,
        actor: str = "",
        request_id: str = "",
    ) -> dict[str, Any]:
        started = time.time()
        rid = request_id or new_id("wres")
        stages: list[dict[str, Any]] = []
        q = (query or "").strip()
        status = web_config_report(self.fabric.search_provider, self.fabric.fetch_provider)
        fabric_status = status.get("WEB_FABRIC_STATUS") or "NOT_CONFIGURED"

        def mark(stage: str, **detail: Any) -> None:
            stages.append({"stage": stage, "ts": time.time(), **sanitize_args(detail)})

        mark("research_planner", query_preview=q[:200])
        plan = self.fabric.planner.plan(q)
        mark("query_generation", queries=plan.get("queries") or [q])

        if fabric_status != "READY":
            out = {
                "ok": False,
                "WEB_FABRIC_STATUS": fabric_status,
                "WEB_PROVIDER_STATUS": fabric_status,
                "WEB_RESEARCH_STATUS": "NOT_CONFIGURED",
                "CITATION_STATUS": "NOT_CONFIGURED",
                "fabricated_citations": False,
                "fabricated_urls": False,
                "fabricated_results": False,
                "citations": [],
                "evidence": [],
                "answer": f"Web research unavailable: WEB_FABRIC_STATUS={fabric_status}",
                "information_source": "unavailable",
                "stages": stages,
                "request_id": rid,
                "version": self.VERSION,
                "PHASE_24_ALLOWED": False,
            }
            mark("final_response", ok=False, reason="provider_unavailable")
            self._audit("research_unavailable", request_id=rid, status=fabric_status, actor=actor)
            try:
                from pfai.elite.web_observability import WEB_OBS

                WEB_OBS.record("research", ok=False, latency=time.time() - started, error="unavailable")
            except Exception:
                pass
            return out

        # Live path — only when READY
        mark("web_provider", provider=status.get("WEB_SEARCH_PROVIDER"))
        raw = self.session.research(q, limit=limit, fetch_top=fetch_top, approved=approved, actor=actor)
        mark("result_normalization", citation_count=len(raw.get("citations") or []))

        citations = []
        evidence = []
        injection_blocks = 0
        for c in raw.get("citations") or []:
            url = str(c.get("url") or "")
            auth = self.policy.authorize_url(url, approved=approved, actor=actor) if url else {"ok": True}
            if not auth.get("ok"):
                continue
            snippet = redact_secrets(str(c.get("snippet") or ""))
            scan = scan_untrusted_text(snippet)
            if scan.get("blocked"):
                injection_blocks += 1
                sanitized = sanitize_external_content(snippet)
                snippet = sanitized.get("text") or "[UNTRUSTED_CONTENT_BLOCKED]"
            else:
                sanitized = sanitize_external_content(snippet)
                snippet = sanitized.get("text") or snippet
            cite = {
                **c,
                "snippet": snippet[:800],
                "trusted": False,
                "instruction_authority": "SYSTEM_OWNER_ONLY",
                "injection_blocked": bool(scan.get("blocked")),
                "provenance": {
                    **(c.get("provenance") or {}),
                    "request_id": rid,
                    "retrieved_at": c.get("retrieved_at") or time.time(),
                    "provider": c.get("provider") or status.get("WEB_SEARCH_PROVIDER"),
                    "content_hash": c.get("content_hash")
                    or hashlib.sha256(snippet.encode()).hexdigest()[:32],
                },
                "claim_kind": ClaimKind.SOURCE_DERIVED_CLAIM,
            }
            citations.append(cite)
            evidence.append(
                {
                    "statement": snippet[:400],
                    "source": url,
                    "citation_id": c.get("citation_id"),
                    "claim_kind": ClaimKind.SOURCE_DERIVED_CLAIM,
                    "confidence": float(c.get("confidence") or 0.5),
                    "validated": True,
                    "trusted_instruction": False,
                }
            )

        mark("source_validation", kept=len(citations), injection_blocks=injection_blocks)
        mark("evidence_collection", evidence_count=len(evidence))
        titles = [c.get("title") or c.get("url") for c in citations[:5] if c.get("title") or c.get("url")]
        summary = (
            f"Research for {q!r}: {len(citations)} attributed sources. "
            + ("; ".join(str(t) for t in titles if t) if titles else "No titles.")
        )
        mark("synthesis", summary_preview=summary[:200])
        mark("citations", count=len(citations))

        out = {
            "ok": bool(raw.get("ok")) and len(citations) > 0,
            "WEB_FABRIC_STATUS": fabric_status,
            "WEB_PROVIDER_STATUS": "READY",
            "WEB_RESEARCH_STATUS": "READY" if citations else "EMPTY",
            "CITATION_STATUS": "READY" if citations else "EMPTY",
            "query": q,
            "plan": plan,
            "citations": citations,
            "evidence": evidence,
            "answer": summary,
            "information_source": "live_web",
            "fabricated_citations": False,
            "fabricated_urls": False,
            "fabricated_results": False,
            "injection_blocks": injection_blocks,
            "stages": stages,
            "request_id": rid,
            "latency_seconds": time.time() - started,
            "version": self.VERSION,
            "PHASE_24_ALLOWED": False,
            "policy_audit": self.policy.audit()[-5:],
        }
        mark("final_response", ok=out["ok"])
        self._audit("research_finished", request_id=rid, ok=out["ok"], citations=len(citations), actor=actor)
        try:
            from pfai.elite.web_observability import WEB_OBS

            WEB_OBS.record(
                "research",
                ok=bool(out["ok"]),
                latency=time.time() - started,
                injection_blocks=injection_blocks,
            )
        except Exception:
            pass
        return out
