# PHASE 18 — Security

## Boundaries preserved

- Owner authentication (server-side)
- ActionPermissionGate / AuthorizedExecutor
- TargetAuthorizationGate + TargetRegistry + ScopeEnforcementLayer
- Deny-by-default
- Sandbox boundaries (`READY_BOUNDED`)
- Audit logging with secret redaction
- Rate limiting on authorized targets
- Rollback / LKG model retention
- Secret isolation (metrics, findings, logs)

## Security analysis (defensive)

`Phase18SecurityAnalysis` extends Phase 17 engine coverage for registered/local applications:

- authentication / authorization weaknesses
- IDOR / access control
- input validation, injection, XSS, CSRF, SSRF heuristics
- insecure file handling
- secrets exposure (redacted evidence)
- insecure configuration / security headers / cookies / sessions
- dependency **inventory** (not a live CVE feed)
- unsafe crypto usage
- API authorization / rate-limit heuristics
- logging/auditing weaknesses

Findings always include: `finding_id`, `severity`, `confidence`, `affected_component`, `evidence`, `explanation`, `remediation`, `verification_status`.

**Never claims 100% secure.**

## Authorized testing

Uses existing `AuthorizedSecurityTester` + `AuthorizedWebFabricOps`.

Before any active check:

1. resolve target  
2. verify registration  
3. verify authorization  
4. verify scope  
5. verify allowed action  
6. verify environment (production needs owner approval)  
7. create audit record  
8. execute bounded test  
9. collect evidence  
10. stop at scope boundary  

No automatic scope expansion. No arbitrary Internet scanning. No persistence or unauthorized access. No unrestricted exploit automation.

## Remediation policy

- Safe low-risk categories (`secret_exposure`, `missing_security_headers`, `insecure_cors`) may auto-apply only when `allow_auto_safe_fixes` is explicitly configured **and** policy permits.
- Sensitive categories require owner approval (`owner_approved_sensitive`).
- Regression increase in high/critical findings triggers rollback.

## Privilege sources (only)

Only the authorization layer may authorize an action.

Not privilege sources:

- client roles
- URLs
- model output
- skills
- tools
