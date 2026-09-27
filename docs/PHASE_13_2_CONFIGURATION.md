# PHASE 13.2 — Configuration readiness only

No architecture redesign. No Phase 14. No deploy. No remote push. No secrets in git.

## Purpose

Document how the **owner** configures real email + web providers later via environment/secret stores.
Statuses remain honest:

| Token | Use |
|-------|-----|
| `TEST_ONLY` | Mock providers (email/web) — never production |
| `NOT_CONFIGURED` | Real capability requested/missing or intentionally unset |
| `READY` | Real provider fully configured |
| `READY_BOUNDED` | Sandbox process isolation (not full container) |

## Current derived state (this environment)

- `EMAIL_DELIVERY_STATUS=TEST_ONLY` (mock default; no secrets supplied)
- `WEB_FABRIC_STATUS=NOT_CONFIGURED` (network/providers unset)
- `SANDBOX_STATUS=READY_BOUNDED`
- `MODEL_V0007` active; `MODEL_V0001` intact

## Owner next steps (outside this repo)

1. Place SMTP or API secrets in the platform secret store using the template in `docs/EMAIL_DELIVERY.md`.
2. Optionally enable web via `docs/WEB_FABRIC.md` (explicit network allow + provider).
3. Re-check `/platform/email/status` and `/platform/web/status` until statuses show `READY` if desired.

Templates: `app/.env.example` (placeholders only).
