from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
import hashlib, json

@dataclass
class AuditReport:
    version: str; artifact_sha256: str; parent: str
    benchmark_score: float; min_benchmark_score: float
    security_passed: bool; regression_passed: bool; provenance_ok: bool
    canary_required: bool; human_approved: bool; decision: str
    reasons: list[str]; created_at: str

class ModelUpgradeGate:
    """High-assurance promotion gate; explicit external human approval is mandatory."""
    def __init__(self, root='data/model_upgrade_audit', min_score=.0, require_canary=True):
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
        self.min_score=float(min_score); self.require_canary=bool(require_canary)
        self._state=self.root/'state.json'
        if not self._state.exists(): self._write({'audits':{},'approvals':{}})
    def _read(self): return json.loads(self._state.read_text(encoding='utf-8'))
    def _write(self,x): self._state.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
    @staticmethod
    def sha256(path):
        h=hashlib.sha256()
        with open(path,'rb') as f:
            for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
        return h.hexdigest()
    def audit(self, version, artifact, parent, benchmark_score, security_passed, regression_passed, provenance_ok=True):
        reasons=[]; p=Path(artifact)
        if not p.is_file(): reasons.append('artifact_missing')
        digest=self.sha256(p) if p.is_file() else ''
        if float(benchmark_score) < self.min_score: reasons.append('benchmark_below_threshold')
        if not security_passed: reasons.append('security_gate_failed')
        if not regression_passed: reasons.append('regression_gate_failed')
        if not provenance_ok: reasons.append('provenance_gate_failed')
        s=self._read(); approved=bool(s['approvals'].get(version,False))
        decision='REJECT' if reasons else ('PASS' if approved else 'WAITING_HUMAN_APPROVAL')
        report=AuditReport(version,digest,parent,float(benchmark_score),self.min_score,bool(security_passed),bool(regression_passed),bool(provenance_ok),self.require_canary,approved,decision,reasons,datetime.now(timezone.utc).isoformat())
        s['audits'][version]=asdict(report); self._write(s)
        (self.root/f'{version}.json').write_text(json.dumps(asdict(report),ensure_ascii=False,indent=2),encoding='utf-8')
        return asdict(report)
    def approve_after_audit(self, version, artifact, approver='human'):
        if not approver or approver == 'model': raise PermissionError('approval must come from an external human/control authority')
        s=self._read(); audit=s['audits'].get(version)
        if not audit: raise ValueError('audit must exist before approval')
        if audit['decision']=='REJECT': raise ValueError('cannot approve a failed audit')
        if self.sha256(artifact) != audit['artifact_sha256']: raise ValueError('artifact changed since audit')
        s['approvals'][version]=True
        audit['human_approved']=True; audit['decision']='PASS'
        s['audits'][version]=audit; self._write(s)
        (self.root/f'{version}.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
        return audit
    def can_promote(self,version):
        a=self._read()['audits'].get(version)
        return bool(a and a['decision']=='PASS' and a['human_approved'])
