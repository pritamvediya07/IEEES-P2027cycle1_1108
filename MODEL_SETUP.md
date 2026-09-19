# LLM Model Setup Guide

This guide covers on-device (Ollama) setup for the models used in the PALA paper experiments, and the optional cloud API backends of `exp1_vuln_multimodel.py`.

---

## Models Used in the Paper

| Model | Ollama tag / API model | Size | Used in |
|-------|-----------|-----------|---------|
| **Qwen 2.5 72B** | `qwen2.5:72b` | 47 GB (Q4_K_M) | Primary model: all UERANSIM experiments (RQ1–RQ5); srsRAN E3, E5 |
| **Mistral Large** | `mistral-large:latest` | 73 GB (Q4_K_M) | Cross-family rows of Table 2 (Exp 1 multimodel) and Table 3 (Exp 3 multimodel) |
| **Llama 3.1 70B** | `llama3.1:70b` | 42 GB (Q4_K_M) | Cross-family rows of Table 2 (Exp 1 multimodel) and Table 3 (Exp 3 multimodel) |
| **Llama 3.1 8B** | `llama3.1:latest` | 4.9 GB (Q4_K_M) | srsRAN E6 capability sweep, 7-8B tier |
| **Gemma 3 12B** | `gemma3-12b-it-q8:latest` | 12 GB (Q8_0) | srsRAN E6 capability sweep, 12-15B tier |
| **Claude Sonnet 4.5** | `claude-sonnet-4-5` (Anthropic API) | — | srsRAN E6 capability sweep, frontier tier (needs a paid `ANTHROPIC_API_KEY`) |

`qwen3-coder:30b` appears only in the partial E6 30–36B cell; that tier is not rerun by default (`live-srsran` runs `--tiers 7-8B,12-15B`).

**Note:** Of the UERANSIM models, Qwen 2.5 72B is the only one needed for everything except the cross-family rows of Table 2 (§6.2) and Table 3 (§6.4); those rows also need `mistral-large:latest` and `llama3.1:70b`. The srsRAN capability sweep (E6) additionally needs `llama3.1:latest` and `gemma3-12b-it-q8:latest`, and the Anthropic API for its frontier tier.

---

## Option A — On-Device via Ollama (Paper Setup)

This is exactly how the paper experiments were run, and it is **required** for Track B: every UERANSIM experiment runs through a local Ollama. There is no GPU-free route.

### 1. Install Ollama

```bash
curl -fsSL https://ollama.ai/install.sh | sh
# Start the daemon (if not started automatically):
ollama serve &
```

Verify: `ollama list`

### 2. Pull Models

```bash
# Primary model — required for all UERANSIM experiments
ollama pull qwen2.5:72b              # 47 GB

# Cross-family rows (Tables 2 and 3)
ollama pull mistral-large:latest     # 73 GB
ollama pull llama3.1:70b             # 42 GB

# srsRAN E6 capability tiers (Track C2)
ollama pull llama3.1:latest          # 4.9 GB, 7-8B tier
ollama pull gemma3-12b-it-q8:latest  # 12 GB, 12-15B tier
```

**Total disk space:** ~162 GB for the three UERANSIM models, ~179 GB with the E6 tiers. Only 47 GB is required for the primary-model experiments.

### 3. Hardware Requirements

| Model | Minimum VRAM | Recommended |
|-------|-------------|-------------|
| `qwen2.5:72b` | 48 GB | 1× A100-80GB or 2× A40-48GB |
| `llama3.1:70b` | 42 GB | 1× A100-80GB or 2× A40-48GB |
| `mistral-large:latest` | 73 GB | 2× A100-80GB or 4× A40-48GB |

The paper's runs used a single 96 GB GPU (see the README's *Reference System*); Ollama loads one model at a time.

**CPU offload note:** Ollama can offload layers to CPU RAM if VRAM is insufficient, but inference will be 10–50× slower. A 48-layer 72B model at ~2 tokens/sec means ~45 min per trial vs ~3 min with full GPU. For the 30-trial primary experiment this is ~22 hrs vs ~1.5 hrs.

### 4. Configure `.env`

```bash
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:72b
```

### 5. Verify

```bash
curl -s http://localhost:11434/api/chat \
  -d '{"model":"qwen2.5:72b","messages":[{"role":"user","content":"reply OK"}],"stream":false}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['message']['content'])"
# Expected output: OK (or similar)
```

---

## Option B — Cloud API (`exp1_vuln_multimodel.py` only)

Cloud backends are supported **only** by `wave_experiments/exp1_vuln_multimodel.py`, which produces the cross-family rows of Table 2. Every other experiment (including Exp 1 for Qwen, Exp 3 multimodel and all RQ2–RQ5 experiments) runs through the local Ollama of Option A. Results from a cloud provider will differ from the paper (different quantization, sampling), and a provider model that is not the paper's model gives a result that is not the paper's.

Install the optional clients first:

```bash
pip install -r requirements-api.txt   # openai (OpenAI-compatible providers), google-genai
```

