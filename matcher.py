"""Link website locations to CRM accounts and turn the differences into proposals.

Nothing here talks to the network or writes anything: it takes two lists
(locations, accounts) and returns (proposals, report). That makes it easy to
test and safe to re-run.

Proposal types
  update        change fields on one account (name, address, zip, parent, care type)
  create        website location with no CRM account
  chow          SOP case: create a new account under Bellhaven and point the old
                account(s) at it with chow_current_account; old account untouched
  chow_link     SOP case where the "new" account already exists: only set
                chow_current_account on the old one
  duplicate     set duplicate_of_account + status Inactive on the losing copy
  needs_review  under Bellhaven in the CRM but not on the website, no other clue
"""
from __future__ import annotations

import config
import sop
from normalize import (core_name, house_number, is_po_box, norm_city, norm_name,
                       norm_phone, norm_street, norm_zip, similarity)

WATCHED = ["name", "parent_id", "billing_street", "billing_city", "billing_state", "billing_zip",
           "care_type", "status", "lifetime_revenue", "outstanding_ar",
           "chow_current_account", "duplicate_of_account"]


def snapshot(account: dict) -> dict:
    keep = WATCHED + ["account_id", "parent_name", "phone", "note"]
    return {k: account.get(k) for k in keep}


def find_operator_parent(accounts: list) -> dict:
    wanted = norm_name(config.OPERATOR_PARENT_NAME)
    found = [a for a in accounts if not a.get("parent_id") and norm_name(a["name"]).startswith(wanted)
             and a.get("status") != "Inactive" and not a.get("duplicate_of_account")]
    if len(found) != 1:
        raise RuntimeError(f"Expected exactly one '{config.OPERATOR_PARENT_NAME}' parent account, found {len(found)}.")
    return found[0]


def match(loc: dict, acct: dict):
    """Return {'rule', 'score', ...} when the account is this location, else None."""
    street_l, street_a = norm_street(loc["street"]), norm_street(acct.get("billing_street"))
    same_zip = bool(norm_zip(loc["zip"])) and norm_zip(loc["zip"]) == norm_zip(acct.get("billing_zip"))
    same_city = (norm_city(loc["city"]) == norm_city(acct.get("billing_city"))
                 and loc["state"].upper() == (acct.get("billing_state") or "").upper())
    street_sim = similarity(street_l, street_a)
    name_sim = similarity(norm_name(loc["name"]), norm_name(acct["name"]))
    phone = bool(norm_phone(loc.get("phone"))) and norm_phone(loc.get("phone")) == norm_phone(acct.get("phone"))
    same_house = bool(house_number(loc["street"])) and house_number(loc["street"]) == house_number(acct.get("billing_street"))

    rule = score = None
    if street_l and street_l == street_a and same_zip:
        rule, score = "Same street address and zip", 100
    elif street_l and street_l == street_a and same_city:
        rule, score = "Same street address and city (zip differs)", 95
    elif same_house and street_sim >= config.STREET_FUZZY_MIN and (same_zip or same_city):
        rule, score = "Same house number, very similar street, same city/zip", street_sim
    elif name_sim >= config.NAME_MATCH_MIN and (same_city or same_zip):
        rule, score = "Same name in the same city (street differs)", name_sim
    if rule is None:
        return None
    return {"rule": rule, "score": score, "name_similarity": name_sim,
            "street_similarity": street_sim, "phone_match": phone}


def near_misses(loc: dict, accounts: list) -> list:
    """Accounts that look related but were deliberately NOT matched. Evidence only."""
    out, core = [], core_name(loc["name"])
    for a in accounts:
        sim = similarity(core, core_name(a["name"])) if core else 0
        if sim < config.NEAR_MISS_MIN:
            continue
        where = f"{a.get('billing_street')}, {a.get('billing_city')}, {a.get('billing_state')}"
        same_city = norm_city(loc["city"]) == norm_city(a.get("billing_city")) and loc["state"] == a.get("billing_state")
        why = "same city but a different street address" if same_city else "different city/state"
        out.append({"account_id": a["account_id"], "name": a["name"], "address": where,
                    "parent_name": a.get("parent_name") or "(no parent)",
                    "reason": f"Similar name ({sim}%), {why} - treated as a different facility."})
    return out


