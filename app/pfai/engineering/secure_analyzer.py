"""PHASE 14 secure code analysis — evidence-based, never fabricates findings."""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from pfai.authorized_execution import sanitize_args
from pfai.engineering.types import SecurityFinding, Severity, new_id


# Patterns that indicate likely issues — only reported with file evidence
_RULES: list[dict[str, Any]] = [
    {
        "category": "secret_exposure",
        "severity": Severity.CRITICAL.value,
        "confidence": 0.9,
        "pattern": re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*=\s*['\"][^'\"]{8,}['\"]"),
        "explanation": "Hard-coded secret-like assignment detected in source.",
        "remediation": "Move secrets to environment variables or a secret store; rotate exposed values.",
    },
    {
        "category": "injection_risk",
        "severity": Severity.HIGH.value,
        "confidence": 0.75,
        "pattern": re.compile(r"(?i)(execute\(|cursor\.execute\(|os\.system\(|subprocess\.(call|run|Popen)\().*%|(\+|format\().*(SELECT|INSERT|UPDATE|DELETE)"),
        "explanation": "Possible SQL/command construction via string formatting.",
        "remediation": "Use parameterized queries / argument lists; never concatenate untrusted input into commands.",
    },
    {
        "category": "path_traversal",
        "severity": Severity.HIGH.value,
        "confidence": 0.7,
        "pattern": re.compile(r"(?i)open\([^\)]*\+|Path\([^\)]*\+|os\.path\.join\([^\)]*request"),
        "explanation": "User-influenced path construction without obvious sanitization.",
        "remediation": "Resolve paths under an allowlisted root; reject '..' segments.",
    },
    {
        "category": "ssrf_risk",
        "severity": Severity.HIGH.value,
        "confidence": 0.65,
        "pattern": re.compile(r"(?i)(urllib\.request\.urlopen|requests\.(get|post)|httpx\.(get|post))\([^\)]*request\.|user_url|target_url"),
        "explanation": "HTTP client call appears to use request/user-controlled URL.",
        "remediation": "Validate URL scheme/host; block private/metadata addresses; allowlist destinations.",
    },
    {
        "category": "xss_risk",
        "severity": Severity.MEDIUM.value,
        "confidence": 0.6,
        "pattern": re.compile(r"(?i)innerHTML\s*=|document\.write\(|\|safe\}|mark_safe\("),
        "explanation": "Potential unsafe HTML injection sink.",
        "remediation": "Encode untrusted output; avoid innerHTML with user data; use contextual encoding.",
    },
    {
        "category": "insecure_cors",
        "severity": Severity.MEDIUM.value,
        "confidence": 0.8,
        "pattern": re.compile(r"(?i)Access-Control-Allow-Origin['\"\s:]*\*"),
        "explanation": "Wildcard CORS origin detected.",
        "remediation": "Restrict CORS to explicit trusted origins.",
    },
    {
        "category": "insecure_deserialization",
        "severity": Severity.HIGH.value,
        "confidence": 0.85,
        "pattern": re.compile(r"(?i)\bpickle\.loads?\(|yaml\.load\([^\)]*\)(?!.*Loader)"),
        "explanation": "Unsafe deserialization API usage.",
        "remediation": "Avoid pickle on untrusted data; use yaml.safe_load.",
    },
    {
        "category": "weak_input_validation",
        "severity": Severity.LOW.value,
        "confidence": 0.5,
        "pattern": re.compile(r"(?i)eval\(|exec\(|__import__\(['\"]os['\"]\)"),
        "explanation": "Dynamic code execution sink.",
        "remediation": "Remove eval/exec on untrusted input; use safe parsers.",
    },
]


class SecureCodeAnalyzer:
    """Static defensive analyzer — reports only when evidence exists in files."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _iter_source_files(self) -> list[Path]:
        exts = {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".env", ".json", ".yml", ".yaml", ".sql"}
        files = []
        if not self.root.exists():
            return files
        for p in self.root.rglob("*"):
            if not p.is_file():
                continue
            if ".pfai" in p.parts or "node_modules" in p.parts or ".git" in p.parts:
                continue
            if p.suffix.lower() in exts or p.name in (".env", ".env.example"):
                files.append(p)
        return files

    def analyze(self) -> dict[str, Any]:
        findings: list[SecurityFinding] = []
        scanned = 0
        for path in self._iter_source_files():
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            scanned += 1
            rel = str(path.relative_to(self.root)) if path.is_relative_to(self.root) else str(path)
            # Skip reporting secrets inside .env.example placeholders with empty values
            for rule in _RULES:
                for i, line in enumerate(text.splitlines(), start=1):
                    if not rule["pattern"].search(line):
                        continue
                    # Do not flag empty placeholder assignments in examples
                    if rel.endswith(".env.example") and re.search(r"=\s*$", line):
                        continue
                    evidence = line.strip()[:240]
                    # Redact obvious secret values in evidence
                    evidence = re.sub(
                        r"(?i)(password|secret|token|api[_-]?key)\s*=\s*['\"][^'\"]+['\"]",
                        r"\1='[REDACTED]'",
                        evidence,
                    )
                    findings.append(
                        SecurityFinding(
                            finding_id=new_id("find"),
                            category=rule["category"],
                            severity=rule["severity"],
                            confidence=float(rule["confidence"]),
                            affected_component=rel,
                            file_path=rel,
                            line_hint=i,
                            evidence=evidence,
                            explanation=rule["explanation"],
                            remediation=rule["remediation"],
                            provenance={"analyzer": "SecureCodeAnalyzer", "phase": 14},
                        )
                    )
            # Python AST extra: assert bare except pass for auth-looking names — skip fabrication
            if path.suffix == ".py":
                findings.extend(self._python_ast_checks(path, text, rel))
        # Deduplicate by category+file+line
        uniq: dict[str, SecurityFinding] = {}
        for f in findings:
            key = f"{f.category}:{f.file_path}:{f.line_hint}:{f.evidence}"
            uniq[key] = f
        out = [f.to_dict() for f in uniq.values()]
        return {
            "ok": True,
            "scanned_files": scanned,
            "finding_count": len(out),
            "findings": out,
            "fabricated": False,
            "note": "Only evidence-backed findings reported",
        }

    def _python_ast_checks(self, path: Path, text: str, rel: str) -> list[SecurityFinding]:
        findings: list[SecurityFinding] = []
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return findings
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "eval":
                findings.append(
                    SecurityFinding(
                        finding_id=new_id("find"),
                        category="weak_input_validation",
                        severity=Severity.HIGH.value,
                        confidence=0.9,
                        affected_component=rel,
                        file_path=rel,
                        line_hint=getattr(node, "lineno", None),
                        evidence="eval(...)",
                        explanation="Use of eval detected via AST.",
                        remediation="Remove eval; parse with safe libraries.",
                        provenance={"analyzer": "SecureCodeAnalyzer.ast", "phase": 14},
                    )
                )
        return findings

    def security_headers_from_html(self, html: str) -> list[dict[str, Any]]:
        """Passive HTML header meta checks — not fabricated network results."""
        findings = []
        if "Content-Security-Policy" not in html:
            findings.append(
                {
                    "category": "missing_security_headers",
                    "severity": Severity.LOW.value,
                    "evidence": "CSP meta/header not found in HTML",
                    "remediation": "Add Content-Security-Policy",
                }
            )
        return findings
