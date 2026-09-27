import urllib.request
class WebTool:
    def __init__(self,policy,audit=None): self.policy=policy; self.audit=audit
    def fetch(self,url):
        if not self.policy.allow_url(url):
            if self.audit: self.audit.record('policy','web_denied',{'url':url})
            raise PermissionError('URL denied by network policy')
        req=urllib.request.Request(url,headers={'User-Agent':'PFAI/0.2'})
        with urllib.request.urlopen(req,timeout=10) as r: data=r.read(self.policy.max_chars)
        if self.audit: self.audit.record('tool','web_fetch',{'url':url,'bytes':len(data)})
        return data.decode('utf-8','replace')
