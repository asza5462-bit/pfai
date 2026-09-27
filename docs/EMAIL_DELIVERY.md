# Email Delivery Configuration (Phase 13.2 — configuration readiness)

Provider-agnostic Email OTP delivery. Credentials **never** belong in source code,
logs, API responses, git, or frontend storage.

## Status vocabulary (derived — never forced)

| Status | Meaning |
|--------|---------|
| `READY` | Real `smtp` or `api` provider fully configured |
| `TEST_ONLY` | `MockEmailProvider` (dev/tests only — **not** production) |
| `NOT_CONFIGURED` | Production requested but provider incomplete → fail-closed |
| `READY_BOUNDED` | *(not used for email; see sandbox)* |

Inspect: `email_config_report()` → `EMAIL_DELIVERY_STATUS`, or owner `GET /platform/email/status`.

## Production SMTP template (environment / secret store only)

Set these in the deployment secret store (values omitted on purpose):

```bash
PFAI_ENV=production
PFAI_EMAIL_PROVIDER=smtp

# Owner identity (OTP recipient must match)
PFAI_OWNER_EMAIL=                 # alias docs name: OWNER_EMAIL

# SMTP — canonical names
PFAI_SMTP_HOST=                   # alias: SMTP_HOST
PFAI_SMTP_PORT=587                # alias: SMTP_PORT
PFAI_SMTP_USER=                   # alias: SMTP_USERNAME
PFAI_SMTP_PASSWORD=               # alias: SMTP_PASSWORD  (SECRET)
PFAI_SMTP_FROM=                   # alias: SMTP_FROM
PFAI_SMTP_TLS=true                # alias: SMTP_TLS
```

Optional generic HTTP API instead of SMTP:

```bash
PFAI_EMAIL_PROVIDER=api
PFAI_EMAIL_API_ENDPOINT=
PFAI_EMAIL_API_KEY=               # SECRET
PFAI_EMAIL_FROM=
```

After configuration, confirm **`EMAIL_DELIVERY_STATUS=READY`**.  
Mock must never report READY.

## Fail-closed production behavior

When `PFAI_ENV` is `production`/`prod`/`staging` (or `PFAI_EMAIL_REQUIRE_PRODUCTION=1`):

- `mock` / missing provider → `FailClosedEmailProvider` → `EMAIL_DELIVERY_STATUS=NOT_CONFIGURED`
- Incomplete SMTP/API → same fail-closed path
- No silent fallback to Mock

## Security invariants

- OTP never in logs, API responses, localStorage, or source
- Hashed single-use OTP, expiry, attempt limits, resend cooldown, lockout
- Enumeration-resistant request responses
- Owner-only authorization unchanged

See also: `app/.env.example` (placeholders only).
