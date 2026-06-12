"""
Export market finder using UN Comtrade (free, no API key).
Ranks which countries import Indian embroidery / apparel, by value —
so outreach can target the biggest real markets.
"""
import json
from datetime import datetime

INDIA = "699"  # UN Comtrade reporter code for India

# Product groups relevant to an embroidery/garment business
PRODUCTS = [
    {"code": "5810", "label": "Embroidery (in piece/strips/motifs)"},
    {"code": "61",   "label": "Apparel — knitted/crocheted"},
    {"code": "62",   "label": "Apparel — woven (not knitted)"},
]


def fetch_market(cmd_code: str, period: str = "2023") -> list:
    """Return India's exports of a product, ranked by partner country (excl. World)."""
    import comtradeapicall as ct
    df = ct.previewFinalData(
        typeCode="C", freqCode="A", clCode="HS", period=period,
        reporterCode=INDIA, cmdCode=cmd_code, flowCode="X",
        partnerCode=None, partner2Code=None, customsCode=None, motCode=None,
        maxRecords=500, includeDesc=True,
    )
    if df is None or len(df) == 0:
        return []
    # Comtrade preview can return duplicate rows per partner (different mode-of-
    # transport / partner2 breakdowns). Keep the MAX value per country to avoid
    # double-counting rather than summing.
    by_country = {}
    for _, r in df.iterrows():
        partner = str(r.get("partnerDesc", ""))
        if partner in ("World", "", "nan"):
            continue
        val = float(r.get("primaryValue", 0) or 0)
        if val <= 0:
            continue
        # keep the largest single reported value for that country
        by_country[partner] = max(by_country.get(partner, 0), val)
    out = [{"country": k, "value_usd": round(v)} for k, v in by_country.items()]
    out.sort(key=lambda x: x["value_usd"], reverse=True)
    return out


def build_export_markets(period: str = "2023") -> dict:
    """Fetch all product groups, return a structured result for the UI."""
    result = {"period": period, "generated_at": datetime.utcnow().isoformat(), "products": []}
    for p in PRODUCTS:
        try:
            ranked = fetch_market(p["code"], period)
            total = sum(x["value_usd"] for x in ranked)
            result["products"].append({
                "code": p["code"], "label": p["label"],
                "total_usd": total, "top": ranked[:20],
            })
        except Exception as e:
            result["products"].append({
                "code": p["code"], "label": p["label"],
                "error": str(e), "top": [],
            })
    return result


def cache_export_markets(period: str = "2023"):
    """Fetch and store in settings table as JSON."""
    from engine.db import save_settings
    data = build_export_markets(period)
    save_settings({"export_markets": json.dumps(data)})
    return data


def get_cached_export_markets() -> dict:
    from engine.db import get_settings
    raw = get_settings().get("export_markets", "")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}
