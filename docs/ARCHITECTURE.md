# PFAI Architecture

**Mission:** Long-Lived Adaptive AI Platform (20–30 year horizon).  
See `docs/LONGEVITY.md` for the longevity foundation, coupling audit, and port map.

## High-level shape (today + additive ports)

```
Browser (RTL Dashboard + AI Command Chat + Coding Academy)
        │  HTTP + X-Owner-Secret
        ▼
FastAPI (`pfai.api:app`)  — public contracts stable
  ├── /chat/*  → CommandAgent (ops brain)
  │                 └─ coding intents → CodingAgent
  ├── /coding/* → Coding Academy APIs
  ├── ToolRouter (ops + coding tools, Owner Gate on sensitive)
  └── Heart: runtime, continuous, sandbox, memory, curriculum JSON

Longevity ports (PHASE 1 contracts; not all wired yet):
  ProviderRegistry · ModelRouter · LTM · Knowledge Versioning
  Safe Learning Pipeline · MigrationRunner · Export · Backup/DR
  Evaluation compare · Compatibility Layer · Bounded Self-Heal
```

## Platform contracts

| Contract | Package | Notes |
|---|---|---|
| Orchestrator / roles / skills | `pfai.interfaces.*` | Additive orchestration surface |
| Ports (storage/vector/embed/export) | `pfai.interfaces.ports` | Replaceable infrastructure |
| LTM kinds | `pfai.interfaces.memory` | Model-agnostic structured memory |
| Safe learning | `pfai.interfaces.learning` | No prod weight mutation |
| Versioning | `pfai.interfaces.versioning` | Knowledge/config/skill/tool |
| Migration | `pfai.interfaces.migration` | `PFAI_SCHEMA_VERSION` |
| Backup/DR | `pfai.interfaces.backup` | Over existing managers |
| Provider/Model registries | `pfai.interfaces.model` | Vendor-agnostic |
| Eval compare | `pfai.interfaces.evaluation` | Before promote |
| Compat layer | `pfai.interfaces.compat` | Future runtime/DB/provider upgrades |
| Scaffolds | `pfai.longevity.*` | Non-wired reference implementations |

## Coding Intelligence stack

| Component | Module | Role |
|---|---|---|
| Coding Agent | `coding_agent.py` | Learning vs Engineering modes, intent routing |
| Curriculum Engine | `coding_curriculum.py` | Extensible JSON tracks/lessons/projects/knowledge |
| Tutor | `coding_tutor.py` | Paths, hints, exercises, adaptive next |
| Skill Profile | `coding_skill_profile.py` | Assessment, skills, progress, repeated errors |
| Academy Memory | `coding_academy_memory.py` | Durable coding_* facts via MemoryStore |
| Reviewer | `coding_reviewer.py` | Static/security/maintainability review |
| Debugger | `coding_debugger.py` | Progressive debugging trainer |
| Quality Gate | `coding_quality.py` | Never claim untested code works |
| Sandbox | `code_execution_evaluator.py` | Existing isolated Python subprocess |
| Training scaffold | `coding_training_scaffold.py` | Dataset/eval collection; no auto fine-tune |

Curriculum data lives under `configs/coding/` (add tracks without rewriting the engine).

## LLM providers

- **Core runs without any commercial vendor** (Echo / Mock / local openai_compatible)
- Anthropic optional (`ANTHROPIC_API_KEY`) — never a Core requirement
- New providers register via ProviderRegistry (scaffold in `pfai.longevity`)

## Safety

- Sandbox: no secrets, no host FS, no network, rlimits
- Sensitive ops remain Owner-gated
- Fine-tuning never automatic on production
- Self-heal is bounded and rollback-first


## Autonomous Training (PHASE 6)

Weight training is handled only by `pfai.longevity.autonomous_training.AutonomousTrainingOrchestrator`.

Loop: experience → sanitize/validate → immutable dataset version → trigger → backend train → checkpoints → multi-suite evaluation → shadow compare → activate → monitor → rollback.

`DurableSafeLearningPipeline` continues knowledge/memory learning and **does not** mutate model weights.

Training is forbidden from modifying owner authentication, OTP, authorization, secrets, or security policy (see ADR-026).


## PHASE 7 additions

- `TrainingRuntimeDetector` — honest AVAILABLE/PARTIALLY_AVAILABLE/UNAVAILABLE probes
- `ActiveModelRuntime` — activation/rollback switches the served model pointer
- `SkillPackRegistry` — versioned skill packs gated by AuthorizedExecutor
- Learning Control Center — owner UI/API for training/skills observability
