"""End to end against a snapshot of the real sandbox data, with an in-memory CRM."""
import applier
import matcher
import pipeline
import store

OP = "0015QAPLGS3FVYEEEM"  # Bellhaven Senior Living (Parent Account)


def by_type(proposals):
    out = {}
    for p in proposals:
        out.setdefault(p["type"], {})[p["account_id"] or p["slug"]] = p
    return out


def test_classification(locations, accounts):
    props, report = matcher.plan(locations, accounts)
    t = by_type(props)
    # SOP: revenue + open AR under the wrong parent -> new account, old one untouched
    assert set(t["chow"]) == {"001U6RW32TY0WSXZZB", "001A34WFSUYHCRBLFT"}          # Tiffin, Marietta
    # revenue but no AR, or no billing at all -> straight re-parent
    assert t["update"]["001LGFPBJY4N9MB6KL"]["changes"] == {"parent_id": OP}       # Lima
    assert t["update"]["001UKEFGADQ8YCZ4YM"]["changes"] == {"parent_id": OP}       # Findlay (had no parent)
    assert t["update"]["001H1JMVZWP46D5VUF"]["changes"] == {"parent_id": OP, "name": "Bellhaven of Zanesville"}
    assert t["update"]["001CF3LDWVRGL09P4F"]["changes"] == {"billing_zip": "45662"}  # Portsmouth typo
    assert t["update"]["001RJU1X4NBWC1Q0G7"]["changes"] == {"name": "Bellhaven of Chagrin Falls"}
    # sold facility with open AR whose new-owner account already exists -> link only
    assert t["chow_link"]["001SXSF4ELF0Z2LGDM"]["changes"] == {"chow_current_account": "0017JP8Z1UQ763BVK3"}
    # duplicates keep the copy that is already under Bellhaven
    assert t["duplicate"]["001JD2MWRA74LTSN24"]["changes"]["duplicate_of_account"] == "001UELXDAKFRKB8932"
    assert t["duplicate"]["001QU150PM4Z15UA71"]["changes"]["duplicate_of_account"] == "001EGU7BMJ942ZTRE6"
    assert len(t["duplicate"]) == 7
    # look-alikes are NOT matched: same name other state, similar name other street, New Carlisle vs Carlisle
    assert set(t["create"]) == {"bellhaven-of-batavia", "bellhaven-at-union-square", "bellhaven-of-carlisle", "amberly-manor"}
    assert t["create"]["amberly-manor"]["evidence"]["near_misses"][0]["account_id"] == "0015D74ZLRY810RGY5"
    assert set(t["needs_review"]) == {"00116ETS45BL7DTQP7", "0016PVXH4B25HWR7QE"}  # Alliance, Coldwater
    # PO Box billing address is matched but not overwritten
    assert "001NXP9X46CWEPSLSV" not in t["update"]
    assert len(report) == 35 + 3


def approve_all(db, crm):
    for p in store.list_proposals(db, "pending"):
        result = applier.apply(crm, p, save_progress=lambda r, k=p["key"]: store.set_status(db, k, "approved", r))
        store.set_status(db, p["key"], "applied", result)


def test_approve_everything_then_rerun_is_clean(locations, crm):
    db = store.connect(":memory:")
    scraped = {"locations": locations, "warnings": []}
    first = pipeline.run(db, crm, scraped)
    assert first["new"] == 27
    assert crm.writes == []                       # the pipeline itself never writes

    approve_all(db, crm)
    a = crm.accounts
    # CHOW: old account untouched apart from the pointer; new one under Bellhaven
    tiffin = a["001U6RW32TY0WSXZZB"]
    assert tiffin["parent_id"] == "001FWSQ30SFW6S7604" and tiffin["status"] == "Active" and tiffin["note"] == ""
    new = a[tiffin["chow_current_account"]]
    assert new["parent_id"] == OP and new["name"] == "Bellhaven of Tiffin" and new["lifetime_revenue"] == 0
    assert a["001SXSF4ELF0Z2LGDM"]["parent_id"] == OP and a["001SXSF4ELF0Z2LGDM"]["chow_current_account"] == "0017JP8Z1UQ763BVK3"
    assert a["001LGFPBJY4N9MB6KL"]["parent_id"] == OP
    assert a["001QU150PM4Z15UA71"]["status"] == "Inactive"
    assert sum(1 for w in crm.writes if w[0] == "POST") == 6   # 4 new locations + 2 CHOW accounts

    writes_before = len(crm.writes)
    second = pipeline.run(db, crm, scraped)
    assert second["proposed"] == 0 and second["new"] == 0      # corrected CRM produces nothing
    assert len(crm.writes) == writes_before


def test_rejected_items_are_not_proposed_again(locations, crm):
    db = store.connect(":memory:")
    scraped = {"locations": locations, "warnings": []}
    pipeline.run(db, crm, scraped)
    for p in store.list_proposals(db, "pending"):
        store.set_status(db, p["key"], "rejected")
    again = pipeline.run(db, crm, scraped)
    assert again["new"] == 0 and again["already_known"] == 27
    assert store.list_proposals(db, "pending") == []


def test_write_refused_if_account_changed_after_proposal(locations, crm):
    db = store.connect(":memory:")
    pipeline.run(db, crm, {"locations": locations, "warnings": []})
    lima = next(p for p in store.list_proposals(db, "pending") if p["account_id"] == "001LGFPBJY4N9MB6KL")
    crm.accounts["001LGFPBJY4N9MB6KL"]["outstanding_ar"] = 900   # billing changed overnight
    try:
        applier.apply(crm, lima)
        assert False, "should have refused"
    except applier.Stale:
        pass
    assert crm.writes == []


def test_broken_scrape_stops_the_run(locations, crm):
    db = store.connect(":memory:")
    pipeline.run(db, crm, {"locations": locations, "warnings": []})
    try:
        pipeline.run(db, crm, {"locations": locations[:5], "warnings": []})
        assert False, "should have stopped"
    except RuntimeError:
        pass
