# Web Fabric (Phase 13.1)

Provider-agnostic search/fetch/research subsystem. **Never fabricates** web results.

## WEB_FABRIC_STATUS (derived)

| Status | Meaning |
|--------|---------|
| `READY` | Real search and/or fetch provider configured with network explicitly allowed |
| `TEST_ONLY` | `MockWebSearchProvider` / `MockWebFetchProvider` selected |
| `NOT_CONFIGURED` | Default — reports `WEB_PROVIDER_UNAVAILABLE` (no fake results) |

## Interfaces

- `WebSearchProvider` / `WebFetchProvider`
- `WebProviderRegistry` — catalogs factories (`mock`, `ddg`, `http_search`, `http_fetch`, `unavailable`)
- `WebResearchExecutor` — skill/tool-facing execute + audit
- `WebInformationFabric` — search → fetch → parse → verify → summarize with provenance
- Claim kinds: `FACT`, `SOURCE-DERIVED CLAIM`, `MODEL INFERENCE`, `USER-PROVIDED INFORMATION`, `UNCERTAIN RESULT`

## Environment variables

| Variable | Purpose |
|----------|---------|
| `PFAI_WEB_ALLOW_NETWORK` | Must be `1`/`true` to enable any real network provider |
| `PFAI_WEB_SEARCH_PROVIDER` | `mock` \| `ddg` / `ddg_html` \| `http` / `http_search` |
| `PFAI_WEB_FETCH_PROVIDER` | `mock` \| `http` / `http_fetch` |
| `PFAI_WEB_SEARCH_ENDPOINT` | Generic HTTP search JSON endpoint (optional) |
| `PFAI_WEB_SEARCH_API_KEY` | Optional secret for generic search |
| `PFAI_WEB_SEARCH_QUERY_PARAM` | Default `q` |
| `PFAI_WEB_TIMEOUT` | Default `15` |
| `PFAI_WEB_ALLOW_PRIVATE` | Default off — enabling private IPs is strongly discouraged |

No commercial vendor is mandatory. Optional DDG HTML adapter is a configuration choice, not a hard dependency.

## Safety controls

- URL scheme allowlist (`http`/`https` only)
- DNS resolution + private/loopback/link-local/metadata host blocking (SSRF)
- Redirect validation (max redirects; re-check each hop)
- Content-type allowlist
- Max response size / timeouts
- Rate limiting on HTTP fetch
- Secret/token redaction in fetched text
- Audit events on deny/ok

## Owner checklist

1. Decide whether outbound web is allowed in this deployment.
2. Set `PFAI_WEB_ALLOW_NETWORK=1` only if intended.
3. Choose search/fetch providers via env — never embed credentials in code.
4. Confirm `/platform/web/status` shows `WEB_FABRIC_STATUS=READY` only after real config.
