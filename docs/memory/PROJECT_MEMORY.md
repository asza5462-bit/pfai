# PFAI Project Memory

Last updated: 2026-09-27 (Longevity Architecture Foundation PHASE 1)

## Snapshot

| Item | Value |
|---|---|
| Version | 8.0.0 |
| Mission | Long-Lived Adaptive AI Platform (20–30y) |
| Command Chat | `/chat/*` |
| Coding Academy | `/coding/*` + Dashboard section |
| Longevity docs | `docs/LONGEVITY.md` + ADR-012..020 |
| Schema version | `PFAI_SCHEMA_VERSION = 1` |
| LLM | Anthropic optional; Echo/Mock/local first-class |
| Continuous training | enabled + env kill switch; no auto-promote |
| Fine-tune | Never automatic on prod; safe learning → knowledge |
| Platform scaffolds | `pfai.interfaces` + `pfai.longevity` (not wired) |
| Next | Longevity PHASE 2 — ProviderRegistry/ModelRouter wiring (await approval) |

## Verification

- pytest: (update after run)
- Live smoke: (update after run)

## Operator secrets (platform only)

- `ANTHROPIC_API_KEY` (optional for live Claude)
- `PFAI_OWNER_EMAIL` / `PFAI_OWNER_SECRET_HASH`
