"""PHASE 14 — Application Engineering & Authorized Cyber Defense types."""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FindingStatus(str, Enum):
    OPEN = "open"
    FIXED = "fixed"
    VERIFIED = "verified"
    FALSE_POSITIVE = "false_positive"
    WONT_FIX = "wont_fix"


class TargetAuthDecision(str, Enum):
    DENY = "DENY"
    ALLOW = "ALLOW"
    NEEDS_APPROVAL = "NEEDS_APPROVAL"


class ProjectKind(str, Enum):
    STATIC_WEBSITE = "static_website"
    FRONTEND_APP = "frontend_application"
    BACKEND_API = "backend_api"
    FULLSTACK = "full_stack_application"
    DATABASE_BACKED = "database_backed_application"
    SERVICE_API = "service_api"


@dataclass
class SecurityFinding:
    finding_id: str
    category: str
    severity: str
    confidence: float
    affected_component: str
    evidence: str
    explanation: str
    remediation: str
    verification_status: str = FindingStatus.OPEN.value
    file_path: str = ""
    line_hint: int | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TargetScope:
    target_id: str
    declaration: str  # ownership / authorization statement
    scope: str
    allowed_actions: list[str] = field(default_factory=list)
    rate_limit_per_minute: int = 30
    max_requests: int = 100
    timeout_seconds: float = 10.0
    approved: bool = False
    actor: str = ""
    local_only: bool = True
    allow_external: bool = False
    domains: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EngineeringArtifact:
    artifact_id: str
    kind: str
    root: str
    files: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    checkpoint_id: str = ""
    validation: dict[str, Any] = field(default_factory=dict)
    security: dict[str, Any] = field(default_factory=dict)
    complete: bool = False
    report: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def now_ts() -> float:
    return time.time()
