# Web Fabric Configuration (Phase 13.2 — configuration readiness)

Provider-agnostic search/fetch. **Never fabricates** results. No mandatory commercial vendor.

## Status vocabulary (derived — never forced)

| Status | Meaning |
|--------|---------|
| `READY` | Network explicitly allowed **and** a real search/fetch provider configured |
| `TEST_ONLY` | Mock web providers selected for tests |
| `NOT_CONFIGURED` | Default / no real provider — `WEB_PROVIDER_UNAVAILABLE` |
| `READY_BOUNDED` | *(not used for web; see sandbox)* |

Do **not** mark READY merely because interfaces exist.

## Environment-only production template

```bash
# Explicit opt-in to outbound network (required for READY)
PFAI_WEB_ALLOW_NETWORK=1

# Search provider (pick one — none are mandatory vendors)
#   ddg / ddg_html  — optional HTML search adapter
#   http / http_search — generic JSON search endpoint you control
PFAI_WEB_SEARCH_PROVIDER=http_search
PFAI_WEB_SEARCH_ENDPOINT=         # your search API URL
# PFAI_WEB_SEARCH_API_KEY=        # SECRET if required — never commit
# PFAI_WEB_SEARCH_QUERY_PARAM=q

# Fetch provider
PFAI_WEB_FETCH_PROVIDER=http_fetch
PFAI_WEB_TIMEOUT=15
PFAI_WEB_ALLOW_PRIVATE=0          # keep 0 — SSRF private/local blocking
```

Minimal optional public-HTML search (still no vendor lock-in):

```bash
PFAI_WEB_ALLOW_NETWORK=1
PFAI_WEB_SEARCH_PROVIDER=ddg
PFAI_WEB_FETCH_PROVIDER=http_fetch
```

If unset / network denied → keep **`WEB_FABRIC_STATUS=NOT_CONFIGURED`**.

Confirm via `web_config_report()` or owner `GET /platform/web/status`.

## Security controls (verified in code + tests)

| Control | Present |
|---------|---------|
| SSRF protection (scheme/host/DNS) | yes |
| Private / loopback / metadata blocking | yes |
| Redirect validation (re-check each hop) | yes |
| Timeouts | yes |
| Response-size limits | yes |
| Content-type restrictions | yes |
| Secret / token redaction | yes |
| Rate limiting (HTTP fetch) | yes |
| Audit logging | yes |

See also: `app/.env.example`, `docs/SANDBOX_SECURITY.md`.
