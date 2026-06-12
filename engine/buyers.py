"""
International buyer finder — for a given country + product, finds importer
companies and extracts public contact info (best-effort, free).

2-step chain:
  1. Web-search for importer/buyer companies in the country (via ddgs)
  2. Visit candidate company sites, extract public emails/phones
"""
import re
import ssl
import time
import hashlib
import urllib.request
from datetime import datetime

from engine.contacts import EMAIL_RE, PHONE_RE, _clean_emails, _clean_phones, HEADERS

# Directory/aggregator domains to skip as "companies" (they're listings, not buyers)
SKIP_DOMAINS = [
    "wikipedia", "go4worldbusiness", "tradeindia", "exportersindia", "alibaba",
    "indiamart", "linkedin", "facebook", "youtube", "amazon", "made-in-china",
    "dnb.com", "zaubacorp", "justdial", "yellowpages", "europages", "kompass",
    "import", "export-portal", "tradeford", "google", "bing", "duckduckgo",
]


def _ssl_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _domain(url: str) -> str:
    m = re.search(r'https?://([^/]+)', url)
    return m.group(1).lower() if m else ""


def find_buyers(country: str, product: str = "garments", max_companies: int = 8,
                verbose: bool = True) -> list:
    """
    Returns list of buyer dicts: {company, country, website, email, phone, source_url}.
    """
    from ddgs import DDGS

    queries = [
        f"{product} importer company in {country} contact email",
        f"{product} wholesale buyer {country} contact us",
        f"clothing apparel importer {country} company website",
    ]

    seen_domains = set()
    candidates = []
    with DDGS() as d:
        for q in queries:
            if verbose:
                print(f"    search: {q}")
            try:
                hits = d.text(q, region="wt-wt", max_results=8)
            except Exception as e:
                if verbose:
                    print(f"      search error: {e}")
                time.sleep(3)
                continue
            for h in hits:
                url = h.get("href", "")
                dom = _domain(url)
                if not dom or dom in seen_domains:
                    continue
                if any(s in dom for s in SKIP_DOMAINS):
                    continue
                seen_domains.add(dom)
                candidates.append({
                    "title": h.get("title", ""), "url": url, "domain": dom,
                    "snippet": h.get("body", ""),
                })
            time.sleep(1.5)

    # step 2: visit each candidate, extract contacts
    results = []
    now = datetime.utcnow().isoformat()
    for c in candidates[:max_companies]:
        company = re.sub(r'\s*[-|–].*$', '', c["title"]).strip()[:80]
        # if the title is generic (Contact / Home / About), derive from domain
        if not company or re.fullmatch(r'(?i)(contact|contact us|home|about|about us)', company):
            d = c["domain"].replace("www.", "").split(".")[0]
            company = d.replace("-", " ").title()
        email, phone = "", ""
        # try home page then /contact
        for path in ["", "/contact", "/contact-us", "/about"]:
            try:
                url = c["url"].rstrip("/") + path if path else c["url"]
                req = urllib.request.Request(url, headers=HEADERS)
                body = urllib.request.urlopen(req, timeout=10, context=_ssl_ctx()).read().decode("utf-8", "replace")
                body = re.sub(r'<(script|style).*?</\1>', ' ', body, flags=re.S)
                emails = _clean_emails(EMAIL_RE.findall(body))
                # prefer an email on the company's own domain
                own = [e for e in emails if c["domain"].split(":")[0].replace("www.", "") in e]
                if own:
                    email = own[0]
                elif emails:
                    email = emails[0]
                phones = _clean_phones(PHONE_RE.findall(body)) if email else []
                if phones:
                    phone = phones[0]
                if email:
                    break
            except Exception:
                continue
        if verbose:
            print(f"      {'✓' if email else '·'} {company[:40]} | {email or 'no email'}")
        results.append({
            "company": company, "country": country, "website": c["url"],
            "email": email, "phone": phone, "source_url": c["url"],
            "snippet": c["snippet"][:200], "scraped_at": now,
        })
    return results


def find_and_store_buyers(country: str, product: str = "garments", max_companies: int = 8) -> int:
    """Find buyers and store them in the contacts table tagged with country."""
    from engine.db import upsert_contact
    rows = find_buyers(country, product, max_companies)
    new = 0
    for r in rows:
        uid = hashlib.md5(f"{r['company']}|{r['country']}|{r['email']}".encode()).hexdigest()
        if upsert_contact({
            "uid": uid, "company": r["company"], "person": "",
            "role": f"Importer — {product} ({country})",
            "email": r["email"], "phone": r["phone"],
            "source_url": r["source_url"],
            "notes": f"Export lead: {country}. {r['snippet']}"[:250],
            "scraped_at": r["scraped_at"], "country": country,
        }):
            new += 1
    return new
