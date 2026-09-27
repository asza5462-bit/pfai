# PHASE 18 — Application Engineering

## Pipeline

`ApplicationEngineering` implements:

1. Understand requirements  
2. Design architecture  
3. Create project structure via adapters  
4. Generate frontend / backend / APIs (adapter-dependent)  
5. Database schemas (where applicable)  
6. Authentication + authorization stubs (deny-by-default)  
7. Tests + documentation  
8. Static checks (parallel where safe)  
9. Run tests in bounded sandbox  
10. Identify failures / propose & apply authorized safe fixes  
11. Retest  
12. Produce versioned artifact + audit  

## Coding agent bridge

`CodingAgentBridge` connects inspection, code search, dependency inventory, architecture analysis, implementation, testing, debugging/refactoring support, and documentation updates.

Every modification yields:

- change set  
- reason  
- affected files  
- tests executed + result  
- rollback information  
- audit record  

Never bypasses authorization.

## Learning / training

Successful engineering/security tasks may feed Experience Bridge → Learning → Evaluation → Dataset → Autonomous Training.

Constraints:

- Do not learn unverified security conclusions automatically  
- Training remains evaluated, versioned, checkpointed, rollbackable  
- Isolated from authentication/security policy  
- Model updates never modify authorization rules  
- LKG retained; candidates do not destroy the accepted model  

## Sandbox

Generated applications run under existing bounded sandbox:

- isolated workspace, resource limits, timeout  
- filesystem / process / network restrictions  
- cleanup + artifact capture  

`SANDBOX_STATUS=READY_BOUNDED` (not full container isolation).

## Performance

Bounded parallelism for static analysis, unit tests, and independent security checks. Caching of repository indexing / dependency metadata is best-effort. Authorization and correctness are never sacrificed for speed.
