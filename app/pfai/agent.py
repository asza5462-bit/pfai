class Agent:
    def __init__(self,model,memory,tools,audit,rag=None,reflector=None):
        self.model=model; self.memory=memory; self.tools=tools; self.audit=audit; self.rag=rag; self.reflector=reflector
    def answer(self,question):
        if self.rag:
            result=self.rag.answer(question)
            answer_text=result.get('answer','') if isinstance(result,dict) else str(result)
        else:
            memories=self.memory.search(question,5); context='\n'.join(x['content'] for x in memories)
            prompt=f"Question: {question}\nRelevant memory:\n{context}\nAnswer only from supported context; say when uncertain."
            self.audit.record('agent','generate',{'question':question})
            answer_text=self.model.generate(prompt); result=answer_text
        if self.reflector:
            try: self.reflector.reflect(question,answer_text)
            except Exception: pass
        return result
    ask=answer
