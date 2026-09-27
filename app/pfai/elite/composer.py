"""PHASE 12/13 SkillComposer — auditable multi-skill execution graphs with safety checks."""
from __future__ import annotations

from typing import Any

from pfai.elite.discovery import SkillDiscoveryEngine
from pfai.elite.skill_registry_v2 import SkillRegistry2
from pfai.elite.types import CompositionNode, RiskLevel, SkillGraph, new_id
from pfai.interfaces.skills import SkillContext
from pfai.interfaces.tools import ToolPermission


_TEMPLATES: dict[str, list[str]] = {
    "research": [
        "research_planning",
        "web_search",
        "source_discovery",
        "evidence_extraction",
        "contradiction_detection",
        "research_synthesis",
        "answer_verification",
    ],
    "web": [
        "web_search",
        "web_fetch",
        "source_verification",
        "citation_tracking",
        "research_synthesis",
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

_RISK_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_PERM_RANK = {
    ToolPermission.READ.value: 0,
    ToolPermission.LOW_RISK_WRITE.value: 1,
    ToolPermission.HIGH_RISK_WRITE.value: 2,
    ToolPermission.PRODUCTION.value: 3,
    ToolPermission.SECRETS.value: 4,
    ToolPermission.DATA_DELETE.value: 4,
}


class SkillComposer:
    def __init__(self, registry: SkillRegistry2, discovery: SkillDiscoveryEngine | None = None) -> None:
        self.registry = registry
        self.discovery = discovery or SkillDiscoveryEngine(registry)
        self.max_composite_risk = RiskLevel.HIGH.value

    def compose(self, task: str, *, context: dict[str, Any] | None = None) -> SkillGraph:
        discovered = self.discovery.discover(task, context=context, limit=12)
        intents = discovered.get("intents") or ["reason"]
        primary = intents[0]
        # Web-ish tasks prefer web template
        task_l = (task or "").lower()
        if any(w in task_l for w in ("web search", "search the web", "fetch url", "http://", "https://")):
            primary = "web"
        template = list(_TEMPLATES.get(primary) or _TEMPLATES["reason"])
        discovered_ids = [c["skill_id"] for c in discovered.get("candidates") or []]
        ordered: list[str] = []
        for sid in template:
            if self.registry.get(sid):
                ordered.append(sid)
        for sid in discovered_ids:
            if sid not in ordered and self.registry.get(sid) and len(ordered) < 10:
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
        graph = SkillGraph(
            graph_id=new_id("graph"),
            nodes=nodes,
            rationale=[
                f"primary_intent:{primary}",
                f"template:{primary}",
                f"discovered:{discovered_ids[:5]}",
            ],
        )
        validation = self.validate_composition(graph, actor_permission=ToolPermission.READ.value)
        if not validation.get("ok"):
            graph.rationale.append(f"validation_warning:{validation.get('error')}")
            # Strip privilege-elevating / cyclic nodes rather than elevating
            if validation.get("safe_nodes") is not None:
                allowed = set(validation["safe_nodes"])
                graph.nodes = [n for n in graph.nodes if n.node_id in allowed]
        return graph

    def detect_cycles(self, graph: SkillGraph) -> list[str]:
        by_id = {n.node_id: n for n in graph.nodes}
        visiting: set[str] = set()
        visited: set[str] = set()
        cycles: list[str] = []

        def dfs(nid: str, path: list[str]) -> None:
            if nid in visiting:
                cycles.append(" -> ".join(path + [nid]))
                return
            if nid in visited or nid not in by_id:
                return
            visiting.add(nid)
            for dep in by_id[nid].depends_on:
                dfs(dep, path + [nid])
            visiting.remove(nid)
            visited.add(nid)

        for nid in by_id:
            dfs(nid, [])
        return cycles

    def validate_composition(
        self,
        graph: SkillGraph,
        *,
        actor_permission: str = "read",
        available_tools: list[str] | None = None,
        available_model_caps: list[str] | None = None,
    ) -> dict[str, Any]:
        """Validate deps, permissions, conflicts, tool/model requirements, risk — no privilege elevation."""
        actor_permission = str(actor_permission or "read").lower()
        cycles = self.detect_cycles(graph)
        missing_deps: list[str] = []
        conflicts: list[str] = []
        tool_gaps: list[str] = []
        model_gaps: list[str] = []
        risk_violations: list[str] = []
        privilege_attempts: list[str] = []
        safe_nodes: list[str] = []
        actor_rank = _PERM_RANK.get(actor_permission, 0)
        max_risk = _RISK_RANK.get(self.max_composite_risk, 2)
        seen_skills: set[str] = set()

        for node in graph.nodes:
            d = self.registry.get(node.skill_id, node.skill_version or None)
            if not d:
                missing_deps.append(node.skill_id)
                continue
            # dependency existence
            dep_check = self.registry.validate_dependencies(node.skill_id)
            if not dep_check.get("ok"):
                missing_deps.extend(dep_check.get("missing") or [])
            # privilege: skill cannot require higher than actor
            skill_perm = d.permissions_required or ToolPermission.READ.value
            if _PERM_RANK.get(skill_perm, 0) > actor_rank:
                privilege_attempts.append(f"{node.skill_id}:{skill_perm}")
                continue
            # risk
            if _RISK_RANK.get(str(d.risk_level), 0) > max_risk:
                risk_violations.append(f"{node.skill_id}:{d.risk_level}")
                continue
            # conflicts: same skill twice with different versions
            key = node.skill_id
            if key in seen_skills:
                conflicts.append(f"duplicate_skill:{key}")
            seen_skills.add(key)
            # tools
            for tid in list(d.required_tools or d.compatible_tools or []):
                if available_tools is not None and tid not in available_tools:
                    tool_gaps.append(f"{node.skill_id}:{tid}")
            # model capabilities
            for cap in list(getattr(d, "required_model_capabilities", None) or []):
                if available_model_caps is not None and cap not in available_model_caps:
                    model_gaps.append(f"{node.skill_id}:{cap}")
            safe_nodes.append(node.node_id)

        ok = not cycles and not privilege_attempts and not risk_violations and not missing_deps
        return {
            "ok": ok,
            "cycles": cycles,
            "missing_dependencies": sorted(set(missing_deps)),
            "conflicts": conflicts,
            "tool_gaps": tool_gaps,
            "model_capability_gaps": model_gaps,
            "risk_violations": risk_violations,
            "privilege_attempts": privilege_attempts,
            "safe_nodes": safe_nodes,
            "error": (
                "circular_dependency"
                if cycles
                else "privilege_elevation_blocked"
                if privilege_attempts
                else "risk_limit_exceeded"
                if risk_violations
                else "missing_dependencies"
                if missing_deps
                else ""
            ),
            "composition_cannot_elevate_privileges": True,
        }

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
        actor_permission: str = "READ",
    ) -> dict[str, Any]:
        # Normalize legacy uppercase permission labels
        actor_permission = str(actor_permission or "read").lower()
        if actor_permission == "write":
            actor_permission = ToolPermission.LOW_RISK_WRITE.value
        validation = self.validate_composition(graph, actor_permission=actor_permission)
        plan = {
            "graph": graph.to_dict(),
            "validation": validation,
            "order": [n.node_id for n in self.topological_order(graph)],
        }
        if validation.get("privilege_attempts"):
            return {
                "ok": False,
                "status": "FAILED",
                "error": "privilege_elevation_blocked",
                "graph": graph.to_dict(),
                "plan": plan,
                "trace": [],
                "final": None,
            }
        args = dict(initial_args or {})
        results: dict[str, Any] = {}
        trace: list[dict[str, Any]] = []
        status = "SUCCESS"
        for node in self.topological_order(graph):
            if validation.get("safe_nodes") and node.node_id not in validation["safe_nodes"]:
                trace.append(
                    {
                        "node_id": node.node_id,
                        "skill_id": node.skill_id,
                        "ok": False,
                        "error": "skipped_unsafe_node",
                        "output": None,
                    }
                )
                status = "PARTIAL_SUCCESS"
                continue
            invoke_args = dict(args)
            invoke_args.update(node.args_map)
            # Never pass non-serializable runtime objects into skill args/audit
            invoke_args.pop("_web_fabric", None)
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
                ctx=SkillContext(mode="compose", extras={"graph_id": graph.graph_id, "plan": plan}),
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
            "plan": plan,
            "trace": trace,
            "final": trace[-1]["output"] if trace else None,
        }
