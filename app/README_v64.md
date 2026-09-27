# PFAI v6.4 — Distributed Training & Research Fabric

Adds policy-aware orchestration for training, research, and evaluation jobs on already-authorized workers.

Key controls:
- resource-aware dispatch through the v6.3 scheduler;
- explicit job kinds: training, research, evaluation;
- evaluation records benchmark/security/regression/provenance results;
- model promotion always passes through the high-assurance upgrade gate;
- external human/control approval is required before promotion;
- failed security/regression/provenance checks cannot be approved.

This layer does not claim to train model weights by itself. Real training requires an installed backend, model, dataset, and actual compute.
