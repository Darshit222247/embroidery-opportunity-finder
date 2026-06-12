# Embroidery Opportunity Finder

A local web app that finds business opportunities for a computerized embroidery / garment
manufacturer in India — government tenders, corporate vendor openings, export buyers, and
procurement contacts — all in one dashboard, powered by free tools and a local LLM.

## What it does

- **Scrapes opportunities** from the web (DuckDuckGo), the GeM government procurement portal
  (Playwright headless browser), and tender-directory sites (dirhunt).
- **AI-scores every lead** for relevance using a local Ollama model.
- **Extracts tender PDF details** — quantity, turnover requirement, EMD, deadline, eligibility,
  and whether embroidery is actually required.
- **Finds procurement contacts** (email/phone) at major companies (Tata, D-Mart, Reliance, etc.).
- **Export markets** — ranks which countries import Indian embroidery/apparel using free
  UN Comtrade trade data, with a per-country buyer-finder.
- **Outreach (SDR)** — AI-drafts personalized outreach emails and tracks a pipeline
  (Draft → Sent → Replied → Meeting → Won).
- **Eligibility checker** — enter your turnover + MSE status; each tender shows if you qualify.

## Tech stack

- Python + Flask (web dashboard, SQLite store)
- Playwright (headless Chrome scraping)
- Ollama (local LLM — `gemma4:31b-cloud` by default)
- ddgs, pypdf, dirhunt, comtradeapicall — all free / open source
- No paid APIs required

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
# Ollama must be installed and running with a model pulled, e.g.:
#   ollama pull gemma4:31b-cloud
```

## Run

```bash
# Web dashboard
python3 app.py
# then open http://localhost:5050

# Or the CLI engine
python3 search.py            # full run: scrape + AI analyse + enrich
python3 search.py --scrape   # scrape only
python3 search.py --analyse  # AI analysis only
python3 search.py --discover # directory discovery (dirhunt)
python3 search.py --contacts # find procurement contacts
python3 search.py --enrich   # extract GeM PDF details
python3 search.py --fix-urls # validate / clean URLs
```

## Dashboard tabs

- **Opportunities** — tenders & corporate leads with relevance score, deadline, eligibility
- **Contacts** — procurement & buyer contacts (email/phone)
- **Outreach** — AI-drafted emails + SDR pipeline
- **Export markets** — UN Comtrade country rankings + per-country buyer finder

## Notes

- The SQLite database (`opportunities.db`) and any `.env` are git-ignored.
- Optional `BRAVE_API_KEY` is no longer required — search uses free DuckDuckGo.
- Built for a Maharashtra-based business with 18 computerized embroidery machines, but the
  query banks in `engine/scraper.py` can be edited for any region/industry.

## Disclaimer

For authorized business-research use. Respect the terms of service of the sites it queries.
Tender deadlines and contact details should always be verified on the official source before acting.
