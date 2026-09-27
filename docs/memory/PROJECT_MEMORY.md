# PFAI Project Memory

Last updated: 2026-09-27 (Longevity PHASE 5)

## Snapshot

| Item | Value |
|---|---|
| Version | 8.0.0 |
| Mission | Long-Lived Adaptive AI Platform (20–30y) |
| Command Chat | `/chat/*` (unchanged primary UX) |
| Orchestrator | `/orchestrate` + `/platform/*` (additive) |
| Providers | echo, mock, openai_compatible, local, open_weight, anthropic(optional) |
| Anthropic required | **false** |
| Local/open-weight | Adapter implemented; runtime connected only if probe succeeds |
| Learning | Durable gated pipeline; no weight mutation |
| Schema version | target **3**; applied in this dev env when backup-first run succeeds |
| Owner auth | Email OTP + passcode + session cookie + optional X-Owner-Secret |
| Owner email env | `PFAI_OWNER_EMAIL` (never hard-code in frontend) |
| Email provider | `PFAI_EMAIL_PROVIDER=mock|smtp` + `PFAI_SMTP_*` |

## Verification

- See PHASE 5 completion report / `docs/CHANGELOG_AGENT_CONTEXT.md`
