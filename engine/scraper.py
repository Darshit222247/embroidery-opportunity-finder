"""
Multi-source scraper using:
  1. DuckDuckGo (ddgs) — free open-source web search, no API key needed
  2. Playwright        — headless Chrome for GeM bidplus (JS-rendered)
"""

import urllib.request
import urllib.parse
import json
import re
import hashlib
import time
import os
from datetime import datetime

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

# ── Search query bank — DEMAND SIDE ONLY (who gives out work) ────────────────

SEARCH_QUERIES = [
    # Government tenders (buyers by definition)
    {"q": 'embroidered uniform tender India 2026',                              "cat": "gov",    "src": "Gov tender"},
    {"q": 'embroidery work tender government India 2026',                       "cat": "gov",    "src": "Gov tender"},
    {"q": 'school uniform supply tender Maharashtra 2026',                      "cat": "gov",    "src": "State tender"},
    {"q": 'police uniform supply tender Maharashtra 2026',                      "cat": "gov",    "src": "State tender"},
    {"q": 'hospital staff uniform supply tender Maharashtra',                   "cat": "gov",    "src": "State tender"},
    {"q": 'garment stitching supply tender government India 2026',              "cat": "gov",    "src": "Gov tender"},
    {"q": 'embroidered badge monogram supply tender India',                     "cat": "gov",    "src": "Gov tender"},
    {"q": 'railway uniform supply tender India 2026',                           "cat": "gov",    "src": "Railways"},
    {"q": 'army defence uniform supply tender India 2026',                      "cat": "gov",    "src": "Defence tender"},
    {"q": 'anganwadi asha worker uniform saree supply tender Maharashtra',      "cat": "gov",    "src": "State tender"},
    {"q": 'municipal corporation uniform supply tender Maharashtra 2026',       "cat": "gov",    "src": "Municipal"},
    {"q": 'PSU bank uniform supply tender India 2026',                          "cat": "gov",    "src": "PSU"},

    # Corporate procurement — companies that BUY garment/embroidery work
    {"q": 'Tata Motors vendor registration supplier uniform garment',           "cat": "corp",   "src": "Tata"},
    {"q": 'Tata group supplier registration portal textile garment',            "cat": "corp",   "src": "Tata"},
    {"q": 'Avenue Supermarts DMart vendor registration supplier apparel',       "cat": "corp",   "src": "D-Mart"},
    {"q": 'Reliance Retail supplier vendor registration apparel garments',      "cat": "corp",   "src": "Reliance"},
    {"q": 'Trent Westside Zudio vendor supplier registration garment',          "cat": "corp",   "src": "Trent/Tata"},
    {"q": 'Aditya Birla Fashion vendor supplier registration garment',          "cat": "corp",   "src": "ABFRL"},
    {"q": 'Raymond Arvind vendor job work garment outsourcing',                 "cat": "corp",   "src": "Textile majors"},
    {"q": 'Myntra Flipkart seller garment manufacturer onboarding bulk',        "cat": "corp",   "src": "E-commerce"},
    {"q": 'hotel chain housekeeping uniform procurement India RFQ',             "cat": "corp",   "src": "Hospitality"},
    {"q": 'hospital chain uniform scrubs procurement India bulk order',         "cat": "corp",   "src": "Healthcare"},
    {"q": 'airline uniform procurement India tender RFQ',                       "cat": "corp",   "src": "Airlines"},
    {"q": 'school chain uniform procurement India bulk annual contract',        "cat": "corp",   "src": "Education"},
    {"q": 'security agency uniform procurement bulk India',                     "cat": "corp",   "src": "Security"},
    {"q": 'garment export house job work outsourcing embroidery Mumbai',        "cat": "corp",   "src": "Export house"},

    # Export / B2B buyer leads
    {"q": 'buyer looking for embroidery work India bulk order',                 "cat": "export", "src": "B2B"},
    {"q": 'garment buyer requirement embroidery manufacturer India',            "cat": "export", "src": "B2B"},
    {"q": 'embroidered garments import buyer UAE USA UK from India',            "cat": "export", "src": "Export"},
    {"q": 'apparel sourcing agent India embroidery requirement',                "cat": "export", "src": "Sourcing agent"},

    # Maharashtra state portal (via search)
    {"q": 'mahatenders.gov.in uniform tender 2026',                            "cat": "gov",    "src": "Mahatenders"},
    {"q": 'mahatenders.gov.in school uniform dress supply',                    "cat": "gov",    "src": "Mahatenders"},
    {"q": 'Maharashtra zilla parishad school uniform tender 2026',             "cat": "gov",    "src": "Mahatenders"},
    {"q": 'Maharashtra anganwadi saree uniform supply tender 2026',            "cat": "gov",    "src": "State tender"},
    {"q": 'Mumbai municipal corporation BMC uniform tender 2026',              "cat": "gov",    "src": "Municipal"},
    {"q": 'Maharashtra police home guard uniform tender 2026',                 "cat": "gov",    "src": "State tender"},

    # More corporates / institutional buyers
    {"q": 'Vishal Mega Mart vendor registration apparel supplier',             "cat": "corp",   "src": "Vishal Mega Mart"},
    {"q": 'Spencers Retail vendor supplier registration garment',              "cat": "corp",   "src": "Spencers"},
    {"q": 'V-Mart retail vendor supplier registration apparel',                "cat": "corp",   "src": "V-Mart"},
    {"q": 'Bata Liberty footwear uniform vendor supplier India',               "cat": "corp",   "src": "Footwear"},
    {"q": 'Indian Railways zonal uniform supply contractor tender',            "cat": "gov",    "src": "Railways"},
    {"q": 'Ordnance Factory clothing uniform supplier registration',           "cat": "gov",    "src": "Defence PSU"},
    {"q": 'Infosys TCS Wipro corporate uniform tshirt vendor bulk',            "cat": "corp",   "src": "IT majors"},
    {"q": 'Decathlon India garment manufacturer supplier onboarding',          "cat": "corp",   "src": "Decathlon"},
]

