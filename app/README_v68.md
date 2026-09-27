# PFAI v6.8 — Automated Backup Rotation & Recovery Manager

Adds verified recovery-point management over v6.7:
- atomic backup creation and manifest updates
- SHA-256 verification
- configurable retention (minimum 2)
- safe rotation that never removes the newest verified recovery point
- tamper detection
- atomic restore of the latest verified point
- no bypass of security, permission, or model-upgrade gates
