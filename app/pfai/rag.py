class RAGEngine:
    def __init__(self, model, store, research=None, audit=None):
        self.model, self.store, self.research_engine, self.audit = model, store, research, audit

    def _hits(self, question, urls=None):
        if self.research_engine:
            ev=self.research_engine.research(question, limit=5, urls=urls)['evidence']
            return [{'source':e['source'],'content':e['excerpt'],'score':e['score'],'verified':e.get('verified',True)} for e in ev]
        return self.store.search(question,5)

    def answer(self, question, urls=None):
        hits=self._hits(question,urls)
        context='\n\n'.join(f"[Source: {h.get('source','')}] {h.get('content',h.get('excerpt',''))}" for h in hits)
        prompt=("You are PFAI. Answer using only the supplied evidence. Separate facts from uncertainty. "
                "If evidence is insufficient, say so. Do not invent sources.\n\nQuestion: "+question+"\n\nEvidence:\n"+context)
        answer=self.model.generate(prompt)
        sources=[h.get('source','') for h in hits]
        out={'answer':answer,'hits':hits,'sources':sources}
        if self.audit: self.audit.record('rag','answer',{'question':question,'sources':len(sources)})
        return out

RAG=RAGEngine
