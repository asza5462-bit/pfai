# PHASE 13 Production Readiness Matrix

Evidence from repository code, `email_config_report()`, `web_config_report()`,
`Sandbox.metadata()`, Elite status, model registry SQLite, and pytest output
(2026-09-27 Phase 13 run).

| Subsystem | Status | Evidence | Limitations | Production configuration required |
|-----------|--------|----------|-------------|-----------------------------------|
| Email OTP | PARTIAL / TEST_ONLY default | `email_provider.py` Mock/SMTP/API/FailClosed; OTP hashed single-use in `owner_auth.py`; `EMAIL_PROVIDER=mock`, `EMAIL_PRODUCTION_READY=false` at startup | Production forbids silent mock (`FailClosedEmailProvider`) | `PFAI_EMAIL_PROVIDER=smtp\|api` + SMTP/API secrets; `PFAI_ENV=production` or `PFAI_EMAIL_REQUIRE_PRODUCTION=1` |
| Model Router | READY (offline defaults) | `model_router.py` phase 13; capability routing; `anthropic_required=false`; import AST has no Anthropic | Commercial/local endpoints optional | `MODEL_PROVIDER` / `MODEL_NAME` / `MODEL_ENDPOINT` as needed |
| Web Fabric | NOT_CONFIGURED | `elite/web_fabric.py`; default `WEB_STATUS=WEB_PROVIDER_UNAVAILABLE`; no fabricated results | Network search/fetch off until explicitly enabled | `PFAI_WEB_ALLOW_NETWORK=1` + `PFAI_WEB_SEARCH_PROVIDER=ddg` / `PFAI_WEB_FETCH_PROVIDER=http` |
| Tool Fabric | READY (bounded) | `ToolFabric.status_registry()`; REAL tools + LEGACY merge; AuthorizedExecutor gate | Legacy tools still listed; skills never execute privileged ops directly | Owner approval for gated tools |
| MCP | READY (safe-default) | `mcp_adapter.py` untrusted default deny | External tools need explicit owner trust | Owner trust + approval to enable |
| Sandbox | PARTIAL | `SANDBOX_MODE=process_workspace`; secret-path denial; env filter; rlimits best-effort | **Not** full container/VM isolation | Host egress controls if needed; do not claim cgroup/namespace isolation |
| Skill Fabric | READY | 81 skills registered (76 Phase 12 + 5 web); versioning/promote/rollback | Handlers are original deterministic implementations | Optional quality-gate automation for new versions |
| Unified Chat | READY | `/chat` → EliteOrchestrator phase 13 intent→plan→skills→model→tools→verify→learn | Auto-routing uses capability heuristics | Optional explicit mode overrides |
| Learning | READY | `SkillLearningBridge` sanitize/filter/candidates; no auto-promote | Learning log empty until traffic | Experience bridge optional handoff |
| Autonomous Training | READY | Phase 11 pipeline preserved; isolation intact | GPU/runtime env-dependent | Existing training env / gates |
| Evaluation | READY | ProductionQualityGate + platform eval suites | — | Suites already registered |
| Owner Auth | READY | Server-side OTP/passcode/session; public URL never grants owner | Email delivery depends on provider config | Production email provider |
| Security | READY | Invariants tested; privilege escalation rejected; model/skill/tool cannot grant privileges | Process-level immutability only | Keep owner gates on management routes |
| Memory/LTM/Knowledge | READY (prior phases) | Unchanged in Phase 13 | — | — |
| Self-Heal | READY | Bounded safe actions only; no auth mutation | — | — |
| Rollback | READY | Model promotion history + skill promotion history | — | — |

Honest states used: READY / PARTIAL / NOT_CONFIGURED / UNAVAILABLE / TEST_ONLY.
Never marked READY merely because an interface exists without an operational path.
