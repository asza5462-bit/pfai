from pathlib import Path
class TextIngestor:
    def __init__(self,memory): self.memory=memory
    def ingest_text(self,text,source='manual',kind='knowledge',chunk_size=1200,overlap=150):
        text=text.strip(); added=0
        if not text: return 0
        step=max(1,chunk_size-overlap)
        for start in range(0,len(text),step):
            chunk=text[start:start+chunk_size].strip()
            if chunk:
                self.memory.add(kind,chunk,source,0.8); added+=1
            if start+chunk_size>=len(text): break
        return added
    def ingest_file(self,path):
        p=Path(path); return self.ingest_text(p.read_text(encoding='utf-8'),str(p))
