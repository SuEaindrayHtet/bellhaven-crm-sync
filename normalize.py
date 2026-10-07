"""Text clean-up so '980 W Michigan Ave' equals '980 West Michigan Avenue'."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

STREET_WORDS = {
    "street": "st", "avenue": "ave", "av": "ave", "road": "rd", "drive": "dr",
    "lane": "ln", "boulevard": "blvd", "court": "ct", "place": "pl",
    "pk": "pike", "parkway": "pkwy", "highway": "hwy", "circle": "cir",
    "terrace": "ter", "trail": "trl", "square": "sq",
    "north": "n", "south": "s", "east": "e", "west": "w",
    "northwest": "nw", "northeast": "ne", "southwest": "sw", "southeast": "se",
}

# Words that say nothing about which facility it is. Only used for the
# "near miss" hint shown to reviewers, never for an automatic match.
GENERIC_NAME_WORDS = {
    "bellhaven", "the", "of", "at", "and", "senior", "living", "care", "center",
    "centre", "nursing", "rehab", "rehabilitation", "health", "healthcare",
    "community", "communities", "home", "campus",
}


def _clean(text: str) -> str:
    text = (text or "").lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def norm_street(street: str) -> str:
    return " ".join(STREET_WORDS.get(tok, tok) for tok in _clean(street).split())


def house_number(street: str) -> str:
    m = re.match(r"\s*(\d+)", street or "")
    return m.group(1) if m else ""


def is_po_box(street: str) -> bool:
    return bool(re.match(r"p\s*o\s*box\b", _clean(street)))


def norm_name(name: str) -> str:
    """Case, punctuation, '&' vs 'and' and a leading 'The' are not real differences."""
    return re.sub(r"^the ", "", _clean(name))


def core_name(name: str) -> str:
    return " ".join(t for t in norm_name(name).split() if t not in GENERIC_NAME_WORDS)


def norm_city(city: str) -> str:
    return _clean(city)


def norm_zip(zip_code: str) -> str:
    return re.sub(r"\D", "", str(zip_code or ""))[:5]


def norm_phone(phone: str) -> str:
    return re.sub(r"\D", "", str(phone or ""))[-10:]


def similarity(a: str, b: str) -> int:
    """0-100. Word order is ignored ('Barks Rd W' vs 'W Barks Rd')."""
    if not a or not b:
        return 0
    a, b = " ".join(sorted(a.split())), " ".join(sorted(b.split()))
    return round(SequenceMatcher(None, a, b).ratio() * 100)
