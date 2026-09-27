# PFAI Operations

## Local run (API + Dashboard)

```bash
cd app
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

# Required for owner-gated routes and real Anthropic calls:
export PFAI_OWNER_EMAIL='szz5462@gmail.com'
# Prefer: python -m pfai.hash_owner_secret   (prints pbkdf2 hash; paste below)
# Treat any previously shared passcode as compromised — use a NEW secret before deploy.
export PFAI_OWNER_SECRET_HASH='(paste hash only — never the plaintext passcode)'
# export ANTHROPIC_API_KEY=...   # set in your shell/platform secrets only

python run_web.py
# open http://127.0.0.1:8000/
```

Health check:

```bash
curl -s http://127.0.0.1:8000/health
```

## Command Chat

Owner-authenticated conversational control plane:

```bash
curl -X POST http://127.0.0.1:8000/chat/message \
  -H "Content-Type: application/json" \
  -H "X-Owner-Secret: YOUR_SECRET" \
  -d '{"message":"حلل حالة النظام"}'
```

Useful routes:

| Method | Path | Purpose |
|---|---|---|
| POST | `/chat/message` | Send command to Brain |
| POST | `/chat/approve/{pending_id}` | Approve sensitive tool |
| POST | `/chat/reject/{pending_id}` | Reject sensitive tool |
| GET | `/chat/tools` | Tool catalog |
| GET | `/chat/audit` | Executable command audit |
| GET/POST | `/chat/memory/*` | Search / remember / forget / correct |

Without `ANTHROPIC_API_KEY`, Mock provider plans tools for UI/dev testing. Set the key only in platform secrets for live Claude planning/composition.

Sensitive tools (continuous start/stop, remember/forget/correct, …) never execute until owner approval.

## Coding Academy

```bash
curl -H "X-Owner-Secret: YOUR_SECRET" http://127.0.0.1:8000/coding/tracks
curl -X POST -H "X-Owner-Secret: YOUR_SECRET" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/coding/sandbox \
  -d '{"code":"def answer():\n return 15\n","test_code":"assert answer()==15"}'
```

Routes include `/coding/assessment`, `/coding/path`, `/coding/lesson/...`, `/coding/hint`, `/coding/exercise/submit`, `/coding/review`, `/coding/debug/*`, `/coding/projects`, `/coding/chat`.
Extend languages/tracks via JSON in `configs/coding/` without rewriting the engine. Python sandbox reuses the isolated evaluator; other languages are taught/reviewed without false runtime claims.

## Continuous learning worker

```bash
cd app
python run_continuous.py
```

Enable/disable:

| Control | Effect |
|---|---|
| `configs/default.json` → `continuous_training.enabled` | Base switch (currently `true`) |
| `PFAI_CONTINUOUS_TRAINING_ENABLED=false` | Force off (overrides config) |
| `PFAI_CONTINUOUS_TRAINING_ENABLED=true` | Force on (overrides config) |

Promotion to active **never** happens automatically. Use owner-authenticated API:

- `POST /continuous/approve/{version}`
- `POST /continuous/promote/{version}`

## Environment variables

