# PFAI v5.3 — Forensic & Controlled Recovery Center

Adds defensive incident evidence collection and controlled recovery. Evidence is hashed and stored in a hash-chained ledger. Recovery is bound to an exact plan hash and requires an external approver; the model/agent cannot approve or execute recovery.

Lifecycle: OPEN -> CONTAINED -> RECOVERY_PLANNED -> RECOVERY_APPROVED -> RECOVERED -> CLOSED.

Ledger integrity is checked before sensitive forensic operations. This component does not perform offensive actions or automatically restore access.
