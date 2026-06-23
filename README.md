# Rebon

Personalized probiotic recommender — research tool and recommendation engine backed by PubMed evidence data and a local LLM.

## What it does

- Maintains a curated database of probiotic strains enriched with PubMed evidence (conditions, evidence tier, effective dose, viability, key RCTs)
- Stores enriched strains in ChromaDB for semantic search
- Serves a web UI to browse strains, filter by column, and inspect individual strain details

The recommender and products tabs are under active development.

## Stack

- **Python 3.11+** with FastAPI + uvicorn
- **LangGraph + LangChain** for the agent pipeline (in progress)
- **Ollama** (`llama3.1:8b`) for local LLM inference
- **ChromaDB** with `nomic-embed-text` embeddings via Ollama
- **PubMed NCBI E-utilities** for strain evidence enrichment

## Prerequisites

1. **Python 3.11+**
2. **Ollama** — install from [ollama.com](https://ollama.com), then pull the required models:
   ```bash
   ollama pull llama3.1:8b
   ollama pull nomic-embed-text
   ```

## Setup

```bash
git clone https://github.com/gryu-rebon/Rebon.git
cd rebon

# Install dependencies (editable install)
pip3 install -e . --break-system-packages

# Copy environment config
cp .env.example .env
```

`.env` defaults are fine for local development — no API keys required.

## Running the web app

Make sure Ollama is running, then:

```bash
uvicorn src.rebon.api.main:app --reload --port 8000
```

Open [http://localhost:8000](http://localhost:8000). The **Strains** tab is live; Recommender, Products, and Conditions tabs are placeholders.

## Enriching strains

Strain data lives in `data/strains.json`. The enrichment script pulls PubMed abstracts for each strain and uses Ollama to extract structured fields.

```bash
# Enrich all unenriched strains (default)
python3 -m rebon.scraper.enrich_strains

# Re-enrich a specific strain
python3 -m rebon.scraper.enrich_strains --id akkermansia_muciniphila

# Re-enrich everything (overwrite existing)
python3 -m rebon.scraper.enrich_strains --all

# Preview without writing
python3 -m rebon.scraper.enrich_strains --dry-run

# Use a different model
python3 -m rebon.scraper.enrich_strains --model llama3.2:3b
```

Enrichment requires Ollama running with `llama3.1:8b`. The script retries NCBI requests automatically on transient errors.
