"""Scrape every Bellhaven community from the website.

Three things the site does that this handles on purpose:
  * The directory is paginated and asking for a page past the end just repeats
    the last page, so we follow the "Next" link instead of counting pages.
  * Street address, zip and the full care list are only on the detail pages.
  * The home page links to a community that the directory leaves out, so links
    on the home page are followed too.
"""
from __future__ import annotations

import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

import config

COMMUNITY_LINK = re.compile(r"^/communities/([a-z0-9-]+)/?$")


def parse_list(html: str):
    """Return (slugs on this page, relative URL of the next page or None, claimed total or None)."""
    soup = BeautifulSoup(html, "html.parser")
    slugs = []
    for a in soup.select(".card a[href]"):
        m = COMMUNITY_LINK.match(a["href"])
        if m and m.group(1) not in slugs:
            slugs.append(m.group(1))
    next_url = None
    for a in soup.select(".pager a[href]"):
        if "next" in a.get_text().lower():
            next_url = a["href"]
    claimed = re.search(r"(\d+)\s+communities listed", soup.get_text())
    return slugs, next_url, int(claimed.group(1)) if claimed else None


def parse_extra_links(html: str):
    """Community links anywhere on a page (used for the home page)."""
    soup = BeautifulSoup(html, "html.parser")
    found = []
    for a in soup.select("a[href]"):
        m = COMMUNITY_LINK.match(a["href"])
        if m and m.group(1) not in found:
            found.append(m.group(1))
    return found


def parse_detail(html: str, slug: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.select_one(".wrap h1") or soup.find("h1")
    fields = {}
    for dt in soup.select("dl.detail dt"):
        dd = dt.find_next_sibling("dd")
        if dd is not None:
            fields[dt.get_text(strip=True).lower()] = dd

    street = city = state = zip_code = ""
    if "address" in fields:
        lines = [l.strip() for l in fields["address"].get_text("\n").split("\n") if l.strip()]
        if lines:
            m = re.match(r"^(.*?),\s*([A-Z]{2})\s+(\d{5})(?:-\d{4})?$", lines[-1])
            if m:
                city, state, zip_code = m.group(1).strip(), m.group(2), m.group(3)
                street = ", ".join(lines[:-1])
            else:
                street = ", ".join(lines)

    care = []
    if "care offerings" in fields:
        care = [b.get_text(strip=True) for b in fields["care offerings"].select(".badge")]
        if not care:
            care = [t.strip() for t in fields["care offerings"].get_text(",").split(",") if t.strip()]

    def text(key):
        return fields[key].get_text(" ", strip=True) if key in fields else ""

    notice = soup.select_one(".wrap .notice")
    return {
        "slug": slug,
        "name": h1.get_text(" ", strip=True) if h1 else "",
        "street": street, "city": city, "state": state, "zip": zip_code,
        "care_offerings": care,
        "administrator": text("administrator"),
        "phone": text("phone"),
        "notice": notice.get_text(" ", strip=True) if notice else "",
        "url": f"{config.SITE_URL}/communities/{slug}",
    }


def _get(session, url: str) -> str:
    last = None
    for attempt in range(3):
        try:
            r = session.get(url, timeout=20)
            r.raise_for_status()
            return r.text
        except requests.RequestException as exc:  # retry on network hiccups
            last = exc
            time.sleep(1 + attempt)
    raise RuntimeError(f"Could not fetch {url}: {last}")


def scrape(session=None) -> dict:
    """Return {'locations': [...], 'claimed_total': int|None, 'warnings': [...]}."""
    session = session or requests.Session()
    session.headers.setdefault("User-Agent", "bellhaven-crm-sync/1.0")

    slugs, seen_pages, claimed, warnings = [], set(), None, []
    url = "/communities"
    while url and url not in seen_pages and len(seen_pages) < 200:
        seen_pages.add(url)
        page_slugs, url, page_claimed = parse_list(_get(session, urljoin(config.SITE_URL, url)))
        claimed = page_claimed or claimed
        slugs += [s for s in page_slugs if s not in slugs]
    listed = set(slugs)

    for slug in parse_extra_links(_get(session, config.SITE_URL + "/")):
        if slug not in slugs:
            slugs.append(slug)
            warnings.append(f"'{slug}' is linked from the home page but missing from the directory.")

    locations = []
    for slug in slugs:
        loc = parse_detail(_get(session, f"{config.SITE_URL}/communities/{slug}"), slug)
        loc["listed_in_directory"] = slug in listed
        missing = [k for k in ("name", "street", "city", "state", "zip") if not loc[k]]
        if missing:
            warnings.append(f"'{slug}' is missing {', '.join(missing)}; skipped.")
            continue
        locations.append(loc)

    if claimed is not None and claimed != len(listed):
        warnings.append(f"Directory says {claimed} communities but lists {len(listed)}.")
    return {"locations": locations, "claimed_total": claimed, "warnings": warnings}


if __name__ == "__main__":
    import json
    result = scrape()
    print(json.dumps(result, indent=2))
    print(f"\n{len(result['locations'])} locations", *result["warnings"], sep="\n")