# ── Contact-finder query bank — procurement people at major companies ────────

CONTACT_QUERIES = [
    {"q": 'Tata Motors procurement head sourcing manager contact email',            "company": "Tata Motors"},
    {"q": 'Tata group merchandise sourcing manager uniform contact',                "company": "Tata Group"},
    {"q": 'Trent Westside Zudio sourcing merchandiser contact email',               "company": "Trent (Tata)"},
    {"q": 'Avenue Supermarts DMart purchase manager apparel contact email',         "company": "D-Mart"},
    {"q": 'DMart vendor helpdesk supplier contact email phone',                     "company": "D-Mart"},
    {"q": 'Reliance Retail apparel sourcing head procurement contact',              "company": "Reliance Retail"},
    {"q": 'Aditya Birla Fashion sourcing merchandiser procurement contact email',   "company": "ABFRL"},
    {"q": 'Raymond garment procurement vendor development contact email',           "company": "Raymond"},
    {"q": 'Arvind Mills vendor development job work contact email',                 "company": "Arvind"},
    {"q": 'Shoppers Stop Lifestyle merchandise sourcing contact email',             "company": "Shoppers Stop"},
    {"q": 'Taj Hotels IHCL procurement uniform housekeeping contact',               "company": "Taj Hotels (Tata)"},
    {"q": 'Oberoi ITC hotels uniform procurement purchase contact',                 "company": "Hotel chains"},
    {"q": 'Indigo Air India uniform procurement vendor contact',                    "company": "Airlines"},
    {"q": 'Apollo Fortis hospital uniform scrubs procurement contact',              "company": "Hospital chains"},
    {"q": 'SIS G4S security uniform procurement purchase contact India',            "company": "Security cos"},
]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _uid(url: str, title: str) -> str:
    return hashlib.md5(f"{url}|{title}".encode()).hexdigest()


def _now() -> str:
    return datetime.utcnow().isoformat()


# ── Source 1: DuckDuckGo via ddgs (free, open source, no API key) ────────────

def ddg_search(query: str, count: int = 6) -> list:
    """
    Search DuckDuckGo via the ddgs package.
    Returns list of {title, url, snippet}.
    """
    from ddgs import DDGS

    results = []
    with DDGS() as d:
        for item in d.text(query, region="in-en", max_results=count):
            results.append({
                "title":   item.get("title", "").strip(),
                "url":     item.get("href", "").strip(),
                "snippet": item.get("body", "").strip()[:300],
            })
    return results


