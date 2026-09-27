# PHASE 16 Architecture — Unified Intelligence & Engineering Integration

Integration phase over PHASE 15. Not a rewrite.

## Primary surface

`EliteOrchestrator.chat()` → `UnifiedIntelligenceLoop.run()` → existing fabrics.

## Coherent pipeline

```
User Intent
→ Intent Classification
→ Planning
→ Skill Discovery
→ Skill Composition
→ Model Selection
→ Tool Selection
→ Authorization          # never bypassed
→ Execution
→ Observation
→ Verification
→ Evaluation
→ Result
→ Experience / Memory
→ Learning Candidate     # cannot modify authz/security policy
→ Optional Autonomous Training  # never auto-started from chat
→ Quality Gate
→ Activation or Rollback # LKG preserved; no silent activation
```

## Component map

| Concern | Existing component | Phase 16 role |
|---------|-------------------|---------------|
| Chat / command | `EliteOrchestrator.chat` | Primary surface |
| Loop | `UnifiedIntelligenceLoop` | Stage orchestration + meta intents |
| Skills | SkillRegistry2 + Phase 14/15 skills | Discovery / composition |
| Tools / MCP | ToolFabric / MCPAdapter | Authorized execution |
| Coding / apps | UnifiedCodingWorkflow / ApplicationBuilder | Engineering paths |
| Security | SecureCodeAnalyzer / TargetAuthorizationGate / Remediation / SecurityRegression | Defensive only |
| Web | WebInformationFabric + aliases | Honest NOT_CONFIGURED when unset |
| Sandbox | Sandbox READY_BOUNDED | Network deny default |
| Learning | SkillLearningBridge | Candidates without privilege grants |
| Training | AutonomousTrainingOrchestrator | Isolated; LKG preserved |
| Models | ModelRouter + ModelRegistry | Capability routing; open-weight supported |
| Observability | PlatformObservability | Scrubbed status snapshot |
| Auth | Owner + ActionPermissionGate | Server-side; client roles untrusted |

## Meta chat intents (bounded)

- Train a candidate model → export learning only (requires approval + allow_training_ops); **does not train/activate**
- Evaluate the latest model → status only
- Rollback the latest candidate → rollback path without destroying LKG
- Create a new skill → learning pipeline proposals; **no auto-activate**

## Non-goals

- No Phase 17
- No remote push / deploy
- No unrestricted scanning or offensive tooling
- No silent sandbox upgrade to unrestricted execution
