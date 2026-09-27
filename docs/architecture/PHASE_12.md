# PHASE 12 — Elite AI Skills + Tools + Models Fabric

PFAI is no longer model-centric only. Phase 12 adds a unified fabric:

```
USER → /chat (EliteOrchestrator)
  → intent / mode detection
  → SkillDiscoveryEngine
  → SkillComposer (versioned graph)
  → ModelRouter (local/open-weight/mock/echo)
  → ToolFabric (+ MCP adapter, untrusted by default)
  → AuthorizedExecutor / ActionPermissionGate
  → SelfCheckEngine
  → SkillLearningBridge → (optional) autonomous training experience bridge
  → promotion / rollback (skills + models remain separate authorities)
```

## Security boundary

Skills, tools, and models are **capabilities**, never authorities.
Privileged work must pass `ActionPermissionGate` → `AuthorizedExecutor`.
Training remains isolated from authentication, authorization, secrets, and security policy.

## Packages

- `pfai/elite/` — SkillRegistry2, discovery, composer, tool fabric, MCP, sandbox, unified orchestrator
- Existing `pfai/skills/registry.py` remains the invoke choke-point bridge
- Existing `pfai/tool_router.py`, `pfai/model_router.py`, autonomous training unchanged in authority

## Modes

CHAT, REASON, CODE, RESEARCH, DATA, DOCUMENT, PLAN, SKILL, TOOL, LEARN, EVALUATE, SELF_CHECK, SELF_HEAL

## Non-goals

- No Phase 13
- No deploy / remote push
- No proprietary prompt/weight copying from commercial providers
