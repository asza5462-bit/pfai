# PFAI v6.10 — Recovery Policy & Automatic Safe Recovery

Built from verified PFAI v6.9. Adds policy-gated recovery: a valid live database is left untouched; an invalid database may be automatically restored only from a verified SQLite-integrity-checked snapshot. Invalid audit ledgers or unverified snapshots deny recovery. A forensic copy of the invalid live database is retained before replacement, and recovery decisions/actions are recorded in a hash-chained audit ledger.
