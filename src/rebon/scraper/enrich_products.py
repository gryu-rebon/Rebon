"""
Enrich products.json with detailed supplement info from DSLD (NIH), iHerb, and Amazon.

Priority:
  1. DSLD (api.ods.od.nih.gov) — authoritative label data, no scraping required
  2. iHerb product page (URL already in products.json) — supplement facts + price
  3. Amazon product page (URL already in products.json) — description + price fallback

Fields added per product:
  dsld_id, upc, serving_size, servings_per_container, form,
  supplement_facts (list of ingredients w/ amount + unit),
  probiotic_strains (extracted subset), total_cfu,
  price, image_url, description, detail_source

Usage:
    cd ~/Developments/rebon
    python -m rebon.scraper.enrich_products                      # enrich all
    python -m rebon.scraper.enrich_products --brand "Florastor"
    python -m rebon.scraper.enrich_products --force              # re-enrich existing
    python -m rebon.scraper.enrich_products --dry-run

Requirements:
    pip install requests beautifulsoup4 lxml
"""

from __future__ import annotations

import argparse
import json
import random
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ── Paths ──────────────────────────────────────────────────────────────────────

PRODUCTS_PATH = Path(__file__).parents[3] / "data" / "products.json"

# ── DSLD API ──────────────────────────────────────────────────────────────────
# Docs: https://api.ods.od.nih.gov/dsld/v8/
# Search param is `q`; label details at /label/{id}

DSLD_SEARCH   = "https://api.ods.od.nih.gov/dsld/v8/search-filter"
DSLD_LABEL    = "https://api.ods.od.nih.gov/dsld/v8/label/{dsld_id}"

# ── HTTP ──────────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

DELAY_RANGE = (1.5, 3.5)


def _get_json(url: str, params: dict | None = None, retries: int = 3) -> dict | list | None:
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=20)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 503) and attempt < retries - 1:
                wait = 10 * (attempt + 1)
                print(f"    {r.status_code} — retrying in {wait}s...")
                time.sleep(wait)
            elif r.status_code == 404:
                return None
            else:
                print(f"    HTTP {r.status_code} for {url}")
                return None
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(3)
            else:
                print(f"    Request failed: {e}")
    return None


def _get_html(url: str, retries: int = 3) -> BeautifulSoup | None:
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            if r.status_code == 200:
                return BeautifulSoup(r.text, "lxml")
            if r.status_code in (429, 503) and attempt < retries - 1:
                wait = 10 * (attempt + 1)
                print(f"    {r.status_code} — retrying in {wait}s...")
                time.sleep(wait)
            elif r.status_code in (403, 404):
                print(f"    {r.status_code} for {url} — skipping")
                return None
            else:
                print(f"    HTTP {r.status_code} for {url}")
                return None
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(3)
            else:
                print(f"    Request failed: {e}")
    return None


def _sleep():
    time.sleep(random.uniform(*DELAY_RANGE))


# ── CFU parsing ───────────────────────────────────────────────────────────────

_CFU_RE = re.compile(r"([\d,.]+)\s*(billion|million)?\s*CFU", re.IGNORECASE)
_BILLION_WORDS = re.compile(r"([\d,.]+)\s*[Bb]illion", re.IGNORECASE)
_MILLION_WORDS = re.compile(r"([\d,.]+)\s*[Mm]illion", re.IGNORECASE)


def _parse_cfu(text: str) -> float | None:
    """Return CFU as a plain float (billions), or None if not parseable."""
    if not text:
        return None
    m = _CFU_RE.search(text)
    if m:
        val = float(m.group(1).replace(",", ""))
        if m.group(2) and m.group(2).lower() == "million":
            val /= 1000
        return val
    m = _BILLION_WORDS.search(text)
    if m:
        return float(m.group(1).replace(",", ""))
    m = _MILLION_WORDS.search(text)
    if m:
        return float(m.group(1).replace(",", "")) / 1000
    return None


_PROBIOTIC_GENERA = re.compile(
    r"\b(Lactobacillus|Bifidobacterium|Saccharomyces|Bacillus|Streptococcus|"
    r"Enterococcus|Pediococcus|Lactococcus|Leuconostoc|Akkermansia|Clostridium)\b",
    re.IGNORECASE,
)


def _is_probiotic_ingredient(name: str) -> bool:
    return bool(_PROBIOTIC_GENERA.search(name))


# ── DSLD enrichment ───────────────────────────────────────────────────────────

