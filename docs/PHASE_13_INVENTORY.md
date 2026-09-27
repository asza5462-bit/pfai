# PHASE 13 Forensic Inventory (pre-change)

Generated before Phase 13 behavior changes. Evidence from repository paths and prior audit.

## Phase 11 (autonomous training / production model)

| Component | Path | Notes |
|-----------|------|-------|
| AutonomousTrainingOrchestrator | `app/pfai/longevity/autonomous_training/orchestrator.py` | REAL |
| ProductionQualityGate | `.../production_validation.py` | REAL |
| ModelRegistry + LKG | `.../model_registry.py` | REAL |
| PromotionHistory | `.../promotion_history.py` | REAL append-only |
| Rollback | `.../rollback.py` | history-based resolve |
| TrainingSafetyIsolation | `.../isolation.py` | blocks auth/secrets mutation |
| Verified artifacts | `data/longevity/training_phase9_verify/` | model-v0007 ACTIVE+ready; model-v0001 previous LKG |

## Phase 12 (elite skill fabric)

| Component | Path | Classification |
|-----------|------|----------------|
| SkillRegistry2 | `app/pfai/elite/skill_registry_v2.py` | REAL |
| SkillDiscovery | `app/pfai/elite/discovery.py` | REAL |
| SkillComposer | `app/pfai/elite/composer.py` | REAL |
| Elite library (~76) | `app/pfai/elite/elite_library.py` | REAL deterministic handlers |
| ToolFabric | `app/pfai/elite/tool_fabric.py` | REAL (+ legacy merge) |
| MCPAdapter | `app/pfai/elite/mcp_adapter.py` | REAL untrusted-default |
| Sandbox | `app/pfai/elite/sandbox.py` | REAL bounded |
| EliteOrchestrator /chat | `app/pfai/elite/unified_orchestrator.py` + `api.py` | REAL |
| SkillLearningBridge | `app/pfai/elite/skill_learning.py` | REAL |
| Legacy SkillRegistry | `app/pfai/skills/registry.py` | REAL invoke bridge |

## Platform core

| Component | Path |
|-----------|------|
| ModelRouter | `app/pfai/model_router.py` |
| ProviderRegistry | `app/pfai/longevity/provider_registry.py` |
| ToolRouter (legacy) | `app/pfai/tool_router.py` |
| AuthorizedExecutor / ActionPermissionGate | `app/pfai/authorized_execution.py` |
| OwnerAuth + Email OTP | `app/pfai/owner_auth.py` |
| EmailProvider | `app/pfai/email_provider.py` (Mock + SMTP; mock default) |
| SelfCheck / SelfHeal | `app/pfai/self_check.py` |
| Orchestrator (PHASE 4) | `app/pfai/orchestrator.py` |
| Migrations | `app/pfai/longevity/migrations.py` |
| Audit (authz / training) | `authorized_execution.py`, `longevity/autonomous_training/audit.py` |
| LTM / Knowledge | `memory_system.py`, `knowledge_layer.py`, `longevity/durable_learning.py` |

## Mock / Echo-only paths (current)

- `MockEmailProvider` default when `PFAI_EMAIL_PROVIDER` unset
- `EchoProvider` / `MockCommandProvider` roles in ModelRouter defaults
- `api.py` may bind `runtime.model` as default (can surface AnthropicProvider if configured)
- Elite skill handlers: original deterministic implementations (not remote LLM bodies)
- MCP without owner trust: denied (safe)

## Production-capable paths (current)

- Phase 11 LoRA checkpoint serving for model-v0007 (local)
- SMTP email when `PFAI_EMAIL_PROVIDER=smtp` + host/from configured
- transformers_local / local / open_weight / openai_compatible adapters in ProviderRegistry
- ToolFabric + AuthorizedExecutor gated tools
- ProductionQualityGate + promotion/rollback history

## Prior audit warnings (to address in Phase 13)

1. Email OTP delivery Mock in default env — need fail-closed production mode + API provider
2. ModelRouter default can bind commercial adapter — ensure optional, capability-driven, truthful unavailable
3. No WEB/INFORMATION skills — add real web fabric with WEB_PROVIDER_UNAVAILABLE
4. Skill learning log may be empty until traffic
5. Discovery ranking quality
6. Process-level immutability (not OS WORM)
7. Mock-heavy tests ≠ GPU/provider proof

## Phase 13 policy

- Preserve Phase 11/12 artifacts and tests
- No deploy / no remote push / no Phase 14
- Prefer adapters + honest NOT_CONFIGURED over fakes
