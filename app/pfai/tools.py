class ToolGateway:
    def __init__(self,web=None,audit=None): self.web=web; self.audit=audit
    def call(self,name,**kwargs):
        if name=='web.fetch':
            if not self.web: raise PermissionError('Web tool unavailable')
            return self.web.fetch(kwargs['url'])
        if self.audit: self.audit.record('policy','unknown_tool_denied',{'tool':name})
        raise PermissionError(f'Unknown or disabled tool: {name}')
