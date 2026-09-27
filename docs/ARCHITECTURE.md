# PFAI Architecture

## High-level shape

```
Browser (RTL Dashboard + AI Command Chat + Coding Academy)
        │  HTTP + X-Owner-Secret
        ▼
FastAPI (`pfai.api:app`)  — public contracts unchanged
  ├── /chat/*  → CommandAgent (ops brain)
  │                 └─ coding intents → CodingAgent
  ├── /coding/* → Coding Academy APIs
  ├── ToolRouter (ops + coding tools, Owner Gate on sensitive)
  └── Heart: runtime, continuous, sandbox, memory, curriculum JSON

Target (additive Orchestrator — phased; PHASE 1 = contracts only):

Chat / Control Center
        │
        ▼
PFAI Orchestrator (coordination only; wraps existing brains)
  ├── Context: MemorySystem + KnowledgeLayer
  ├── Planner (ReasoningCore adapter)
  ├── ModelRouter (role → provider; Local/Mock first; Anthropic optional)
  ├── ToolRouter + SkillRegistry
  ├── Coding / Education / Sandbox (kept)
  ├── Evaluation + Self-check / Self-heal (gated)
  └── Goals + Core runtime
```

## Platform contracts (PHASE 1)

| Contract | Package | Scaffold module | Target phase |
|---|---|---|---|
| OrchestratorRequest/Result | `pfai.interfaces` | `orchestrator.py` | 2 |
| ModelRole / ModelRouter | `pfai.interfaces.model` | `model_router.py` | 2 |
| MemorySystem | `pfai.interfaces.memory` | `memory_system.py` | 3 |
| KnowledgeLayer | `pfai.interfaces.knowledge` | `knowledge_layer.py` | 3 |
| TaskPlanner | `pfai.interfaces.planner` | `task_planner.py` | 4 |
| Skill / SkillRegistry | `pfai.interfaces.skills` | `skills/registry.py` | 5 |
| ToolPermission | `pfai.interfaces.tools` | (maps onto ToolRouter) | 4 |
| EvaluationSuite | `pfai.interfaces.evaluation` | (wrap EvaluationLab) | 7 |
| SelfCheck / SelfHeal | `pfai.interfaces.self_check` | `self_check.py` / `self_heal.py` | 7–8 |
| GoalSystem | `pfai.interfaces.goals` | `goal_system.py` | 9 |

PHASE 1 does **not** wire these into `api.py` or change Dashboard behavior.

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

- Anthropic optional (`ANTHROPIC_API_KEY`)
- OpenAI-compatible / local models via existing `openai_compatible` provider
- Mock fallback for offline teaching/tool planning

## Safety

- Sandbox: no secrets, no host FS, no network, rlimits
- Sensitive ops remain Owner-gated
- Fine-tuning never automatic on production
