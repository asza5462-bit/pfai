# PFAI Longevity Architecture (20–30 Year Horizon)

**Product principle:** PFAI = **Long-Lived Adaptive AI Platform**  
Durable · Modular · Portable · Auditable · Versioned · Recoverable · Extensible · Model-agnostic · Provider-agnostic

This document is the PHASE 1 Architecture Foundation. Implementations arrive in later phases via adapters; existing FastAPI + Dashboard features stay.

---

## 1. Current architecture (as of 8.0)

```
RTL Dashboard ──HTTP──► FastAPI (pfai.api)
                          ├── CommandAgent + ToolRouter + Owner Gate
                          ├── Coding Academy (/coding/*)
                          ├── Continuous learning (gated; no auto-promote)
                          ├── MemoryStore (SQLite) + optional VectorStore
                          ├── Model: Anthropic | openai_compatible | Echo | Mock
                          ├── Embeddings: Hash | SentenceTransformers
                          ├── BackupManager + DisasterRecovery (SQLite-oriented)
                          └── EvaluationLab / RegressionCapture / registries (JSON)
```

Public contracts kept forever (stable surface): `/health`, `/chat/*`, `/coding/*`, `/continuous/*`, Dashboard.

---

## 2. Longevity risks (coupling audit)

| Area | Current binding | Risk if frozen 20y | Port / mitigation |
|---|---|---|---|
| LLM | `app.py` branches on `anthropic` / `openai_compatible` / echo | Vendor or API disappearance | `ProviderRegistry` + `ModelRouter` |
| Default config | `model.provider=anthropic` | Implies vendor even if Echo works | Config stays; Core must not require key |
| Memory DB | SQLite files under `data/` | Engine/OS path changes | `RelationalStorePort` + migrations |
| Vectors | SQLite + JSON float vectors | Scale / format obsolescence | `VectorStorePort` + `EmbeddingPort` |
| Embeddings | Hash or sentence-transformers | Model package churn | Embedding port; memory content stays text |
| Hosting | Docker / Render / Railway docs | Host vendors change | App portable; no host in Core |
| Learning | Continuous + optional weight_training scaffold | Accidental prod weight drift | `SafeLearningPipeline` (weights forbidden in Core) |
| Knowledge | Mostly unversioned rows / JSON | No rollback of bad knowledge | `KnowledgeVersion` + versioned store |
| Skills/Tools | Single registry version | Breaking tool upgrades | `SkillVersion` / `ToolVersion` |
| Schema | Implicit CREATE TABLE IF NOT EXISTS | Silent drift | `PFAI_SCHEMA_VERSION` + `MigrationRunner` |
| Export | Partial (backups per file) | Lock-in / loss on move | `ExportPort` / export bundle |
| Self-heal | Limited | Unsafe auto-change | Bounded heal: detect→…→rollback |

---

## 3. Target longevity architecture

```
                    ┌─────────────────────────────────────────┐
                    │     Stable Product Surface (kept)         │
                    │  Dashboard · FastAPI routes · Owner Gate  │
                    └──────────────────┬──────────────────────┘
                                       │
                    ┌──────────────────▼──────────────────────┐
                    │     Application / Orchestration           │
                    │  Command · Coding · Planner · Skills      │
                    └──────────────────┬──────────────────────┘
                                       │
         ┌───────────────┬─────────────┼─────────────┬───────────────┐
         ▼               ▼             ▼             ▼               ▼
   Memory (LTM)    Knowledge      Learning Gate   Evaluation    Self-Check
   kinds+version   versioned      L→E→V→Store     + compare     + bounded heal
         │               │             │             │               │
         └───────────────┴──────┬──────┴─────────────┴───────────────┘
                                ▼
                    ┌───────────────────────────────┐
                    │     Ports (replaceable)         │
                    │ Storage · Vector · Embedding    │
                    │ Model Provider · Blob · Export  │
                    │ Backup · Migration · Compat     │
                    └───────────────────────────────┘
                                │
              adapters today ───┴─── adapters in 5–20 years
              SQLite/Hash/Echo/Mock/Optional Anthropic/Local
```

### Design rules
1. **Never** put a commercial API inside Core invariants.
2. Memory/knowledge are **structured, exportable data** — not model weights.
3. Learning in production = curated knowledge, not silent fine-tunes.
4. Every important mutation is **versioned** and **rollback-capable**.
5. Assume Python, SQLite, Anthropic, and today's hosts may all be gone — ports survive.

---

## 4. Memory Architecture (Long-Term)

Kinds (`MemoryKind`): episodic · semantic · procedural · user_preference · project_knowledge · learned_lesson · verified_knowledge · interaction_history  

Records carry: id, kind, content, source, confidence, version, status, timestamps, provenance.  
Vectors are optional indexes; SQLite/text remains source of truth until a migrated store replaces it.

Contracts: `MemoryRecord`, `LongTermMemoryProtocol` in `pfai.interfaces.memory`.

---

## 5. Learning Architecture (safe)

Pipeline: **Ingest → Evaluate → Validate → Store (Memory/Knowledge) → Future Improvement**  
Sources: experience, task outcomes, feedback, errors, corrections, verified knowledge, successful workflows.  

`SafeLearningPipeline.allows_weight_mutation() == False` for Core.  
Weight training remains optional offline scaffold + owner promotion (existing ADR-003/011).

---

## 6. Versioning / Migration / Config

- Knowledge / Config / Skill / Tool versioning (`pfai.interfaces.versioning`)
- Schema version constant `PFAI_SCHEMA_VERSION` + `MigrationRunner`
- Rollback via versioned store (new active version from prior payload for audit)

---

## 7. Backup / Recovery / Export

Ports over existing `BackupManager` + `DisasterRecovery`.  
Export bundle format `pfai-export-v1` for portable memory/knowledge/config/skills/schema.

---

## 8. Model / Provider Architecture

- `ProviderRegistry` — register Echo/Mock/local first; Anthropic optional
- `ModelRegistry` — candidate → owner-approved active → rollback
- `ModelRouter` — role → provider instance

---

## 9. Evaluation Architecture

- Regression suites (existing pytest + EvaluationLab)
- `VersionComparisonProtocol` — baseline vs candidate before promote
- No promote without compare + owner when production-impacting

---

## 10. Self-diagnostics & bounded self-heal

Heal steps only: detect → diagnose → propose → apply_safe → test → rollback.  
High-risk / irreversible changes require Owner; never auto-apply.

---

## 11. Future Compatibility Layer

Tracks schema version, supported provider/storage kinds, Python floor.  
Guides upgrades of runtime, deps, DB, model APIs, OS, deploy env.

---

## 12. Phase boundary

| Phase | Focus |
|---|---|
| **1 (this)** | Contracts, docs, ADRs, non-wired scaffolds, tests |
| 2 | Wire ProviderRegistry + ModelRouter adapters (keep Echo default path) |
| 3+ | LTM adapters, knowledge versioning, safe learning store, export, migrations, eval compare, bounded heal |

Do not skip phases. Do not replace FastAPI/Dashboard in foundation work.
