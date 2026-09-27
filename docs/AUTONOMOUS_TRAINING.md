# Autonomous Training (PHASE 9 + learning data growth)

Loop:

observation → LearningCandidate pipeline → dataset version (quality gate) →
trigger decision → train → checkpoint → evaluate vs LKG → canary →
activate/reject → monitor → rollback → record

Triggers: min examples, **dataset growth**, schedule, regression recovery, performance opportunity, owner request.  
**Never** train on every chat message. Candidate collect endpoints do not train.

Owner tick: `POST /platform/training/tick`  
Learning stats: `GET /platform/learning/statistics`

Autonomous flag: `AUTONOMOUS_TRAINING_ENABLED` (default true). Training still cannot bypass evaluation/canary.

Security: training cannot modify auth, OTP, permissions, secrets, or audit integrity.
GPU is never faked; CPU resource/timeout limits apply.
