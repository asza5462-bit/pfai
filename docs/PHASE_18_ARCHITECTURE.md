# PHASE 18 — Architecture

## Purpose

Authorized Web & Application Engineering Fabric for PFAI.

PFAI may build, inspect, test, secure, debug, maintain, and improve applications and websites **only** when they are:

1. PFAI-owned assets, or
2. Explicitly registered in `TargetRegistry`, with
3. Owner-declared authorization and scope.

This is **not** an unrestricted hacking or Internet scanning system.

## Components

| Component | Module | Role |
|-----------|--------|------|
| TargetRegistry (schema v2) | `engineering/target_registry.py` | Versioned registry; DENY default |
| ScopeEnforcementLayer | `engineering/scope_enforcement.py` | Host/path/port/method/action gates |
| ApplicationEngineering | `engineering/application_engineering.py` | Requirements → versioned artifact |
| Adapters | `engineering/adapters.py` | Python/FastAPI, Node, React, Next.js, DB, static, fullstack |
| CodingAgentBridge | `engineering/coding_agent_bridge.py` | Inspect/search/modify + changeset audit |
| Phase18SecurityAnalysis | `engineering/phase18_security.py` | Expanded defensive analysis |
| RemediationEngine | `engineering/remediation_engine.py` | DETECT→…→AUDIT pipeline |
| AuthorizedWebFabricOps | `engineering/authorized_web_ops.py` | Registry-gated HTTP/API/crawl |
| Phase18ChatFabric | `engineering/phase18_chat.py` | Arabic/English unified chat routes |
| EngineeringMetrics | `engineering/engineering_metrics.py` | Observability without secrets |
| Skills / Gates | `phase18_skills.py` / `phase18_gates.py` | Tool fabric + quality gate |

## Pipelines

### Application build

`understand → architecture → structure → generate → auth stubs → tests → docs → static checks → test → optional safe fix → retest → versioned artifact`

### Security remediation

`DETECT → CLASSIFY → EXPLAIN → PROPOSE FIX → OWNER/AUTHORIZATION CHECK → APPLY FIX → TEST → SECURITY RECHECK → REGRESSION TEST → VERSION → AUDIT`

### Authorized web ops

`resolve target → verify registration → verify authorization → verify scope → verify allowed action → verify environment → audit → bounded execute → evidence → stop at boundary`

## Authorization invariants

- Default authorization: **DENY**
- A URL in chat never authorizes
- Client-provided roles never authorize
- Model output never authorizes
- Skills/tools never self-elevate
- Production targets require explicit owner approval
- Training/model updates never modify authorization rules

## Implemented adapters (honest)

- `static_website` (HTML/CSS/JS)
- `fastapi_python` (FastAPI-style backend)
- `nodejs_rest` (Node HTTP API skeleton)
- `react_frontend`
- `nextjs` (App Router skeleton)
- `database_backed` (SQL schema + parameterized repo stub)
- `fullstack`

Unsupported frameworks are **not** claimed.
