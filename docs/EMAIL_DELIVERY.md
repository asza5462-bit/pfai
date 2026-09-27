# Email Delivery Configuration (Phase 13.1)

Provider-agnostic Email OTP delivery. Credentials **never** belong in source code,
logs, API responses, or frontend storage.

## EMAIL_DELIVERY_STATUS (derived, never forced)

| Status | Meaning |
|--------|---------|
| `READY` | `smtp` or `api` provider fully configured (`host`/`endpoint` + `from` + secrets as required) |
| `TEST_ONLY` | `MockEmailProvider` selected (dev/test only) |
| `NOT_CONFIGURED` | Fail-closed / incomplete production configuration |

Inspect via `email_config_report()` or `GET /platform/email/status` (owner-gated).

## Environment variables

### Provider selection

| Variable | Values | Notes |
|----------|--------|-------|
| `PFAI_EMAIL_PROVIDER` | `mock` \| `smtp` \| `api` | Default unset → mock in non-production |
| `PFAI_ENV` / `ENV` | `production` / `prod` / `staging` | Enables fail-closed (no silent mock) |
| `PFAI_EMAIL_REQUIRE_PRODUCTION` | `1`/`true` | Force fail-closed even outside prod env labels |

### SMTP (`PFAI_EMAIL_PROVIDER=smtp`)

| Variable | Required | Notes |
|----------|----------|-------|
| `PFAI_SMTP_HOST` | yes | SMTP hostname |
| `PFAI_SMTP_PORT` | no | Default `587` |
| `PFAI_SMTP_USER` | usually | Login username |
| `PFAI_SMTP_PASSWORD` | usually | **Secret** — env/secret store only |
| `PFAI_SMTP_FROM` | yes | From address (falls back to USER) |
| `PFAI_SMTP_TLS` | no | Default `true` |
| `PFAI_SMTP_TIMEOUT` | no | Default `20` |

### Generic HTTP API (`PFAI_EMAIL_PROVIDER=api`)

| Variable | Required | Notes |
|----------|----------|-------|
| `PFAI_EMAIL_API_ENDPOINT` | yes | Provider-agnostic POST JSON endpoint |
| `PFAI_EMAIL_API_KEY` | yes | **Secret** |
| `PFAI_EMAIL_FROM` | yes | From address |
| `PFAI_EMAIL_API_TIMEOUT` | no | Default `20` |
| `PFAI_EMAIL_API_AUTH_HEADER` | no | Default `Authorization` |
| `PFAI_EMAIL_API_AUTH_SCHEME` | no | Default `Bearer` |

### OTP security knobs (non-secret)

| Variable | Default |
|----------|---------|
| `PFAI_OTP_TTL_SECONDS` | `300` |
| `PFAI_OTP_LENGTH` | `6` |
| `PFAI_OTP_MAX_ATTEMPTS` | `5` |
| `PFAI_OTP_RESEND_COOLDOWN` | `60` |
| `PFAI_OTP_MAX_REQUESTS_PER_HOUR` | `10` |

## Security invariants

- OTP values never returned in API responses, never logged, never stored plaintext (PBKDF2 hash).
- Single-use, expiry, attempt limits, resend cooldown, lockout preserved.
- Enumeration-resistant uniform OTP request responses.
- Production refuses silent Mock fallback (`FailClosedEmailProvider`).
- Owner-only authorization unchanged.
