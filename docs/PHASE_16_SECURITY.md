# PHASE 16 Security

Preserves all PHASE 15 guarantees.

## Invariants

| Invariant | Status |
|-----------|--------|
| Server-side owner authorization | preserved |
| Deny-by-default target authorization | preserved |
| No client-controlled privilege escalation | preserved |
| Skills cannot grant privileges | preserved |
| Tools require ActionPermissionGate | preserved |
| MCP untrusted deny-default | preserved |
| Sandbox network deny default | preserved |
| Secrets scrubbed from observability / learning | preserved |
| Training isolated from authz / owner privileges | preserved |
| LKG (model-v0001) not destroyed | preserved |
| Active production model-v0007 not replaced by chat | preserved |
| No unrestricted third-party exploitation | preserved |
| Offensive chat language rejected | preserved |

## Authorized testing only

External active testing still requires:

declaration + scope + approval + allow_external + TargetAuthorizationGate ALLOW

Default remains **DENY**.

## Learning / training boundary

Learning candidates **cannot** modify:

- authentication
- authorization
- security policy
- system permissions / tool privileges

Autonomous training remains optional and quality-gated; activation requires the existing production-quality gate (not chat).