| Variable | Required | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | For real Claude | Platform secret only |
| `PFAI_OWNER_EMAIL` | For owner routes | Sole owner identity |
| `PFAI_OWNER_SECRET_HASH` | For owner routes | Passcode hash only (pbkdf2 or legacy sha256) |
| `PFAI_OWNER_SESSION_TTL` | Optional | Owner session seconds |
| `PFAI_OWNER_MAX_FAILURES` | Optional | Auth lockout threshold |
| `PFAI_OWNER_LOCKOUT_SECONDS` | Optional | Auth lockout duration |
| `PFAI_EMAIL_PROVIDER` | Optional | `mock` (default) / `smtp` / `api` for Email OTP — see `docs/EMAIL_DELIVERY.md` |
| `PFAI_SMTP_HOST` / `PORT` / `USER` / `PASSWORD` / `FROM` | Optional | SMTP OTP delivery (env secrets only); aliases `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_TLS` |
| `PFAI_WEB_ALLOW_NETWORK` + `PFAI_WEB_*` | Optional | Web fabric — see `docs/WEB_FABRIC.md`; stays NOT_CONFIGURED until set |
| `PFAI_OTP_TTL_SECONDS` / `RESEND_COOLDOWN` / `MAX_ATTEMPTS` | Optional | OTP lifetime / cooldown / attempts |
| `MODEL_PROVIDER` / `MODEL_NAME` / `MODEL_ENDPOINT` | Optional | Local/open-weight/openai_compatible selection |
| `MODEL_TIMEOUT` / `MAX_TOKENS` / `TEMPERATURE` / `CONTEXT_LENGTH` | Optional | Local adapter generation settings |
| `TRAINING_ENABLED` | Optional | Autonomous training master switch (default true) |
| `TRAINING_MIN_EXAMPLES` | Optional | Min validated examples before auto-trigger |
| `TRAINING_SCHEDULE` | Optional | Seconds between scheduled training windows |
| `TRAINING_MAX_RUNTIME` | Optional | Max seconds per training job |
| `TRAINING_MAX_RESOURCE_BUDGET` | Optional | Max concurrent training jobs |
| `TRAINING_ALLOW_MOCK` | Optional | Tests/dev only — never pretends real weight updates |
| `AUTONOMOUS_TRAINING_ENABLED` | Optional | Allow automatic training cycles (default true) |
| `TRAINING_MIN_FREE_MEMORY` / `TRAINING_MIN_FREE_DISK` | Optional | Admission thresholds (GB) |
| `TRAINING_MAX_CONCURRENT_JOBS` | Optional | Concurrent training cap |
| `MODEL_CANARY_ENABLED` / `MODEL_CANARY_REQUEST_LIMIT` / `MODEL_CANARY_FAILURE_THRESHOLD` | Optional | Shadow/canary controls |
| `MODEL_REVISION` / `MODEL_LICENSE` / `TRAINING_METHOD` | Optional | Model metadata + lora/qlora/full |
| `MODEL_PATH` | Optional | Local HF model directory for real training |
| `MODEL_DOWNLOAD_APPROVED` | Optional | Must be true to pull hub models |
| `TRAINING_BACKEND` | Optional | Default `transformers_lora` |
| `TRAINING_MAX_STEPS` / `TRAINING_SEED` / `TRAINING_MAX_CHECKPOINTS` | Optional | Bounded real training knobs |
| `PFAI_CONTINUOUS_TRAINING_ENABLED` | Optional | Override continuous loop |
| `PFAI_CORS_ORIGINS` | Optional | Comma-separated origins |
| `PFAI_HOST` | Optional | Default `0.0.0.0` in `run_web.py` |
| `PORT` / `PFAI_PORT` | Optional | Default `8000` |
| `PFAI_LOG_LEVEL` | Optional | Default `INFO` |
| `PFAI_LOCAL_MODEL_ID` | Optional | Local student model for SFT |

See also `docs/OWNER_AUTH.md` for first-time setup, sessions, and rotation.
See `docs/TRAINING_RUNTIME.md` for real LoRA enablement, rollback, and honesty labels.

## Real open-weight model (PHASE 9)

```bash
# Explicit install only (requires --approve):
python -m pfai.longevity.autonomous_training.install_open_weight \
  --model distilgpt2 --dest data/models/distilgpt2 --approve

export MODEL_PATH=data/models/distilgpt2
export MODEL_PROVIDER=transformers_local
export MODEL_LICENSE=apache-2.0

# Discover / status (owner-gated):
curl -H "X-Owner-Secret: …" 'http://127.0.0.1:8000/platform/models/open-weight?probe_load=false'
```

See `docs/REAL_MODEL_RUNTIME.md` and `docs/TRAINING_LIMITATIONS.md`.

## Real training (PHASE 8)

```bash
cd app
python -m pfai.longevity.autonomous_training.setup_runtime
export MODEL_PATH=data/models/tiny-random-gpt2   # or your open-weight dir
export MODEL_LICENSE=apache-2.0-or-upstream
export TRAINING_MAX_STEPS=5
# owner-gated:
curl -s -H "X-Owner-Secret: …" http://127.0.0.1:8000/platform/runtime/status
curl -s -X POST -H "X-Owner-Secret: …" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/platform/training/start \
  -d '{"owner_requested":true,"activate_if_pass":true}'
```

Rollback: `POST /platform/training/rollback` or `POST /platform/models/{id}/rollback`.

## Docker

```bash
# from repo root (directory containing Dockerfile)
docker build -t pfai:8.0.0 .
docker run --rm -p 8000:8000 \
  -e PFAI_OWNER_EMAIL \
  -e PFAI_OWNER_SECRET_HASH \
  -e ANTHROPIC_API_KEY \
  -v pfai-data:/app/data \
  pfai:8.0.0
```

Compose (API + optional continuous profile):

```bash
docker compose up -d
docker compose --profile continuous up -d
```

## Recommended hosting

Prefer a **long-running Docker web service** with a persistent disk:

1. **Render** — Docker runtime + disk (already sketched in `render.yaml`)
2. **Railway** — Docker + volume (already sketched in `railway.toml`)
3. **VM / VPS** — Docker Compose or systemd (`deploy/pfai-continuous.service`)

**Not recommended:** Vercel serverless — no fit for SQLite state, continuous worker, or code sandbox process model.

## Production checklist

- [ ] Set owner email + secret hash in platform secrets
- [ ] Set Anthropic key in platform secrets (not in git)
- [ ] Mount persistent volume on `/app/data`
- [ ] Confirm `/health` returns ok
- [ ] Confirm dashboard loads at `/`
- [ ] Decide whether continuous worker runs (same host profile or second service)
- [ ] Keep `auto_promote` false; use owner gate for promotions
