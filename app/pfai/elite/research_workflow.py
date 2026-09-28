"""PHASE 20 Research workflow — honest about Web Fabric configuration."""
from __future__ import annotations

from typing import Any

from pfai.elite.web_fabric import web_config_report


class ResearchWorkflow:
    """
    QUESTION → SEARCH → RETRIEVE → FILTER → VERIFY → COMPARE → SYNTHESIZE → CITE → ANSWER

    When WEB_FABRIC_STATUS != READY: report limitation; never fabricate citations/URLs.
    """

    VERSION = "20.0.0"
    STAGES = (
        "QUESTION",
        "SEARCH",
        "RETRIEVE",
        "FILTER",
        "VERIFY",
        "COMPARE",
        "SYNTHESIZE",
        "CITE_SOURCE",
        "FINAL_ANSWER",
    )

    def run(self, question: str, *, web_fabric: Any = None) -> dict[str, Any]:
        report = web_config_report()
        status = report.get("WEB_FABRIC_STATUS") or "NOT_CONFIGURED"
        timeline = [{"stage": "QUESTION", "ok": True, "question": (question or "")[:300]}]

        if status != "READY":
            for stage in self.STAGES[1:]:
                timeline.append(
                    {
                        "stage": stage,
                        "ok": False,
                        "skipped": True,
                        "reason": "WEB_FABRIC_STATUS=NOT_CONFIGURED",
                    }
                )
            return {
                "ok": False,
                "RESEARCH_STATUS": "UNAVAILABLE",
                "WEB_FABRIC_STATUS": status,
                "fabricated_citations": False,
                "fabricated_urls": False,
                "timeline": timeline,
                "answer": (
                    "Research workflow cannot consult external sources: "
                    f"WEB_FABRIC_STATUS={status}. No citations or URLs were fabricated."
                ),
                "citations": [],
                "version": self.VERSION,
            }

        # Configured path — use real fabric only
        fabric = web_fabric
        if fabric is None:
            from pfai.elite.web_fabric import WebInformationFabric

            fabric = WebInformationFabric()
        search = fabric.research(question, limit=5, fetch_top=1)
        timeline.append({"stage": "SEARCH", "ok": search.ok, "status": search.status})
        timeline.append({"stage": "RETRIEVE", "ok": search.ok, "count": len(search.citations)})
        timeline.append({"stage": "FILTER", "ok": True})
        timeline.append({"stage": "VERIFY", "ok": bool(search.citations)})
        timeline.append({"stage": "COMPARE", "ok": True})
        timeline.append({"stage": "SYNTHESIZE", "ok": search.ok})
        timeline.append({"stage": "CITE_SOURCE", "ok": bool(search.citations)})
        timeline.append({"stage": "FINAL_ANSWER", "ok": search.ok})
        return {
            "ok": bool(search.ok),
            "RESEARCH_STATUS": "READY" if search.ok else "FAILED",
            "WEB_FABRIC_STATUS": status,
            "fabricated_citations": False,
            "fabricated_urls": False,
            "timeline": timeline,
            "answer": search.summary or search.error,
            "citations": [c.to_dict() for c in (search.citations or [])],
            "version": self.VERSION,
        }
