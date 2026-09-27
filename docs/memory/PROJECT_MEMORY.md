# PFAI Project Memory

Last updated: 2026-09-27 (Coding Academy)

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

## Verification

- pytest: 292 passed

## Operator secrets (platform only)

- `ANTHROPIC_API_KEY` (optional for live Claude)
- `PFAI_OWNER_EMAIL` / `PFAI_OWNER_SECRET_HASH`
