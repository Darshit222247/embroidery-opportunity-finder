"""
Embroidery Opportunity Finder
Searches government tenders and corporate procurement for Maharashtra-based embroidery businesses.
Run:  python3 finder.py
Opens results in your browser as an HTML dashboard.
"""

import urllib.request
import urllib.parse
import json
import html
import re
import os
import webbrowser
import datetime
from html.parser import HTMLParser

# ── Search targets ──────────────────────────────────────────────────────────

SEARCHES = [
    # Government portals
    {
        "label": "GeM portal – embroidery / uniform",
        "query": 'site:gem.gov.in "embroidery" OR "embroidered uniform" OR "uniform embroidery"',
        "category": "gov",
        "source": "GeM Portal",
    },
    {
        "label": "GeM portal – textile / apparel",
        "query": 'site:gem.gov.in "embroidered" OR "embroidery work" Maharashtra',
        "category": "gov",
        "source": "GeM Portal",
    },
    {
        "label": "CPPP – uniform tender",
        "query": 'site:eprocure.gov.in "uniform" "embroidery" OR site:eprocure.gov.in "embroidered garments"',
        "category": "gov",
        "source": "CPPP",
    },
    {
        "label": "Maharashtra state tenders – uniform",
        "query": 'site:mahatenders.gov.in "uniform" OR "embroidery" OR "embroidered"',
        "category": "gov",
        "source": "Mahatenders",
    },
    {
        "label": "Tender search – school uniform Maharashtra",
        "query": '"school uniform" "embroidery" tender Maharashtra 2025 OR 2026',
        "category": "gov",
        "source": "Web search",
    },
    {
        "label": "Police / defence uniform embroidery tender",
        "query": '"police uniform" OR "defence uniform" embroidery tender Maharashtra',
        "category": "gov",
        "source": "Web search",
    },
    # Corporate procurement
    {
        "label": "Tata Group – embroidery vendor / supplier",
        "query": 'Tata Group "embroidery supplier" OR "embroidery vendor" OR "embroidered uniform" procurement',
        "category": "corp",
        "source": "Tata Group",
    },
    {
        "label": "D-Mart – textile / embroidery supplier",
        "query": 'D-Mart "embroidery" OR "embroidered" supplier vendor registration Maharashtra',
        "category": "corp",
        "source": "D-Mart",
    },
    {
        "label": "Reliance Retail – garment vendor",
        "query": 'Reliance Retail "embroidery" OR "embroidered garments" vendor supplier registration',
        "category": "corp",
        "source": "Reliance Retail",
    },
    {
        "label": "Flipkart / Myntra – embroidery seller",
        "query": 'Flipkart OR Myntra "embroidery work" OR "embroidered" manufacturer supplier Maharashtra',
        "category": "corp",
        "source": "Flipkart/Myntra",
    },
    {
        "label": "Aditya Birla / More retail – uniform",
        "query": '"Aditya Birla" OR "More retail" "embroidery" uniform supplier vendor',
        "category": "corp",
        "source": "Aditya Birla",
    },
    {
        "label": "ITC – uniform / textile procurement",
        "query": 'ITC Limited "embroidery" OR "embroidered uniform" supplier procurement India',
        "category": "corp",
        "source": "ITC",
    },
    # Export / B2B
    {
        "label": "IndiaMART – export embroidery buyer",
        "query": 'site:indiamart.com "embroidery" buyer OR "embroidery work" requirement Maharashtra',
        "category": "export",
        "source": "IndiaMART",
    },
    {
        "label": "TradeIndia – embroidery bulk order",
        "query": 'site:tradeindia.com "embroidery" buyer OR "machine embroidery" requirement',
        "category": "export",
        "source": "TradeIndia",
    },
]

VENDOR_REGISTRATION_LINKS = [
    {"name": "GeM Portal – Seller registration", "url": "https://seller.gem.gov.in/", "desc": "Register to sell/supply to all central govt departments"},
    {"name": "Tata Vendor Registration", "url": "https://www.tata.com/business/supplier", "desc": "Become a Tata Group approved vendor"},
    {"name": "Reliance Retail Vendor", "url": "https://www.relianceretail.com/", "desc": "Supplier empanelment for Reliance stores"},
    {"name": "Mahatenders (Maharashtra)", "url": "https://mahatenders.gov.in/", "desc": "Maharashtra state government tenders"},
    {"name": "CPPP – Central tenders", "url": "https://eprocure.gov.in/", "desc": "Central Public Procurement Portal"},
    {"name": "IndiaMART – List your business", "url": "https://seller.indiamart.com/", "desc": "Get export and B2B inquiries"},
    {"name": "NSIC Tender Portal", "url": "https://www.nsic.co.in/", "desc": "MSE-reserved tenders, price preference for small businesses"},
    {"name": "MSME Udyam Registration", "url": "https://udyamregistration.gov.in/", "desc": "Mandatory for govt tender benefits & MSME schemes"},
]