These commands call the script directly, so first set the stored results aside (otherwise the script resumes from them and runs no new trials); see the README's *Running Multimodel Experiments via API*.

### Qwen 2.5 72B — via Together AI

**Provider:** https://www.together.ai  
**API model ID:** `Qwen/Qwen2.5-72B-Instruct-Turbo`

```bash
# .env configuration:
OPENAI_COMPAT_KEY=your_together_key
OPENAI_COMPAT_BASE_URL=https://api.together.xyz/v1
OPENAI_COMPAT_MODEL=Qwen/Qwen2.5-72B-Instruct-Turbo
```

```bash
# Run the RQ1 vulnerable arm for Qwen with the Together AI backend:
source .venv/bin/activate
python wave_experiments/exp1_vuln_multimodel.py \
    --models qwen2.5:72b \
    --backend openai_compat \
    --api-model Qwen/Qwen2.5-72B-Instruct-Turbo
```

`exp1_end_to_end.py` (vulnerable + defended arms) runs through Ollama only; its options are
`--arm {vulnerable,defended,both}` and `--trials N`. The API backends (`--backend`,
`--api-model`, `--backend-map`) are options of `exp1_vuln_multimodel.py`.

---

### Llama 3.1 70B — via Groq

**Provider:** https://console.groq.com  
**API model ID:** none available — Groq has **retired** `llama-3.1-70b-versatile`, the model this route used. Any model Groq serves today can be passed with `--api-model`, but it is then not the paper's model.

```bash
# .env configuration (the Groq key goes in OPENAI_COMPAT_KEY):
OPENAI_COMPAT_KEY=your_groq_key
OPENAI_COMPAT_BASE_URL=https://api.groq.com/openai/v1
```

```bash
# Run with the Groq backend (substitute a model Groq currently serves):
python wave_experiments/exp1_vuln_multimodel.py \
    --models llama3.1:70b \
    --backend groq \
    --api-model <model-id-served-by-groq>
```

---

### Mistral Large — via Mistral API

**Provider:** https://console.mistral.ai  
**API model ID:** `mistral-large-latest`

```bash
# .env configuration:
OPENAI_COMPAT_KEY=your_mistral_key
OPENAI_COMPAT_BASE_URL=https://api.mistral.ai/v1
OPENAI_COMPAT_MODEL=mistral-large-latest
```

```bash
# Run Mistral experiments with Mistral API backend:
python wave_experiments/exp1_vuln_multimodel.py \
    --models mistral-large:latest \
    --backend openai_compat \
    --api-model mistral-large-latest
```

---

### Gemini

`--backend gemini` (`GEMINI_API_KEY`, `GEMINI_MODEL` in `.env`) exists in the code, but Gemini is **not** a paper model; it is not used for any result in the paper.

---

## Quick Reference — API Backends

To run the models in sequence with their respective API backends (same Groq caveat as above):

```bash
python wave_experiments/exp1_vuln_multimodel.py \
    --models qwen2.5:72b llama3.1:70b mistral-large:latest \
    --backend-map '{"qwen2.5:72b": ["openai_compat", "Qwen/Qwen2.5-72B-Instruct-Turbo"],
                    "llama3.1:70b": ["groq", "<model-id-served-by-groq>"],
                    "mistral-large:latest": ["openai_compat", "mistral-large-latest"]}'
```

---

## Backend Selection Summary

| Model (paper) | On-device (Ollama) | Cloud API (`exp1_vuln_multimodel.py` only) |
|--------------|-------------------|-----------------|
| qwen2.5:72b | `ollama pull qwen2.5:72b` | Together AI `Qwen/Qwen2.5-72B-Instruct-Turbo` |
| mistral-large | `ollama pull mistral-large:latest` | Mistral API `mistral-large-latest` |
| llama3.1:70b | `ollama pull llama3.1:70b` | Groq: paper model retired; Together AI `meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo` (built-in default of the `together` backend) |
| llama3.1:latest (8B) | `ollama pull llama3.1:latest` | — (srsRAN E6, Ollama only) |
| gemma3-12b-it-q8 | `ollama pull gemma3-12b-it-q8:latest` | — (srsRAN E6, Ollama only) |
| claude-sonnet-4-5 | — | Anthropic API, `ANTHROPIC_API_KEY` (srsRAN E6 frontier tier; client in `requirements-srsran.txt`) |

**Recommendation for evaluators without a GPU:** Track B cannot run without a local GPU. Use Track A and C1 (offline); the live tracks need the hardware listed in the README's *Hardware for the Reproduced badge*.

---

## Notes on Result Reproducibility

- **Stored results (final_experiments/)** were produced with the exact Ollama models shown above (and the Anthropic API for the E6 frontier tier). `reproduce_results.py` verifies these stored results and requires no LLM at all.
- **Live experiment runs** with API backends will produce different numerical results due to different quantization, system prompts, and sampling behavior at cloud providers; a provider model that differs from the paper's model is not a reproduction of the paper's row.
- The agent runs at temperature 0.1 (`LLM_TEMPERATURE = 0.1` in `config/settings.py`) for all experiments, but some APIs enforce minimum temperature floors.
