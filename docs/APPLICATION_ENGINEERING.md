# Application Engineering (Phase 15)

Additive layer on Phase 14 `ApplicationBuilder` / templates / workspace checkpoints.

## Capabilities

| Capability | Module | Notes |
|------------|--------|-------|
| Project / repo inspection | `ProjectInspector` | Structure, deps manifests, architecture hints |
| Modification workflow | `EngineeringWorkflow` | plan → affected files → reason → execution record → tests → rollback |
| Website / app build | `ApplicationBuilder` + `UnifiedCodingWorkflow` | Templates; completion only when files+tests pass |
| Unified coding loop | `UnifiedCodingWorkflow` | understand → plan → edit → test → repair → report |
| Documentation outline | skill `documentation_generation` | Advisory |
| DevOps planning | skill `devops_planning` | Never claims deploy without deploy |

## Modification rules

Every change must include:

- plan
- affected files
- reason
- execution record (`.pfai/engineering_records.jsonl`)
- tests result
- rollback / checkpoint id

Unrelated files are not written even if supplied in a writers map.

## Status

`APPLICATION_ENGINEERING_STATUS=READY` (evidence: Phase 15 tests + gates).

See `docs/PHASE_15_FINAL_AUDIT.md`.
