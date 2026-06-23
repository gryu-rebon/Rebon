"""
Seed ChromaDB with strain data from data/strains.json.

Usage:
    python -m rebon.db.ingest                # seed strains
    python -m rebon.db.ingest --reset        # drop and re-seed
    python -m rebon.db.ingest --dry-run      # show what would be seeded

Requirements:
    ollama pull nomic-embed-text
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .chroma import get_client, EMBEDDING_FN

STRAINS_PATH = Path(__file__).parents[3] / "data" / "strains.json"


# ── document builders ─────────────────────────────────────────────────────────

def _strain_document(s: dict) -> str:
    lines = [
        f"Strain: {s['name']}",
        f"Conditions: {', '.join(s.get('conditions', []))}",
        f"Evidence tier: {s.get('evidence_tier', 'unknown')}",
        f"Effective CFU dose: {s.get('effective_cfu_dose_label') or 'unknown'}",
        f"Viability: {s.get('viability') or 'unknown'}",
        f"Survivability: {s.get('survivability_notes') or ''}",
        f"Notes: {s.get('notes') or ''}",
    ]
    if s.get("key_rcts"):
        lines.append("Key RCTs: " + "; ".join(s["key_rcts"]))
    return "\n".join(lines)


def _strain_metadata(s: dict) -> dict:
    """Flat metadata for filtering — ChromaDB only accepts str/int/float/bool."""
    return {
        "evidence_tier": s.get("evidence_tier") or "unknown",
        "conditions": ", ".join(s.get("conditions") or []),
        "viability": s.get("viability") or "unknown",
        "enteric_coated": bool(s.get("enteric_coated")),
        "enriched": bool(s.get("enriched")),
    }


# ── seed ──────────────────────────────────────────────────────────────────────

def seed_strains(reset: bool = False, dry_run: bool = False) -> int:
    with open(STRAINS_PATH) as f:
        strains = json.load(f)

    # Only seed enriched strains with at least one condition
    valid = [
        s for s in strains
        if s.get("enriched") and s.get("conditions")
    ]

    print(f"  Strains in file: {len(strains)}")
    print(f"  Enriched + has conditions: {len(valid)}")

    if dry_run:
        for s in valid:
            print(f"  → {s['id']}  ({s.get('evidence_tier')})  {s.get('conditions', [])[:3]}")
        return len(valid)

    client = get_client()

    if reset:
        try:
            client.delete_collection("strains")
            print("  Dropped existing strains collection.")
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name="strains",
        embedding_function=EMBEDDING_FN,
        metadata={"hnsw:space": "cosine"},
    )

    collection.upsert(
        ids=[s["id"] for s in valid],
        documents=[_strain_document(s) for s in valid],
        metadatas=[_strain_metadata(s) for s in valid],
    )
    return len(valid)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Seed ChromaDB with strain data")
    parser.add_argument("--reset", action="store_true", help="Drop and re-seed the collection")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    print("Seeding strains...")
    n = seed_strains(reset=args.reset, dry_run=args.dry_run)
    if not args.dry_run:
        print(f"  ✓ {n} strains upserted into ChromaDB")


if __name__ == "__main__":
    main()