def _care_types(loc: dict) -> list:
    return [config.CARE_MAP[c] for c in loc.get("care_offerings", []) if c in config.CARE_MAP]


def _new_account_fields(loc: dict, parent_id: str, note: str) -> dict:
    care = _care_types(loc)
    return {"name": loc["name"], "parent_id": parent_id, "billing_street": loc["street"],
            "billing_city": loc["city"], "billing_state": loc["state"], "billing_zip": loc["zip"],
            "care_type": care[0] if care else "", "phone": loc.get("phone", ""),
            "status": "Active", "note": note}


def _field_fixes(loc: dict, acct: dict, operator_id: str):
    """Compare website vs CRM for the surviving account. Returns (changes, notes, warnings)."""
    changes, notes, warnings = {}, [], []
    if acct.get("parent_id") != operator_id:
        changes["parent_id"] = operator_id
        notes.append(f"move parent from {acct.get('parent_name') or '(none)'} to Bellhaven")
    if norm_name(acct["name"]) != norm_name(loc["name"]):
        changes["name"] = loc["name"]
        notes.append(f"rename '{acct['name']}' to '{loc['name']}'")
    if is_po_box(acct.get("billing_street")):
        warnings.append("CRM billing address is a PO Box; left alone because a billing address can differ from the physical one.")
    elif norm_street(acct.get("billing_street")) != norm_street(loc["street"]):
        changes["billing_street"] = loc["street"]
        notes.append(f"street '{acct.get('billing_street')}' to '{loc['street']}'")
    if norm_city(acct.get("billing_city")) != norm_city(loc["city"]):
        changes["billing_city"] = loc["city"]
        notes.append(f"city to {loc['city']}")
    if (acct.get("billing_state") or "").upper() != loc["state"].upper():
        changes["billing_state"] = loc["state"]
        notes.append(f"state to {loc['state']}")
    if norm_zip(acct.get("billing_zip")) != norm_zip(loc["zip"]):
        changes["billing_zip"] = loc["zip"]
        notes.append(f"zip {acct.get('billing_zip')} to {loc['zip']}")
    care = _care_types(loc)
    if care and acct.get("care_type") not in care:
        changes["care_type"] = care[0]
        notes.append(f"care type '{acct.get('care_type')}' to '{care[0]}'")
    return changes, notes, warnings


def _sentence(notes: list) -> str:
    text = "; ".join(notes)
    return text[:1].upper() + text[1:] + "."


