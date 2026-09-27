# PFAI v6.1 — Global Observability & Command Center

Adds a read-mostly command-center layer above the v5.9 Global Orchestrator.

- Global worker health snapshot with explicit `HEALTHY` / `DEGRADED` / `ISOLATED` states.
- Stale-worker alerts from heartbeat age.
- Hash-chained observability ledger with integrity verification.
- Dashboard data is observational; it does not bypass Owner Control, Policy, Zero-Trust, Sentinel, or Recovery gates.
- Operational actions must continue through the existing control-plane authorization paths.
