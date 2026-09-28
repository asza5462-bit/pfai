# PHASE 19 — Unified AI Core

## Purpose

Unify existing PFAI capabilities into one coherent AI operating core without replacing working subsystems or fabricating availability.

## Architecture

```
USER REQUEST
  → INTENT / TASK ANALYSIS (CapabilityRouter)
  → PLANNING
  → CAPABILITY DISCOVERY
  → SKILL SELECTION (SkillDiscovery + SkillComposer)
  → TOOL SELECTION (ToolFabric / MCP catalog filter)
  → MODEL ROUTING (ModelRouter capability select — honest availability)
  → MEMORY / KNOWLEDGE RETRIEVAL (bounded, verified sources only)
  → EXECUTION (specialized handlers + EliteOrchestrator)
  → OBSERVATION
  → VALIDATION / TESTING (SelfCheckEngine)
  → RESULT
  → LEARNING / EXPERIENCE RECORD (gated; unverified not trusted)
  → EVALUATION
  → OPTIONAL FUTURE TRAINING DATA (never auto-activates; LKG preserved)
```

Primary modules:

| Module | Role |
|--------|------|
| `elite/unified_ai_core.py` | Operating core |
| `elite/capability_router.py` | Multi-label capability routing |
| `elite/algorithm_intelligence.py` | Algorithm analysis + verified templates |
| `elite/unified_intelligence_loop.py` | Chat entry → UnifiedAICore + meta intents |
| `elite/phase19_skills.py` / `phase19_gates.py` | Skills + quality gate |

## Capability routing

Capabilities are discovered from request text + context (not a hard-coded task table). A single request may require many capabilities (coding + algorithms + testing + evaluation + security).

## Skill / tool composition

Uses existing SkillRegistry2, SkillComposer graphs, ToolFabric, and MCPAdapter. Skills cannot self-elevate. Tool execution remains authorization → scope → execute → audit → validate.

## Model routing

Uses existing ModelProvider / ModelRouter. Never hard-codes a commercial provider. Claims availability only when the runtime confirms a bound provider. Echo/mock remain valid for tests.

## Coding / algorithm / security intelligence

- Coding: CodingAgentBridge + ApplicationEngineering + UnifiedCodingWorkflow (existing)
- Algorithms: structured identification, textbook complexity, edge cases, optional optimized templates with **real** embedded tests — **no fabricated benchmarks**
- Security: Phase18SecurityAnalysis + authorized testing gates — URL/chat never authorizes unrestricted external tests

## Web Fabric

`WEB_FABRIC_STATUS=NOT_CONFIGURED` until owner configures a real provider. No fabricated search results.

## Learning & autonomous training

Successful verified turns may record experiences. Training still requires existing quality gates, preserves LKG, and **cannot** modify owner auth, authorization, security policy, permissions, or audit policy.

## Self-improvement

Self-check → diagnosis → bounded proposal → tests → evaluation → version → rollback on regression. No uncontrolled self-modification.

## Security boundaries

Never trust client role fields, URL parameters, localStorage admin flags, or model/skill/tool self-grants. Training cannot alter authorization.

## Limitations

- Web fabric not configured by default
- Sandbox is `READY_BOUNDED` (not full container isolation)
- Algorithm complexity statements are asymptotic classifications, not measured timings
- Security analysis does not claim 100% secure
- Email delivery remains TEST_ONLY until owner SMTP/config
