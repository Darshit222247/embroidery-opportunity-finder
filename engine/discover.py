"""
Directory discovery using dirhunt (Nekmo's web directory crawler).
Crawls key tender + vendor portals to find listing/section URLs that
keyword searches miss, then filters to garment/uniform/embroidery/vendor paths.
"""
import subprocess
import re
import os
import hashlib
from datetime import datetime

# dirhunt CLI location (installed via pip --user on this machine)
DIRHUNT_BIN = os.path.expanduser("~/Library/Python/3.9/bin/dirhunt")
if not os.path.exists(DIRHUNT_BIN):
    DIRHUNT_BIN = "dirhunt"  # fall back to PATH

# Portals worth crawling — seeded with textile/garment category pages so
# dirhunt discovers the actual tender-listing sub-directories under them.
SEED_PORTALS = [
    {"url": "https://www.globaltenders.com/textile-tenders",          "cat": "gov",  "src": "GlobalTenders"},
    {"url": "https://www.globaltenders.com/textiles-garments-tenders", "cat": "gov",  "src": "GlobalTenders"},
    {"url": "https://www.globaltenders.com/clothing-tenders",         "cat": "gov",  "src": "GlobalTenders"},
    {"url": "https://www.tenderdetail.com/garments-tenders",          "cat": "gov",  "src": "TenderDetail"},
    {"url": "https://www.firsttender.com/bids/army-uniform-tenders.html", "cat": "gov", "src": "FirstTender"},
    {"url": "https://www.bidassist.com/",                             "cat": "gov",  "src": "BidAssist"},
    {"url": "https://trentlimited.com/pages/fashion-lifestyle",        "cat": "corp", "src": "Trent (Tata)"},
]

# Keep only directory URLs whose path strongly hints at relevant demand.
# Narrow: must mention garment/uniform/textile work OR a vendor/supplier path.
RELEVANT_PATH = re.compile(
    r'(uniform|embroider|garment|textile|apparel|cloth(?:ing)?|dress|fabric|'
    r'leather|jute|yarn|fashion|vendor[\s_-]*reg|supplier[\s_-]*reg|'
    r'vendor[\s_-]*registration|become[\s_-]*a[\s_-]*supplier|sourcing|rfq)',
    re.I
)

# Drop obviously irrelevant sections
SKIP_PATH = re.compile(
    r'(login|signup|signin|password|cart|privacy|terms|about-?us|contact-?us|'
    r'faq|blog|news/|career|sitemap|\.css|\.js|\.png|\.jpg)',
    re.I
)


def _uid(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


def run_dirhunt(target_url: str, timeout: int = 90) -> list:
    """
    Run dirhunt on a single URL, return list of discovered URLs (status 200).
    """
    try:
        proc = subprocess.run(
            [DIRHUNT_BIN, target_url, "--threads", "4"],
            capture_output=True, text=True, timeout=timeout,
        )
        output = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired as e:
        # use whatever was captured before timeout
        output = (e.stdout or "") + (e.stderr or "")
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
    except Exception as e:
        print(f"      dirhunt error: {e}")
        return []

    # Parse lines like:  [200] https://site.com/path  (HTML document)
    urls = re.findall(r'\[200\]\s+(https?://[^\s]+)', output)
    # also catch redirect targets
    urls += re.findall(r'Redirect to:\s+(https?://[^\s]+)', output)
    return list(dict.fromkeys(urls))  # dedupe, preserve order


def discover_all(verbose: bool = True) -> list:
    """
    Crawl all seed portals with dirhunt, filter to relevant directory URLs.
    Returns opportunity dicts ready for DB insertion.
    """
    found = []
    now = datetime.utcnow().isoformat()
    seen = set()

    for portal in SEED_PORTALS:
        if verbose:
            print(f"    [dirhunt] crawling {portal['src']}: {portal['url']}")
        urls = run_dirhunt(portal["url"])
        kept = 0
        for url in urls:
            path = url.split(portal["url"].rstrip("/"), 1)[-1] if portal["url"] in url else url
            if SKIP_PATH.search(url):
                continue
            if not RELEVANT_PATH.search(url):
                continue
            uid = _uid(url)
            if uid in seen:
                continue
            seen.add(uid)
            # build a readable title from the path
            title = url.rstrip("/").split("/")[-1].replace("-", " ").replace("_", " ").title()
            if not title:
                title = portal["src"] + " section"
            found.append({
                "uid": uid,
                "title": f"{title} [{portal['src']}]",
                "url": url,
                "source": portal["src"],
                "category": portal["cat"],
                "snippet": f"Directory section discovered via dirhunt on {portal['src']}",
                "scraped_at": now,
            })
            kept += 1
        if verbose:
            print(f"      → {len(urls)} URLs found, {kept} relevant kept")

    return found