# ── Google search scraper (no API key needed) ────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36"
}

class ResultParser(HTMLParser):
    """Minimal parser to pull search result titles, URLs, snippets from Google HTML."""
    def __init__(self):
        super().__init__()
        self.results = []
        self._in_title = False
        self._in_snippet = False
        self._current = {}
        self._depth = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        cls = attrs.get("class", "")
        href = attrs.get("href", "")
        # result container
        if tag == "div" and "g" in cls.split():
            self._current = {}
        # title link
        if tag == "a" and href.startswith("/url?"):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
            url = qs.get("q", [""])[0]
            if url and not url.startswith("/"):
                self._current["url"] = url
        if tag == "h3":
            self._in_title = True
            self._current["title"] = ""
        if tag == "span" and "st" in cls:
            self._in_snippet = True
            self._current["snippet"] = ""

    def handle_endtag(self, tag):
        if tag == "h3":
            self._in_title = False
            if self._current.get("title") and self._current.get("url"):
                self.results.append(dict(self._current))
        if tag == "span":
            self._in_snippet = False

    def handle_data(self, data):
        if self._in_title:
            self._current["title"] = self._current.get("title", "") + data
        if self._in_snippet:
            self._current["snippet"] = self._current.get("snippet", "") + data


def google_search(query, num=5):
    """Fetch top Google results for a query. Returns list of {title, url, snippet}."""
    encoded = urllib.parse.quote_plus(query)
    url = f"https://www.google.com/search?q={encoded}&num={num}&hl=en"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        # Parse with regex as fallback (Google HTML changes often)
        results = []
        # Extract links
        links = re.findall(r'<a href="/url\?q=([^&"]+)[^"]*"[^>]*><h3[^>]*>(.*?)</h3>', body)
        for raw_url, raw_title in links[:num]:
            u = urllib.parse.unquote(raw_url)
            t = re.sub(r"<[^>]+>", "", raw_title).strip()
            if u.startswith("http") and t:
                # grab snippet nearby (best-effort)
                idx = body.find(raw_url)
                snip_html = body[idx:idx+600] if idx != -1 else ""
                snip_match = re.search(r'<span[^>]*>(.*?)</span>', snip_html, re.S)
                snip = re.sub(r"<[^>]+>", "", snip_match.group(1)).strip() if snip_match else ""
                results.append({"title": html.unescape(t), "url": u, "snippet": html.unescape(snip[:200])})
        return results
    except Exception as e:
        return [{"title": f"Search failed: {e}", "url": "", "snippet": ""}]


# ── HTML dashboard builder ───────────────────────────────────────────────────

CAT_COLORS = {
    "gov":    {"bg": "#E6F1FB", "text": "#0C447C", "label": "Government tender", "icon": "ti-building-bank"},
    "corp":   {"bg": "#EEEDFE", "text": "#3C3489", "label": "Corporate",         "icon": "ti-building-store"},
    "export": {"bg": "#EAF3DE", "text": "#27500A", "label": "Export / B2B",      "icon": "ti-world"},
}

