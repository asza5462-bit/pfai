# PHASE 22 — Production Integration & Live Web Fabric

## Goal

Integrate existing AI Core, Skill Fabric, Tool Fabric, Agent Execution Engine, Scheduler, Model Router, Learning, Autonomous Training, Security, Observability, and Web Fabric into one production-grade execution path — **without rewriting** those systems.

## Architecture

```
Frontend / API
    │
    ▼
ProductionRuntime (coordinator)
    │
    ├─ AuthN / AuthZ (server-side)
    ├─ UnifiedIntelligenceLoop
    │     ├─ AgentExecutionEngine (complex / multi-step)
    │     └─ UnifiedAICore (simpler turns)
    ├─ Skill Fabric + Tool Fabric + MCP
    ├─ ModelRouter (V0007 active; V0001 LKG)
    ├─ Sandbox (READY_BOUNDED)
    ├─ Web Fabric (honest NOT_CONFIGURED until providers configured)
    ├─ Email abstraction (TEST_ONLY until owner config)
    ├─ Learning → training eligibility (isolated from authz)
    └─ Observability / diagnostics (no secrets)
```

## Modules added / extended

| Module | Role |
|--------|------|
| `elite/production_runtime.py` | Unified coordinator + diagnostics |
| `elite/phase22_skills.py` | Production/web policy skills |
| `elite/phase22_gates.py` | Evidence-derived gate; `PHASE_23_ALLOWED=false` |
| `elite/web_fabric.py` | `WebPolicyGate`, `WebResearchSession`, aliases |
| `elite/task_state.py` | `PLANNED` / `BLOCKED` / `RETRYING` |
| `elite/mcp_adapter.py` | `health` / `discover_capabilities` |
| `api.py` | `/chat` → production; `/runtime/*`; `/platform/phase22/status` |
| `static/assets/chat.js` | Safe execution progress UI |

## Chat routing

- `POST /chat` always uses `ProductionRuntime`.
- `POST /chat/message` uses ProductionRuntime for multi-capability / agent-style requests; CommandAgent remains for operational tools and Coding Academy intents.

## Model routing

Preserves `ModelProvider` / `ModelRouter`. Active production model is `MODEL_V0007` (`production_ready`). LKG `MODEL_V0001` intact. No silent replacement; candidates still require evaluation gates before activation.

## MCP

Untrusted by default. Discovery, capability listing, schema/permission mapping, timeouts, audit, failure refusal without owner trust. Same authorization gates as native tools.

## Sandbox

Bounded process sandbox with CPU/memory/runtime/disk/process/network/output limits as implemented. Diagnostics report `READY_BOUNDED` and `full_container_isolation=false`.

## Learning & autonomous training

Experience → validation → quality filter → provenance → eligibility. Bad experiences do not auto-train. Training cannot modify authn/authz/security policy. Activation only after gates; LKG preserved; rollback ready.

## Observability

Request/task/session IDs, model/skill/tool versions, durations, cache/retry/failure/recovery, final status — with secret scrubbing.

## Configuration

Production email/web credentials must come from environment/secret management — never source, tests, frontend, logs, docs, Git, or API responses.

## Stop conditions honored

No deploy. No remote push. No Phase 23. No fabricated web/benchmarks. No weakened security invariants.
