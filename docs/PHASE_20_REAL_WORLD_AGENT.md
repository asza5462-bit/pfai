# PHASE 20 — Real-World Agent & Execution Fabric

## Purpose

Turn the Unified AI Core into a real end-to-end agent execution layer: decompose complex requests, select capabilities/skills/tools/models, execute with dependency awareness, observe, validate, recover within budgets, and record auditable experience — without a second AI brain.

## Architecture

```
USER REQUEST
  → TASK UNDERSTANDING (CapabilityRouter)
  → TASK DECOMPOSITION (TaskDecomposer)
  → PLAN
  → CAPABILITY / SKILL / TOOL / MODEL SELECTION
  → EXECUTION (AgentExecutionEngine, dependency-aware)
  → OBSERVATION
  → VALIDATION (SelfCheckEngine)
  → RECOVERY IF NEEDED (FailureRecovery + bounded remediation)
  → RE-VALIDATION
  → FINAL RESULT
  → EXPERIENCE RECORD (verified only)
  → EVALUATION
```

Chat entry remains `UnifiedIntelligenceLoop`:

- Multi-step / multi-capability requests → `AgentExecutionEngine`
- Simpler turns → `UnifiedAICore`
- Meta intents (train / evaluate / rollback / skill propose) stay bounded; LKG preserved

## Primary modules

| Module | Role |
|--------|------|
| `elite/agent_execution_engine.py` | Multi-step execution engine |
| `elite/task_state.py` | Explicit task state machine |
| `elite/task_decomposer.py` | Capability-driven plan composition |
| `elite/execution_budgets.py` | Hard stops (steps/retries/tools/models/time/depth) |
| `elite/research_workflow.py` | Research stages; honest web status |
| `elite/phase20_skills.py` / `phase20_gates.py` | Skills + evidence gate |
| `elite/unified_intelligence_loop.py` | Routes to engine or core |

## Task state machine

States: `CREATED`, `PLANNING`, `READY`, `RUNNING`, `WAITING`, `VALIDATING`, `RECOVERING`, `COMPLETED`, `FAILED`, `CANCELLED`, `ROLLED_BACK`.

Invalid transitions are rejected. Tasks persist under `data/longevity/elite/agent_tasks/` (or test store paths). Progress percent reflects actual state/step completion (not fabricated).

## Planning & decomposition

Plans are composed from the capability registry templates — not a single hard-coded script. Dependencies are sequential by default; only non-mutating parallel-safe steps may run concurrently.

## Coding / algorithm execution

- Coding: `CodingAgentBridge` inspect/search/architecture + remediation for approved fixes + real pytest when `project_path` exists
- Algorithms: `AlgorithmIntelligence.full_pipeline` with real embedded tests; `BENCHMARK_STATUS=UNAVAILABLE` unless a real benchmark runtime is invoked
- Success requires validation — editing a file alone is not success

## Failure recovery & self-repair

Bounded recovery: capture → classify → retry/alternative within `max_retries` → re-validate → stop if unsafe/exhausted.

Self-repair uses existing remediation (DETECT → DIAGNOSE → PROPOSE → AUTHORIZE → APPLY → TEST → VALIDATE → COMMIT/ROLLBACK). Never modifies owner auth, authorization policy, security boundaries, secrets, or audit policy.

## Research / Web Fabric

`WEB_FABRIC_STATUS=NOT_CONFIGURED` until owner configures a real provider. Research workflow reports limitation; never fabricates citations or URLs. Interface is ready for search → retrieve → filter → verify → compare → synthesize → cite once configured.

## Tool / MCP / model routing

All tools pass discovery → authorization → scope → execution → capture → validation → audit. MCP tools do not bypass authorization. Model selection uses existing `ModelRouter`; unavailable models return explicit capability-unavailable results — never fabricated execution.

## Budgets & performance

Configurable limits: max steps, retries, tool calls, model calls, execution time, nested depth. Exceeding a budget stops safely with preserved state.

Measured latencies: planning, routing, model, tool, execution, validation, recovery, total. Local benchmark writes `data/longevity/elite/phase20_benchmark.json`.

## Learning & autonomous training

Validated completed tasks may record experience. Unverified turns do not enter trusted pathways. Export to training candidates never auto-activates a model and cannot alter security/auth. Preserves `MODEL_V0007` active and `MODEL_V0001` LKG.

## Security

- Client role / privilege fields ignored
- Offensive / unrestricted external testing rejected
- No tool/skill self-elevation
- Secrets scrubbed from audit/observability
- No claim of 100% security

## Observability

Auditable execution traces (task_id, states, plan, selections, validation, retries, final status). Never records passwords, OTPs, API keys, session secrets, or private credentials.

## Configuration

- Engine budgets: `ExecutionBudgets` defaults (24 steps, 2 retries, 40 tool calls, 20 model calls, 120s, depth 4)
- Force-failure hooks for tests: `force_tool_failure`, `force_model_failure`
- Force agent path: context `force_agent_engine=True`
- API: `GET /platform/phase20/status` (owner)

## Limitations

- Web fabric not configured by default
- Sandbox is `READY_BOUNDED`
- No fabricated benchmarks or model execution
- Email remains TEST_ONLY until owner config
- Parallelism only when dependency analysis confirms safety
