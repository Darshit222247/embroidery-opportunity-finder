"""
URL fixer — validates every URL in the database:
  - follows redirects and stores the final canonical URL
  - marks dead links (404/timeout) so they are removed from results
  - strips tracking parameters
"""
import urllib.request
import urllib.parse
import ssl
import re
from engine.db import get_conn

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term",
                   "utm_content", "fbclid", "gclid", "msclkid", "ref"}


def _ssl_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def clean_url(url: str) -> str:
    """Strip tracking params, fragments."""
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qsl(parsed.query)
    query = [(k, v) for k, v in query if k.lower() not in TRACKING_PARAMS]
    return urllib.parse.urlunparse(parsed._replace(
        query=urllib.parse.urlencode(query), fragment=""
    ))


def check_url(url: str, timeout: int = 15, retries: int = 2):
    """
    Returns (status, final_url):
      status: 'ok' | 'dead' | 'error'
      final_url: URL after redirects (canonical)
    Retries transient timeouts before giving up.
    """
    if not url or not url.startswith("http"):
        return "dead", url
    last_exc = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS, method="GET")
            with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as r:
                final = r.geturl()
                code = r.getcode()
            if code < 400:
                return "ok", clean_url(final)
            return "dead", url
        except urllib.error.HTTPError as e:
            # 403/405/406/429 = bot-blocked but page exists for humans → keep
            if e.code in (403, 405, 406, 429, 999):
                return "ok", clean_url(url)
            return "dead", url
        except Exception as e:
            last_exc = e
            continue  # retry transient timeout / connection reset
    return "error", url


def ensure_columns():
    conn = get_conn()
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(opportunities)").fetchall()]
    if "url_status" not in cols:
        conn.execute("ALTER TABLE opportunities ADD COLUMN url_status TEXT DEFAULT ''")
    conn.commit()
    conn.close()


def fix_all_urls(verbose=True, recheck=False) -> dict:
    """
    Validate every opportunity URL. Updates url and url_status in DB.
    Returns summary counts.
    """
    ensure_columns()
    conn = get_conn()
    if recheck:
        rows = conn.execute("SELECT id, url FROM opportunities").fetchall()
    else:
        rows = conn.execute(
            "SELECT id, url FROM opportunities WHERE url_status = '' OR url_status IS NULL"
        ).fetchall()
    conn.close()

    counts = {"ok": 0, "dead": 0, "error": 0, "fixed_redirect": 0}

    for i, row in enumerate(rows):
        url = row["url"]
        status, final_url = check_url(url)
        counts[status] = counts.get(status, 0) + 1

        if verbose:
            mark = {"ok": "✓", "dead": "✗", "error": "?"}[status]
            print(f"  [{i+1}/{len(rows)}] {mark} {url[:75]}")
            if status == "ok" and final_url != url:
                print(f"        → redirected to: {final_url[:70]}")
                counts["fixed_redirect"] += 1

        conn = get_conn()
        conn.execute(
            "UPDATE opportunities SET url=?, url_status=? WHERE id=?",
            (final_url, status, row["id"])
        )
        conn.commit()
        conn.close()

    return counts


def purge_dead(verbose=True) -> int:
    """Delete opportunities whose URL is confirmed dead."""
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) FROM opportunities WHERE url_status='dead'").fetchone()[0]
    conn.execute("DELETE FROM opportunities WHERE url_status='dead'")
    conn.commit()
    conn.close()
    if verbose:
        print(f"  Purged {n} dead-link entries.")
    return n
