"""
Query functions for the strains ChromaDB collection.

Runnable for smoke-testing:
    python -m rebon.db.query "IBS bloating"
    python -m rebon.db.query "anxiety sleep" --tier strong
    python -m rebon.db.query "vaginal health" --n 5
"""

from __future__ import annotations

import argparse

from .chroma import get_client, EMBEDDING_FN


def query_strains(
    condition: str,
    n_results: int = 5,
    evidence_tier: str | None = None,
) -> list[dict]:
    """
    Semantic search over the strains collection.

    Args:
        condition:     Free-text condition/symptom (e.g. "IBS bloating").
        n_results:     Number of results to return.
        evidence_tier: Optional filter — "strong", "moderate", or "preliminary".

    Returns:
        List of dicts with strain_id, evidence_tier, conditions, distance, document.
    """
    client = get_client()
    col = client.get_collection("strains", embedding_function=EMBEDDING_FN)

    where = {"evidence_tier": {"$eq": evidence_tier}} if evidence_tier else None

    results = col.query(
        query_texts=[condition],
        n_results=n_results,
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    out = []
    for i, strain_id in enumerate(results["ids"][0]):
        meta = results["metadatas"][0][i]
        out.append({
            "strain_id": strain_id,
            "evidence_tier": meta.get("evidence_tier"),
            "conditions": meta.get("conditions"),
            "viability": meta.get("viability"),
            "distance": round(results["distances"][0][i], 4),
            "document": results["documents"][0][i],
        })
    return out


def get_strain(strain_id: str) -> dict | None:
    """Fetch a single strain record by ID."""
    client = get_client()
    col = client.get_collection("strains", embedding_function=EMBEDDING_FN)
    result = col.get(ids=[strain_id], include=["documents", "metadatas"])
    if not result["ids"]:
        return None
    return {
        "strain_id": strain_id,
        "metadata": result["metadatas"][0],
        "document": result["documents"][0],
    }


# ── CLI smoke test ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Query the strains collection")
    parser.add_argument("query", nargs="?", default="IBS bloating")
    parser.add_argument("--tier", choices=["strong", "moderate", "preliminary"], default=None)
    parser.add_argument("--n", type=int, default=5)
    args = parser.parse_args()

    print(f"\n── Strain search: '{args.query}' ──\n")
    results = query_strains(args.query, n_results=args.n, evidence_tier=args.tier)

    if not results:
        print("No results.")
        return

    for r in results:
        print(f"[{r['distance']:.4f}] {r['strain_id']}")
        print(f"  Evidence: {r['evidence_tier']}")
        print(f"  Conditions: {r['conditions']}")
        print()


if __name__ == "__main__":
    main()
