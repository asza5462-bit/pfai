# PFAI v6.6 — Persistent Global State & Event Ledger

Adds transactional SQLite persistence for critical state and a tamper-evident hash-chained event ledger. SQLite WAL + FULL synchronous mode are used for durable commits. The ledger verifies every event against its predecessor. JSON remains suitable for human-readable export, while critical runtime state is persisted transactionally.

This is a local persistence layer; production deployments should place the database on reliable storage and use backups/replication appropriate to their environment.
