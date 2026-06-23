"""
Enrich strains.json with PubMed evidence data via NCBI E-utilities + Ollama.

For each unenriched strain:
  1. Search PubMed for RCTs / meta-analyses
  2. Fetch top abstracts
  3. Ask Ollama to extract structured fields
  4. Patch data/strains.json in place

Usage:
    cd ~/Developments/rebon
    python -m rebon.scraper.enrich_strains                   # enrich all unenriched
    python -m rebon.scraper.enrich_strains --id akkermansia_muciniphila
    python -m rebon.scraper.enrich_strains --all             # re-enrich everything
    python -m rebon.scraper.enrich_strains --dry-run         # print changes, no write
    python -m rebon.scraper.enrich_strains --search "Akkermansia muciniphila gut barrier"

Requirements:
    pip install requests langchain-ollama --break-system-packages
    Ollama running locally with your chosen model pulled
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import requests
from langchain_ollama import OllamaLLM

# ── Config ─────────────────────────────────────────────────────────────────────

STRAINS_PATH = Path(__file__).parents[3] / "data" / "strains.json"

NCBI_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
NCBI_EFETCH  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
NCBI_API_KEY = ""          # optional — raises rate limit from 3 to 10 req/s
PUBMED_MAX_RESULTS = 10    # abstracts to fetch per strain
ABSTRACT_CHAR_LIMIT = 8000 # max chars sent to LLM

DEFAULT_MODEL = "llama3.1:8b"  # override with --model flag

EVIDENCE_TIERS = {"strong", "moderate", "preliminary", "unknown"}

# Fields only written when currently empty
FILL_ONLY = {"effective_cfu_dose", "effective_cfu_dose_label", "viability",
             "enteric_coated", "survivability_notes"}
# Fields overwritten even if already populated (when --update is set)
UPDATE_ALWAYS = {"evidence_tier", "key_rcts", "notes", "conditions"}


# ── PubMed helpers ─────────────────────────────────────────────────────────────

def pubmed_search(strain_name: str, extra_terms: str = "", n: int = PUBMED_MAX_RESULTS) -> list[str]:
    """Return up to n PMIDs for clinical/review studies on this strain."""
    # Use genus + species (first two words) as the core query
    species = " ".join(strain_name.split()[:2])
    base = f'("{species}"[Title/Abstract]) AND probiotic[Title/Abstract]'
    clinical = '(randomized[Title/Abstract] OR "clinical trial"[pt] OR "systematic review"[pt] OR "meta-analysis"[pt])'
    query = f"{base} AND {clinical}"
    if extra_terms:
        query = f'({query}) AND ({extra_terms})'

    params = {
        "db": "pubmed", "term": query,
        "retmax": n, "retmode": "json", "sort": "relevance",
    }
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY

    r = requests.get(NCBI_ESEARCH, params=params, timeout=15)
    r.raise_for_status()
    ids = r.json()["esearchresult"]["idlist"]

    # If no clinical hits, fall back to broader search (any article type)
    if not ids:
        params["term"] = f'"{species}"[Title/Abstract] AND probiotic[Title/Abstract]'
        r = requests.get(NCBI_ESEARCH, params=params, timeout=15)
        r.raise_for_status()
        ids = r.json()["esearchresult"]["idlist"]

    return ids


def pubmed_fetch_abstracts(pmids: list[str]) -> str:
    """Fetch plain-text abstracts for a list of PMIDs."""
    if not pmids:
        return ""
    params = {
        "db": "pubmed", "id": ",".join(pmids),
        "rettype": "abstract", "retmode": "text",
    }
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
    r = requests.get(NCBI_EFETCH, params=params, timeout=20)
    r.raise_for_status()
    return r.text


# ── LLM extraction ─────────────────────────────────────────────────────────────

EXTRACTION_PROMPT = """\
You are a clinical evidence reviewer specialising in probiotic research.

Below are PubMed abstracts for the probiotic strain: {strain_name}
Strain designation (if known): {designation}

---
{abstracts}
---

Based ONLY on the abstracts above, extract the following fields as JSON.
Use null for any field where the abstracts provide insufficient evidence.

{{
  "conditions": ["list of health conditions/symptoms supported by ≥1 RCT or meta-analysis"],
  "evidence_tier": "strong | moderate | preliminary | unknown",
  "effective_cfu_dose": "numeric string e.g. '1e9' or '5e9', or null",
  "effective_cfu_dose_label": "human-readable e.g. '1 billion CFU/day', or null",
  "viability": "shelf-stable | refrigerated | unknown",
  "enteric_coated": true | false | null,
  "survivability_notes": "1-2 sentences on stability/delivery, or null",
  "key_rcts": ["Author et al. YEAR — key finding (PMID XXXXXXXX, Journal)"],
  "notes": "1-2 sentences summarising the evidence landscape for this strain"
}}

