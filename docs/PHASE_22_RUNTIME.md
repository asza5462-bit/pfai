# PHASE 22 — Production Runtime

## Purpose

`ProductionRuntime` is the single coherent execution path over existing fabrics. It does **not** rewrite UnifiedAICore, AgentExecutionEngine, Scheduler, Skill Fabric, Tool Fabric, MCP, Sandbox, Learning, or Autonomous Training.

## Flow

```
User Request
  → Authentication (caller / require_owner)
  → Authorization (server-side; client role fields stripped)
  → Intent / Capability routing (UnifiedIntelligenceLoop)
  → Task decomposition / planning
  → Skill selection (SkillRegistry2 — no self-elevation)
  → Tool selection (ToolFabric / MCP — AuthorizedExecutor)
  → Model routing (ModelRouter — no silent active replacement)
  → AgentExecutionEngine | UnifiedAICore
  → Tool/MCP execution + Sandbox where required
  → Result validation
  → Observability
  → Memory / learning candidate (no auto-activation)
  → Final response (response_kind + safe progress)
```

## Entry points

| Surface | Path |
|---------|------|
| Unified chat | `POST /chat` → `ELITE.production.handle` |
| Command Chat UI (complex) | `POST /chat/message` → ProductionRuntime when multi-capability |
| Command Chat UI (ops tools) | `POST /chat/message` → CommandAgent |
| Diagnostics | `GET /runtime/status`, `/runtime/capabilities`, `/runtime/health`, `/system/status` |
| Phase status | `GET /platform/phase22/status` |

## Response kinds

`answer_only` · `plan` · `tool_execution` · `code_execution` · `research` · `agent_execution` · `authorization_rejection`

## Progress (UI-safe)

Understanding → Planning → Selecting capabilities → Executing → Validating → Completed

No secrets, env vars, or internal security metadata in progress labels.

## Configuration honesty

| Signal | Default until owner config |
|--------|----------------------------|
| `WEB_FABRIC_STATUS` | `NOT_CONFIGURED` |
| `EMAIL_DELIVERY_STATUS` | `TEST_ONLY` |
| `SANDBOX_STATUS` | `READY_BOUNDED` |

## Next phase

`PHASE_23_ALLOWED=false` always from this runtime.
