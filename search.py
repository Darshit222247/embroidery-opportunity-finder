"""
Main entry point for the Embroidery Opportunity Search Engine.

Usage:
  python3 search.py            # full run: scrape + AI analyse
  python3 search.py --scrape   # scrape only (no AI)
  python3 search.py --analyse  # AI analyse pending items only
  python3 search.py --stats    # show DB stats
  python3 search.py --list     # print top results to terminal
"""

import sys
import os
import time
from datetime import datetime

# ensure engine package is importable
sys.path.insert(0, os.path.dirname(__file__))

from engine.config import load_env, has_brave_key
load_env()  # load .env file before importing scraper (which reads BRAVE_API_KEY)

from engine.db import (init_db, upsert_opportunity, get_pending_ai, get_all,
                       log_run, stats, upsert_contact, get_contacts)
from engine.scraper import scrape_all, CONTACT_QUERIES
from engine.ai import analyse_batch


def run_scrape(verbose=True):
    if verbose:
        print("\n── Scraping sources ─────────────────────────────────────")
    items = scrape_all(delay=1.2)
    new = 0
    for item in items:
        if upsert_opportunity(item):
            new += 1
    if verbose:
        print(f"\n  Scraped {len(items)} results → {new} new, {len(items)-new} already known")
    return len(items), new


def run_ai(verbose=True):
    pending = get_pending_ai()
    if not pending:
        if verbose:
            print("  No pending items for AI analysis.")
        return 0
    if verbose:
        print(f"\n── AI analysis ({len(pending)} items) ────────────────────────")
    return analyse_batch(pending, verbose=verbose)


def print_stats():
    s = stats()
    print(f"""
── Database stats ──────────────────────────────────
  Total opportunities : {s['total']}
  Government tenders  : {s['gov']}
  Corporate leads     : {s['corp']}
  Export / B2B        : {s['export']}
  Pending AI          : {s['pending_ai']}
  Last scraped        : {s['last_scraped'] or 'never'}
────────────────────────────────────────────────────""")


def print_top(n=20):
    rows = get_all(min_relevance=0, limit=n)
    if not rows:
        print("  No results yet. Run: python3 search.py")
        return
    print(f"\n── Top {len(rows)} opportunities (relevance ≥ 6) ──────────────")
    for r in rows:
        stars = "★" * r["relevance"] + "☆" * (10 - r["relevance"])
        val = f"₹{r['value_inr']:,}" if r["value_inr"] else "—"
        print(f"""
  [{r['category'].upper():6}] {stars}  {r['source']}
  {r['title'][:80]}
  {r['summary'] or r['snippet'][:120]}
  Value: {val}  |  Deadline: {r['deadline'] or '—'}  |  Location: {r['location'] or '—'}
  Next step: {r['action'] or '—'}
  {r['url'][:80]}""")


def print_contacts():
    rows = get_contacts()
    if not rows:
        print("  No contacts yet. Run: python3 search.py --contacts")
        return
    print(f"\n── {len(rows)} procurement contacts ────────────────────────")
    current = None
    for c in rows:
        if c["company"] != current:
            current = c["company"]
            print(f"\n  ◆ {c['company']}")
        line = "    "
        if c["person"]:
            line += f"{c['person']} — "
        line += c["role"] or "Contact"
        print(line)
        if c["email"]:
            print(f"      Email : {c['email']}")
        if c["phone"]:
            print(f"      Phone : {c['phone']}")
        print(f"      Source: {c['source_url'][:75]}")
        if c["notes"]:
            print(f"      Note  : {c['notes'][:75]}")


def main():
    args = sys.argv[1:]
    init_db()

    if "--stats" in args:
        print_stats()
        return

    if "--list" in args:
        print_top(30)
        return

    if "--contacts" in args:
        from engine.contacts import find_contacts
        print("\n── Finding procurement contacts at major companies ──────")
        found = find_contacts(CONTACT_QUERIES)
        new = sum(1 for c in found if upsert_contact(c))
        print(f"\n  {len(found)} contacts found, {new} new saved.")
        print_contacts()
        return

    if "--show-contacts" in args:
        print_contacts()
        return

    if "--enrich" in args:
        from engine.pdfdetail import enrich_gem_opportunities
        print("\n── Enriching GeM tenders from bid PDFs ──────────────────")
        n = enrich_gem_opportunities(limit=40)
        print(f"\n  Enriched {n} GeM tenders with PDF details.")
        return

    if "--discover" in args:
        from engine.discover import discover_all
        print("\n── Discovering directory URLs with dirhunt (Nekmo) ──────")
        found = discover_all()
        new = sum(1 for o in found if upsert_opportunity(o))
        print(f"\n  {len(found)} relevant directory URLs found, {new} new saved.")
        print("  Run 'python3 search.py --analyse' to score them, then '--fix-urls'.")
        print_stats()
        return

    if "--fix-urls" in args:
        from engine.urlfix import fix_all_urls, purge_dead
        print("\n── Validating all URLs ──────────────────────────────────")
        counts = fix_all_urls(recheck="--recheck" in args)
        print(f"\n  OK: {counts['ok']}  Dead: {counts['dead']}  "
              f"Unreachable: {counts['error']}  Redirects fixed: {counts['fixed_redirect']}")
        purge_dead()
        print_stats()
        return

    started = datetime.utcnow().isoformat()
    total_found = new_added = ai_done = 0

    if "--analyse" in args:
        ai_done = run_ai()
        print(f"\n  AI analysis complete: {ai_done} items processed.")
        print_stats()
        return

    if "--scrape" in args:
        total_found, new_added = run_scrape()
        print_stats()
        return

    # Default: full run
    print("\n╔══════════════════════════════════════════════╗")
    print("║   Embroidery Opportunity Search Engine       ║")
    print("║   Maharashtra · 18-machine computerized      ║")
    print("╚══════════════════════════════════════════════╝")

    total_found, new_added = run_scrape()
    ai_done = run_ai()

    # auto-enrich GeM tenders with PDF details
    try:
        from engine.pdfdetail import enrich_gem_opportunities
        print("\n── Enriching GeM tenders from bid PDFs ──────────────────")
        enrich_gem_opportunities(limit=40)
    except Exception as e:
        print(f"  enrich skipped: {e}")

    # drop tenders whose deadline has already passed
    try:
        from engine.db import purge_expired_tenders
        n = purge_expired_tenders()
        print(f"  Purged {n} expired tenders.")
    except Exception as e:
        print(f"  purge skipped: {e}")

    finished = datetime.utcnow().isoformat()
    log_run(started, finished, total_found, new_added)

    print_stats()
    print_top(10)
    print("\nRun 'python3 search.py --list' anytime to see all top results.")
    print("Run 'python3 search.py --stats' for database summary.\n")


if __name__ == "__main__":
    main()
