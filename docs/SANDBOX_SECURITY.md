# Sandbox Security (Phase 13.1)

## SANDBOX_STATUS

**`READY_BOUNDED`** — process/workspace sandbox with honest limitations.

This is **not** full container/VM isolation unless a future container backend is wired.
Do not claim cgroup/namespace/seccomp isolation from the default backend.

## Controls (verified)

| Control | Behavior |
|---------|----------|
| Execution timeout | Enforced via communicate timeout + process-group kill |
| Memory / CPU limits | `resource.setrlimit` where supported (best-effort) |
| Isolated temp workspace | Unique `pfai-sandbox-*` directory |
| Path traversal prevention | Reject `..` parts; resolve must stay under root |
| Env sanitization | Drop secret-like keys/values; strip SMTP/API/owner keys |
| Network default | **Disabled**; explicit `allow_network=True` required |
| Max output size | Truncate stdout/stderr |
| Subprocess / process-tree cleanup | `start_new_session` + `killpg` on timeout/cancel |
| Dangerous command filtering | Deny destructive/network escape patterns |
| Secret path denial | Block probes for credentials/OTP/session/keys |
| Audit logging | Append-only in-memory audit list per instance |
| Deterministic failures | `status`: `SUCCESS` / `FAILED` / `DENIED` |

## Backend seam

`SandboxBackend` / `ProcessSandboxBackend` allow a future Docker/container/VM
implementation without changing Skill or Tool interfaces.

## Metadata keys

Returned by `Sandbox.metadata()` / `GET /platform/sandbox/status`:

- `SANDBOX_STATUS=READY_BOUNDED`
- `SANDBOX_MODE=process_workspace`
- `full_container_isolation=false` (for default backend)
- `SANDBOX_LIMITATIONS` — explicit list of what is **not** claimed
