# PHASE 17 Security Operations Overview

Defensive only. Builds on Phase 14–16.

## Flow

```
Owner/AuthZ → Target Registry → Scope Enforcement → Tool Permission →
Sandbox → Audit → Execution → Findings → Remediation → Retest → Learn
```

## Key modules

| Module | Role |
|--------|------|
| `target_registry.py` | Authorized targets; DENY default |
| `scope_enforcement.py` | Fail-closed scope validation |
| `web_security_engine.py` | Source/header/config analysis |
| `security_ops.py` | SDLC, reports, monitoring |
| `phase17_skills.py` | Versioned `security.*` skills |
| `phase17_gates.py` | `PHASE_17_SECURITY_QUALITY_GATE` |

## Web Fabric

Still **NOT_CONFIGURED** until owner sets providers. Architecture ready to correlate research when configured — no activation without config; no secrets in source.

## Sandbox

Reported honestly as **READY_BOUNDED**.
