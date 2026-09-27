# PHASE 18 — Authorized Testing

## Gate sequence

Every active test must:

1. Resolve target via `TargetRegistry.resolve`  
2. Verify registration  
3. Verify `authorization_status == AUTHORIZED`  
4. Verify scope (host / domain / port / path)  
5. Verify allowed action / testing method  
6. Verify environment (production → explicit owner approval)  
7. Create audit record  
8. Execute **bounded** test  
9. Collect evidence  
10. Stop at scope boundary  

## Systems

- `TargetAuthorizationGate` (legacy local/declaration flows)
- `ScopeEnforcementLayer` (registry-backed)
- `AuthorizedSecurityTester` (passive HTTP + local static)
- `AuthorizedWebFabricOps` (health, crawl, discover, API test)

## Forbidden

- Scanning arbitrary Internet targets  
- Automatic scope expansion  
- Persistence / unauthorized access  
- Destructive or offensive methods  
- Claiming live external testing that did not occur  

## Production

Production environment targets require explicit owner authorization (`approved=True`). No silent promotion from staging scopes.
