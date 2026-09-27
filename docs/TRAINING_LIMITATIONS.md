# Training Limitations (PHASE 9)

- GPU unavailable in this environment → CPU LoRA only; no QLoRA without CUDA+bitsandbytes.
- Real open-weight starter used: **distilgpt2 (~82M)** — not a large foundation model.
- Bounded training (few steps, short sequences) for verification.
- Dataset is curated/seeded and small relative to production corpora.
- Evaluation gates use platform suites; they do **not** by themselves certify SOTA quality.
- `MODEL_QUALITY_PRODUCTION_VALIDATED = false` until larger datasets and measured task suites justify it.
- No deploy in PHASE 9. No silent model downloads.