def _strip_product_name_for_search(name: str) -> str:
    """Remove trailing pack-size details to improve DSLD search relevance."""
    clean = re.sub(r",?\s*\d+\s*(Vegetarian\s+)?Capsules.*$", "", name, flags=re.IGNORECASE)
    clean = re.sub(r",?\s*\d+\s*(Sticks|Tablets|Softgels|Gummies|Sachets|Packets|Servings).*$", "", clean, flags=re.IGNORECASE)
    # Also strip parenthetical suffixes like "(250 mg per Capsule)"
    clean = re.sub(r"\s*\(.*?\)\s*$", "", clean)
    return clean.strip()


def _parse_dsld_label(label: dict) -> tuple[list[dict], list[dict], float | None, str | None, str | None]:
    """Extract supplement_facts, probiotic_strains, total_cfu, serving_size, servings_per_container."""
    supplement_facts: list[dict] = []
    probiotic_strains: list[dict] = []
    cfu_values: list[float] = []
    serving_size: str | None = None
    servings_per_container: str | None = None

    for facts_block in label.get("dietarySupplementsFacts", []):
        qty = facts_block.get("servingSizeQuantity")
        unit = facts_block.get("servingSizeUnitName")
        if qty and unit:
            serving_size = f"{qty} {unit}".strip()
        spc = facts_block.get("servingsPerContainer")
        if spc:
            servings_per_container = str(spc)

        for ing in facts_block.get("ingredients", []):
            data = ing.get("data", {})
            ing_name   = ing.get("name", "") or ""
            alt_name   = ing.get("altName", "") or ""
            quantity   = data.get("sfbQuantityQuantity") or ""
            unit_name  = data.get("unitName") or ""
            amount_str = f"{quantity} {unit_name}".strip() if quantity else unit_name

            display_name = ing_name + (f" {alt_name}".rstrip() if alt_name.strip() else "")
            entry = {
                "name": display_name.strip(),
                "amount": amount_str or None,
                "category": data.get("ingredientEntryCategory") or None,
            }
            supplement_facts.append(entry)

            category = data.get("ingredientEntryCategory", "") or ""
            if category == "bacteria" or _is_probiotic_ingredient(ing_name):
                cfu = _parse_cfu(amount_str) or _parse_cfu(ing_name)
                strain_entry = {**entry}
                if cfu is not None:
                    strain_entry["cfu_billion"] = cfu
                    cfu_values.append(cfu)
                probiotic_strains.append(strain_entry)

            # Recurse into blends / child ingredients
            for child in ing.get("childInfo", []):
                child_data = child.get("data", {})
                child_name = child.get("name", "") or ""
                child_qty  = child_data.get("sfbQuantityQuantity") or ""
                child_unit = child_data.get("unitName") or ""
                child_amt  = f"{child_qty} {child_unit}".strip() if child_qty else child_unit
                child_cat  = child_data.get("ingredientEntryCategory", "") or ""

                child_entry = {
                    "name": child_name.strip(),
                    "amount": child_amt or None,
                    "category": child_cat or None,
                }
                supplement_facts.append(child_entry)
                if child_cat == "bacteria" or _is_probiotic_ingredient(child_name):
                    cfu = _parse_cfu(child_amt) or _parse_cfu(child_name)
                    strain_entry = {**child_entry}
                    if cfu is not None:
                        strain_entry["cfu_billion"] = cfu
                        cfu_values.append(cfu)
                    probiotic_strains.append(strain_entry)

    total = sum(cfu_values) if cfu_values else None
    return supplement_facts, probiotic_strains, total, serving_size, servings_per_container


