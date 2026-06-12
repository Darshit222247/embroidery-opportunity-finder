"""
GeM tender PDF detail extractor.
Downloads a bid document PDF and pulls structured fields:
quantity, value/turnover, experience, eligibility, dates, item specs,
and whether embroidery is mentioned.
"""
import urllib.request
import ssl
import re
import os
import io
import json
from datetime import datetime

import pypdf

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}


def _ssl_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def download_pdf_text(url: str, timeout: int = 25) -> str:
    """Download a PDF and return its full extracted text."""
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as r:
        data = r.read()
    reader = pypdf.PdfReader(io.BytesIO(data))
    return "\n".join(p.extract_text() for p in reader.pages)


def _clean(text: str) -> str:
    """Collapse the doubled/spaced Hindi-English label noise."""
    # remove standalone Devanagari runs to isolate English content
    return text


def _field(text: str, label: str, stop_labels=None) -> str:
    """
    Find the value that follows an English label like '/Total Quantity'.
    Returns the first meaningful line after it.
    """
    idx = text.find(label)
    if idx == -1:
        return ""
    after = text[idx + len(label): idx + len(label) + 400]
    # split into lines, drop empty / devanagari-only / slash lines
    lines = []
    for ln in after.split("\n"):
        s = ln.strip().strip("/").strip()
        if not s:
            continue
        # skip lines that are purely devanagari or punctuation
        if re.fullmatch(r'[ऀ-ॿ\s()/.,:-]+', s):
            continue
        lines.append(s)
    return lines[0] if lines else ""


def parse_gem_pdf(url: str) -> dict:
    """Return a dict of extracted tender details."""
    try:
        text = download_pdf_text(url)
    except Exception as e:
        return {"error": str(e)}

    detail = {
        "bid_end_date":     _field(text, "/Bid End Date/Time"),
        "ministry":         _field(text, "/Ministry/State Name"),
        "department":       _field(text, "/Department Name"),
        "organisation":     _field(text, "/Organisation Name"),
        "total_quantity":   _field(text, "/Total Quantity"),
        "item_category":    _field(text, "/Item Category"),
        "min_turnover":     _field(text, "bidder (For 3 Years)"),
        "experience_years": _field(text, "same/similar service"),
        "mse_relaxation":   "",
        "documents_required": "",
        "emd_amount":       _field(text, "/EMD Amount"),
        "embroidery_required": False,
    }

    # MSE relaxation: grab the Yes/No | Complete pattern after the label
    mse = re.search(r'(Yes|No)\s*\|\s*(Complete|Partial)', text)
    if mse:
        detail["mse_relaxation"] = re.sub(r'\s+', ' ', mse.group(0))

    # documents required (longer free-text)
    di = text.find("/Document required")
    if di == -1:
        di = text.find("Document required")
    if di != -1:
        chunk = text[di: di + 500]
        seller = chunk.split("from seller")[-1] if "from seller" in chunk else chunk
        seller = re.sub(r'[ऀ-ॿ]+', '', seller)
        seller = re.sub(r'\s+', ' ', seller).strip(" /\n")
        detail["documents_required"] = seller[:300]

    # ── Smart embroidery detection ──────────────────────────────────────
    # Real garment embroidery vs accessory monograms (belt buckle = NOT embroidery)
    low = text.lower()

    # Strong positives: explicit embroidery on garments
    strong = ["embroider", "embroidered logo", "embroidered crest", "school crest",
              "school logo", "logo embroidery", "chest logo", "pocket logo",
              "name embroidered", "embroidered emblem", "embroidered name",
              "rank badge", "arm monogram", "shoulder badge", "insignia",
              "embroidered badge", "crest on", "logo on shirt", "logo on blazer"]

    # Accessory-only monograms that should NOT count as embroidery work
    accessory_only = ["monogram buckle", "belt with monogram", "buckle",
                      "monogram belt"]

    has_strong = any(k in low for k in strong)

    # "monogram" alone: count only if NOT just a belt-buckle reference
    monogram_present = "monogram" in low
    only_accessory = monogram_present and all(
        ("monogram buckle" in low or "belt with monogram" in low)
        for _ in [0]
    ) and not any(k in low for k in ["embroider", "crest", "logo", "insignia",
                                     "rank badge", "emblem"])

    detail["embroidery_required"] = bool(has_strong)
    detail["embroidery_confidence"] = (
        "high" if has_strong
        else "accessory-only" if only_accessory
        else "none"
    )
    # surface the matched evidence so the user can judge
    detail["embroidery_evidence"] = [k for k in strong if k in low][:4]

    detail["relevant_keywords"] = [
        k for k in ["embroidery", "uniform", "garment", "fabric", "stitching",
                    "logo", "crest", "badge", "dress", "apparel", "textile",
                    "blazer", "shirt"]
        if k in low
    ]

    return detail


def enrich_gem_opportunities(limit=15, verbose=True) -> int:
    """
    For GeM opportunities in the DB, download the PDF, extract details,
    and store them in the snippet/summary fields (JSON in a new column).
    Returns count enriched.
    """
    from engine.db import get_conn

    conn = get_conn()
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(opportunities)").fetchall()]
    if "pdf_detail" not in cols:
        conn.execute("ALTER TABLE opportunities ADD COLUMN pdf_detail TEXT DEFAULT ''")
        conn.commit()

    rows = conn.execute(
        "SELECT id, title, url FROM opportunities "
        "WHERE url LIKE '%bidplus.gem.gov.in/showbidDocument%' "
        "AND (pdf_detail = '' OR pdf_detail IS NULL) LIMIT ?", (limit,)
    ).fetchall()
    conn.close()

    done = 0
    for r in rows:
        if verbose:
            print(f"  [{done+1}/{len(rows)}] {r['title'][:55]}...")
        detail = parse_gem_pdf(r["url"])
        conn = get_conn()
        conn.execute("UPDATE opportunities SET pdf_detail=? WHERE id=?",
                     (json.dumps(detail), r["id"]))
        conn.commit()
        conn.close()
        if verbose and "error" not in detail:
            print(f"        Qty: {detail.get('total_quantity','?')} | "
                  f"Turnover: {detail.get('min_turnover','?')} | "
                  f"Embroidery: {detail.get('embroidery_required')}")
        done += 1
    return done
