# PFAI Architecture

## High-level shape

```
Browser (RTL Dashboard + AI Command Chat)
        │  HTTP + X-Owner-Secret
        ▼
FastAPI app (`pfai.api:app`)
  ├── static `/` + `/assets/chat.js`
  ├── Command Chat `/chat/*`  → CommandAgent (Brain)
  │         ↓
  │    ToolRouter (whitelist + approval)
  │         ↓
  │    Heart callbacks → Runtime / Continuous / Recovery / Memory / Metrics
  ├── public: /health, /system, /metrics, …
  └── owner-gated legacy routes (/ask, /continuous/*, /code/*, …)
        │
        ▼
Local data plane (`app/data/`)
  SQLite memory/vectors, command_chat.sqlite3, command_audit.jsonl, registries
```

## Command Chat roles

| Layer | Module | Role |
|---|---|---|
| Brain | `command_agent.py` | Plan, call tools, compose reply, approval flow |
| Router | `tool_router.py` | Whitelist tools; block sensitive until approved |
| Memory | `command_memory.py` | Conversations + pending actions + MemoryStore bridge |
| Audit | `command_audit.py` | Append-only executable command audit |
| Mock | `model_mock.py` | Offline planner when Anthropic key absent |
| Heart | existing core | Real health/system/continuous/memory/metrics services |

## Process roles

| Process | Entry | Role |
|---|---|---|
| API / Web | `run_web.py` / `uvicorn pfai.api:app` | Dashboard + HTTP API + Command Chat |
| Continuous learner | `run_continuous.py` | 24/7 learning cycles (no auto-promote) |
| Production core | `run_production.py` | Scheduler/orchestrator loop (dry_run default) |

## Frontend

- `app/pfai/static/index.html` + `assets/chat.js`
- Owner secret in `sessionStorage` only
- Optional CORS via `PFAI_CORS_ORIGINS`

## Model providers

- `anthropic` — env `ANTHROPIC_API_KEY` only
- `openai_compatible` / `echo`
- Command Chat uses Mock when Anthropic key is unset

## Safety boundaries

1. Continuous `require_human_approval=True` / `auto_promote=False`
2. Owner gate on deploy/promote/recovery-destructive actions
3. Command Chat sensitive tools require `/chat/approve`
4. Network deny-by-default
5. Phase-1 chat learning = memory/feedback/corrections — not weight mutation

## Module map (selected)

- `api.py`, `runtime.py`, `app.py`
- `command_agent.py`, `tool_router.py`, `command_memory.py`, `command_audit.py`
- `continuous_learning_orchestrator.py`, `code_learning_pipeline.py`
- `research_gate.py`, `policy.py`, `owner_control.py`
- `logging_setup.py`, `continuous_gate.py`