def enrich_from_dsld(product: dict, brand_name: str | None = None) -> dict | None:
    """Search DSLD by product name; return enriched fields or None.

    brand_name — market name of the brand (e.g. "Florastor"), used to filter results.
    """
    name = product["name"]
    clean = _strip_product_name_for_search(name)
    brand_on_page = (product.get("brand_on_page") or brand_name or "").lower()

    base_params: dict = {
        "size": 10,
        "from": 0,
        "status": "2",  # 2 = all (on and off market)
        "ingredient_group": "bacteria",
    }

    # Strategy 1: brand filter + product name query
    hits: list = []
    if brand_on_page:
        params = {**base_params, "q": clean, "brand": brand_on_page}
        data = _get_json(DSLD_SEARCH, params=params)
        _sleep()
        hits = (data or {}).get("hits", [])

    # Strategy 2: product name only (probiotic-filtered)
    if not hits:
        params = {**base_params, "q": clean}
        data = _get_json(DSLD_SEARCH, params=params)
        _sleep()
        hits = (data or {}).get("hits", [])

    # Strategy 3: brand-only search (pick highest scored probiotic product)
    if not hits and brand_on_page:
        params = {**base_params, "brand": brand_on_page}
        data = _get_json(DSLD_SEARCH, params=params)
        _sleep()
        hits = (data or {}).get("hits", [])

    if not hits:
        return None

    # Re-rank: weight brand match + product name token overlap heavily
    _STOP = {"the", "a", "an", "and", "or", "with", "for", "of", "in", "to"}

    def _tokenize(s: str) -> set[str]:
        return {re.sub(r"[^a-z0-9]", "", w) for w in s.lower().split()} - _STOP - {""}

    name_tokens = _tokenize(clean)

    def _score(hit: dict) -> float:
        src = hit.get("_source", {})
        hit_brand = (src.get("brand") or "").lower()
        hit_pname = (src.get("productName") or "").lower()
        score = 0.0
        # Strong bonus if the brand_on_page token appears in the DSLD brand OR product name
        if brand_on_page:
            brand_tok = re.sub(r"[^a-z0-9]", "", brand_on_page)
            if brand_tok in re.sub(r"[^a-z0-9 ]", "", hit_brand).split():
                score += 50
            elif brand_tok in re.sub(r"[^a-z0-9 ]", "", hit_pname).split():
                score += 30
        # Bonus for each product name token present in DSLD product name
        hit_tokens = _tokenize(hit_pname)
        overlap = len(name_tokens & hit_tokens)
        score += overlap * 5
        return score

    chosen = max(hits, key=_score)
    # Require at least a brand match or a reasonable token overlap
    best_score = _score(chosen)
    if best_score < 5:
        print(f"        DSLD: no confident match (best score={best_score:.0f}) — skipping")
        return None
    src = chosen.get("_source", {})
    dsld_id = chosen.get("_id")
    if not dsld_id:
        return None

    # Fetch full label
    label = _get_json(DSLD_LABEL.format(dsld_id=dsld_id))
    if not label:
        return None
    _sleep()

    supplement_facts, probiotic_strains, total_cfu, serving_size, servings_per = _parse_dsld_label(label)

    # Infer form from langualSupplementForm
    form_raw = src.get("langualSupplementForm") or ""
    form_match = re.search(r"(CAPSULE|TABLET|SOFTGEL|POWDER|LIQUID|GUMM|LOZENGE|BAR)", form_raw, re.IGNORECASE)
    form = form_match.group(1).capitalize() if form_match else None

    # Net content (e.g. "30.0 Capsule(s)")
    net_content = (src.get("netContentQuantities") or "").strip()

    return {
        "dsld_id": str(dsld_id),
        "dsld_product_name": src.get("productName") or None,
        "net_content": net_content or None,
        "serving_size": serving_size,
        "servings_per_container": servings_per,
        "form": form,
        "supplement_facts": supplement_facts,
        "probiotic_strains": probiotic_strains,
        "total_cfu_billion": total_cfu,
    }


# ── iHerb enrichment ─────────────────────────────────────────────────────────

def enrich_from_iherb(product: dict) -> dict | None:
    """Scrape iHerb product page for supplement facts and price."""
    url = product.get("url")
    if not url or "iherb.com" not in url or "/New-Products" in url:
        return None

    soup = _get_html(url)
    if not soup:
        return None
    _sleep()

    result: dict = {}

    # Price
    price_el = soup.select_one(
        "[itemprop='price'], .price, #price, .product-price, "
        "span[class*='price']"
    )
    if price_el:
        price_text = price_el.get("content") or price_el.get_text(strip=True)
        result["price"] = price_text or None

    # Image
    img_el = soup.select_one(
        "img#iherb-product-image, img.product-image, "
        "img[itemprop='image'], #heroImgUrl"
    )
    if img_el:
        result["image_url"] = img_el.get("src") or img_el.get("data-src") or None

    # Supplement facts table
    facts_section = soup.select_one(
        "#supplement-facts, .supplement-facts, "
        "div[class*='supplement-facts'], section[class*='supplement']"
    )
    supplement_facts: list[dict] = []
    probiotic_strains: list[dict] = []
    cfu_values: list[float] = []

    if facts_section:
        rows = facts_section.select("tr, li[class*='ingredient'], div[class*='ingredient-row']")
        for row in rows:
            cells = row.select("td, span[class*='name'], span[class*='amount']")
            if len(cells) >= 2:
                ing_name   = cells[0].get_text(strip=True)
                amount_str = cells[1].get_text(strip=True)
                if not ing_name:
                    continue
                entry = {"name": ing_name, "amount": amount_str or None}
                supplement_facts.append(entry)
                if _is_probiotic_ingredient(ing_name):
                    cfu = _parse_cfu(amount_str) or _parse_cfu(ing_name)
                    strain_entry = {**entry}
                    if cfu is not None:
                        strain_entry["cfu_billion"] = cfu
                        cfu_values.append(cfu)
                    probiotic_strains.append(strain_entry)

    result["supplement_facts"] = supplement_facts
    result["probiotic_strains"] = probiotic_strains
    result["total_cfu_billion"] = sum(cfu_values) if cfu_values else None

    # Serving size from the facts panel header
    serving_el = soup.select_one(
        "td.serving-size, span[class*='serving-size'], "
        "div[class*='serving-size'], [class*='servingSize']"
    )
    result["serving_size"] = serving_el.get_text(strip=True) if serving_el else None

    # Description (product overview / short description)
    desc_el = soup.select_one(
        "#product-overview, .product-overview, "
        "div[class*='product-description'], div[itemprop='description']"
    )
    if desc_el:
        result["description"] = desc_el.get_text(" ", strip=True)[:1000]

    return result if any(v for v in result.values() if v and v != "iherb") else None


