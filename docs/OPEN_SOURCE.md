# PFAI Open Source

PFAI application source is licensed under **Apache License 2.0** (`LICENSE`).

## What is open

- FastAPI control plane, Command Chat brain, Coding Academy, tool router
- Continuous learning orchestration (candidate curation / evaluation)
- Autonomous training control plane (eligibility, jobs, rollback)
- Dashboard UI (`app/pfai/static/`)

## What stays private / operator-owned

- Deployed secrets (`ANTHROPIC_API_KEY`, `PFAI_OWNER_PASSWORD_HASH`, session keys)
- Live Render/runtime volumes and operator datasets
- Third-party model weights under their own licenses (`app/data/models/*/LICENSE*`)

## Continuous evolution (honest)

1. Chat + academy successes feed the **experience bridge** (learning candidates).
2. Training eligibility is evaluated on quality gates — never invented.
3. Model **promotion / activation** stays an explicit privileged operation.
4. Open Chat Tool Execution removes approval locks in Public Access Mode so the
   brain can run tools immediately; it does **not** auto-train production weights.

## Making the GitHub repository public

If the GitHub repo is still private, the copyright license still applies to the
source tree. Publishing visibility is an operator action:

```bash
gh repo edit asza5462-bit/pfai --visibility public
```

Audit for secrets before flipping visibility.
