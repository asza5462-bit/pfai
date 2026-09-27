# Skill Composition

`SkillComposer` builds a dependency-ordered `SkillGraph` from templates + discovery.

Templates cover research, code, reason, data, document, tool flows.

Execution:

- topological order
- pipes prior outputs
- stop-on-failure optional
- auditable trace per node
- failure → PARTIAL_SUCCESS / FAILED (never silent success)
