class Benchmark:
    def __init__(self,model): self.model=model
    def run(self,cases):
        results=[]; passed=0
        for c in cases:
            out=self.model.generate(c['prompt'])
            ok=all(x.lower() in out.lower() for x in c.get('must_contain',[]))
            results.append({'id':c.get('id','case'),'passed':ok,'output':out})
            passed+=int(ok)
        return {'score':passed/max(len(cases),1),'passed':passed,'total':len(cases),'results':results}
