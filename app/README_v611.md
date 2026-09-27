# PFAI v6.11 — Recovery Quorum & Approval Control

Built from verified PFAI v6.10. Adds external approval quorum for high-impact/forced recovery. Routine recovery from a verified snapshot remains automatic when the live database is invalid. Forced recovery requires a configurable quorum of distinct external approvers; model/agent/system identities cannot satisfy the quorum. Approval and recovery actions are recorded in the tamper-evident recovery ledger.
