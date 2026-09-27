"""PHASE 12 SkillComposer — auditable multi-skill execution graphs."""
from __future__ import annotations

from typing import Any

from pfai.elite.discovery import SkillDiscoveryEngine
from pfai.elite.skill_registry_v2 import SkillRegistry2
from pfai.elite.types import CompositionNode, SkillGraph, new_id
from pfai.interfaces.skills import SkillContext


_TEMPLATES: dict[str, list[str]] = {
    "research": [
        "research_planning",
        "source_discovery",
        "evidence_extraction",
        "contradiction_detection",
        "research_synthesis",
        "answer_verification",
    ],
    "code": [
        "repository_navigation",
        "problem_decomposition",
        "code_generation",
        "test_generation",
        "security_review",
        "answer_verification",
    ],
    "reason": [
        "reasoning",
        "task_planning",
        "structured_thinking",
        "self_critique",
        "answer_verification",
    ],
    "data": [
        "dataset_inspection",
        "data_analysis",
        "statistical_analysis",
        "answer_verification",
    ],
    "document": [
        "document_analysis",
        "document_summarization",
        "structured_extraction",
        "answer_verification",
    ],
    "tool": [
        "tool_discovery",
        "tool_selection",
        "execution_planning",
        "execution_verification",
    ],
}


class SkillComposer:
    def __init__(self, registry: SkillRegistry2, discovery: SkillDiscoveryEngine | None = None) -> None:
        self.registry = registry
        self.discovery = discovery or SkillDiscoveryEngine(registry)

    def compose(self, task: str, *, context: dict[str, Any] | None = None) -> SkillGraph:
        discovered = self.discovery.discover(task, context=context, limit=12)
        intents = discovered.get("intents") or ["reason"]
        primary = intents[0]
        template = list(_TEMPLATES.get(primary) or _TEMPLATES["reason"])
        # Prefer discovered skills that also appear in template; fill gaps from template
        discovered_ids = [c["skill_id"] for c in discovered.get("candidates") or []]
        ordered: list[str] = []
        for sid in template:
            if self.registry.get(sid):
                ordered.append(sid)
        # Attach high-scoring extras not already present (bounded)
        for sid in discovered_ids:
            if sid not in ordered and self.registry.get(sid) and len(ordered) < 10:
                # only add if category aligns
                ordered.append(sid)
        nodes: list[CompositionNode] = []
        for i, sid in enumerate(ordered):
            d = self.registry.get(sid)
            nodes.append(
                CompositionNode(
                    node_id=f"n{i+1}",
                    skill_id=sid,
                    skill_version=(d.version if d else ""),
                    depends_on=[f"n{i}"] if i else [],
                )
            )
        return SkillGraph(
            graph_id=new_id("graph"),
            nodes=nodes,
            rationale=[
                f"primary_intent:{primary}",
                f"template:{primary}",
                f"discovered:{discovered_ids[:5]}",
            ],
        )

    def topological_order(self, graph: SkillGraph) -> list[CompositionNode]:
        by_id = {n.node_id: n for n in graph.nodes}
        pending = set(by_id)
        done: list[CompositionNode] = []
        while pending:
            progress = False
            for nid in list(pending):
                node = by_id[nid]
                if all(dep not in pending for dep in node.depends_on):
                    done.append(node)
                    pending.remove(nid)
                    progress = True
            if not progress:
                # cycle / bad deps — fail closed by returning current + remaining in declaration order
                for nid in sorted(pending):
                    done.append(by_id[nid])
                break
        return done

    def execute(
        self,
        graph: SkillGraph,
        *,
        initial_args: dict[str, Any] | None = None,
        approved: bool = False,
        actor: str = "",
        stop_on_failure: bool = True,
    ) -> dict[str, Any]:
        args = dict(initial_args or {})
        results: dict[str, Any] = {}
        trace: list[dict[str, Any]] = []
        status = "SUCCESS"
        for node in self.topological_order(graph):
            invoke_args = dict(args)
            invoke_args.update(node.args_map)
            # pipe prior outputs
            if results:
                invoke_args["prior"] = results
                last = trace[-1]["output"] if trace else None
                if isinstance(last, dict):
                    invoke_args.update({k: v for k, v in last.items() if k not in invoke_args})
            res = self.registry.invoke(
                node.skill_id,
                invoke_args,
                version=node.skill_version or None,
                approved=approved,
                actor=actor,
                ctx=SkillContext(mode="compose", extras={"graph_id": graph.graph_id}),
            )
            step = {
                "node_id": node.node_id,
                "skill_id": node.skill_id,
                "version": node.skill_version,
                "ok": res.ok,
                "error": res.error,
                "output": res.output,
                "meta": res.meta,
            }
            trace.append(step)
            results[node.node_id] = res.output
            if not res.ok:
                status = "FAILED" if stop_on_failure else "PARTIAL_SUCCESS"
                if stop_on_failure:
                    break
        if status == "SUCCESS" and any(not t["ok"] for t in trace):
            status = "PARTIAL_SUCCESS"
        return {
            "ok": status in ("SUCCESS", "PARTIAL_SUCCESS"),
            "status": status,
            "graph": graph.to_dict(),
            "trace": trace,
            "final": trace[-1]["output"] if trace else None,
        }
