import math, re
from collections import Counter

TOKEN_RE = re.compile(r"[\w\u0600-\u06ff]+", re.UNICODE)

def tokens(text):
    return TOKEN_RE.findall(text.lower())

class BM25Retriever:
    """Dependency-free lexical retrieval; replace/augment with vector DB later."""
    def __init__(self, memory):
        self.memory = memory
    def search(self, query, limit=5):
        docs = self.memory.all_documents()
        q = tokens(query)
        if not q or not docs: return []
        N = len(docs); avgdl = sum(len(tokens(d['content'])) for d in docs) / max(N,1)
        df = Counter()
        tokenized=[]
        for d in docs:
            t=tokens(d['content']); tokenized.append(t)
            for x in set(t): df[x]+=1
        out=[]; k1=1.5; b=.75
        for d,t in zip(docs,tokenized):
            c=Counter(t); score=0.0
            for term in q:
                if term not in c: continue
                idf=math.log(1+(N-df[term]+0.5)/(df[term]+0.5))
                score += idf*(c[term]*(k1+1))/(c[term]+k1*(1-b+b*len(t)/max(avgdl,1)))
            if score>0: out.append((score,d))
        out.sort(key=lambda x:x[0], reverse=True)
        return [dict(score=round(s,4), **d) for s,d in out[:limit]]
