# PFAI Operations

## Local run (API + Dashboard)

```bash
cd app
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

# Required for owner-gated routes and real Anthropic calls:
export PFAI_OWNER_EMAIL='you@example.com'
export PFAI_OWNER_SECRET_HASH="$(python3 -c 'import hashlib; print(hashlib.sha256(b"YOUR_SECRET").hexdigest())')"
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
| `PFAI_OWNER_EMAIL` | For owner routes | Identity |
| `PFAI_OWNER_SECRET_HASH` | For owner routes | SHA-256 of plaintext secret |
| `PFAI_CONTINUOUS_TRAINING_ENABLED` | Optional | Override continuous loop |
| `PFAI_CORS_ORIGINS` | Optional | Comma-separated origins |
| `PFAI_HOST` | Optional | Default `0.0.0.0` in `run_web.py` |
| `PORT` / `PFAI_PORT` | Optional | Default `8000` |
| `PFAI_LOG_LEVEL` | Optional | Default `INFO` |
| `PFAI_LOCAL_MODEL_ID` | Optional | Local student model for SFT |

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
