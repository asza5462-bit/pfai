# Owner Authentication & First-time Setup

PFAI owner privileges are **server-side only**. The Dashboard never stores the owner passcode.

**Email OTP was permanently removed.** Owner login is **email + password** + HttpOnly session only.

## Environment variables (required for production)

Set these in the host secret store (e.g. Render Environment Variables). Never commit values.

| Variable | Purpose |
|---|---|
| `PFAI_OWNER_EMAIL` | Sole authorized owner email (server-side allowlist) |
| `PFAI_OWNER_SECRET_HASH` | Password hash only — **never** the plaintext password |
| `PFAI_ENV` | Set to `production` (or `prod`) on real hosts |

Optional:

| Variable | Purpose |
|---|---|
| `PFAI_OWNER_SESSION_TTL` | Session idle lifetime seconds (default `28800`) |
| `PFAI_OWNER_SESSION_ABS_MAX` | Absolute session auto-lock seconds (default `86400`) |
| `PFAI_OWNER_MAX_FAILURES` | Failures before lockout (default `5`) |
| `PFAI_OWNER_LOCKOUT_SECONDS` | Lockout cooldown (default `900`) |
| `PFAI_COOKIE_SECURE` | Dev override: `true` forces Secure cookies; `false` allows HTTP cookies locally |

Do **not** set `PFAI_EMAIL_*`, `PFAI_SMTP_*`, or `PFAI_OTP_*` for authentication — those paths are gone.

## Production HTTPS + Secure cookies (required)

On any production host:

1. Serve the app **only over HTTPS** (TLS at the reverse proxy or platform edge).
2. Set `PFAI_ENV=production` — this **always** sets the `Secure` flag on `pfai_owner_session`.
3. Prefer also setting `PFAI_COOKIE_SECURE=true` for clarity; production ignores attempts to disable Secure cookies.

Local development may use HTTP when `PFAI_ENV` is unset/non-production and (optionally) `PFAI_COOKIE_SECURE=false`. Without that override, Secure still follows the request scheme / `x-forwarded-proto`.

## Generate a hash (do this on a trusted machine)

```bash
cd app
python -m pfai.hash_owner_secret
# enter password (hidden) → prints pbkdf2_sha256$... hash
# Set on Render (or local env):
#   PFAI_OWNER_EMAIL=<owner email>
#   PFAI_OWNER_SECRET_HASH=<paste hash only>
```

Legacy SHA-256 hex hashes are still accepted for existing environments, but new setups should use PBKDF2 via `hash_owner_secret`.

**Never** put the plaintext password or hash in Git, README, frontend, tests, logs, or chat.

## First-time setup (local / fresh volume)

If no owner is configured and setup is not locked:

1. Open the Dashboard → **صلاحية المالك**
2. Enter owner email + strong passcode + confirmation
3. Server stores **hash only** under `data/security/` and writes `owner_setup.lock`
4. Setup cannot be re-run to steal ownership

Production hosts should still set `PFAI_OWNER_EMAIL` / `PFAI_OWNER_SECRET_HASH` as platform secrets.

## Login / logout / session

- `POST /owner/login` `{ "email", "password" }` → HttpOnly session cookie `pfai_owner_session` (SameSite=Strict; Secure on HTTPS / always in production). Legacy field `passcode` is still accepted as an alias.
- `POST /owner/logout` → clears session
- `GET /owner/status` → public flags (`setup_required`, `authenticated`, `auth_methods`) — no secrets; `email_otp=REMOVED`
- Owner APIs also accept legacy `X-Owner-Secret` for automation (verified server-side)

Failed logins use a **uniform** error and apply rate-limit lockout.

Routes `/owner/otp/request` and `/owner/otp/verify` are removed (404).

## Compromised development passcodes

Any passcode that was shared during development must be treated as **compromised**.
Before any real deployment, choose a **new** production passcode, generate a new hash,
and rotate `PFAI_OWNER_SECRET_HASH` (and clear old sessions).

## Public vs owner-gated surfaces (security notes)

Intentionally public (no secrets / no private content):

- `/health`, `/system`, `/metrics`, `/modules`, `/deployments`, `/continuous/status`
- `/owner/status`, Dashboard `/`

Owner-gated (private knowledge, memory, code, privileged ops):

- `/knowledge/search`, `/regression/pending`, and all mutate/ops routes
