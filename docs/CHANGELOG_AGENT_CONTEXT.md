# Agent Context Changelog

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
