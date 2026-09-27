# PFAI v2.2.0 — Reasoning Core

Adds a bounded reasoning core with planning, working memory, tool/handler execution, verification, critique-driven repair, retries, and concise auditable summaries. It does not store or expose hidden chain-of-thought. Tool permissions remain outside the reasoning core and are enforced by the existing policy/tool gateway.

The core is designed for the 24/7 production loop: tasks can be evaluated, repaired, and then routed to the existing learning/training pipeline. Limits prevent unbounded step, retry, or repair loops.

## Validation

All project tests pass. Existing ResourceWarning messages from legacy SQLite tests are non-fatal.
