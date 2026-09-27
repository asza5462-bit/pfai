# Owner Authentication & First-time Setup

PFAI owner privileges are **server-side only**. The Dashboard never stores the owner passcode.

## Environment variables (required for production)

| Variable | Purpose |
|---|---|
| `PFAI_OWNER_EMAIL` | Sole authorized owner identity (example for this deployment: `szz5462@gmail.com`) |
| `PFAI_OWNER_SECRET_HASH` | Passcode hash only — **never** the plaintext passcode |
| `PFAI_ENV` | Set to `production` (or `prod`) on real hosts |

Optional:

| Variable | Purpose |
|---|---|
| `PFAI_OWNER_SESSION_TTL` | Session idle lifetime seconds (default `28800`) |
| `PFAI_OWNER_SESSION_ABS_MAX` | Absolute session auto-lock seconds (default `86400`) |
| `PFAI_OWNER_MAX_FAILURES` | Failures before lockout (default `5`) |
| `PFAI_OWNER_LOCKOUT_SECONDS` | Lockout cooldown (default `900`) |
| `PFAI_COOKIE_SECURE` | Dev override: `true` forces Secure cookies; `false` allows HTTP cookies locally |

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
# enter passcode (hidden) → prints pbkdf2_sha256$... hash
export PFAI_OWNER_EMAIL='szz5462@gmail.com'
export PFAI_OWNER_SECRET_HASH='(paste hash here)'
```

Legacy SHA-256 hex hashes are still accepted for existing environments:

```bash
python3 -c 'import hashlib; print(hashlib.sha256(b"YOUR_NEW_SECRET").hexdigest())'
```

**Never** put the plaintext passcode in Git, README, frontend, tests, logs, or chat.

## First-time setup (local / fresh volume)

If no owner is configured and setup is not locked:

1. Open the Dashboard → **صلاحية المالك**
2. Enter owner email + strong passcode + confirmation
3. Server stores **hash only** under `data/security/` and writes `owner_setup.lock`
4. Setup cannot be re-run to steal ownership

Production hosts should still set `PFAI_OWNER_EMAIL` / `PFAI_OWNER_SECRET_HASH` as platform secrets.

## Login / logout / session

- `POST /owner/login` → HttpOnly session cookie `pfai_owner_session` (SameSite=Strict; Secure on HTTPS / always in production)
- `POST /owner/logout` → clears session
- `GET /owner/status` → public flags (`setup_required`, `authenticated`) — no secrets
- Owner APIs also accept legacy `X-Owner-Secret` for automation (verified server-side)

Failed logins use a **uniform** error and apply rate-limit lockout.

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

Test-only note: Starlette's `TestClient` may emit a deprecation warning preferring `httpx2` over `httpx`. That warning is test-harness only and does not affect the running application; do not downgrade FastAPI/Starlette to hide it.