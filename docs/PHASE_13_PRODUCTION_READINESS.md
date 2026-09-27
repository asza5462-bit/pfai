# PHASE 13 Production Readiness Matrix (updated 13.1)

Statuses are **derived from configuration and runtime evidence**, never forced green.

Legend: `READY` | `READY_BOUNDED` | `NOT_CONFIGURED` | `TEST_ONLY` | `BLOCKED`

| Subsystem | Status | Evidence | Limitations | Owner configuration required |
|-----------|--------|----------|-------------|------------------------------|
| Email OTP / Delivery | **TEST_ONLY** in this env (`EMAIL_DELIVERY_STATUS`) | `email_config_report()`; Mock default; fail-closed in production | Delivery READY only when SMTP/API fully configured | See `docs/EMAIL_DELIVERY.md` — `PFAI_EMAIL_PROVIDER=smtp\|api` + secrets |
| Model Router | **READY** | Phase 13 capability router; `anthropic_required=false` | Remote providers optional | `MODEL_PROVIDER` / endpoint env as needed |
| Web Fabric | **NOT_CONFIGURED** | `WEB_FABRIC_STATUS=NOT_CONFIGURED`; SSRF-hardened adapters present | No fake results; network off until explicitly allowed | See `docs/WEB_FABRIC.md` — `PFAI_WEB_ALLOW_NETWORK` + provider |
| Tool Fabric | **READY** | Status registry REAL/LEGACY; AuthorizedExecutor | Legacy tools classified honestly | Owner approval for gated tools |
| MCP | **READY** | Untrusted deny-by-default | External tools need trust+approval | Owner trust path |
| Sandbox | **READY_BOUNDED** | `SANDBOX_STATUS=READY_BOUNDED`; backend seam for future container | Not full container/VM | Optional future Docker backend |
| Skill Fabric | **READY** | 81 skills; versioning/rollback | Deterministic original handlers | Quality gate for promotions |
| Unified Chat | **READY** | EliteOrchestrator phase 13 path + gates | — | Owner session for /chat as configured |
| Learning | **READY** | Sanitize → candidate; no auto-promote | — | — |
| Autonomous Training | **READY** | Phase 11 pipeline preserved | No retrain in 13.1 | Existing gates |
| Evaluation | **READY** | ProductionQualityGate retained | — | — |
| Owner Auth | **READY** | OTP hashing/expiry/limits unchanged | Email delivery depends on provider | Production email config |
| Security | **READY** | Escalation reject; skill/tool/MCP/training isolation tests | — | — |
| Memory/LTM/Knowledge | **READY** | Prior phases | — | — |
| Self-Heal | **READY** | Bounded; no auth mutation | — | — |
| Rollback | **READY** | Model + skill history | — | — |

## Exact remaining owner actions for full production email/web

1. Configure SMTP or API email secrets (never commit them).
2. Confirm `EMAIL_DELIVERY_STATUS=READY` via `/platform/email/status`.
3. If web research is required: set `PFAI_WEB_ALLOW_NETWORK=1` and choose providers; confirm `WEB_FABRIC_STATUS=READY`.
4. Keep sandbox at `READY_BOUNDED` unless deploying a future container backend.

Related docs: `EMAIL_DELIVERY.md`, `WEB_FABRIC.md`, `SANDBOX_SECURITY.md`, `PHASE_13_FINAL_AUDIT.md`.
