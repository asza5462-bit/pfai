from __future__ import annotations
import hashlib, json, re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

@dataclass(frozen=True)
class Example:
    instruction: str
    response: str
    source: str = "unknown"
    metadata: dict | None = None

@dataclass(frozen=True)
class DatasetManifest:
    dataset_id: str
    version: str
    total: int
    train: int
    validation: int
    test: int
    sha256: str
    quality_score: float

class DataFactory:
    def __init__(self, min_chars: int = 3, max_chars: int = 20000):
        self.min_chars, self.max_chars = min_chars, max_chars

    def clean(self, rows: Iterable[dict | Example]) -> list[Example]:
        seen = set(); out=[]
        for row in rows:
            e = row if isinstance(row, Example) else Example(
                instruction=str(row.get("instruction", "")).strip(),
                response=str(row.get("response", "")).strip(),
                source=str(row.get("source", "unknown")),
                metadata=row.get("metadata") or {},
            )
            e = Example(re.sub(r"\s+", " ", e.instruction), re.sub(r"\s+", " ", e.response), e.source, e.metadata)
            key = hashlib.sha256((e.instruction+"\\0"+e.response).encode()).hexdigest()
            if len(e.instruction) < self.min_chars or len(e.response) < self.min_chars: continue
            if len(e.instruction)+len(e.response) > self.max_chars or key in seen: continue
            seen.add(key); out.append(e)
        return out

    def split(self, rows: list[Example], train_ratio=.8, val_ratio=.1) -> dict[str,list[Example]]:
        rows = list(rows); n=len(rows)
        ntr=int(n*train_ratio); nv=int(n*val_ratio)
        if n >= 3:
            ntr=max(1,ntr); nv=max(1,nv); nte=max(1,n-ntr-nv)
            while ntr+nv+nte>n: ntr-=1
        else: ntr=max(0,n-2); nv=1 if n>=2 else 0; nte=n-ntr-nv
        return {"train":rows[:ntr],"validation":rows[ntr:ntr+nv],"test":rows[ntr+nv:ntr+nv+nte]}

    def manifest(self, dataset_id:str, version:str, splits:dict[str,list[Example]]) -> DatasetManifest:
        payload=[asdict(x) for k in ("train","validation","test") for x in splits[k]]
        raw=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":" )).encode()
        quality=sum(1 for x in payload if x["instruction"] and x["response"])/len(payload) if payload else 0.0
        return DatasetManifest(dataset_id,version,len(payload),len(splits["train"]),len(splits["validation"]),len(splits["test"]),hashlib.sha256(raw).hexdigest(),quality)

    def save_jsonl(self, path: str|Path, rows: Iterable[Example]) -> None:
        p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
        with p.open("w",encoding="utf-8") as f:
            for r in rows: f.write(json.dumps(asdict(r),ensure_ascii=False)+"\n")
