# Sandbox

`Sandbox` provides an isolated workspace with:

- filesystem boundary under sandbox root
- command list execution + timeout
- sanitized environment (strips secret-like keys)
- output capture / exit codes / cleanup / audit

No automatic access to owner credentials, session secrets, auth DBs, or private keys.