# ── Amazon enrichment ─────────────────────────────────────────────────────────

def enrich_from_amazon(product: dict) -> dict | None:
    """Scrape Amazon product page for supplement facts and price."""
    url = product.get("url")
    if not url or "amazon.com" not in url:
        return None

    soup = _get_html(url)
    if not soup:
        return None
    _sleep()

    # CAPTCHA check
    if soup.select_one("form[action='/errors/validateCaptcha']") or \
       "robot" in (soup.get_text()[:500] or "").lower():
        print("    Amazon: CAPTCHA detected — skipping")
        return None

    result: dict = {}

    # Price
    price_el = soup.select_one(
        "span.a-price-whole, span.a-offscreen, "
        "#priceblock_ourprice, #price_inside_buybox"
    )
    if price_el:
        result["price"] = price_el.get_text(strip=True) or None

    # Image
    img_data = soup.select_one("#imgTagWrapperId img, #landingImage")
    if img_data:
        result["image_url"] = (
            img_data.get("data-old-hires")
            or img_data.get("src")
            or None
        )

    # Supplement facts table (Amazon puts these in the "Important Information" section
    # or in a "Supplement Facts" table)
    supplement_facts: list[dict] = []
    probiotic_strains: list[dict] = []
    cfu_values: list[float] = []

    # Look for supplement facts in product detail sections
    detail_sections = soup.select(
        "div#detailBullets_feature_div, "
        "div#productDescription, "
        "div#aplus, "
        "div[class*='supplement']"
    )
    for section in detail_sections:
        rows = section.select("tr")
        for row in rows:
            cells = row.select("td, th")
            if len(cells) >= 2:
                ing_name   = cells[0].get_text(strip=True)
                amount_str = " ".join(c.get_text(strip=True) for c in cells[1:])
                if not ing_name or ing_name.lower().startswith("serving"):
                    continue
                entry = {"name": ing_name, "amount": amount_str or None}
                supplement_facts.append(entry)
                if _is_probiotic_ingredient(ing_name):
                    cfu = _parse_cfu(amount_str) or _parse_cfu(ing_name)
                    strain_entry = {**entry}
                    if cfu is not None:
                        strain_entry["cfu_billion"] = cfu
                        cfu_values.append(cfu)
                    probiotic_strains.append(strain_entry)

    result["supplement_facts"] = supplement_facts
    result["probiotic_strains"] = probiotic_strains
    result["total_cfu_billion"] = sum(cfu_values) if cfu_values else None

    # Description
    desc_el = soup.select_one(
        "#productDescription p, #feature-bullets ul, "
        "div[id='aplus'] p"
    )
    if desc_el:
        result["description"] = desc_el.get_text(" ", strip=True)[:1000]

    return result if any(v for v in result.values() if v) else None


# ── Per-product orchestration ──────────────────────────────────────────────────

