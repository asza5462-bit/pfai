from dataclasses import dataclass, asdict
from urllib.parse import urlparse
import re

@dataclass
class Evidence:
    source: str
    title: str
    excerpt: str
    score: float = 0.0
    verified: bool = False

class ResearchEngine:
    def __init__(self, store, web=None, policy=None, audit=None):
        self.store, self.web, self.policy, self.audit = store, web, policy, audit

    def _clean(self, text, n=700):
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:n]

    def research(self, question, limit=5, urls=None):
        evidence=[]
        for item in self.store.search(question, limit):
            evidence.append(Evidence(item.get('source','memory'), item.get('metadata',{}).get('title','knowledge'), self._clean(item.get('content','')), float(item.get('score',0)), True))
        for url in (urls or [])[:3]:
            if not self.web: continue
            try:
                text=self.web.fetch(url)
                evidence.append(Evidence(url, urlparse(url).netloc, self._clean(text), 0.0, True))
            except Exception as exc:
                if self.audit: self.audit.record('research','source_error',{'url':url,'error':str(exc)})
        result={'question':question,'evidence':[asdict(e) for e in evidence], 'count':len(evidence)}
        if self.audit: self.audit.record('research','completed',{'question':question,'count':len(evidence)})
        return result