# ── Source 2: Playwright — GeM bidplus ──────────────────────────────────────

def gem_playwright_search(keywords: list = None) -> list:
    """
    Use headless Chromium to load GeM bid search and parse bid cards.
    Each card has: Bid No., Items (product name), Quantity, Ministry, dates.
    """
    from playwright.sync_api import sync_playwright

    if keywords is None:
        keywords = ["uniform", "dress material", "textile garment", "garment supply", "school dress", "embroidery"]

    all_results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=HEADERS["User-Agent"])

        for kw in keywords:
            try:
                print(f"      [GeM] searching: {kw}")
                page.goto("https://bidplus.gem.gov.in/all-bids", wait_until="networkidle", timeout=35000)
                page.wait_for_timeout(1500)
                # Fill the search box (id=searchBid) and press Enter
                page.fill("#searchBid", kw)
                page.wait_for_timeout(500)
                page.keyboard.press("Enter")
                page.wait_for_timeout(3000)
                # sort by latest closing date → bids with the MOST time left to bid
                try:
                    page.evaluate("sort('Bid-End-Date-Latest')")
                    page.wait_for_timeout(3000)
                except Exception:
                    pass

                content = page.content()

                # Build map: bid number → real document URL
                # <a class="bid_no_hover" href="showbidDocument/9427806">GEM/2026/B/7628193</a>
                doc_links = {}
                for href, bno in re.findall(
                    r'<a[^>]+class="bid_no_hover"[^>]+href="(/?(?:showbidDocument|showradocumentPdf)/\d+)"[^>]*>\s*(GEM/\d{4}/[A-Z]/\d+)',
                    content
                ):
                    doc_links[bno] = "https://bidplus.gem.gov.in" + (href if href.startswith("/") else "/" + href)

                # Extract all bid cards via visible text parsing.
                # Label varies: "Bid No.:" (default view) or "BID NO:" (after sort).
                visible = page.inner_text("body")
                blocks = re.split(r'(?:Bid No\.?:|BID NO:)', visible, flags=re.I)

                for block in blocks[1:]:  # skip header
                    lines = [l.strip() for l in block.split('\n') if l.strip()]

                    bid_no = ""
                    item_name = ""
                    quantity = ""
                    ministry = ""
                    end_date = ""

                    for line in lines[:20]:
                        if re.match(r'GEM/\d{4}/[A-Z]/\d+', line):
                            bid_no = re.search(r'GEM/\d{4}/[A-Z]/\d+', line).group(0)
                        elif line.startswith("Items:"):
                            item_name = line.replace("Items:", "").replace("\xa0", "").strip()
                        elif line.startswith("Quantity:"):
                            quantity = line.replace("Quantity:", "").replace("\xa0", "").strip()
                        elif line.startswith("End Date:"):
                            end_date = line.replace("End Date:", "").replace("\xa0", "").strip()
                        elif line.startswith("Ministry of") or line.startswith("Department of"):
                            ministry = line.strip()

                    if not bid_no or not item_name:
                        continue

                    # Try to get the full item name from HTML (it's truncated in visible text)
                    if bid_no:
                        full_title_match = re.search(
                            rf'{re.escape(bid_no)}.*?Items.*?<[^>]+>([^<]{{10,200}})<',
                            content, re.S
                        )
                        if full_title_match:
                            item_name = full_title_match.group(1).strip()

                    # Use the real document link captured from the page; fall back to search page
                    gem_url = doc_links.get(
                        bid_no,
                        f"https://bidplus.gem.gov.in/all-bids?searchBid={urllib.parse.quote(kw)}"
                    )
                    snippet = f"Bid: {bid_no} | Qty: {quantity} | Ministry: {ministry} | Closes: {end_date}"

                    all_results.append({
                        "title":   f"{item_name} [{bid_no}]",
                        "url":     gem_url,
                        "snippet": snippet.strip(" |"),
                    })

            except Exception as e:
                print(f"      [GeM playwright error] {kw}: {e}")

        browser.close()

    # deduplicate by bid number
    seen = set()
    unique = []
    for r in all_results:
        bid_match = re.search(r'GEM/\d{4}/[A-Z]/\d+', r["title"])
        key = bid_match.group(0) if bid_match else r["title"][:60]
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


