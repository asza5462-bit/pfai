# PFAI v6.9 — Recovery Drill & Self-Verification

Built from the verified PFAI v6.8 source tree.

Adds isolated recovery drills for backup snapshots. A drill verifies the snapshot (optionally by SHA-256), restores a temporary copy, runs SQLite integrity checks, counts readable state rows, and destroys the temporary recovery environment. The live database is never modified by a drill.

This is verification only: it does not silently promote a restored state or bypass security/permission/model-upgrade gates.
