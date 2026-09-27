# PFAI Architecture

## High-level shape

```
Browser (RTL Dashboard)
        │  HTTP + optional X-Owner-Secret
        ▼
FastAPI app (`pfai.api:app`)
  ├── static `/` → dashboard
  ├── public: /health, /system, /metrics, /modules, search-ish reads
  └── owner-gated: /ask, /continuous/*, /code/*, /deploy/*, /recovery/drill, ...
        │
        ├── PFAIRuntime → Agent / Memory / RAG / Metrics / Deploy
        ├── ContinuousLearningOrchestrator (curate → evaluate → pending approval)
        ├── CodeLearningPipeline + SandboxedCodeEvaluator
        ├── ResearchGate + Policy (deny-by-default network)
        └── OwnerControl (auth + append-only ledger)
        │
        ▼
Local data plane (`app/data/`)
  SQLite memory/vectors, JSON registries, audit/events logs
```

## Process roles

| Process | Entry | Role |
|---|---|---|
| API / Web | `run_web.py` / `uvicorn pfai.api:app` | Dashboard + HTTP API |
| Continuous learner | `run_continuous.py` | 24/7 learning cycles (no auto-promote) |
| Production core | `run_production.py` | Scheduler/orchestrator loop (dry_run default) |

## Frontend

- Single file: `app/pfai/static/index.html`
- Talks only to backend REST endpoints
- Owner secret lives in `sessionStorage` only
- Optional separate hosting via `PFAI_CORS_ORIGINS`

## Model providers

Configured in `configs/default.json` → `model.provider`:

- `anthropic` — Messages API; key from env (`ANTHROPIC_API_KEY`)
- `openai_compatible` — local/gateway chat completions
- `echo` — offline placeholder

## Safety boundaries (non-negotiable)

1. `LearningLoop.require_human_approval=True` for continuous service wiring
2. `ContinuousConfig.auto_promote=False` hard-coded in `run_continuous.py`
3. Owner gate on promote/approve/deploy/recovery-destructive actions
4. Network: both `allow_network` and non-empty exact host allowlist required
5. Secrets never loaded from committed config files for Anthropic/owner secret

## Module map (selected)

- `api.py` — HTTP surface
- `runtime.py` / `app.py` — composition root
- `continuous_learning_orchestrator.py` — learning coordination
- `code_learning_pipeline.py` — solve → verify → curate
- `research_gate.py` / `policy.py` — outbound web policy
- `owner_control.py` — authentication + authorization ledger
- `logging_setup.py` — structured application logging
- `continuous_gate.py` — config + env enable/disable gate
