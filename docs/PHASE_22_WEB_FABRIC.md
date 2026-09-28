# PHASE 22 — Web Fabric

## Status

Until an owner-configured production search/fetch provider is present and tested:

**WEB_FABRIC_STATUS = NOT_CONFIGURED**

No fabricated search results. No fabricated citations. No claim of external web access when unavailable.

## Interfaces (provider-independent)

| Interface | Implementation |
|-----------|----------------|
| `WebSearchProvider` | Abstract + Unavailable / Mock / optional DDG HTML |
| `WebFetchProvider` | Abstract + Unavailable / Mock / `HttpWebFetchProvider` |
| `WebPageParser` | alias → `SourceParser` |
| `WebContentExtractor` | alias → `SourceParser` |
| `WebCitationProvider` | alias → `SourceVerifier` |
| `WebResearchSession` | Session budgets + honest NOT_CONFIGURED |
| `WebPolicyGate` | SSRF / domain / budget / credential-in-URL denial |

## Controls

- URL validation (`validate_url_for_fetch`)
- Block localhost, private IPs, link-local, metadata hosts
- Dangerous schemes rejected (`file:`, `ftp:`, …)
- Redirect target re-validation (`_NoRedirect`)
- Timeouts, response-size limits, content-type allowlist
- Rate limiting + request budgets
- Secret redaction on content
- Credentials never placed in URLs
- Environment variables never exposed to web tools

## Multi-provider

`WebProviderRegistry` + `web_providers_from_env()` select providers from configuration. No hard-coded single commercial vendor.

## Research sessions

`WebResearchSession.research()` returns empty citations and `fabricated_citations=false` when status ≠ READY.
