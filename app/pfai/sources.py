from dataclasses import dataclass
from datetime import datetime, timezone

@dataclass(frozen=True)
class Source:
    uri:str
    title:str=''
    publisher:str=''
    retrieved_at:str=''
    def as_dict(self): return {'uri':self.uri,'title':self.title,'publisher':self.publisher,'retrieved_at':self.retrieved_at or datetime.now(timezone.utc).isoformat()}
