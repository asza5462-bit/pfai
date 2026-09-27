# Cyber Defense (Phase 15)

Defensive-only. Extends Phase 14 `SecureCodeAnalyzer`, `TargetAuthorizationGate`, `AuthorizedSecurityTester`, `RemediationLoop`.

## Authorization boundary

Default: **DENY**.

Active testing requires:

1. ownership/authorization declaration
2. scope
3. allowed actions
4. rate / time / resource limits
5. approval
6. audit logging

No authorization → no active external testing.

Allowed contexts: owner-controlled systems, local projects, explicitly authorized labs/sandboxes.

## Workflow

DISCOVER → CLASSIFY → VERIFY → EXPLAIN → PROPOSE FIX → APPLY AUTHORIZED FIX → TEST → SECURITY RETEST → REGRESSION TEST → RECORD

A finding is **not** marked fixed unless verification shows the issue is gone.

## Skills (versioned)

`secure_code_review`, `dependency_audit`, `api_security_review`, `authentication_review`, `authorization_review`, `web_security_review`, `secrets_audit`, `threat_modeling`, `vulnerability_triage`, `remediation_planning`, `security_regression`, `secure_configuration_review`, plus Phase 14 defense skills.

Skills cannot grant themselves privileges.

## Status

- `SECURITY_ANALYSIS_STATUS=READY`
- `AUTHORIZED_TESTING_STATUS=READY_BOUNDED`
- `REMEDIATION_STATUS=READY`
