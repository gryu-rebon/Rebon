# Project: rebon

## Overview
Personalized probiotic recommender app. Rebuilt from scratch (POC was in ~/Developments/Probiotics recommender).

## Repo
- GitHub: https://github.com/gryu-rebon/Rebon.git
- Local: ~/Developments/rebon
- Branch: main

## Stack
- Python 3.14
- FastAPI + uvicorn (web app / API)
- LangGraph + LangChain + langchain-ollama (agent, default model: llama3.1:8b)
- ChromaDB + nomic-embed-text via Ollama (vector store)
- PubMed E-utilities API (strain enrichment)
- Ollama for local LLM inference

## Project structure
src/rebon/
  api/main.py        — FastAPI app + embedded HTML UI (tabbed: Strains live, others placeholder)
  agent/             — LangGraph skeleton (state.py, graph.py)
  db/chroma.py       — ChromaDB client
  db/ingest.py       — Seeds enriched strains into ChromaDB
  db/query.py        — Semantic strain search
  scraper/enrich_strains.py — PubMed + Ollama strain enrichment pipeline
data/
  strains.json       — 78 strains (59 enriched as of session 2025-06-23)
  chroma/            — Persisted ChromaDB

## Run commands
uvicorn src.rebon.api.main:app --reload --port 8000
python -m src.rebon.scraper.enrich_strains         # enrich unenriched strains
python -m src.rebon.db.ingest                      # seed ChromaDB
python -m src.rebon.db.query "IBS bloating"        # smoke test

## Current state (2026-06-23)
- Strains tab live in web app (search, filter by evidence tier, sort, detail panel, in-DB flag)
- 59/78 strains enriched; remaining 19 will be enriched when llama3.1:8b is pulled
- Products, Recommender, Conditions tabs are placeholders
- No product data yet (DSLD or iHerb scraper not yet ported)
- Package must be installed editable before running: pip3 install -e . --break-system-packages

## POC reference
~/Developments/Probiotics recommender — original POC with scraper, agent, and GUTCheck UI
