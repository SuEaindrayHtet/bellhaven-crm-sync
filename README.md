# Bellhaven CRM sync

Keeps the CRM's Bellhaven accounts in line with the Bellhaven website. A daily
job proposes changes; a person approves or rejects each one in a small review
app; only approved changes are written to the CRM.

## Run it

```bash
cd bellhaven-assessment
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q          # 14 tests, no network needed
python pipeline.py           # scrape + match + store proposals (writes nothing to the CRM)
python app.py                # review app at http://127.0.0.1:5050
```

The API token is read from `.env` (`BELLHAVEN_API_TOKEN=...`), which is git-ignored.

## How it fits together

| File | Job |
|---|---|
| `scraper.py` | Follows the directory's "Next" links, then reads every detail page. Also follows community links on the home page. |
| `crm.py` | The only code that calls the CRM API. |
| `normalize.py` | Makes "980 W Michigan Ave" equal "980 West Michigan Avenue". |
| `matcher.py` | Pure function: (locations, accounts) -> proposals + a report. No network, no writes. |
| `sop.py` | The billing rule: revenue AND open AR means CHOW, otherwise re-parent. |
| `store.py` | SQLite. Each proposal has a hash key, which is what makes re-runs safe. |
| `pipeline.py` | The daily job: scrape, read CRM, match, store. |
| `applier.py` | Writes one approved proposal, after re-checking the account has not changed. |
| `app.py` | Flask review screen. The only place a write can start. |
| `config.py` | Thresholds and the care-type mapping. |

## Where to change things

- Match strictness: `STREET_FUZZY_MIN`, `NAME_MATCH_MIN` in `config.py`.
- A new website care label: `CARE_MAP` in `config.py`.
- The SOP condition: `must_preserve()` in `sop.py` (tests in `tests/test_sop.py`).
- Which duplicate survives: `rank()` inside `matcher.plan()`.
- What the reviewer sees: `view()` in `app.py` and `templates/index.html`.
- A new street abbreviation: `STREET_WORDS` in `normalize.py`.

## Schedule

`.github/workflows/daily.yml` (GitHub Actions) or `crontab.txt` (local cron).
The scheduled job only creates proposals.