def enrich_product(product: dict, sources: list[str], brand_name: str | None = None) -> dict:
    """Try each source in priority order; merge best available data.

    Tracks which source contributed which fields in `detail_sources`:
      {
        "dsld":   ["supplement_facts", "probiotic_strains", ...],
        "iherb":  ["price", "image_url"],
        "amazon": ["description"],
      }
    """
    enriched = dict(product)

    detail: dict = {}
    detail_sources: dict[str, list[str]] = {}

    def _merge(source_name: str, source_data: dict | None) -> None:
        if not source_data:
            return
        contributed: list[str] = []
        for k, v in source_data.items():
            if k == "detail_source":
                continue
            if v is None:
                continue
            if k not in detail:
                detail[k] = v
                contributed.append(k)
        if contributed:
            detail_sources[source_name] = contributed

    if "dsld" in sources:
        print(f"      [DSLD] searching...")
        dsld_data = enrich_from_dsld(product, brand_name=brand_name)
        _sleep()
        if dsld_data:
            print(f"        found dsld_id={dsld_data.get('dsld_id')}, "
                  f"{len(dsld_data.get('supplement_facts', []))} ingredients")
            _merge("dsld", dsld_data)

    # iHerb: always try for price/image even if DSLD provided supplement_facts
    if "iherb" in sources:
        print(f"      [iHerb] scraping product page...")
        iherb_data = enrich_from_iherb(product)
        if iherb_data:
            print(f"        {len(iherb_data.get('supplement_facts', []))} ingredients from iHerb")
            _merge("iherb", iherb_data)

    # Amazon: fallback for supplement facts if still missing; also picks up price/description
    if "amazon" in sources:
        print(f"      [Amazon] scraping product page...")
        amz_data = enrich_from_amazon(product)
        if amz_data:
            print(f"        {len(amz_data.get('supplement_facts', []))} ingredients from Amazon")
            _merge("amazon", amz_data)

    if detail_sources:
        detail["detail_sources"] = detail_sources

    enriched.update(detail)
    return enriched


def _is_enriched(product: dict) -> bool:
    return bool(product.get("detail_sources") or product.get("dsld_id") or product.get("supplement_facts"))


# ── Main ──────────────────────────────────────────────────────────────────────

def run(
    brand_filter: str | None,
    sources: list[str],
    dry_run: bool,
    force: bool,
    limit: int | None,
):
    with open(PRODUCTS_PATH) as f:
        brands = json.load(f)

    if brand_filter:
        brands = [b for b in brands if brand_filter.lower() in (b.get("brand") or "").lower()
                  or brand_filter.lower() in (b.get("market_name") or "").lower()]
        if not brands:
            print(f"No brand matching '{brand_filter}'")
            return

    total_products = 0
    enriched_count = 0

    for brand_entry in brands:
        brand_name = brand_entry.get("brand", "?")
        products = brand_entry.get("products", [])
        if not products:
            continue

        print(f"\n→ {brand_name} ({len(products)} products)")

        market_name = brand_entry.get("market_name") or brand_name

        enriched_products = []
        for product in products:
            if not force and _is_enriched(product):
                enriched_products.append(product)
                continue

            if limit and enriched_count >= limit:
                enriched_products.append(product)
                continue

            print(f"    {product['name'][:80]}")
            total_products += 1

            enriched = enrich_product(product, sources, brand_name=market_name)
            enriched_products.append(enriched)
            enriched_count += 1
            _sleep()

        brand_entry["products"] = enriched_products

    if dry_run:
        print(f"\n[dry-run] Would enrich {total_products} products across {len(brands)} brands")
        for b in brands:
            enriched_in_brand = sum(1 for p in b.get("products", []) if _is_enriched(p))
            print(f"  {b['brand']}: {enriched_in_brand}/{len(b.get('products', []))} enriched")
    else:
        with open(PRODUCTS_PATH, "w") as f:
            json.dump(brands, f, indent=2, ensure_ascii=False)
        total = sum(len(b.get("products", [])) for b in brands)
        enriched_total = sum(
            sum(1 for p in b.get("products", []) if _is_enriched(p))
            for b in brands
        )
        print(f"\nDone. {PRODUCTS_PATH.name} — {enriched_total}/{total} products enriched.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enrich products.json with supplement details")
    parser.add_argument("--brand", help="Filter to a single brand (substring match)")
    parser.add_argument(
        "--source",
        choices=["dsld", "iherb", "amazon", "all"],
        default="all",
        help="Which sources to use (default: all — DSLD first, then iHerb, then Amazon)",
    )
    parser.add_argument("--force", action="store_true", help="Re-enrich already-enriched products")
    parser.add_argument("--dry-run", action="store_true", help="Print summary without writing")
    parser.add_argument("--limit", type=int, help="Max number of products to enrich (for testing)")
    args = parser.parse_args()

    src_map = {
        "dsld":   ["dsld"],
        "iherb":  ["iherb"],
        "amazon": ["amazon"],
        "all":    ["dsld", "iherb", "amazon"],
    }
    run(
        brand_filter=args.brand,
        sources=src_map[args.source],
        dry_run=args.dry_run,
        force=args.force,
        limit=args.limit,
    )
