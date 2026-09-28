# PHASE 22 — Security

## Non-negotiable invariants

1. URL access never grants Owner.
2. Frontend role fields are never trusted (stripped in `ProductionRuntime.handle`).
3. Authorization is server-side (`require_owner`, ActionPermissionGate, AuthorizedExecutor).
4. Skills cannot elevate privileges (`cannot_grant_privileges` training metadata; invoke via AuthorizedExecutor).
5. Tools cannot elevate privileges.
6. Models cannot elevate privileges.
7. Training cannot modify authentication.
8. Training cannot modify authorization.
9. Web access cannot bypass security gates (`WebPolicyGate` + `validate_url_for_fetch`).
10. MCP cannot bypass security gates (untrusted by default; owner trust required).
11. Sandbox cannot bypass security gates (`READY_BOUNDED`).
12. External actions require appropriate authorization.
13. Dangerous actions require owner approval where configured.
14. All protected actions are auditable.
15. Secrets never enter model prompts unless explicitly and safely required.
16. Secrets never enter training datasets.
17. Secrets never enter model checkpoints.
18. Current LKG (`MODEL_V0001`) remains recoverable; active `MODEL_V0007` preserved.
19. No uncontrolled self-modification.
20. No fabricated external evidence.

## Web SSRF / abuse controls

- Block localhost, private, link-local, metadata endpoints
- Scheme allowlist: `http`/`https` only
- Redirect re-validation
- Size / timeout / content-type / rate / budget limits
- Credentials-in-URL forbidden
- Audit logging without secret material

## Diagnostics safety

`/runtime/*` and `/system/status` expose capability state only — never env values, passwords, OTP, API keys, cookies, or private filesystem contents.

## Honesty warnings (non-blocking)

- `EMAIL_DELIVERY_STATUS=TEST_ONLY` until owner configuration
- `WEB_FABRIC_STATUS=NOT_CONFIGURED` until owner configuration
- `SANDBOX=READY_BOUNDED` (not full container isolation)
- Dependency audit = manifest/inventory unless live vulnerability scanning exists
- Never claim 100% security
