"""
B2B SDR agent — drafts personalized outreach emails for procurement contacts
and corporate leads, pitching the embroidery business. Uses local Ollama.
"""
import json
import urllib.request
import re

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "gemma4:31b-cloud"

# Business profile used in every pitch (edit via settings later)
DEFAULT_PROFILE = {
    "company": "your embroidery business",
    "location": "Maharashtra, India",
    "machines": "18 hi-tech computerized embroidery machines",
    "capabilities": "logo embroidery, monograms, school/corporate uniform crests, "
                    "badges, patches, bulk garment embroidery",
    "capacity": "large-volume orders with fast turnaround",
    "sender_name": "[Your Name]",
    "phone": "[Your Phone]",
}

SYSTEM = """You are a B2B sales development representative writing concise, professional
cold outreach emails for an Indian computerized embroidery manufacturing business.
Emails must be short (max 150 words), specific, polite, and end with a clear call to action.
Return ONLY valid JSON: {"subject": "...", "body": "..."} — no markdown, no extra text."""

PROMPT = """Write a cold outreach email.

OUR BUSINESS:
- {company} based in {location}
- {machines}
- Services: {capabilities}
- Can handle {capacity}

RECIPIENT:
- Company: {target_company}
- Role/Desk: {role}
- Context: {context}

GOAL: {goal}

Write a personalized email. Reference what the recipient's company does and how our
embroidery capacity can serve them (uniforms, branding, bulk garment work).
Sign off as {sender_name}, {company}, phone {phone}.
Return JSON: {{"subject": "...", "body": "..."}}"""


def _profile(overrides=None):
    p = dict(DEFAULT_PROFILE)
    if overrides:
        for k in ("company", "sender_name", "phone", "location"):
            if overrides.get(k):
                p[k] = overrides[k]
    return p


def draft_email(target_company: str, role: str = "", context: str = "",
                goal: str = "introduce our embroidery services and request vendor registration / a sourcing contact",
                profile_overrides: dict = None) -> dict:
    """Generate a single outreach email via Ollama. Returns {subject, body}."""
    p = _profile(profile_overrides)
    prompt = PROMPT.format(
        target_company=target_company, role=role or "Procurement / Sourcing team",
        context=context or "Identified as a buyer of uniforms/garments who may need embroidery work.",
        goal=goal, **p,
    )
    payload = json.dumps({
        "model": MODEL, "system": SYSTEM, "prompt": prompt, "stream": False,
        "options": {"temperature": 0.4, "num_predict": 350},
    }).encode()
    try:
        req = urllib.request.Request(OLLAMA_URL, data=payload,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = json.loads(r.read()).get("response", "{}").strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        d = json.loads(raw)
        return {"subject": str(d.get("subject", ""))[:200],
                "body": str(d.get("body", ""))[:2000]}
    except Exception as e:
        return {"subject": f"Embroidery services for {target_company}",
                "body": f"(AI draft failed: {e}) — write manually."}
