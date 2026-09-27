# PFAI v6.5 — Persistent Global State & Recovery

Adds durable recovery state to the v6.3 scheduler and v6.4 distributed training/research fabric.

Key controls:
- atomic JSON state writes with fsync + replace;
- recovery of RUNNING jobs to PENDING after process restart;
- checkpoint preservation across recovery;
- failed-worker exclusion remains enforced;
- bounded event history;
- explicit SQLite close/context-manager/destructor paths for vector and semantic stores;
- regression test proving no ResourceWarning from the repaired stores.

Recovery does not grant permissions or bypass security/promotion gates.
