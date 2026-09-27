# Owner Authentication & First-time Setup

PFAI owner privileges are **server-side only**. The Dashboard never stores the owner passcode.

## Environment variables (required for production)

| Variable | Purpose |
|---|---|
| `PFAI_OWNER_EMAIL` | Sole authorized owner identity (example for this deployment: `szz5462@gmail.com`) |
| `PFAI_OWNER_SECRET_HASH` | Passcode hash only — **never** the plaintext passcode |

Optional:

| Variable | Purpose |
|---|---|
| `PFAI_OWNER_SESSION_TTL` | Session idle lifetime seconds (default `28800`) |
| `PFAI_OWNER_SESSION_ABS_MAX` | Absolute session auto-lock seconds (default `86400`) |
| `PFAI_OWNER_MAX_FAILURES` | Failures before lockout (default `5`) |
| `PFAI_OWNER_LOCKOUT_SECONDS` | Lockout cooldown (default `900`) |
| `PFAI_COOKIE_SECURE` | Force `Secure` cookies (`true`/`false`) |

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

- `POST /owner/login` → HttpOnly session cookie `pfai_owner_session` (SameSite=Strict; Secure on HTTPS)
- `POST /owner/logout` → clears session
- `GET /owner/status` → public flags (`setup_required`, `authenticated`) — no secrets
- Owner APIs also accept legacy `X-Owner-Secret` for automation (verified server-side)

Failed logins use a **uniform** error and apply rate-limit lockout.

## Compromised development passcodes

Any passcode that was shared during development must be treated as **compromised**.
Before any real deployment, choose a **new** production passcode, generate a new hash,
and rotate `PFAI_OWNER_SECRET_HASH` (and clear old sessions).
