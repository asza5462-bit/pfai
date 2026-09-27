# Skill Registry 2.0

`SkillRegistry2` stores immutable `(skill_id, version)` rows plus:

- active pointer
- previous version
- LKG version
- append-only `skill_promotion_history.jsonl`
- audit table

API (owner-protected):

- `GET /platform/elite/skills`
- `GET /platform/elite/skills/{id}/versions`
- `POST /platform/elite/skills/activate`
- `POST /platform/elite/skills/rollback`
