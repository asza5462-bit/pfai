# PFAI Project Memory

Last updated: 2026-09-27 (PHASE 1 Orchestrator interfaces)

## Snapshot

| Item | Value |
|---|---|
| Version | 8.0.0 |
| Command Chat | `/chat/*` |
| Coding Academy | `/coding/*` + Dashboard section |
| Curriculum | Extensible JSON `configs/coding/` |
| Sandbox | Existing Python `SandboxedCodeEvaluator` |
| LLM | Anthropic optional; local/openai_compatible/Mock OK |
| Continuous training | enabled + env kill switch; no auto-promote |
| Fine-tune | Scaffold only — never automatic on prod |
| Platform | PHASE 1 done — interfaces/scaffolds only; not wired to API |
| Next | PHASE 2 (Orchestrator + Model Router) — wait for operator review |

## Verification

- pytest: (update after PHASE 1 run)

## Operator secrets (platform only)

- `ANTHROPIC_API_KEY` (optional for live Claude)
- `PFAI_OWNER_EMAIL` / `PFAI_OWNER_SECRET_HASH`
