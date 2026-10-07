"""Write ONE approved proposal to the CRM. Called only from the review app.

Before writing, the account is fetched again and compared with what the
reviewer saw. If it changed in the meantime the write is refused.
"""
from __future__ import annotations

from datetime import date

import sop
from matcher import WATCHED
from normalize import norm_street, norm_zip


class Stale(Exception):
    """The CRM no longer looks like the evidence the reviewer approved."""


def _check_unchanged(crm, before: dict) -> dict:
    fresh = crm.get_account(before["account_id"])
    changed = [k for k in WATCHED if str(fresh.get(k) or "") != str(before.get(k) or "")
               and not (k in ("lifetime_revenue", "outstanding_ar") and float(fresh.get(k) or 0) == float(before.get(k) or 0))]
    if changed:
        raise Stale(f"Account {before['account_id']} changed since it was proposed ({', '.join(changed)}). Re-run the pipeline.")
    return fresh


def _with_note(fresh: dict, changes: dict) -> dict:
    """Append our note to any existing note instead of overwriting it."""
    changes = dict(changes)
    if changes.get("note"):
        stamped = f"[{date.today().isoformat()} sync] {changes['note']}"
        changes["note"] = f"{fresh['note']} | {stamped}" if fresh.get("note") else stamped
    return changes


def _find_existing(crm, fields: dict):
    """Guard against creating the same account twice (e.g. a retry after a timeout)."""
    for a in crm.list_accounts(parent_id=fields["parent_id"]):
        if (norm_street(a.get("billing_street")) == norm_street(fields["billing_street"])
                and norm_zip(a.get("billing_zip")) == norm_zip(fields["billing_zip"])
                and not a.get("duplicate_of_account")):
            return a
    return None


def apply(crm, proposal: dict, save_progress=lambda result: None) -> dict:
    kind, changes, ev = proposal["type"], proposal["changes"], proposal["evidence"]
    result = dict(proposal.get("result") or {})

    if kind == "create":
        existing = _find_existing(crm, changes)
        if existing:
            return {"account_id": existing["account_id"], "note": "Already existed; nothing created."}
        created = crm.create_account(changes)
        return {"account_id": created["account_id"], "created": created}

    if kind == "chow":
        # Step 1: the new account (remember its id before step 2 so a retry cannot create a second one).
        new_id = result.get("new_account_id")
        if not new_id:
            for old_id in changes["link_old_ids"]:
                old = crm.get_account(old_id)
                if old.get("chow_current_account"):
                    raise Stale(f"{old_id} already has chow_current_account set.")
                if not sop.must_preserve(old):
                    raise Stale(f"{old_id} no longer has revenue and open AR; SOP says re-parent instead. Re-run the pipeline.")
            existing = _find_existing(crm, changes["create"])
            new_id = existing["account_id"] if existing else crm.create_account(changes["create"])["account_id"]
            result["new_account_id"] = new_id
            save_progress(result)
        # Step 2: point the old account(s) at it. Nothing else on them is touched.
        for old_id in changes["link_old_ids"]:
            crm.update_account(old_id, {"chow_current_account": new_id})
        result["linked"] = changes["link_old_ids"]
        return result

    # update / duplicate / chow_link / needs_review all PATCH one existing account.
    fresh = _check_unchanged(crm, ev["account"])
    if kind == "update" and "parent_id" in changes and sop.must_preserve(fresh):
        raise Stale("Account now has revenue and open AR; SOP forbids re-parenting. Re-run the pipeline.")
    if kind in ("duplicate", "chow_link"):
        target = changes.get("duplicate_of_account") or changes.get("chow_current_account")
        survivor = crm.get_account(target)
        if survivor.get("duplicate_of_account") or survivor.get("status") == "Inactive":
            raise Stale(f"Target account {target} is itself inactive or a duplicate.")
    updated = crm.update_account(proposal["account_id"], _with_note(fresh, changes))
    return {"account_id": proposal["account_id"], "updated": updated}
