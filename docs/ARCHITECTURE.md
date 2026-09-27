# PFAI Architecture

## High-level shape

```
Browser (RTL Dashboard + AI Command Chat + Coding Academy)
        │  HTTP + X-Owner-Secret
        ▼
FastAPI (`pfai.api:app`)
  ├── /chat/*  → CommandAgent (ops brain)
  │                 └─ coding intents → CodingAgent
  ├── /coding/* → Coding Academy APIs
  ├── ToolRouter (ops + coding tools, Owner Gate on sensitive)
  └── Heart: runtime, continuous, sandbox, memory, curriculum JSON
```

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
