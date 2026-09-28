# PHASE 23 — Security

## Invariants preserved

- Server-side `require_owner` / ActionPermissionGate / AuthorizedExecutor
- Client role fields never trusted
- Skills/tools/models/MCP/web cannot self-elevate
- Training cannot modify authn/authz/security policy
- MODEL_V0007 active; MODEL_V0001 LKG intact; rollback ready
- Secrets never in source, frontend, Git, logs, or API diagnostics
- No fabricated web results / citations / benchmarks

## Prompt-injection defense

External web content is wrapped as untrusted data. Injection patterns (fake SYSTEM, ignore instructions, privilege escalation, secret exfil, tool override, hidden HTML instructions) are detected and stripped. External content never becomes SYSTEM/OWNER instruction authority.

## Web SSRF / abuse

URL validation, private IP / localhost / metadata blocking, redirect re-check, size/timeout/content-type/rate/budget limits, credentials-in-URL forbidden.

## Email honesty

Lifecycle: `TEST_ONLY` | `CONFIGURED` | `VERIFIED` | `READY` | `NOT_CONFIGURED`.  
Current environment: **TEST_ONLY** — no claim of production delivery.
