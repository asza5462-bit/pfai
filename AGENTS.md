# PFAI — Agent Operating Guide

This file is the durable entry point for any AI/human agent working on PFAI.
Do not rely on chat memory alone. Read the docs below before making changes.

## Product

PFAI 8.1 is a production-oriented open AI control plane:

- Backend: FastAPI + Uvicorn (Python)
- Frontend: single RTL Arabic dashboard at `app/pfai/static/index.html`
- Persistence: local SQLite / JSON under `app/data/`
- Model providers: Anthropic (default), OpenAI-compatible, Echo (offline)
- Continuous learning is enabled in config but **never auto-promotes** models

## Mandatory context files

1. `docs/memory/PROJECT_MEMORY.md` — current facts and open risks
2. `docs/ARCHITECTURE.md` — system shape and module boundaries
3. `docs/OPERATIONS.md` — run, deploy, env vars, health
4. `docs/DECISIONS.md` — architectural decisions (ADR-style)
5. `docs/CHANGELOG_AGENT_CONTEXT.md` — what agents changed and why
6. `.cursor/rules/` — hard rules for edits

## Hard rules

1. Never delete or disable an existing user-facing feature without an explicit request.
2. Never break existing API routes or response contracts.
3. Never commit secrets (`ANTHROPIC_API_KEY`, owner plaintext secret, `.env`).
4. Never put API keys or owner passwords in source, README examples as real values, frontend, logs, or chat.
5. Continuous learning may curate/evaluate candidates; **promotion to active requires owner approval**.
6. Network access is deny-by-default (`security.allow_network` + exact `allowed_domains`).
7. Prefer small, modular fixes over rewrites.
8. After meaningful changes: update memory docs and run real tests (not build-only).
9. Do not force Vercel. Prefer Docker + long-running host (Render/Railway/VM).
10. If unsure, inspect code first — do not invent project facts.
11. Owner auth is server-side only (`docs/OWNER_AUTH.md`); never trust frontend role claims.

## Working directory

Application code lives under `app/`. Package import root is `pfai` (set `PYTHONPATH` / run from `app/`).

## Quick verify

```bash
cd app
pip install -r requirements.txt
python -c "from pfai.api import app; print('ok', app.title)"
python -m pytest tests/test_api_wiring.py tests/test_v81_continuous_enable_gate.py tests/test_v88_command_chat.py -q
```

## Command Chat (Brain ↔ Heart)

- UI: Dashboard section `AI Command Chat` (`static/index.html` + `static/assets/chat.js`)
- Brain: `command_agent.py` + `tool_router.py` + `command_memory.py`
- Heart: existing runtime/services via Tool Router callbacks in `api.py`
- In Public Access / production, Open Chat Tool Execution removes approval locks (`PFAI_OPEN_CHAT_TOOLS` / public mode); suite keeps locks via `PFAI_PUBLIC_ACCESS_MODE=0`
- Model promotion still never auto-runs from chat
- Without `ANTHROPIC_API_KEY`, Mock provider drives planning with analytical compose

## Coding Academy

- UI: Dashboard `Coding Academy`
- Brain: `coding_agent.py` (Learning / Engineering)
- Curriculum: JSON under `configs/coding/` (extensible tracks)
- Sandbox: reuse `SandboxedCodeEvaluator`
- Chat phrases like «علمني Python» / «اختبر مستواي» delegate from Command Chat

## Orchestrator platform (phased)

- PHASE 1: contracts in `pfai/interfaces/` + scaffold modules
- PHASE 2: `Orchestrator` + `ProviderRegistry`/`ModelRouter` wired; `/chat/*` preserved; `/orchestrate` additive
- PHASE 3: deep LTM/Knowledge adapters, migration apply+backup, eval baselines, portable export (`/platform/ltm|eval|migrations|export*`)
- PHASE 4: unified ToolPermission + AuthorizedExecutor, versioned skills, TaskPlanner, bounded heal; `/platform/plan|skills*|tools|heal*`
- PHASE 5: Owner username+password auth (Email OTP / email login permanently removed); Local/OpenWeight adapters; migration audit/verify; schema target 3
- PHASE 6: AutonomousTrainingOrchestrator
- PHASE 7: TrainingRuntimeDetector + SkillPacks + Learning Control Center; schema target 5 + dataset/model registries; `/platform/training/*`; schema target 4; training isolated from authority
- Constraints: additive only; no Anthropic force; no auto fine-tune; no external deploy unless asked
- See `docs/ARCHITECTURE.md`, `docs/LONGEVITY.md`, ADRs 008–027 in `docs/DECISIONS.md`

## Longevity mission (20–30 years)

- PFAI = **Long-Lived Adaptive AI Platform** — see `docs/LONGEVITY.md`
- Core must remain model/provider/storage agnostic via ports
- Memory is structured & portable (not tied to one LLM)
- Production learning ≠ automatic weight mutation
- ADRs 012–023 capture longevity decisions
- PHASE 2: `Orchestrator` + `ProviderRegistry`/`ModelRouter` wired; `/chat/*` preserved; `/orchestrate` additive
- PHASE 3: durable LTM versions + knowledge version search + schema migrations with backup + export populate
