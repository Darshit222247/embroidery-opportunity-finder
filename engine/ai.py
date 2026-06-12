"""
Ollama-powered analysis layer.
For each raw opportunity, extracts structured fields and scores relevance
for a Maharashtra-based computerized embroidery business with 18 machines.
"""
import json
import urllib.request
import re

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "gemma4:31b-cloud"

SYSTEM = """You are a procurement analyst for a Maharashtra-based computerized embroidery manufacturing business with 18 hi-tech machines.
Your job is to analyse business opportunity listings and extract structured data.
Always respond with ONLY valid JSON — no markdown fences, no explanation, just the raw JSON object."""

PROMPT_TEMPLATE = """Analyse this business opportunity listing for an embroidery manufacturer in Maharashtra, India.

Title: {title}
Source: {source}
Snippet: {snippet}
URL: {url}

Extract and return this JSON exactly:
{{
  "relevance": <integer 1-10, how relevant this is for a computerised embroidery business with 18 machines>,
  "summary": "<one sentence plain-English summary of the opportunity>",
  "value_inr": <estimated contract value in INR as integer, 0 if unknown>,
  "deadline": "<ISO date YYYY-MM-DD or empty string>",
  "location": "<city/state or Pan India>",
  "quantity": "<e.g. 5000 pieces or empty>",
  "action": "<specific next step the business owner should take, max 15 words>",
  "tags": ["<tag1>", "<tag2>", "<tag3>"]
}}

IMPORTANT — the business is looking for DEMAND (parties that GIVE OUT work), not competitors:
- A government tender to SUPPLY garments/uniforms = good (we bid on it)
- A big company's vendor registration / procurement page = good (we register as their supplier)
- A buyer/RFQ looking for embroidery or garment work = excellent
- A company that SELLS or PROVIDES embroidery services = COMPETITOR, score 1-2
- Any clothing/garment work is acceptable; embroidery work scores highest

Scoring guide for relevance:
- 9-10: Direct embroidery/garment tender or buyer RFQ, high value, Maharashtra preferred
- 7-8:  Uniform/garment supply tender or major-company vendor registration
- 5-6:  Related garment/textile demand, may include embroidery
- 3-4:  Loosely related demand-side page
- 1-2:  Competitor (sells embroidery), irrelevant, or mismatched"""


def analyse(opportunity: dict) -> dict:
    """Send one opportunity to Ollama, return structured analysis dict."""
    prompt = PROMPT_TEMPLATE.format(
        title=opportunity.get("title", ""),
        source=opportunity.get("source", ""),
        snippet=opportunity.get("snippet", "")[:400],
        url=opportunity.get("url", ""),
    )
    payload = json.dumps({
        "model": MODEL,
        "system": SYSTEM,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 400},
    }).encode()

    try:
        req = urllib.request.Request(
            OLLAMA_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read())
        raw = resp.get("response", "{}").strip()
        # Strip markdown fences if model adds them
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        result = json.loads(raw)
        # Normalise
        return {
            "relevance": int(result.get("relevance", 5)),
            "summary":   str(result.get("summary", ""))[:300],
            "value_inr": int(result.get("value_inr", 0) or 0),
            "deadline":  str(result.get("deadline", ""))[:20],
            "location":  str(result.get("location", ""))[:100],
            "quantity":  str(result.get("quantity", ""))[:100],
            "action":    str(result.get("action", ""))[:200],
            "tags":      json.dumps(result.get("tags", [])[:6]),
        }
    except json.JSONDecodeError as e:
        print(f"      [AI parse error] {e} — raw: {raw[:120]}")
        return _fallback()
    except Exception as e:
        print(f"      [AI error] {e}")
        return _fallback()


def _fallback() -> dict:
    return {
        "relevance": 5, "summary": "", "value_inr": 0,
        "deadline": "", "location": "", "quantity": "",
        "action": "Review manually", "tags": "[]",
    }


def analyse_batch(opportunities: list, verbose=True) -> int:
    """
    Analyse a list of raw opportunity dicts from DB (must have uid).
    Saves results back via db.save_ai_analysis.
    Returns count of processed items.
    """
    from engine.db import save_ai_analysis
    done = 0
    for i, opp in enumerate(opportunities):
        if verbose:
            print(f"  [{i+1}/{len(opportunities)}] AI: {opp['title'][:60]}...")
        result = analyse(opp)
        save_ai_analysis(opp["uid"], result)
        done += 1
    return done
