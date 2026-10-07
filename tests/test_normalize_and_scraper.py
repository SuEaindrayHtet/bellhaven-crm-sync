import scraper
from normalize import is_po_box, norm_name, norm_street


def test_street_variants_are_equal():
    assert norm_street("980 W Michigan Ave") == norm_street("980 West Michigan Avenue")
    assert norm_street("4850 NW Sylvania Ave") == norm_street("4850 Northwest Sylvania Avenue")
    assert norm_street("3313 Wilmington Pk") == norm_street("3313 Wilmington Pike")
    assert norm_street("199 Barks Rd W") == norm_street("199 Barks Road West")
    assert norm_street("210 Orchard Lane") != norm_street("431 Main St")


def test_name_punctuation_is_not_a_difference():
    assert norm_name("The Arbors at Bellhaven - Dayton") == norm_name("Arbors at Bellhaven Dayton")
    assert norm_name("Bellhaven Rehab and Nursing") != norm_name("Bellhaven Rehabilitation & Nursing")


def test_po_box():
    assert is_po_box("PO Box 517") and is_po_box("P.O. Box 9") and not is_po_box("12 Post Rd")


LIST_LAST = """<div class="cardgrid"><div class="card"><h3><a href="/communities/amberly-manor">Amberly Manor</a></h3></div></div>
<p>Page 3 of 3 · 34 communities listed</p>
<div class="pager"><a href="/communities?page=2">&larr; Previous</a><span>Page 3 / 3</span></div>"""
LIST_FIRST = LIST_LAST.replace("</span></div>", '</span><a href="/communities?page=2">Next &rarr;</a></div>')
DETAIL = """<div class="wrap"><h1>Bellhaven Rehabilitation &amp; Nursing of Erie</h1><dl class="detail">
<dt>Address</dt><dd>4930 W Lake Rd<br>Erie, PA 16505</dd>
<dt>Care Offerings</dt><dd><span class="badge">Assisted Living</span><span class="badge">Memory Support</span></dd>
<dt>Administrator</dt><dd>Angela Quinn</dd><dt>Phone</dt><dd>(614) 792-9343</dd></dl></div>"""


def test_last_page_has_no_next_link():
    slugs, next_url, claimed = scraper.parse_list(LIST_LAST)
    assert slugs == ["amberly-manor"] and next_url is None and claimed == 34
    assert scraper.parse_list(LIST_FIRST)[1] == "/communities?page=2"


def test_detail_page():
    d = scraper.parse_detail(DETAIL, "x")
    assert d["name"] == "Bellhaven Rehabilitation & Nursing of Erie"
    assert (d["street"], d["city"], d["state"], d["zip"]) == ("4930 W Lake Rd", "Erie", "PA", "16505")
    assert d["care_offerings"] == ["Assisted Living", "Memory Support"]
    assert d["phone"] == "(614) 792-9343"
