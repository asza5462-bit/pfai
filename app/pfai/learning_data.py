from typing import Any, Dict, List

def sanitize_dataset(items: List[Dict[str,Any]], max_chars=12000):
    out=[]
    for x in items:
        if not isinstance(x,dict): continue
        q=str(x.get('prompt','')).strip(); a=str(x.get('answer','')).strip()
        if not q or not a: continue
        out.append({'prompt':q[:max_chars],'answer':a[:max_chars],'source':str(x.get('source','unknown'))[:500]})
    return out
