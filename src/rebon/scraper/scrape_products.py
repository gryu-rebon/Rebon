"""
Scrape probiotic product names from iHerb and Amazon for brands in brands.json.

Phase 1 — builds a product name list per brand.
Phase 2 (future) — enrich each product with full details.

Output: data/products.json

Usage:
    cd ~/Developments/rebon
    python -m rebon.scraper.scrape_products                   # all brands, both sources
    python -m rebon.scraper.scrape_products --brand "Now Foods"
    python -m rebon.scraper.scrape_products --source iherb
    python -m rebon.scraper.scrape_products --source amazon
    python -m rebon.scraper.scrape_products --dry-run

Requirements:
    pip install requests beautifulsoup4 lxml
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

# ── Paths ──────────────────────────────────────────────────────────────────────

BRANDS_PATH   = Path(__file__).parents[3] / "data" / "brands.json"
PRODUCTS_PATH = Path(__file__).parents[3] / "data" / "products.json"

# ── HTTP config ────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Polite delay range between requests (seconds)
DELAY_RANGE = (2.0, 4.5)

MAX_PAGES = 3                  # pages to walk per source search


# ── HTTP helper ────────────────────────────────────────────────────────────────

def _get(url: str, params: dict | None = None, retries: int = 3) -> BeautifulSoup | None:
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=20)
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
        except requests.RequestException as e:
            if attempt < retries - 1:
                time.sleep(3)
            else:
                print(f"    Request failed: {e}")
                return None
    return None


def _sleep():
    time.sleep(random.uniform(*DELAY_RANGE))


# ── iHerb scraper ──────────────────────────────────────────────────────────────

def scrape_iherb(brand_name: str) -> list[dict]:
    """Search iHerb for probiotic products by brand name, filtering by brand field."""
    products = []
    brand_lower = brand_name.lower()
    query = quote_plus(f"{brand_name} probiotic")

    for page in range(1, MAX_PAGES + 1):
        url = f"https://www.iherb.com/search?kw={query}&p={page}"
        soup = _get(url)
        if not soup:
            break

        # Product cards on iHerb search results
        cards = soup.select("div.product-cell-container, div[class*='product-cell']")
        if not cards:
            cards = soup.select("div.product")

        if not cards:
            print(f"    iHerb: no cards found on page {page} (layout may have changed)")
            break

        matched = 0
        for card in cards:
            # Brand label on iHerb cards — must match the target brand
            brand_el = card.select_one(
                "a.product-brand, span.product-brand, div.product-brand, "
                "[class*='product-brand'], [class*='brand-name']"
            )
            card_brand = brand_el.get_text(strip=True).lower() if brand_el else ""
            if card_brand:
                if brand_lower not in card_brand:
                    continue
            # no brand label — fall back to checking the product title
            else:
                name_check = card.select_one(
                    "a.product-title, span.product-title, div.product-title, "
                    "[class*='product-title'], [class*='product-name']"
                )
                if name_check and brand_lower not in name_check.get_text(strip=True).lower():
                    continue

            name_el = card.select_one(
                "a.product-title, span.product-title, div.product-title, "
                "[class*='product-title'], [class*='product-name']"
            )
            if not name_el:
                continue

            name = name_el.get_text(strip=True)
            if not name:
                continue

            link_el = card.select_one("a[href]")
            url_path = link_el["href"] if link_el else None
            product_url = (
                f"https://www.iherb.com{url_path}"
                if url_path and url_path.startswith("/")
                else url_path
            )

            sku_el = card.select_one("[class*='product-sku'], [class*='product-id']")
            sku = sku_el.get_text(strip=True).replace("Item #:", "").strip() if sku_el else None

            products.append({
                "name": name,
                "brand_on_page": brand_el.get_text(strip=True) if brand_el else None,
                "source": "iherb",
                "url": product_url,
                "sku": sku,
            })
            matched += 1

        print(f"    iHerb page {page}: {matched}/{len(cards)} matched brand (total: {len(products)})")
        _sleep()

    return products


# ── Amazon scraper ─────────────────────────────────────────────────────────────

def scrape_amazon(brand_name: str) -> list[dict]:
    """Search Amazon for probiotic products, filtering by brand name in title."""
    products = []
    brand_lower = brand_name.lower()
    query = f"{brand_name} probiotic"

    for page in range(1, MAX_PAGES + 1):
        url = "https://www.amazon.com/s"
        params = {"k": query, "page": page}
        soup = _get(url, params=params)
        if not soup:
            break

        # Check for CAPTCHA
        if soup.select_one("form[action='/errors/validateCaptcha']") or \
           "robot" in soup.get_text().lower()[:500]:
            print("    Amazon: CAPTCHA detected — skipping remaining pages")
            break

        # Standard Amazon search result cards
        cards = soup.select(
            "div[data-component-type='s-search-result'], "
            "div.s-result-item[data-asin]"
        )
        cards = [c for c in cards if c.get("data-asin")]  # filter sponsored/ads rows

        if not cards:
            print(f"    Amazon: no result cards on page {page}")
            break

        for card in cards:
            name_el = card.select_one(
                "span.a-size-medium.a-color-base.a-text-normal, "
                "span.a-size-base-plus.a-color-base.a-text-normal, "
                "h2 span"
            )
            if not name_el:
                continue

            name = name_el.get_text(strip=True)
            if not name:
                continue

            # Filter: brand name must appear in the product title
            if brand_lower not in name.lower():
                continue

            asin = card.get("data-asin", "")
            product_url = f"https://www.amazon.com/dp/{asin}" if asin else None

            products.append({
                "name": name,
                "source": "amazon",
                "url": product_url,
                "asin": asin or None,
            })

        print(f"    Amazon page {page}: +{len(cards)} cards (total so far: {len(products)})")
        _sleep()

    return products


# ── Probiotic filter ──────────────────────────────────────────────────────────

PROBIOTIC_KEYWORDS = {
    "probiotic", "lactobacillus", "bifidobacterium", "acidophilus",
    "bifidus", "saccharomyces", "lacto", "bifido", "flora", "florastor",
    "cfu", "microbiome", "microbiota", "gut health", "spore", "bacillus",
    "streptococcus thermophilus", "enterococcus", "pediococcus",
    "lactococcus", "leuconostoc",
}

def _is_probiotic(name: str) -> bool:
    lower = name.lower()
    return any(kw in lower for kw in PROBIOTIC_KEYWORDS)


# ── Per-brand orchestration ────────────────────────────────────────────────────

SOURCE_FN = {
    "iherb":  scrape_iherb,
    "amazon": scrape_amazon,
}


def _scrape_source(fn, search_names: list[str]) -> list[dict]:
    """Try each search name in order, return results from the first that yields anything."""
    for name in search_names:
        try:
            found = fn(name)
        except Exception as e:
            print(f"    Error scraping with '{name}': {e}")
            found = []
        found = [p for p in found if _is_probiotic(p["name"])]
        if found:
            print(f"    {len(found)} probiotic products found (query: '{name}')")
            return found
        print(f"    0 results for '{name}' — trying next name...")
    return []


def scrape_brand(brand: dict, sources: list[str]) -> dict:
    brand_name = brand["name"]
    market_name = brand.get("market_name") or brand_name
    parent = brand.get("parent")

    # Build ordered list of search names to try: market_name first, then parent
    search_names = [market_name]
    if parent and parent.lower() != market_name.lower():
        search_names.append(parent)

    print(f"\n→ {brand_name} (will try: {search_names})")
    result = {
        "brand": brand_name,
        "market_name": market_name,
        "parent": parent,
        "products": [],
    }

    requested_sources = list(sources)

    for source in requested_sources:
        print(f"  [{source}]")
        found = _scrape_source(SOURCE_FN[source], search_names)

        # iHerb returned nothing — fall back to Amazon if not already running it
        if not found and source == "iherb" and "amazon" not in requested_sources:
            print(f"    iHerb empty — falling back to Amazon")
            found = _scrape_source(SOURCE_FN["amazon"], search_names)

        result["products"].extend(found)
        _sleep()

    # Deduplicate by name (case-insensitive)
    seen: set[str] = set()
    unique = []
    for p in result["products"]:
        key = p["name"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(p)
    result["products"] = unique

    return result


# ── Main ───────────────────────────────────────────────────────────────────────

def run(brand_filter: str | None, sources: list[str], dry_run: bool, force: bool):
    with open(BRANDS_PATH) as f:
        brands = json.load(f)

    if brand_filter:
        brands = [b for b in brands if brand_filter.lower() in b["name"].lower()]
        if not brands:
            print(f"No brand matching '{brand_filter}' found in brands.json")
            return

    # Load existing products
    if PRODUCTS_PATH.exists():
        with open(PRODUCTS_PATH) as f:
            existing = json.load(f)
    else:
        existing = []

    existing_map: dict[str, dict] = {e["brand"]: e for e in existing}

    skipped = [b["name"] for b in brands if not b.get("consumer", True)]
    brands = [b for b in brands if b.get("consumer", True)]
    if skipped:
        print(f"Skipping non-consumer brands: {', '.join(skipped)}")

    # Skip brands that already have products unless --force
    if not force:
        already_done = [b["name"] for b in brands if existing_map.get(b["name"], {}).get("products")]
        brands = [b for b in brands if not existing_map.get(b["name"], {}).get("products")]
        if already_done:
            print(f"Skipping (already scraped): {', '.join(already_done)}")
            print(f"  Use --force to re-scrape them.")

    if not brands:
        print("Nothing to scrape.")
        return

    print(f"Scraping {len(brands)} brand(s) from: {', '.join(sources)}")

    for brand in brands:
        result = scrape_brand(brand, sources)
        existing_map[brand["name"]] = result
        time.sleep(1)

    output = list(existing_map.values())

    if dry_run:
        total = sum(len(b["products"]) for b in output)
        print(f"\n[dry-run] Would write {len(output)} brands, {total} products to {PRODUCTS_PATH.name}")
        for b in output:
            print(f"  {b['brand']}: {len(b['products'])} products")
    else:
        with open(PRODUCTS_PATH, "w") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        total = sum(len(b["products"]) for b in output)
        print(f"\nDone. {PRODUCTS_PATH.name} — {len(output)} brands, {total} products.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape probiotic products from iHerb and Amazon")
    parser.add_argument("--brand", help="Filter to a single brand (substring match)")
    parser.add_argument(
        "--source", choices=["iherb", "amazon", "both"], default="both",
        help="Which source to scrape (default: both)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Print summary without writing")
    parser.add_argument("--force", action="store_true", help="Re-scrape brands that already have products")
    args = parser.parse_args()

    sources = ["iherb", "amazon"] if args.source == "both" else [args.source]
    run(brand_filter=args.brand, sources=sources, dry_run=args.dry_run, force=args.force)