# ── Source 3: Playwright — CPPP / Mahatenders ───────────────────────────────

def cppp_playwright_search(keywords: list = None) -> list:
    """Search CPPP eprocure.gov.in for active tenders using Playwright."""
    from playwright.sync_api import sync_playwright

    if keywords is None:
        keywords = ["embroidery", "embroidered uniform"]

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=HEADERS["User-Agent"])

        for kw in keywords:
            try:
                print(f"      [CPPP] searching: {kw}")
                page.goto(
                    "https://eprocure.gov.in/eprocure/app?page=FrontEndLatestActiveTenders&service=page",
                    wait_until="networkidle", timeout=25000
                )
                page.wait_for_timeout(1500)

                # Fill keyword search
                try:
                    page.fill("input[name='keyword'], input[id*='keyword'], input[placeholder*='keyword']", kw)
                    page.click("input[type='submit'], button[type='submit'], input[value*='Search']")
                    page.wait_for_timeout(2500)
                except Exception:
                    pass

                content = page.content()
                rows = re.findall(r'<tr[^>]*>(.*?)</tr>', content, re.S)
                for row in rows:
                    tds = re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)
                    cells = [re.sub(r'<[^>]+>', ' ', td).strip() for td in tds]
                    cells = [re.sub(r'\s+', ' ', c) for c in cells if len(c.strip()) > 5]
                    if cells and any(
                        any(k in c.lower() for k in ['embroidery', 'uniform', 'garment'])
                        for c in cells
                    ):
                        title = cells[0] if cells else kw
                        results.append({
                            "title": title[:150],
                            "url": "https://eprocure.gov.in/eprocure/app?page=FrontEndLatestActiveTenders&service=page",
                            "snippet": " | ".join(cells[:4])[:250],
                        })

            except Exception as e:
                print(f"      [CPPP playwright error] {kw}: {e}")

        browser.close()

    return results


# ── Master scrape function ────────────────────────────────────────────────────

def scrape_all(delay: float = 1.0) -> list:
    """
    Run all sources. Returns deduplicated list of raw opportunity dicts.
    Falls back gracefully if Brave key is missing.
    """
    seen_uids = set()
    opportunities = []
    now = _now()

    def _add(title, url, source, category, snippet):
        # skip results with no URL or ad-tracking links
        if not url or not url.startswith("http"):
            return
        if any(bad in url for bad in ("bing.com/aclick", "duckduckgo.com/y.js", "googleadservices")):
            return
        uid = _uid(url, title)
        if uid not in seen_uids and title.strip():
            seen_uids.add(uid)
            opportunities.append({
                "uid": uid, "title": title, "url": url,
                "source": source, "category": category,
                "snippet": snippet, "scraped_at": now,
            })

    # ── A: DuckDuckGo search (free, no key) ─────────────────────────────
    print("\n  [DuckDuckGo Search]")
    for i, sq in enumerate(SEARCH_QUERIES):
        print(f"    [{i+1}/{len(SEARCH_QUERIES)}] {sq['src']}: {sq['q'][:55]}...")
        try:
            for r in ddg_search(sq["q"], count=6):
                _add(r["title"], r["url"], sq["src"], sq["cat"], r["snippet"])
        except Exception as e:
            print(f"      error: {e}")
        time.sleep(delay + 1.0)  # be polite to avoid rate limiting

    # ── B: GeM via Playwright ───────────────────────────────────────────
    print("\n  [GeM — Playwright]")
    try:
        for r in gem_playwright_search():
            _add(r["title"], r["url"], "GeM", "gov", r["snippet"])
        print(f"    GeM scraped {sum(1 for o in opportunities if o['source']=='GeM')} items")
    except Exception as e:
        print(f"    GeM error: {e}")

    # ── C: CPPP via Playwright ──────────────────────────────────────────
    print("\n  [CPPP — Playwright]")
    try:
        for r in cppp_playwright_search():
            _add(r["title"], r["url"], "CPPP", "gov", r["snippet"])
        print(f"    CPPP scraped {sum(1 for o in opportunities if o['source']=='CPPP')} items")
    except Exception as e:
        print(f"    CPPP error: {e}")

    print(f"\n  Total unique opportunities found: {len(opportunities)}")
    return opportunities
