# PFAI Project Memory

Last updated: 2026-09-27 (Command Chat Brain↔Heart)

## Snapshot

| Item | Value |
|---|---|
| Version | 8.0.0 |
| Stack | FastAPI + RTL dashboard + AI Command Chat |
| Command Chat | `/chat/*` via CommandAgent + ToolRouter |
| Model | Anthropic env secret; Mock fallback without key |
| Continuous training | `enabled: true` + `PFAI_CONTINUOUS_TRAINING_ENABLED` kill switch |
| Auto-promote | Hard-disabled |
| Chat learning (phase 1) | Memory / feedback / corrections — not weight training |

## Safety invariants

1. Promotion requires owner API + ledger.
2. Command Chat sensitive tools require `/chat/approve`.
3. Secrets never in git/source/frontend/logs.
4. Network deny-by-default.

## Verification

- pytest: 279 passed
- Live Mock chat + legacy `/health` OK

## Operator secrets (platform only)

- `ANTHROPIC_API_KEY`
- `PFAI_OWNER_EMAIL`
- `PFAI_OWNER_SECRET_HASH`
