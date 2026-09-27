# Autonomous Training (PHASE 9)

Loop:

experience → sanitize → validate → dataset version → quality gate → trigger →
train → checkpoint → evaluate vs LKG → canary → activate/reject → monitor → rollback

Triggers: dataset threshold, schedule, regression recovery, owner request.  
**Never** train on every chat message.

Owner tick: `POST /platform/training/tick`

Autonomous flag: `AUTONOMOUS_TRAINING_ENABLED` (default true). Training still cannot bypass evaluation/canary.

Security: training cannot modify auth, OTP, permissions, secrets, or audit integrity.
