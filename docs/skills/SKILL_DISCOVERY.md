# Skill Discovery

`SkillDiscoveryEngine` ranks candidates using:

- inferred intents
- category / capability / name overlap
- enabled + evaluation/health signals
- optional historical scores
- model compatibility hints
- permission filters

Output includes transparent `rationale` per candidate. No hard-coded single “best skill”.
