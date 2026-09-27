# Agent Context Changelog

## 2026-09-27 — AI Command Chat (Brain ↔ Heart)

### Added
- `command_agent.py`, `tool_router.py`, `command_memory.py`, `command_audit.py`, `model_mock.py`
- API `/chat/*` + `/assets/chat.js`
- Dashboard section **AI Command Chat** (default nav entry)
- Tests `tests/test_v88_command_chat.py`

### Behavior
- Chat → Agent → Tool Router → PFAI core services → reply + timeline statuses
- Sensitive tools wait for Owner Gate approval
- Memory persists conversations, preferences, decisions, corrections (SQLite)
- No automatic model-weight mutation from chat learning

### Verified
- 279 pytest tests passed
- Live Mock chat: Arabic system analysis, English health check, continuous_start approval gate, audit log

## 2026-09-27 — Phases 2–7: memory, continuous gates, production, Docker

### Added
- `AGENTS.md`, `docs/memory/PROJECT_MEMORY.md`, `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, `docs/DECISIONS.md`, `.cursor/rules/pfai.mdc`
- `pfai/continuous_gate.py` — config + `PFAI_CONTINUOUS_TRAINING_ENABLED` override
- `pfai/logging_setup.py` — structured stdout logging
- `docker-compose.yml` (API + optional `continuous` profile)
- `.gitignore`, `.dockerignore`, `app/data/.gitkeep`

### Changed
- `run_continuous.py` respects env gate; logs each training cycle; never auto-promotes
- `api.py` — request logging, validation/500 handlers, richer `/health` + `/system`, continuous start/resume blocked when gate off, promote/approve/etc logged to owner ledger + app log
- `runtime.health` accepts extra fields
- `app.py` — openai_compatible secrets via `api_key_env` only (no JSON plaintext keys)
- `configs/default.json` — keep `continuous_training.enabled=true`, add `self_learning`, document gate
- Dockerfile CMD honors `PORT`/`PFAI_HOST`; non-root user retained
- `render.yaml` documents continuous + log env vars
- README / DEPLOY docs aligned with Docker hosting (not Vercel)

### Verified in this environment
- Full pytest suite: all passed
- Live `run_web.py`: `/health`, dashboard `/`, owner gate, code evaluate, continuous status
- Docker image build attempted; daemon/overlay limitations in Cloud Agent VM prevented a successful image layer mount (configs remain ready for Render/Railway/local Docker hosts)

## 2026-09-27 — Phase 2 memory bootstrap

- Created durable agent context files (see ADR-005).
- Operator decisions captured: continuous enabled + human-gated promotion; secrets via env only; no Vercel.
