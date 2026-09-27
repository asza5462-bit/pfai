from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Callable, Iterable
import json, hashlib

@dataclass
class EvalResult:
    name: str
    score: float
    passed: bool
    details: dict

class EvaluationLab:
    def __init__(self, minimum_score=0.0): self.minimum_score=float(minimum_score)
    def evaluate(self, suites: dict[str, Callable[[], float]]):
        results=[]
        for name, fn in suites.items():
            score=float(fn()); results.append(EvalResult(name,score,score>=self.minimum_score,{}))
        overall=sum(x.score for x in results)/len(results) if results else 0.0
        return {'passed': bool(results) and all(x.passed for x in results), 'overall':overall,
                'results':[asdict(x) for x in results], 'fingerprint':self.fingerprint(results)}
    @staticmethod
    def fingerprint(results: Iterable[EvalResult]):
        raw=json.dumps([asdict(x) for x in results],sort_keys=True).encode(); return hashlib.sha256(raw).hexdigest()
