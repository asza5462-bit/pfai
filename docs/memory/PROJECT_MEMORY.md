# PFAI Project Memory

Last updated: 2026-09-27 (Longevity PHASE 2 Orchestrator)

## Snapshot

| Item | Value |
|---|---|
| Version | 8.0.0 |
| Mission | Long-Lived Adaptive AI Platform (20–30y) |
| Command Chat | `/chat/*` (unchanged primary UX) |
| Orchestrator | `/orchestrate` + `/platform/*` (additive) |
| Providers | echo, mock, openai_compatible, anthropic(optional) |
| Anthropic required | **false** |
| Learning | Durable gated pipeline; no weight mutation |
| Schema version | `PFAI_SCHEMA_VERSION = 1` |
| Owner auth | Session cookie + optional X-Owner-Secret; setup lock |
| Owner email env | `PFAI_OWNER_EMAIL` (deploy as `szz5462@gmail.com`) |

## Verification

- pytest: 329 passed
- Live/TestClient smoke: `/health` + Dashboard `/` OK
