# PHASE 18 — Web Fabric

## Status honesty

`AuthorizedWebFabricOps.status()` and `web_config_report()` report:

- `WEB_FABRIC_STATUS=NOT_CONFIGURED` when no real provider/configuration is present
- `WEB_FABRIC_STATUS=READY` only when configured

Do not fake readiness.

## Capabilities (when authorized)

Provider-independent abstraction supporting:

- HTTP / HTTPS client
- API interaction
- Authenticated requests (headers accepted only on authorized path; secrets not logged)
- Response inspection
- Controlled crawling of **registered** targets
- Endpoint discovery **within authorized scope**
- API testing / health checks / integration-style checks

## Defaults

- Arbitrary Internet access: **disabled by default**
- Unregistered URL: rejected (`unregistered_target_or_domain`)
- URL alone never authorizes
- Crawl stops at scope boundary
- SSRF protections via `validate_url_for_fetch`

## Non-capabilities

- No unrestricted Internet research scanner
- No automatic expansion of host/path scope
- No live external security testing claimed unless it actually ran against an authorized target
