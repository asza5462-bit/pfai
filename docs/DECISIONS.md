# PFAI Decisions Log

## ADR-001 — Keep FastAPI monolith with embedded dashboard

- Status: Accepted
- Context: Uploaded PFAI 8.0 already ships API + static RTL dashboard together.
- Decision: Do not rewrite to Next.js/Vercel; keep FastAPI serving `static/index.html`.
- Consequences: Simpler deploy; CORS only needed if UI is hosted separately.

## ADR-002 — Do not target Vercel as primary host

- Status: Accepted
- Context: PFAI needs long-running process, local SQLite, continuous worker, code sandbox.
- Decision: Deploy as Docker on Render/Railway/VM.
- Consequences: Use existing Dockerfile + platform manifests; avoid serverless constraints.

## ADR-003 — Continuous training enabled, promotion always human-gated

- Status: Accepted (2026-09-27)
- Context: Operator wants continuous learning/training support, without unsafe production model swaps.
- Decision:
  - Keep `continuous_training.enabled=true` in config.
  - Allow force disable/enable via `PFAI_CONTINUOUS_TRAINING_ENABLED`.
  - Keep `auto_promote=False` and `require_human_approval=True` non-configurable from JSON.
  - Log cycle/training events to service event logs + owner ledger for gated actions.
- Consequences: Learning can run 24/7; production active model changes remain explicit.

## ADR-004 — Secrets only via environment / platform secret stores

- Status: Accepted
- Context: Anthropic key and owner secret must never appear in git, README real values, or chat.
- Decision: Document placeholders only; runtime reads env vars.
- Consequences: Deploy platforms must inject secrets; local `.env` is gitignored.

## ADR-007 — Coding Academy modular stack on existing sandbox

- Status: Accepted (2026-09-27)
- Context: Need full coding teacher/trainer/reviewer without rewriting PFAI.
- Decision:
  - Add `coding_*` modules + JSON curriculum under `configs/coding/`.
  - Reuse `SandboxedCodeEvaluator` for Python execution.
  - Wire Learning/Engineering modes; chat delegates coding intents to CodingAgent.
  - Anthropic optional; local/openai_compatible/Mock supported.
  - Training scaffold collects examples; no automatic production fine-tune.
- Consequences: Coding Academy dashboard + `/coding/*` APIs; existing code learning pipeline unchanged.

## ADR-006 — Command Chat Brain ↔ Heart via Tool Router

- Status: Accepted (2026-09-27)
- Context: Operator wants a central AI command chat that can operate PFAI safely.
- Decision:
  - Add CommandAgent + ToolRouter + CommandMemory + CommandAudit.
  - Heart access only through registered tool callbacks (no ad-hoc filesystem writes from the model).
  - Sensitive tools require Owner approval before execution.
  - Use Anthropic when `ANTHROPIC_API_KEY` is present; otherwise MockCommandProvider.
  - Phase-1 learning for chat = memory/feedback/approved knowledge/corrections — not automatic weight training.
- Consequences: Dashboard gains AI Command Chat; existing APIs remain intact.

## ADR-005 — Durable agent memory in docs/

- Status: Accepted (2026-09-27)
- Context: Original zip lacked AGENTS.md / docs / .cursor rules.
- Decision: Maintain project memory under `docs/` and `AGENTS.md` after meaningful changes.
- Consequences: Agents must update these files instead of relying on chat history.
