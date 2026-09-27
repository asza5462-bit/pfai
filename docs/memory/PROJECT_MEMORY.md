# PFAI Project Memory

Last updated: 2026-09-27 (phases 2–7 completed in Cloud Agent)

## Snapshot

| Item | Value |
|---|---|
| Version | 8.0.0 |
| Stack | Python FastAPI + static RTL dashboard |
| Default model provider | Anthropic (`ANTHROPIC_API_KEY` env/platform secret only) |
| Continuous training config | `enabled: true` |
| Kill switch | `PFAI_CONTINUOUS_TRAINING_ENABLED=false` |
| Auto-promote | Hard-disabled; owner approval required |
| Frontend | `app/pfai/static/index.html` at `/` |
| Health | `GET /health` (includes continuous gate + owner_configured) |
| Preferred deploy | Docker Compose / Render / Railway / VM with persistent `/app/data` |
| Vercel | Not suitable |

## Safety invariants (do not weaken)

1. Continuous learning may curate/evaluate; promotion requires owner API + ledger.
2. `auto_promote` forced false in continuous wiring.
3. Anthropic/owner secrets never in git or committed files.
4. Network deny-by-default (`allow_network` + exact allowlist).

## Current runtime verification (this agent)

- pytest: full suite green
- Local server: health/dashboard/code-eval/owner auth OK without Anthropic key (fail-closed for live model calls)
- Docker files ready; container build blocked by VM overlayfs limits here — use operator Docker host or Render/Railway build

## Operator still must provide (platform secrets)

- `ANTHROPIC_API_KEY`
- `PFAI_OWNER_EMAIL`
- `PFAI_OWNER_SECRET_HASH`
- Persistent disk for `/app/data`
- Optional second service/profile for `run_continuous.py`