def build_dashboard(all_results, timestamp):
    gov_count   = sum(1 for r in all_results if r["category"] == "gov")
    corp_count  = sum(1 for r in all_results if r["category"] == "corp")
    exp_count   = sum(1 for r in all_results if r["category"] == "export")
    total       = len(all_results)

    cards_html = ""
    for item in all_results:
        c = CAT_COLORS[item["category"]]
        results_html = ""
        for res in item["results"]:
            if not res.get("url"):
                continue
            snip = html.escape(res.get("snippet", ""))
            title = html.escape(res.get("title", "No title"))
            u = html.escape(res["url"])
            results_html += f"""
            <div style="padding:10px 0;border-bottom:0.5px solid #e5e5e5;">
              <a href="{u}" target="_blank" style="font-size:14px;font-weight:500;color:#185FA5;text-decoration:none;">{title}</a>
              <p style="font-size:12px;color:#666;margin:3px 0 0;">{snip}</p>
              <p style="font-size:11px;color:#aaa;margin:2px 0 0;word-break:break-all;">{u[:80]}{"…" if len(u)>80 else ""}</p>
            </div>"""
        if not results_html:
            results_html = '<p style="font-size:13px;color:#aaa;padding:8px 0;">No results found for this search. Try running again later.</p>'

        cards_html += f"""
        <div style="background:#fff;border:0.5px solid #e0e0e0;border-radius:12px;padding:1rem 1.25rem;margin-bottom:1rem;">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;">
            <span style="background:{c['bg']};color:{c['text']};font-size:11px;font-weight:500;padding:2px 10px;border-radius:6px;">{c['label']}</span>
            <span style="font-size:12px;color:#888;">{html.escape(item['source'])}</span>
          </div>
          <p style="font-size:15px;font-weight:500;color:#1a1a1a;margin:0 0 8px;">{html.escape(item['label'])}</p>
          {results_html}
        </div>"""

    # Vendor registration links
    reg_html = ""
    for lnk in VENDOR_REGISTRATION_LINKS:
        reg_html += f"""
        <a href="{lnk['url']}" target="_blank" style="display:block;padding:10px 14px;background:#f8f8f8;border:0.5px solid #e0e0e0;border-radius:8px;text-decoration:none;color:#1a1a1a;margin-bottom:8px;">
          <span style="font-size:14px;font-weight:500;">{html.escape(lnk['name'])}</span>
          <span style="display:block;font-size:12px;color:#666;margin-top:2px;">{html.escape(lnk['desc'])}</span>
        </a>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Embroidery Opportunity Finder</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@latest/dist/tabler-icons.min.css">
<style>
  * {{ box-sizing: border-box; margin:0; padding:0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:#f5f5f2; color:#1a1a1a; padding:1.5rem; }}
  h1 {{ font-size:22px; font-weight:500; }}
  h2 {{ font-size:16px; font-weight:500; margin:1.5rem 0 0.75rem; }}
  .metric {{ background:#fff; border-radius:8px; padding:1rem; text-align:center; border:0.5px solid #e0e0e0; }}
  .metric-num {{ font-size:28px; font-weight:500; }}
  .metric-label {{ font-size:12px; color:#888; margin-top:2px; }}
  @media(max-width:600px){{ .grid4 {{ grid-template-columns:1fr 1fr!important; }} }}
</style>
</head>
<body>
<div style="max-width:860px;margin:0 auto;">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:1.5rem;">
    <div>
      <h1><i class="ti ti-needle-thread" style="font-size:22px;vertical-align:-3px;margin-right:6px;"></i>Embroidery Opportunity Finder</h1>
      <p style="font-size:13px;color:#888;margin-top:3px;">Maharashtra · Last updated: {timestamp}</p>
    </div>
    <span style="font-size:12px;color:#aaa;">18-machine setup · computerized</span>
  </div>

  <div class="grid4" style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:1.5rem;">
    <div class="metric"><div class="metric-num" style="color:#185FA5;">{gov_count}</div><div class="metric-label">Govt tender searches</div></div>
    <div class="metric"><div class="metric-num" style="color:#534AB7;">{corp_count}</div><div class="metric-label">Corporate lead searches</div></div>
    <div class="metric"><div class="metric-num" style="color:#3B6D11;">{exp_count}</div><div class="metric-label">Export lead searches</div></div>
    <div class="metric"><div class="metric-num">{total}</div><div class="metric-label">Total search sections</div></div>
  </div>

  <div style="display:grid;grid-template-columns:2fr 1fr;gap:1.5rem;align-items:start;">
    <div>
      <h2>Live search results</h2>
      {cards_html}
    </div>
    <div>
      <h2>Vendor registration portals</h2>
      <p style="font-size:12px;color:#888;margin-bottom:10px;">Register on these portals to receive tenders and RFQs directly.</p>
      {reg_html}
    </div>
  </div>

  <p style="font-size:11px;color:#bbb;margin-top:2rem;text-align:center;">Run <code>python3 finder.py</code> again anytime for fresh results.</p>
</div>
</body>
</html>"""


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("Embroidery Opportunity Finder")
    print("=" * 40)
    timestamp = datetime.datetime.now().strftime("%d %b %Y, %I:%M %p")
    all_results = []

    for i, s in enumerate(SEARCHES):
        print(f"[{i+1}/{len(SEARCHES)}] Searching: {s['label']}...")
        results = google_search(s["query"], num=4)
        all_results.append({
            "label":    s["label"],
            "category": s["category"],
            "source":   s["source"],
            "results":  results,
        })

    out_path = os.path.join(os.path.dirname(__file__), "opportunities.html")
    html_content = build_dashboard(all_results, timestamp)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"\nDone! Opening dashboard...")
    webbrowser.open(f"file://{out_path}")
    print(f"Saved to: {out_path}")


if __name__ == "__main__":
    main()
