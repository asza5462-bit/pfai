# PHASE 23 — Web Fabric & External Tools

## Status (this environment)

| Signal | Value |
|--------|-------|
| WEB_FABRIC_STATUS | NOT_CONFIGURED |
| WEB_PROVIDER_STATUS | NOT_CONFIGURED |
| WEB_RESEARCH_STATUS | NOT_CONFIGURED |
| CITATION_STATUS | NOT_CONFIGURED |
| EMAIL_DELIVERY_STATUS | TEST_ONLY |
| EMAIL_LIFECYCLE_STATUS | TEST_ONLY |
| MCP_STATUS | READY (servers untrusted by default) |

## Architecture

Provider-independent adapters:

- `WebSearchProvider` / `WebFetchProvider`
- `WebCitationProvider` (alias → SourceVerifier)
- `WebResearchProvider` / `WebResearchPipeline`
- `WebPolicyGate` (SSRF, domain, budget, credentials-in-URL)
- `prompt_injection_guard` (untrusted external content)

Research pipeline:

```
request → planner → query gen → provider → normalize → extract →
dedupe → validate → evidence → synthesis → citations → response
```

When providers are unavailable, the pipeline returns explicit `NOT_CONFIGURED` with empty citations and `fabricated_*=false`.

## Owner configuration

See `app/.env.example`:

- `PFAI_WEB_ALLOW_NETWORK`
- `PFAI_WEB_SEARCH_PROVIDER` / `PFAI_WEB_FETCH_PROVIDER`
- optional `PFAI_WEB_SEARCH_ENDPOINT` + `PFAI_WEB_SEARCH_API_KEY` (secret — never commit)

## MCP

`MCPServerRegistry` registers servers untrusted. Owner `approve_server` / `approve_trust` required before invocation. Never grants owner privileges.

## APIs (owner-only)

- `GET /platform/web/providers`
- `POST /platform/web/search|fetch|research`
- `GET /platform/mcp/status|capabilities`
- `GET /platform/phase23/status`
