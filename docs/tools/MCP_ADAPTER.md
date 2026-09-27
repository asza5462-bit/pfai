# MCP / External Tool Adapter

`MCPAdapter` is provider-agnostic and **untrusted by default**.

- discover → register descriptors (trusted=false)
- owner must `approve_trust` before invoke/register-into-fabric
- timeouts, auditing, schema inspection supported
- missing invoker fails closed
