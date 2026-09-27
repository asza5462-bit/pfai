"""In-memory SkillRegistry scaffold.

PHASE 1: contract-compliant registry with no production skills registered.
PHASE 5 will wrap CodingAgent / Education adapters as skills.
"""
from __future__ import annotations

from typing import Any, Callable

from pfai.interfaces.skills import Skill, SkillContext, SkillResult
from pfai.interfaces.tools import ToolPermission


Handler = Callable[..., Any]


class SkillRegistry:
    """Simple name → (Skill, handler) map. Not wired into API yet."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}
        self._handlers: dict[str, Handler] = {}

    def register(self, skill: Skill, handler: Handler) -> None:
        if not skill.name:
            raise ValueError("skill.name required")
        if skill.permission not in ToolPermission:
            raise ValueError(f"invalid permission: {skill.permission}")
        self._skills[skill.name] = skill
        self._handlers[skill.name] = handler

    def list_skills(self) -> list[Skill]:
        return list(self._skills.values())

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def invoke(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        *,
        ctx: SkillContext | None = None,
        approved: bool = False,
    ) -> SkillResult:
        skill = self._skills.get(name)
        handler = self._handlers.get(name)
        if not skill or not handler:
            return SkillResult(ok=False, error=f"unknown skill: {name}")
        if skill.permission.requires_owner_gate() and not approved:
            return SkillResult(
                ok=False,
                error="owner approval required before skill execution",
                meta={"needs_approval": True, "skill": name, "permission": skill.permission.value},
            )
        try:
            output = handler(**(args or {}), ctx=ctx or SkillContext())
            return SkillResult(ok=True, output=output)
        except TypeError:
            try:
                output = handler(**(args or {}))
                return SkillResult(ok=True, output=output)
            except Exception as exc:
                return SkillResult(ok=False, error=str(exc))
        except Exception as exc:
            return SkillResult(ok=False, error=str(exc))
