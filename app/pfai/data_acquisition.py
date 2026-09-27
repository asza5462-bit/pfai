from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable
import hashlib, json

@dataclass(frozen=True)
class LearningItem:
    instruction: str
    response: str
    track: str
    source: str = 'unknown'
    quality: float = 0.0
    metadata: dict = None

class DataAcquisitionEngine:
    """Offline-first acquisition/curation layer. Network collection is deliberately external/policy-gated."""
    def __init__(self, curriculum, min_quality: float = .40):
        self.curriculum = curriculum
        self.min_quality = float(min_quality)

    def classify(self, instruction: str, response: str) -> str:
        text=(instruction+' '+response).lower()
        ai_terms=('transformer','neural network','machine learning','deep learning','pytorch','llm','tokenizer','fine-tuning','rlhf')
        code_terms=('python','javascript','typescript','java','rust','go ','c++','code','algorithm','debug','test','api','sql','git','docker')
        if any(x in text for x in ai_terms): return 'ai_engineering'
        if any(x in text for x in code_terms): return 'software_engineering'
        return 'general_knowledge'

    def quality(self, instruction: str, response: str, source: str='unknown') -> float:
        # Heuristic quality gate: meaningful length, provenance, non-empty pair, no obvious placeholder.
        q=0.15 if instruction.strip() and response.strip() else 0.0
        if len(instruction.strip()) >= 12: q += .20
        if len(response.strip()) >= 30: q += .20
        if source and source != 'unknown': q += .15
        if len(instruction.strip()) >= 3 and len(response.strip()) >= 3: q += .15
        if any(x in response.lower() for x in ('todo','lorem ipsum')): q -= .25
        if '\x00' not in instruction+response: q += .15
        return max(0.0,min(1.0,q))

    def curate(self, rows: Iterable[dict|LearningItem]) -> list[LearningItem]:
        out=[]; seen=set()
        for row in rows:
            if isinstance(row, LearningItem): item=row
            else:
                ins=str(row.get('instruction','')).strip(); resp=str(row.get('response','')).strip()
                track=row.get('track') or self.classify(ins,resp); src=str(row.get('source','unknown'))
                item=LearningItem(ins,resp,track,src,self.quality(ins,resp,src),row.get('metadata') or {})
            key=hashlib.sha256((item.instruction+'\n'+item.response).encode()).hexdigest()
            if key in seen or item.quality < self.min_quality: continue
            seen.add(key); out.append(item)
        return out

    def export_jsonl(self, rows: Iterable[LearningItem], path: str|Path) -> dict:
        path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
        rows=list(rows); counts={}
        with path.open('w',encoding='utf-8') as f:
            for r in rows:
                counts[r.track]=counts.get(r.track,0)+1
                f.write(json.dumps(asdict(r),ensure_ascii=False)+'\n')
        return {'path':str(path),'total':len(rows),'by_track':counts}
