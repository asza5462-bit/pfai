# Security Regression (Phase 15)

Module: `pfai.engineering.security_regression.SecurityRegressionEngine`

## Behavior

1. After remediation, **verify** finding is gone via `SecureCodeAnalyzer` recheck.
2. Only then `marked_fixed=true`.
3. Generate a **self-contained** regression test under `tests/security_regression/` (no secrets embedded).
4. Execute pytest on that directory; store result in `.pfai/security_regressions.jsonl`.

## Integration

- RemediationLoop records verifications.
- UnifiedCodingWorkflow remediate path generates + runs regressions.
- Skill: `security_regression`
- Evaluation: results feed SkillEvaluationLedger / optional Experience Bridge (validated only).

## Status

READY (local/static). Does not claim live CVE feed coverage.
