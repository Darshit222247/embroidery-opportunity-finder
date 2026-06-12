"""
Contact finder — searches for procurement/sourcing contacts at major companies
that give out garment/embroidery work, then visits the pages and extracts
publicly listed emails, phone numbers, and roles.
"""
import urllib.request
import urllib.parse
import re
import ssl
import hashlib
import time
from datetime import datetime

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.(?:com|in|co\.in|org|net)')
# Indian phone numbers: +91-XXXXXXXXXX, 0XX-XXXXXXXX, 10-digit mobiles
PHONE_RE = re.compile(r'(?:\+91[\s-]?)?(?:0\d{2,4}[\s-]?)?\d{8,10}')

# Junk emails to skip
SKIP_EMAIL_PATTERNS = [
    "example.com", "yourdomain", "domain.com", "email.com", "test.com",
    "sentry", "wixpress", "godaddy", "cloudflare", "schema.org",
    ".png", ".jpg", ".gif", ".webp", ".svg", ".css", ".js",
]

# Known official vendor/supplier registration & procurement contact pages
KNOWN_PORTALS = [
    {"company": "Tata Group",       "person": "", "role": "Supplier registration portal",
     "email": "", "phone": "",
     "source_url": "https://www.tatabusinesshub.com/", "notes": "Tata group official supplier onboarding"},
    {"company": "Tata Motors",      "person": "", "role": "Supplier relations",
     "email": "supplier.connect@tatamotors.com", "phone": "",
     "source_url": "https://www.tatamotors.com/suppliers/", "notes": "Official supplier connect email"},
    {"company": "D-Mart (Avenue Supermarts)", "person": "", "role": "Vendor desk",
     "email": "vendor@dmartindia.com", "phone": "022-33400500",
     "source_url": "https://www.dmartindia.com/contact-us", "notes": "Official vendor contact from D-Mart site"},
    {"company": "Reliance Retail",  "person": "", "role": "Supplier/partner desk",
     "email": "customer.service@ril.com", "phone": "1800-102-7382",
     "source_url": "https://relianceretail.com/contact-us.html", "notes": "Route to merchandise sourcing team"},
    {"company": "ABFRL (Aditya Birla Fashion)", "person": "", "role": "Vendor registration",
     "email": "", "phone": "",
     "source_url": "https://www.abfrl.com/", "notes": "Pantaloons, Allen Solly, Van Heusen, Peter England sourcing"},
    {"company": "Trent Ltd (Westside/Zudio)", "person": "", "role": "Merchandise sourcing",
     "email": "", "phone": "022-67009000",
     "source_url": "https://www.westside.com/", "notes": "Tata retail arm - high volume apparel buyer"},
    {"company": "Raymond Ltd",      "person": "", "role": "Vendor development",
     "email": "corp.communications@raymond.in", "phone": "022-40367000",
     "source_url": "https://www.raymond.in/", "notes": "Garmenting division outsources job work"},
    {"company": "Arvind Ltd",       "person": "", "role": "Vendor development",
     "email": "investor@arvind.in", "phone": "079-68268000",
     "source_url": "https://www.arvind.com/", "notes": "Largest garment exporter - outsources embroidery"},
    {"company": "Indian Hotels (Taj/IHCL)", "person": "", "role": "Central procurement",
     "email": "", "phone": "022-66395515",
     "source_url": "https://www.ihcltata.com/", "notes": "Hotel uniforms with logo embroidery"},
    {"company": "GeM Portal",       "person": "", "role": "Seller helpdesk",
     "email": "helpdesk-gem@gov.in", "phone": "1800-419-3436",
     "source_url": "https://gem.gov.in/", "notes": "Register as seller to receive govt bids"},
    {"company": "NSIC",             "person": "", "role": "MSME tender support",
     "email": "nsicho@nsic.co.in", "phone": "011-26926275",
     "source_url": "https://www.nsic.co.in/", "notes": "MSE tender preference & support"},
]


def _uid(company: str, email: str, phone: str) -> str:
    return hashlib.md5(f"{company}|{email}|{phone}".encode()).hexdigest()


def _fetch_page(url: str, timeout=12) -> str:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read().decode("utf-8", errors="replace")


def _clean_emails(emails: list) -> list:
    out = []
    for e in emails:
        e = e.lower().strip()
        if any(p in e for p in SKIP_EMAIL_PATTERNS):
            continue
        if e not in out:
            out.append(e)
    return out[:5]


def _clean_phones(phones: list) -> list:
    out = []
    for p in phones:
        digits = re.sub(r'\D', '', p)
        if len(digits) < 8 or len(digits) > 12:
            continue
        # skip obviously fake/sequential
        if digits in ("0000000000", "1234567890"):
            continue
        if p.strip() not in out:
            out.append(p.strip())
    return out[:3]


def extract_contacts_from_page(url: str, company: str) -> list:
    """Visit a page and pull publicly listed emails/phones."""
    try:
        body = _fetch_page(url)
    except Exception:
        return []

    # strip scripts/styles to reduce junk
    body = re.sub(r'<script.*?</script>', ' ', body, flags=re.S)
    body = re.sub(r'<style.*?</style>', ' ', body, flags=re.S)

    emails = _clean_emails(EMAIL_RE.findall(body))
    phones = _clean_phones(PHONE_RE.findall(body)) if emails else []

    results = []
    now = datetime.utcnow().isoformat()
    for email in emails:
        results.append({
            "uid": _uid(company, email, ""),
            "company": company,
            "person": "",
            "role": "Listed on website",
            "email": email,
            "phone": phones[0] if phones else "",
            "source_url": url,
            "notes": "Auto-extracted from public page",
            "scraped_at": now,
        })
    return results


def find_contacts(contact_queries: list, max_pages_per_query: int = 3, delay: float = 2.0) -> list:
    """
    For each query: search DuckDuckGo, visit top pages, extract contact info.
    Returns list of contact dicts ready for DB.
    """
    from ddgs import DDGS

    all_contacts = []
    now = datetime.utcnow().isoformat()

    # Seed with known official portals first (verified manually)
    for kp in KNOWN_PORTALS:
        all_contacts.append({
            "uid": _uid(kp["company"], kp["email"], kp["phone"]),
            "company": kp["company"], "person": kp["person"], "role": kp["role"],
            "email": kp["email"], "phone": kp["phone"],
            "source_url": kp["source_url"], "notes": kp["notes"],
            "scraped_at": now,
        })

    with DDGS() as d:
        for i, cq in enumerate(contact_queries):
            print(f"    [{i+1}/{len(contact_queries)}] {cq['company']}: {cq['q'][:50]}...")
            try:
                hits = d.text(cq["q"], region="in-en", max_results=max_pages_per_query)
            except Exception as e:
                print(f"      search error: {e}")
                time.sleep(delay * 2)
                continue

            for hit in hits:
                url = hit.get("href", "")
                if not url or "bing.com/aclick" in url or "duckduckgo.com" in url:
                    continue
                found = extract_contacts_from_page(url, cq["company"])
                if found:
                    print(f"      ✓ {len(found)} contact(s) on {url[:60]}")
                all_contacts.extend(found)

            time.sleep(delay)

    return all_contacts