Evidence tier guide:
  strong:      ≥2 high-quality RCTs or ≥1 meta-analysis with consistent positive results
  moderate:    1 good RCT, or mixed findings across RCTs
  preliminary: only pilot studies, animal models, or in vitro data
  unknown:     no human clinical data found in these abstracts

Return ONLY valid JSON. No explanation, no markdown fences.
"""


def extract_with_llm(strain_name: str, designation: str, abstracts: str, model: str) -> dict | None:
    llm = OllamaLLM(model=model, format="json")
    prompt = EXTRACTION_PROMPT.format(
        strain_name=strain_name,
        designation=designation or "unspecified",
        abstracts=abstracts[:ABSTRACT_CHAR_LIMIT],
    )
    response = llm.invoke(prompt)

    # Strip markdown fences if present
    response = re.sub(r"```(?:json)?", "", response).strip()

    m = re.search(r"\{.*\}", response, re.DOTALL)
    if not m:
        print(f"    ⚠  LLM returned no JSON for {strain_name}")
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        print(f"    ⚠  JSON parse error for {strain_name}: {e}")
        return None


# ── Enrichment logic ───────────────────────────────────────────────────────────

def enrich_strain(
    strain: dict,
    dry_run: bool = False,
    update: bool = False,
    extra_search: str = "",
    model: str = OLLAMA_MODEL,
) -> dict:
    name = strain.get("name", strain["id"])
    designation = strain.get("strain_designation") or ""
    print(f"\n  → {strain['id']}  ({name})")

    pmids = pubmed_search(name, extra_terms=extra_search)
    if not pmids:
        print(f"    No PubMed results — skipping")
        return strain
    print(f"    {len(pmids)} PMIDs: {pmids}")
    time.sleep(0.4)  # respect NCBI rate limit

    abstracts = pubmed_fetch_abstracts(pmids)
    time.sleep(0.4)

    extracted = extract_with_llm(name, designation, abstracts, model)
    if not extracted:
        return strain

    updated = dict(strain)
    changed = []

    for field in FILL_ONLY | UPDATE_ALWAYS:
        new_val = extracted.get(field)
        if not new_val:
            continue
        old_val = updated.get(field)
        is_empty = old_val in (None, "", [], "unknown", False)
        if is_empty or (update and field in UPDATE_ALWAYS):
            if updated.get(field) != new_val:
                updated[field] = new_val
                changed.append(field)

    # Normalise evidence_tier
    if updated.get("evidence_tier") not in EVIDENCE_TIERS:
        updated["evidence_tier"] = "unknown"

    if changed:
        updated["enriched"] = True
        print(f"    ✓  Updated: {', '.join(changed)}")
        if dry_run:
            print(f"    [dry-run] proposed: {json.dumps({f: updated[f] for f in changed}, indent=6)}")
    else:
        print(f"    — No changes")

    return updated


# ── Main ───────────────────────────────────────────────────────────────────────

def run(
    target_id: str | None,
    enrich_all: bool,
    update: bool,
    dry_run: bool,
    extra_search: str,
    model: str,
):
    with open(STRAINS_PATH) as f:
        strains = json.load(f)

    if target_id:
        targets = [s for s in strains if s["id"] == target_id]
        if not targets:
            print(f"Strain '{target_id}' not found in strains.json")
            return
    elif enrich_all or update:
        targets = strains
    else:
        targets = [s for s in strains if not s.get("enriched")]

    print(f"Mode: {'update' if update else 'enrich'} | Model: {model} | Strains: {len(targets)}")

    updated_map = {s["id"]: s for s in strains}
    for strain in targets:
        enriched = enrich_strain(
            strain, dry_run=dry_run, update=update,
            extra_search=extra_search, model=model,
        )
        updated_map[enriched["id"]] = enriched
        time.sleep(1)

    if not dry_run:
        result = list(updated_map.values())
        with open(STRAINS_PATH, "w") as f:
            json.dump(result, f, indent=2)
        enriched_count = sum(1 for s in result if s.get("enriched"))
        print(f"\nDone. {STRAINS_PATH.name} updated — {enriched_count}/{len(result)} strains enriched.")
    else:
        print("\n[dry-run] No files written.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enrich strains.json with PubMed + Ollama")
    parser.add_argument("--id", help="Target a single strain by ID")
    parser.add_argument("--all", action="store_true", help="Re-enrich all strains (fill empty fields)")
    parser.add_argument("--update", action="store_true", help="Overwrite evidence_tier, conditions, key_rcts, notes for all strains")
    parser.add_argument("--dry-run", action="store_true", help="Print proposed changes without writing")
    parser.add_argument("--search", default="", help="Extra PubMed search terms appended to each query")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Claude model to use (default: {DEFAULT_MODEL})")
    args = parser.parse_args()

    run(
        target_id=args.id,
        enrich_all=args.all,
        update=args.update,
        dry_run=args.dry_run,
        extra_search=args.search,
        model=args.model,
    )
