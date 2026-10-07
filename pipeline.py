"""Daily job: scrape -> read CRM -> match -> store proposals. Never writes to the CRM.

    python pipeline.py
"""
from __future__ import annotations

import sys

import config
import matcher
import scraper
import store
from crm import CRM


def run(db=None, crm=None, scrape_result=None) -> dict:
    db = db or store.connect()
    crm = crm or CRM()
    scraped = scrape_result or scraper.scrape()
    locations, warnings = scraped["locations"], list(scraped["warnings"])

    previous = store.last_location_count(db)
    if not locations or len(locations) < previous * config.MIN_SCRAPE_RATIO:
        raise RuntimeError(f"Scrape returned {len(locations)} locations (last run: {previous}). "
                           "Stopping so a broken scrape cannot flag live accounts as removed.")

    accounts = crm.list_accounts()
    proposals, report = matcher.plan(locations, accounts)
    result = store.save_run(db, len(locations), len(accounts), proposals, report, warnings)
    result.update(locations=len(locations), accounts=len(accounts), proposed=len(proposals), warnings=warnings)
    return result


if __name__ == "__main__":
    try:
        r = run()
    except Exception as exc:  # non-zero exit so cron / Actions shows the failure
        print(f"PIPELINE FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"Scraped {r['locations']} locations, read {r['accounts']} CRM accounts.")
    print(f"{r['proposed']} differences found: {r['new']} new proposals, "
          f"{r['already_known']} already decided or pending, {r['stale']} marked stale.")
    for w in r["warnings"]:
        print("  note:", w)
    print("Review them with:  python app.py   then open http://127.0.0.1:5050")
