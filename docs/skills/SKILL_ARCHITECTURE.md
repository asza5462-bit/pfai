# Skill Architecture (PHASE 12)

Skills are versioned, auditable capabilities with metadata (`SkillDefinition`).

Lifecycle:

```
register(version) → validate deps → activate (owner) → LKG mark
  → evaluate → promote new version → rollback via promotion history
```

Rules:

- Versions never silently overwrite
- `ACTIVE_SKILL_VERSION` / `LKG_SKILL_VERSION` / `PREVIOUS_SKILL_VERSION` tracked
- Invoke always through AuthorizedExecutor (via SkillRegistry bridge)
- Skills cannot grant themselves privileges
