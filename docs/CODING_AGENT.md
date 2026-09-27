# Coding Agent / Unified Coding Workflow (Phase 15)

## Existing CodingAgent

`pfai.coding_agent.CodingAgent` remains the academy/learning + engineering coaching agent.

## Phase 15 UnifiedCodingWorkflow

`pfai.engineering.unified_coding_workflow.UnifiedCodingWorkflow` connects:

- ApplicationBuilder / EngineeringWorkflow
- SecureCodeAnalyzer / RemediationLoop / SecurityRegressionEngine
- TargetAuthorizationGate
- SkillEvaluationLedger
- Optional Experience Bridge (validated outcomes only)
- AuthorizedExecutor / ActionPermissionGate

Loop: **understand → plan → edit → test → diagnose → repair → retest → report**

Bounded execution; sandbox network deny-by-default; `deployment_claimed` always false unless a real deploy path is invoked (none in Phase 15).

## Chat integration

EliteOrchestrator routes build/security/inspect intents through UnifiedCodingWorkflow (phase=15) while keeping Phase 14 compatibility fields.

## Status

`CODING_AGENT_STATUS=READY`