def plan(locations: list, accounts: list):
    operator = find_operator_parent(accounts)
    op_id = operator["account_id"]
    parent_ids = {a["parent_id"] for a in accounts if a.get("parent_id")}

    def is_parent(a):
        return a["account_id"] in parent_ids or "(parent account)" in a["name"].lower()

    def already_handled(a):  # earlier runs (or people) already resolved these
        return bool(a.get("duplicate_of_account")) or bool(a.get("chow_current_account"))

    eligible = [a for a in accounts if not is_parent(a) and not already_handled(a)]

    # --- 1. every (location, account) pair that matches; an account belongs to its best location
    best = {}
    for loc in locations:
        for a in eligible:
            m = match(loc, a)
            if m and (a["account_id"] not in best or m["score"] > best[a["account_id"]][1]["score"]):
                best[a["account_id"]] = (loc["slug"], m, a)
    by_loc = {}
    for slug, m, a in best.values():
        by_loc.setdefault(slug, []).append((a, m))

    proposals, report, matched_ids = [], [], set()

    for loc in locations:
        cands = by_loc.get(loc["slug"], [])
        matched_ids.update(a["account_id"] for a, _ in cands)
        row = {"slug": loc["slug"], "location": loc["name"], "city": f"{loc['city']}, {loc['state']}"}

        if not cands:
            proposals.append({
                "type": "create", "account_id": "", "slug": loc["slug"],
                "title": f"Create account: {loc['name']}",
                "summary": f"On the website at {loc['street']}, {loc['city']}, {loc['state']} {loc['zip']} but no CRM account matches. Create it under Bellhaven.",
                "changes": _new_account_fields(loc, op_id, f"Created from Bellhaven website listing {loc['url']}"),
                "evidence": {"location": loc, "near_misses": near_misses(loc, eligible)},
            })
            report.append({**row, "outcome": "No CRM account - create", "account": ""})
            continue

        # SOP: accounts under the wrong parent with revenue AND open AR are frozen.
        locked = [(a, m) for a, m in cands if a.get("parent_id") != op_id and sop.must_preserve(a)]
        locked_ids = {a["account_id"] for a, _ in locked}
        free = [(a, m) for a, m in cands if a["account_id"] not in locked_ids]

        def rank(item):
            a, m = item
            return (a.get("parent_id") == op_id,                 # already under Bellhaven
                    float(a.get("lifetime_revenue") or 0) > 0,   # billing history lives here
                    m["phone_match"],                            # phone equals the website's
                    m["score"],                                  # strength of the address/name match
                    bool(a.get("parent_id")),                    # belongs to some operator vs orphan
                    a.get("status") == "Active",
                    m["name_similarity"],
                    [-ord(c) for c in a["account_id"]])          # stable tie-break: lowest id

        free.sort(key=rank, reverse=True)
        survivor = free[0] if free else None

        if survivor:
            acct, m = survivor
            changes, notes, warnings = _field_fixes(loc, acct, op_id)
            others = [snapshot(a) for a, _ in cands if a["account_id"] != acct["account_id"]]
            if changes:
                ev = {"location": loc, "account": snapshot(acct), "match": m, "others": others, "warnings": warnings}
                if "parent_id" in changes:
                    ev["sop"] = sop.explain(acct)
                proposals.append({
                    "type": "update", "account_id": acct["account_id"], "slug": loc["slug"],
                    "title": f"Fix account: {acct['name']}",
                    "summary": _sentence(notes),
                    "changes": changes, "evidence": ev,
                })
                report.append({**row, "outcome": "Matched - needs fix", "account": acct["name"], "rule": m["rule"]})
            else:
                report.append({**row, "outcome": "Matched - no action", "account": acct["name"],
                               "rule": m["rule"], "notes": warnings})

            for a, dm in free[1:]:
                w = []
                if float(a.get("lifetime_revenue") or 0) > 0 or float(a.get("outstanding_ar") or 0) > 0:
                    w.append("This copy has billing history - confirm with billing before inactivating.")
                proposals.append({
                    "type": "duplicate", "account_id": a["account_id"], "slug": loc["slug"],
                    "title": f"Mark duplicate: {a['name']}",
                    "summary": f"Same facility as '{acct['name']}' ({acct['account_id']}). Keep that one; mark this copy Inactive and point it at the survivor.",
                    "changes": {"duplicate_of_account": acct["account_id"], "status": "Inactive",
                                "note": f"Duplicate of {acct['account_id']} ({loc['name']}); same facility at {loc['street']}, {loc['city']}."},
                    "evidence": {"location": loc, "account": snapshot(a), "match": dm,
                                 "survivor": snapshot(acct), "warnings": w,
                                 "why_survivor": "Survivor chosen in this order: already under Bellhaven, has billing history, phone matches website, match strength, has a parent, Active, name similarity."},
                })
            for a, lm in locked:
                proposals.append({
                    "type": "chow_link", "account_id": a["account_id"], "slug": loc["slug"],
                    "title": f"CHOW link: {a['name']}",
                    "summary": f"Has revenue and open AR, so it stays untouched under {a.get('parent_name') or '(none)'}. Point chow_current_account at the current account '{acct['name']}'.",
                    "changes": {"chow_current_account": acct["account_id"]},
                    "evidence": {"location": loc, "account": snapshot(a), "match": lm,
                                 "survivor": snapshot(acct), "sop": sop.explain(a)},
                })
        else:
            first, m = locked[0]
            proposals.append({
                "type": "chow", "account_id": first["account_id"], "slug": loc["slug"],
                "title": f"CHOW: {first['name']}",
                "summary": f"Belongs under Bellhaven but sits under {first.get('parent_name') or '(none)'} with revenue and open AR. Leave it as is, create a new account under Bellhaven, and set chow_current_account on the old one.",
                "changes": {"create": _new_account_fields(loc, op_id, f"Created by change of ownership (CHOW); previous account {first['account_id']} preserved for billing."),
                            "link_old_ids": [a["account_id"] for a, _ in locked]},
                "evidence": {"location": loc, "account": snapshot(first), "match": m, "sop": sop.explain(first),
                             "others": [snapshot(a) for a, _ in locked[1:]]},
            })
            report.append({**row, "outcome": "Matched - CHOW (new account)", "account": first["name"], "rule": m["rule"]})

    # --- 3. accounts under Bellhaven that the website no longer lists
    for a in eligible:
        if a.get("parent_id") != op_id or a["account_id"] in matched_ids or a.get("status") != "Active":
            continue
        street, zip_code = norm_street(a.get("billing_street")), norm_zip(a.get("billing_zip"))
        twins = [t for t in eligible if t["account_id"] != a["account_id"] and t.get("parent_id")
                 and t.get("parent_id") != op_id and street and norm_street(t.get("billing_street")) == street
                 and norm_zip(t.get("billing_zip")) == zip_code]
        row = {"slug": "", "location": "(not on website)", "city": f"{a.get('billing_city')}, {a.get('billing_state')}", "account": a["name"]}
        if twins and sop.must_preserve(a):
            t = twins[0]
            proposals.append({
                "type": "chow_link", "account_id": a["account_id"], "slug": "",
                "title": f"CHOW link: {a['name']}",
                "summary": f"Not on the Bellhaven website, and '{t['name']}' under {t.get('parent_name')} is at the same address, so ownership has moved. It has revenue and open AR, so it stays untouched; only chow_current_account is set, pointing at the existing new-owner account (no new account needed).",
                "changes": {"chow_current_account": t["account_id"]},
                "evidence": {"account": snapshot(a), "survivor": snapshot(t), "sop": sop.explain(a)},
            })
            report.append({**row, "outcome": "Not on website - sold, CHOW link"})
        elif twins:
            t = twins[0]
            proposals.append({
                "type": "duplicate", "account_id": a["account_id"], "slug": "",
                "title": f"Mark duplicate: {a['name']}",
                "summary": f"Not on the Bellhaven website, and '{t['name']}' under {t.get('parent_name')} is at the same address. No open AR, so mark this stale copy Inactive and point it at that account.",
                "changes": {"duplicate_of_account": t["account_id"], "status": "Inactive",
                            "note": f"No longer a Bellhaven community; facility is now {t['account_id']} ({t['name']})."},
                "evidence": {"account": snapshot(a), "survivor": snapshot(t), "sop": sop.explain(a)},
            })
            report.append({**row, "outcome": "Not on website - duplicate of new owner's account"})
        else:
            proposals.append({
                "type": "needs_review", "account_id": a["account_id"], "slug": "",
                "title": f"Needs review: {a['name']}",
                "summary": "Under the Bellhaven parent in the CRM but not on the Bellhaven website, and no other account shares its address. The new owner is unknown, so flag it rather than guess.",
                "changes": {"status": "Needs Review",
                            "note": "Not listed on the Bellhaven website; ownership needs confirming before any outreach through Bellhaven corporate."},
                "evidence": {"account": snapshot(a)},
            })
            report.append({**row, "outcome": "Not on website - needs review"})

    return proposals, report
