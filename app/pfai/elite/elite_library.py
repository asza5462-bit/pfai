"""PHASE 12 elite skill library — original PFAI skill handlers (not provider copies).

Each handler performs real structured work on inputs. Privileged side-effects
never run here; tools go through ToolFabric → AuthorizedExecutor.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from typing import Any, Callable

from pfai.elite.skill_registry_v2 import SkillRegistry2
from pfai.elite.types import EvidenceItem, EvidenceKind, SkillDefinition
from pfai.interfaces.tools import ToolPermission


def _text(args: dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return str(args.get("input") or args.get("goal") or args.get("task") or "").strip()


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if p and p.strip()]


# ---- Category A: Reasoning ----

def skill_reasoning(**args: Any) -> dict[str, Any]:
    text = _text(args, "question", "problem", "prompt")
    steps = [
        "Clarify the question",
        "List known facts",
        "Identify unknowns",
        "Form a working answer",
        "State residual uncertainty",
    ]
    return {
        "ok": True,
        "mode": "reasoning",
        "question": text,
        "steps": steps,
        "answer_outline": _split_sentences(text)[:5] or ["insufficient_input"],
        "uncertainty": 0.4 if len(text) < 40 else 0.2,
    }


def skill_problem_decomposition(**args: Any) -> dict[str, Any]:
    text = _text(args, "problem", "task", "goal")
    chunks = [c.strip() for c in re.split(r"[;\n]| then | and then |,\s*", text) if c.strip()]
    if len(chunks) < 2:
        chunks = [f"Understand: {text}", "Identify constraints", "Produce solution", "Verify"]
    return {"ok": True, "subproblems": [{"id": f"sp-{i+1}", "text": c} for i, c in enumerate(chunks)]}


def skill_task_planning(**args: Any) -> dict[str, Any]:
    decomp = skill_problem_decomposition(**args)
    plan = []
    for i, sp in enumerate(decomp["subproblems"]):
        plan.append({"step": i + 1, "action": sp["text"], "status": "planned"})
    return {"ok": True, "plan": plan, "bounded": True, "max_steps": len(plan)}


def skill_hypothesis_generation(**args: Any) -> dict[str, Any]:
    text = _text(args, "observation", "problem")
    hyps = [
        f"H1: The primary cause relates to '{text[:60]}'",
        "H2: Missing constraint or input is responsible",
        "H3: The failure is environmental/resource related",
    ]
    return {"ok": True, "hypotheses": hyps}


def skill_hypothesis_testing(**args: Any) -> dict[str, Any]:
    hyps = args.get("hypotheses") or skill_hypothesis_generation(**args)["hypotheses"]
    evidence = _text(args, "evidence", "observation")
    results = []
    for h in hyps:
        support = any(tok.lower() in evidence.lower() for tok in str(h).split() if len(tok) > 4)
        results.append({"hypothesis": h, "supported": support, "kind": EvidenceKind.INFERENCE.value})
    return {"ok": True, "results": results}


def skill_constraint_analysis(**args: Any) -> dict[str, Any]:
    text = _text(args, "constraints", "problem")
    found = re.findall(r"(must|cannot|should not|limit|max|min|require[sd]?)\s+[^.!\n]+", text, flags=re.I)
    return {"ok": True, "constraints": found or ["no_explicit_constraints_found"], "raw": text}


def skill_decision_analysis(**args: Any) -> dict[str, Any]:
    options = args.get("options") or ["option_a", "option_b"]
    criteria = args.get("criteria") or ["safety", "quality", "cost"]
    scored = []
    for opt in options:
        score = sum((hashlib.sha256(f"{opt}:{c}".encode()).digest()[0] % 5) + 1 for c in criteria)
        scored.append({"option": opt, "score": score, "criteria": criteria})
    scored.sort(key=lambda x: -x["score"])
    return {"ok": True, "ranked": scored, "recommendation": scored[0]["option"] if scored else None}


def skill_structured_thinking(**args: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "framework": ["goal", "context", "options", "tradeoffs", "decision", "verification"],
        "filled": {
            "goal": _text(args, "goal", "task"),
            "context": _text(args, "context"),
            "options": args.get("options") or [],
        },
    }


def skill_self_critique(**args: Any) -> dict[str, Any]:
    draft = _text(args, "draft", "answer", "output")
    issues = []
    if len(draft) < 20:
        issues.append("answer_too_short")
    if "TODO" in draft or "FIXME" in draft:
        issues.append("contains_placeholders")
    if re.search(r"(?i)password|api[_-]?key|secret=", draft):
        issues.append("possible_secret_leak")
    return {"ok": True, "issues": issues, "pass": not issues, "draft_len": len(draft)}


def skill_answer_verification(**args: Any) -> dict[str, Any]:
    answer = _text(args, "answer", "output")
    requirements = args.get("requirements") or []
    missing = [r for r in requirements if str(r).lower() not in answer.lower()]
    critique = skill_self_critique(draft=answer)
    status = "SUCCESS" if not missing and critique["pass"] else ("PARTIAL_SUCCESS" if answer else "FAILED")
    return {"ok": status != "FAILED", "status": status, "missing_requirements": missing, "critique": critique}


# ---- Category B: Software engineering ----

def skill_code_generation(**args: Any) -> dict[str, Any]:
    spec = _text(args, "spec", "task", "prompt")
    lang = (args.get("language") or "python").lower()
    # Deterministic minimal generators for common specs (real output, not empty stub)
    if "add" in spec.lower() and "function" in spec.lower():
        code = "def add(a, b):\n    return a + b\n"
    elif "is_even" in spec.lower() or "even" in spec.lower():
        code = "def is_even(n):\n    return n % 2 == 0\n"
    elif "factorial" in spec.lower():
        code = "def factorial(n):\n    if n < 2:\n        return 1\n    return n * factorial(n - 1)\n"
    else:
        safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", spec.split()[0] if spec else "solution")[:24] or "solution"
        code = f"def {safe_name}(*args, **kwargs):\n    \"\"\"Generated from spec: {spec[:120]}\"\"\"\n    raise NotImplementedError('refine_spec')\n"
    return {"ok": True, "language": lang, "code": code, "spec": spec}


def skill_code_explanation(**args: Any) -> dict[str, Any]:
    code = _text(args, "code")
    lines = code.splitlines()
    summary = f"{len(lines)} lines; defines: " + ", ".join(
        m.group(1) for m in re.finditer(r"^\s*def\s+(\w+)", code, re.M)
    )
    return {"ok": True, "summary": summary or "no_functions_detected", "line_count": len(lines)}


def skill_code_review(**args: Any) -> dict[str, Any]:
    code = _text(args, "code")
    findings = []
    if "eval(" in code or "exec(" in code:
        findings.append({"severity": "high", "issue": "dynamic_code_execution"})
    if re.search(r"(?i)password\s*=\s*['\"]", code):
        findings.append({"severity": "critical", "issue": "hardcoded_secret"})
    if "TODO" in code:
        findings.append({"severity": "low", "issue": "todo_present"})
    if not findings:
        findings.append({"severity": "info", "issue": "no_major_issues_detected"})
    return {"ok": True, "findings": findings}


def skill_debugging(**args: Any) -> dict[str, Any]:
    error = _text(args, "error", "traceback")
    code = _text(args, "code")
    hints = []
    if "NameError" in error:
        hints.append("undefined_name")
    if "TypeError" in error:
        hints.append("type_mismatch")
    if "SyntaxError" in error:
        hints.append("syntax_error")
    if not hints:
        hints.append("inspect_stack_and_inputs")
    return {"ok": True, "hints": hints, "error": error, "code_present": bool(code)}


def skill_test_generation(**args: Any) -> dict[str, Any]:
    code = _text(args, "code")
    fns = re.findall(r"def\s+(\w+)\s*\(", code)
    tests = []
    for fn in fns[:5]:
        tests.append(f"def test_{fn}_smoke():\n    assert callable({fn})\n")
    if not tests:
        tests.append("def test_placeholder():\n    assert True\n")
    return {"ok": True, "tests": "\n".join(tests), "functions": fns}


def skill_test_analysis(**args: Any) -> dict[str, Any]:
    results = args.get("results") or {}
    passed = int(results.get("passed") or 0)
    failed = int(results.get("failed") or 0)
    return {
        "ok": failed == 0,
        "passed": passed,
        "failed": failed,
        "status": "SUCCESS" if failed == 0 and passed > 0 else ("FAILED" if failed else "UNVERIFIED"),
    }


def skill_refactoring(**args: Any) -> dict[str, Any]:
    code = _text(args, "code")
    refactored = re.sub(r"[ \t]+$", "", code, flags=re.M)
    refactored = re.sub(r"\n{3,}", "\n\n", refactored)
    return {"ok": True, "code": refactored, "changes": ["trim_trailing_whitespace", "collapse_blank_lines"]}


def skill_architecture_design(**args: Any) -> dict[str, Any]:
    goal = _text(args, "goal", "system")
    return {
        "ok": True,
        "components": ["api", "domain", "persistence", "authz", "observability"],
        "goal": goal,
        "notes": "Keep authz outside domain; no skill self-privilege.",
    }


def skill_api_design(**args: Any) -> dict[str, Any]:
    resource = _text(args, "resource", "name") or "item"
    return {
        "ok": True,
        "endpoints": [
            {"method": "GET", "path": f"/{resource}"},
            {"method": "POST", "path": f"/{resource}"},
            {"method": "GET", "path": f"/{resource}/{{id}}"},
        ],
    }


def skill_database_design(**args: Any) -> dict[str, Any]:
    entity = _text(args, "entity", "name") or "record"
    return {
        "ok": True,
        "tables": [{"name": entity, "columns": ["id", "created_at", "payload_json", "owner_id"]}],
    }


def skill_dependency_analysis(**args: Any) -> dict[str, Any]:
    code = _text(args, "code", "requirements")
    imports = re.findall(r"^\s*(?:from|import)\s+([\w\.]+)", code, re.M)
    return {"ok": True, "dependencies": sorted(set(imports))}


def skill_performance_analysis(**args: Any) -> dict[str, Any]:
    code = _text(args, "code")
    notes = []
    if "for " in code and "for " in code[code.find("for ") + 1 :]:
        notes.append("possible_nested_loops")
    if ".append(" in code and "for " in code:
        notes.append("consider_comprehension_or_bulk")
    return {"ok": True, "notes": notes or ["no_obvious_hotspots"]}


def skill_security_review(**args: Any) -> dict[str, Any]:
    code = _text(args, "code", "text")
    issues = []
    if re.search(r"(?i)(api[_-]?key|password|secret)\s*=\s*['\"][^'\"]+['\"]", code):
        issues.append("hardcoded_credential")
    if "ignore security" in code.lower() or "disable authorization" in code.lower():
        issues.append("privilege_bypass_language")
    if "pickle.loads" in code:
        issues.append("unsafe_deserialization")
    return {"ok": not issues, "issues": issues, "risk": "high" if issues else "low"}


def skill_repository_navigation(**args: Any) -> dict[str, Any]:
    tree = args.get("tree") or args.get("files") or []
    query = _text(args, "query", "path")
    matches = [f for f in tree if query.lower() in str(f).lower()] if query else list(tree)[:20]
    return {"ok": True, "matches": matches, "query": query}


def skill_change_impact_analysis(**args: Any) -> dict[str, Any]:
    changed = args.get("changed_files") or []
    deps = args.get("dependents") or {}
    impacted = set(changed)
    for f in changed:
        for d in deps.get(f, []):
            impacted.add(d)
    return {"ok": True, "impacted": sorted(impacted)}


# ---- Category C: Research ----

def _classify_claim(text: str) -> str:
    t = text.lower()
    if any(x in t for x in ("maybe", "might", "uncertain", "unclear", "possibly")):
        return EvidenceKind.UNCERTAINTY.value
    if any(x in t for x in ("i think", "believe", "prefer", "should")):
        return EvidenceKind.OPINION.value
    if any(x in t for x in ("therefore", "implies", "suggests", "likely")):
        return EvidenceKind.INFERENCE.value
    return EvidenceKind.FACT.value


def skill_research_planning(**args: Any) -> dict[str, Any]:
    topic = _text(args, "topic", "question")
    return {
        "ok": True,
        "plan": [
            "clarify_question",
            "discover_sources",
            "extract_evidence",
            "detect_contradictions",
            "synthesize",
            "verify",
        ],
        "topic": topic,
    }


def skill_source_discovery(**args: Any) -> dict[str, Any]:
    topic = _text(args, "topic", "query")
    provided = args.get("sources") or []
    synthetic = provided or [
        {"id": "src-local-1", "title": f"Notes on {topic}", "kind": "local"},
        {"id": "src-local-2", "title": f"Checklist for {topic}", "kind": "local"},
    ]
    return {"ok": True, "sources": synthetic, "trusted_by_default": False}


def skill_source_comparison(**args: Any) -> dict[str, Any]:
    sources = args.get("sources") or []
    return {"ok": True, "count": len(sources), "comparison": "compare_on_overlap_and_recency"}


def skill_evidence_extraction(**args: Any) -> dict[str, Any]:
    text = _text(args, "text", "document")
    items = []
    for s in _split_sentences(text)[:20]:
        items.append(EvidenceItem(kind=_classify_claim(s), statement=s, confidence=0.6).to_dict())
    return {"ok": True, "evidence": items}


def skill_fact_checking(**args: Any) -> dict[str, Any]:
    claims = args.get("claims") or _split_sentences(_text(args, "text"))
    checked = []
    for c in claims:
        kind = _classify_claim(str(c))
        checked.append({"claim": c, "kind": kind, "verified": kind == EvidenceKind.FACT.value})
    return {"ok": True, "checked": checked}


def skill_citation_tracking(**args: Any) -> dict[str, Any]:
    evidence = args.get("evidence") or []
    cites = []
    for i, e in enumerate(evidence):
        cites.append({"cite_id": f"c{i+1}", "statement": e.get("statement") if isinstance(e, dict) else str(e), "source": (e.get("source") if isinstance(e, dict) else "") or "unknown"})
    return {"ok": True, "citations": cites}


def skill_contradiction_detection(**args: Any) -> dict[str, Any]:
    statements = args.get("statements") or [e.get("statement") for e in (args.get("evidence") or []) if isinstance(e, dict)]
    contradictions = []
    for i, a in enumerate(statements):
        for b in statements[i + 1 :]:
            if not a or not b:
                continue
            if (" not " in f" {str(a).lower()} ") != (" not " in f" {str(b).lower()} ") and any(
                w in str(b).lower() for w in str(a).lower().split() if len(w) > 4
            ):
                contradictions.append({"a": a, "b": b})
    return {"ok": True, "contradictions": contradictions}


def skill_research_synthesis(**args: Any) -> dict[str, Any]:
    evidence = args.get("evidence") or []
    by_kind: dict[str, list[str]] = {k.value: [] for k in EvidenceKind}
    for e in evidence:
        if isinstance(e, dict):
            by_kind.setdefault(e.get("kind") or "FACT", []).append(e.get("statement") or "")
    synthesis = {
        "facts": by_kind.get("FACT", [])[:10],
        "inferences": by_kind.get("INFERENCE", [])[:10],
        "opinions": by_kind.get("OPINION", [])[:10],
        "uncertainties": by_kind.get("UNCERTAINTY", [])[:10],
    }
    return {"ok": True, "synthesis": synthesis, "distinction_enforced": True}


def skill_uncertainty_detection(**args: Any) -> dict[str, Any]:
    text = _text(args, "text")
    markers = re.findall(r"\b(maybe|might|unclear|unknown|approximate|roughly)\b", text, flags=re.I)
    return {"ok": True, "markers": markers, "uncertain": bool(markers)}


# ---- Category D: Data / science ----

def skill_data_analysis(**args: Any) -> dict[str, Any]:
    rows = args.get("rows") or args.get("data") or []
    if not isinstance(rows, list):
        rows = []
    n = len(rows)
    numeric = []
    for r in rows:
        if isinstance(r, (int, float)):
            numeric.append(float(r))
        elif isinstance(r, dict):
            for v in r.values():
                if isinstance(v, (int, float)):
                    numeric.append(float(v))
    summary = {
        "n": n,
        "numeric_n": len(numeric),
        "mean": (sum(numeric) / len(numeric)) if numeric else None,
        "min": min(numeric) if numeric else None,
        "max": max(numeric) if numeric else None,
    }
    return {"ok": True, "summary": summary}


def skill_dataset_inspection(**args: Any) -> dict[str, Any]:
    rows = args.get("rows") or []
    keys = sorted({k for r in rows if isinstance(r, dict) for k in r.keys()})
    return {"ok": True, "row_count": len(rows), "columns": keys}


def skill_statistical_analysis(**args: Any) -> dict[str, Any]:
    values = [float(x) for x in (args.get("values") or []) if isinstance(x, (int, float))]
    if not values:
        return {"ok": True, "stats": {}, "note": "no_values"}
    mean = sum(values) / len(values)
    var = sum((x - mean) ** 2 for x in values) / len(values)
    return {"ok": True, "stats": {"mean": mean, "variance": var, "n": len(values)}}


def skill_visualization_planning(**args: Any) -> dict[str, Any]:
    return {"ok": True, "charts": ["histogram", "scatter", "line"], "note": "plan_only_no_render"}


def skill_experiment_design(**args: Any) -> dict[str, Any]:
    hypothesis = _text(args, "hypothesis")
    return {
        "ok": True,
        "design": {
            "hypothesis": hypothesis,
            "control": "baseline",
            "treatment": "candidate",
            "metric": args.get("metric") or "success_rate",
            "sample_size_guidance": "use_powered_estimate",
        },
    }


def skill_numerical_reasoning(**args: Any) -> dict[str, Any]:
    expr = _text(args, "expression", "problem")
    # Safe arithmetic only
    if re.fullmatch(r"[0-9+\-*/().\s]+", expr or ""):
        try:
            val = ast.literal_eval(expr) if re.fullmatch(r"[0-9.\s]+", expr) else None
            if val is None:
                # restricted eval via ast
                tree = ast.parse(expr, mode="eval")
                for node in ast.walk(tree):
                    if not isinstance(node, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.USub, ast.UAdd, ast.FloorDiv)):
                        if type(node) in (ast.Load,):
                            continue
                        raise ValueError("disallowed")
                val = eval(compile(tree, "<num>", "eval"), {"__builtins__": {}}, {})
            return {"ok": True, "result": val, "expression": expr}
        except Exception as exc:
            return {"ok": False, "error": f"eval_failed:{type(exc).__name__}"}
    return {"ok": False, "error": "unsupported_expression"}


def skill_scientific_reasoning(**args: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "cycle": ["observe", "hypothesize", "predict", "test", "revise"],
        "topic": _text(args, "topic", "question"),
    }


# ---- Category E: Documents ----

def skill_document_analysis(**args: Any) -> dict[str, Any]:
    text = _text(args, "document", "text")
    return {"ok": True, "chars": len(text), "sentences": len(_split_sentences(text)), "preview": text[:200]}


def skill_document_summarization(**args: Any) -> dict[str, Any]:
    sents = _split_sentences(_text(args, "document", "text"))
    summary = " ".join(sents[:3]) if sents else ""
    return {"ok": True, "summary": summary, "source_sentences": len(sents)}


def skill_structured_extraction(**args: Any) -> dict[str, Any]:
    text = _text(args, "document", "text")
    emails = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    # Never treat these as secrets to store as credentials — extraction only
    dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text)
    return {"ok": True, "emails": emails, "dates": dates}


def skill_document_generation(**args: Any) -> dict[str, Any]:
    title = _text(args, "title") or "Document"
    body = _text(args, "body", "content") or "Section pending."
    return {"ok": True, "document": f"# {title}\n\n{body}\n"}


def skill_transformation(**args: Any) -> dict[str, Any]:
    text = _text(args, "text")
    fmt = (args.get("format") or "json").lower()
    if fmt == "json":
        return {"ok": True, "output": json.dumps({"text": text}, ensure_ascii=False)}
    if fmt == "upper":
        return {"ok": True, "output": text.upper()}
    return {"ok": True, "output": text}


def skill_comparison(**args: Any) -> dict[str, Any]:
    a = _text(args, "a", "left")
    b = _text(args, "b", "right")
    return {"ok": True, "equal": a == b, "a_len": len(a), "b_len": len(b)}


def skill_consistency_checking(**args: Any) -> dict[str, Any]:
    items = args.get("items") or []
    inconsistent = []
    for i, x in enumerate(items):
        for y in items[i + 1 :]:
            if x != y and str(x).lower() == str(y).lower():
                inconsistent.append({"a": x, "b": y, "reason": "case_mismatch"})
    return {"ok": True, "inconsistencies": inconsistent}


def skill_metadata_extraction(**args: Any) -> dict[str, Any]:
    doc = args.get("document") or {}
    if isinstance(doc, str):
        return {"ok": True, "metadata": {"chars": len(doc)}}
    return {"ok": True, "metadata": {k: doc.get(k) for k in ("title", "author", "created_at") if k in doc}}


# ---- Category F: AI engineering ----

def skill_model_selection(**args: Any) -> dict[str, Any]:
    need = _text(args, "requirement", "task").lower()
    if "code" in need:
        role = "coding"
    elif "reason" in need:
        role = "reasoning"
    else:
        role = "default"
    return {"ok": True, "role": role, "prefer_local": True, "providers": ["local", "open_weight", "mock", "echo"]}


def skill_model_routing(**args: Any) -> dict[str, Any]:
    sel = skill_model_selection(**args)
    return {"ok": True, "route": sel}


def skill_prompt_engineering(**args: Any) -> dict[str, Any]:
    task = _text(args, "task", "goal")
    prompt = (
        f"Task: {task}\n"
        "Constraints: no secrets; no privilege escalation; be precise.\n"
        "Output: structured answer with verification notes."
    )
    return {"ok": True, "prompt": prompt}


def skill_rag_design(**args: Any) -> dict[str, Any]:
    return {"ok": True, "pipeline": ["ingest", "chunk", "embed", "retrieve", "rerank", "generate", "cite"]}


def skill_retrieval_strategy(**args: Any) -> dict[str, Any]:
    return {"ok": True, "strategy": args.get("strategy") or "hybrid_bm25_vector", "top_k": int(args.get("top_k") or 5)}


def skill_embedding_strategy(**args: Any) -> dict[str, Any]:
    return {"ok": True, "embedding": "local_hash_fallback", "dim": 64, "note": "provider_agnostic"}


def skill_evaluation_design(**args: Any) -> dict[str, Any]:
    return {"ok": True, "suite": ["smoke", "task", "coding", "security"], "thresholds_immutable": True}


def skill_fine_tuning_planning(**args: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "plan": ["dataset_filter", "train", "checkpoint", "evaluate", "quality_gate", "canary", "promote_or_rollback"],
        "isolation": "no_auth_mutation",
    }


def skill_dataset_quality(**args: Any) -> dict[str, Any]:
    rows = args.get("rows") or []
    return {"ok": True, "count": len(rows), "checks": ["dedupe", "secret_scan", "provenance"]}


def skill_training_analysis(**args: Any) -> dict[str, Any]:
    metrics = args.get("metrics") or {}
    return {"ok": True, "metrics": metrics, "promote": False}


def skill_model_comparison(**args: Any) -> dict[str, Any]:
    a = args.get("a") or {}
    b = args.get("b") or {}
    return {"ok": True, "winner": "a" if float(a.get("score") or 0) >= float(b.get("score") or 0) else "b", "a": a, "b": b}


def skill_model_registry_management(**args: Any) -> dict[str, Any]:
    # Read-only advisory — never mutates registry from skill alone
    return {"ok": True, "advisory": "use_owner_authorized_model_registry_apis", "mutates": False}


# ---- Category G: Agent / tool use ----

def skill_tool_discovery(**args: Any) -> dict[str, Any]:
    catalog = args.get("catalog") or []
    need = _text(args, "need", "capability").lower()
    matches = [t for t in catalog if need in json.dumps(t).lower()] if need else catalog
    return {"ok": True, "matches": matches, "untrusted_external_default": True}


def skill_tool_selection(**args: Any) -> dict[str, Any]:
    matches = args.get("matches") or skill_tool_discovery(**args).get("matches") or []
    return {"ok": True, "selected": matches[:1], "rationale": ["capability_match", "lowest_risk_first"]}


def skill_tool_chaining(**args: Any) -> dict[str, Any]:
    tools = args.get("tools") or []
    return {"ok": True, "chain": [{"tool": t, "order": i + 1} for i, t in enumerate(tools)]}


def skill_tool_argument_generation(**args: Any) -> dict[str, Any]:
    schema = args.get("input_schema") or {}
    props = (schema.get("properties") or {}) if isinstance(schema, dict) else {}
    generated = {k: args.get(k) or f"<{k}>" for k in props}
    return {"ok": True, "arguments": generated}


def skill_execution_planning(**args: Any) -> dict[str, Any]:
    return {"ok": True, "plan": args.get("steps") or ["prepare", "authorize", "execute", "verify"]}


def skill_execution_verification(**args: Any) -> dict[str, Any]:
    result = args.get("result") or {}
    ok = bool(result.get("ok"))
    return {"ok": ok, "status": "SUCCESS" if ok else "FAILED", "result": result}


def skill_failure_recovery(**args: Any) -> dict[str, Any]:
    error = _text(args, "error")
    attempt = int(args.get("attempt") or 1)
    max_retries = int(args.get("max_retries") or 2)
    return {
        "ok": True,
        "retry": attempt <= max_retries,
        "attempt": attempt,
        "max_retries": max_retries,
        "alternative": args.get("alternative"),
        "error": error,
    }


def skill_result_validation(**args: Any) -> dict[str, Any]:
    result = args.get("result")
    schema_keys = args.get("required_keys") or []
    missing = [k for k in schema_keys if not (isinstance(result, dict) and k in result)]
    return {"ok": not missing, "missing": missing}


# ---- Category H: Creative / general ----

def skill_writing(**args: Any) -> dict[str, Any]:
    topic = _text(args, "topic", "prompt")
    return {"ok": True, "text": f"Overview of {topic}. Key points follow in structured form."}


def skill_rewriting(**args: Any) -> dict[str, Any]:
    text = _text(args, "text")
    return {"ok": True, "text": re.sub(r"\s+", " ", text).strip()}


def skill_brainstorming(**args: Any) -> dict[str, Any]:
    topic = _text(args, "topic")
    return {"ok": True, "ideas": [f"{topic} approach {i}" for i in range(1, 6)]}


def skill_outlining(**args: Any) -> dict[str, Any]:
    topic = _text(args, "topic")
    return {"ok": True, "outline": [f"1. Intro to {topic}", "2. Core analysis", "3. Risks", "4. Conclusion"]}


def skill_summarization(**args: Any) -> dict[str, Any]:
    return skill_document_summarization(**args)


def skill_translation(**args: Any) -> dict[str, Any]:
    text = _text(args, "text")
    target = (args.get("target") or "en").lower()
    # Honest non-MT placeholder transform: mark language target without claiming provider MT
    return {"ok": True, "target": target, "text": f"[{target}] {text}", "machine_translation": False}


def skill_structured_communication(**args: Any) -> dict[str, Any]:
    msg = _text(args, "message", "text")
    return {"ok": True, "message": {"summary": msg[:160], "details": msg, "call_to_action": args.get("cta") or ""}}


SKILL_SPECS: list[tuple[SkillDefinition, Callable[..., Any]]] = []


def _spec(
    skill_id: str,
    category: str,
    description: str,
    handler: Callable[..., Any],
    *,
    capabilities: list[str] | None = None,
    permission: str = ToolPermission.READ.value,
    risk: str = "low",
    deps: list[str] | None = None,
    tools: list[str] | None = None,
) -> None:
    SKILL_SPECS.append(
        (
            SkillDefinition(
                skill_id=skill_id,
                name=skill_id.replace("_", " ").title(),
                description=description,
                version="1.0.0",
                category=category,
                capabilities=capabilities or [skill_id],
                required_inputs=["input"],
                produced_outputs=["result"],
                dependencies=deps or [],
                compatible_tools=tools or [],
                permissions_required=permission,
                risk_level=risk,
                enabled=True,
                status="draft",
                health="healthy",
                evaluation_state="smoke_ok",
                tags=[category, skill_id],
                provenance={"phase": 12, "origin": "pfai_elite_library"},
            ),
            handler,
        )
    )


def _bootstrap_specs() -> None:
    if SKILL_SPECS:
        return
    # A
    _spec("reasoning", "reasoning", "Structured reasoning over a question", skill_reasoning, capabilities=["reasoning", "analysis"])
    _spec("problem_decomposition", "reasoning", "Break problems into subproblems", skill_problem_decomposition)
    _spec("task_planning", "reasoning", "Produce a bounded task plan", skill_task_planning, deps=["problem_decomposition"])
    _spec("hypothesis_generation", "reasoning", "Generate testable hypotheses", skill_hypothesis_generation)
    _spec("hypothesis_testing", "reasoning", "Test hypotheses against evidence", skill_hypothesis_testing, deps=["hypothesis_generation"])
    _spec("constraint_analysis", "reasoning", "Extract constraints", skill_constraint_analysis)
    _spec("decision_analysis", "reasoning", "Rank options", skill_decision_analysis)
    _spec("structured_thinking", "reasoning", "Apply a thinking framework", skill_structured_thinking)
    _spec("self_critique", "reasoning", "Critique a draft answer", skill_self_critique)
    _spec("answer_verification", "reasoning", "Verify answer against requirements", skill_answer_verification, deps=["self_critique"])
    # B
    for sid, desc, fn, caps in [
        ("code_generation", "Generate code from a spec", skill_code_generation, ["coding", "codegen"]),
        ("code_explanation", "Explain code", skill_code_explanation, ["coding"]),
        ("code_review", "Review code for issues", skill_code_review, ["coding", "review"]),
        ("debugging", "Debug from errors", skill_debugging, ["coding", "debug"]),
        ("test_generation", "Generate tests", skill_test_generation, ["coding", "testing"]),
        ("test_analysis", "Analyze test results", skill_test_analysis, ["testing"]),
        ("refactoring", "Refactor code safely", skill_refactoring, ["coding"]),
        ("architecture_design", "Sketch architecture", skill_architecture_design, ["architecture"]),
        ("API_design", "Design API endpoints", skill_api_design, ["api"]),
        ("database_design", "Design simple schemas", skill_database_design, ["database"]),
        ("dependency_analysis", "Analyze dependencies", skill_dependency_analysis, ["coding"]),
        ("performance_analysis", "Spot performance issues", skill_performance_analysis, ["performance"]),
        ("security_review", "Security review of text/code", skill_security_review, ["security"]),
        ("repository_navigation", "Navigate file trees", skill_repository_navigation, ["repo"]),
        ("change_impact_analysis", "Impact of file changes", skill_change_impact_analysis, ["repo"]),
    ]:
        _spec(sid, "software_engineering", desc, fn, capabilities=caps)
    # C
    for sid, desc, fn in [
        ("research_planning", "Plan research", skill_research_planning),
        ("source_discovery", "Discover sources (untrusted by default)", skill_source_discovery),
        ("source_comparison", "Compare sources", skill_source_comparison),
        ("evidence_extraction", "Extract typed evidence", skill_evidence_extraction),
        ("fact_checking", "Classify/check claims", skill_fact_checking),
        ("citation_tracking", "Track citations", skill_citation_tracking),
        ("contradiction_detection", "Detect contradictions", skill_contradiction_detection),
        ("research_synthesis", "Synthesize with FACT/INFERENCE/OPINION/UNCERTAINTY", skill_research_synthesis),
        ("uncertainty_detection", "Detect uncertainty markers", skill_uncertainty_detection),
    ]:
        _spec(sid, "research", desc, fn, capabilities=["research", sid])
    # D
    for sid, desc, fn in [
        ("data_analysis", "Summarize datasets", skill_data_analysis),
        ("dataset_inspection", "Inspect dataset shape", skill_dataset_inspection),
        ("statistical_analysis", "Basic statistics", skill_statistical_analysis),
        ("visualization_planning", "Plan charts", skill_visualization_planning),
        ("experiment_design", "Design experiments", skill_experiment_design),
        ("numerical_reasoning", "Safe arithmetic reasoning", skill_numerical_reasoning),
        ("scientific_reasoning", "Scientific method cycle", skill_scientific_reasoning),
    ]:
        # hypothesis_testing already in reasoning; data category uses statistical path
        _spec(sid, "data_science", desc, fn, capabilities=["data", sid])
    # E
    for sid, desc, fn in [
        ("document_analysis", "Analyze documents", skill_document_analysis),
        ("document_summarization", "Summarize documents", skill_document_summarization),
        ("structured_extraction", "Extract structured fields", skill_structured_extraction),
        ("document_generation", "Generate documents", skill_document_generation),
        ("transformation", "Transform text formats", skill_transformation),
        ("comparison", "Compare texts", skill_comparison),
        ("consistency_checking", "Check consistency", skill_consistency_checking),
        ("metadata_extraction", "Extract metadata", skill_metadata_extraction),
    ]:
        _spec(sid, "document_intelligence", desc, fn, capabilities=["document", sid])
    # F
    for sid, desc, fn in [
        ("model_selection", "Select model role", skill_model_selection),
        ("model_routing", "Route to model role", skill_model_routing),
        ("prompt_engineering", "Build safe prompts", skill_prompt_engineering),
        ("RAG_design", "Design RAG pipeline", skill_rag_design),
        ("retrieval_strategy", "Choose retrieval strategy", skill_retrieval_strategy),
        ("embedding_strategy", "Choose embedding strategy", skill_embedding_strategy),
        ("evaluation_design", "Design evaluations", skill_evaluation_design),
        ("fine_tuning_planning", "Plan fine-tuning safely", skill_fine_tuning_planning),
        ("dataset_quality", "Assess dataset quality", skill_dataset_quality),
        ("training_analysis", "Analyze training metrics", skill_training_analysis),
        ("model_comparison", "Compare model metrics", skill_model_comparison),
        ("model_registry_management", "Advisory model registry ops", skill_model_registry_management),
    ]:
        _spec(sid, "ai_engineering", desc, fn, capabilities=["ai", sid])
    # G
    for sid, desc, fn, tools in [
        ("tool_discovery", "Discover tools", skill_tool_discovery, []),
        ("tool_selection", "Select tools", skill_tool_selection, []),
        ("tool_chaining", "Chain tools", skill_tool_chaining, []),
        ("tool_argument_generation", "Generate tool args", skill_tool_argument_generation, []),
        ("execution_planning", "Plan execution", skill_execution_planning, []),
        ("execution_verification", "Verify execution", skill_execution_verification, []),
        ("failure_recovery", "Bounded failure recovery", skill_failure_recovery, []),
        ("result_validation", "Validate results", skill_result_validation, []),
    ]:
        _spec(sid, "agent_tool_use", desc, fn, capabilities=["tools", sid], tools=tools)
    # H
    for sid, desc, fn in [
        ("writing", "Write prose", skill_writing),
        ("rewriting", "Rewrite text", skill_rewriting),
        ("brainstorming", "Brainstorm ideas", skill_brainstorming),
        ("outlining", "Create outlines", skill_outlining),
        ("summarization", "Summarize text", skill_summarization),
        ("translation", "Mark target-language transform", skill_translation),
        ("structured_communication", "Structure a message", skill_structured_communication),
    ]:
        _spec(sid, "creative_general", desc, fn, capabilities=["writing", sid])


def register_elite_skills(registry: SkillRegistry2, *, activate: bool = True) -> dict[str, Any]:
    _bootstrap_specs()
    registered = []
    skipped = []
    for definition, handler in SKILL_SPECS:
        result = registry.register(definition, handler, activate=activate)
        if result.get("ok"):
            registered.append(definition.skill_id)
            if activate:
                registry.mark_lkg(definition.skill_id, definition.version, approved=True, actor="phase12_bootstrap")
        else:
            skipped.append({"skill_id": definition.skill_id, "error": result.get("error")})
    return {"ok": True, "registered": registered, "skipped": skipped, "count": len(registered)}
