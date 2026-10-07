"""Review app. Run:  python app.py   then open http://127.0.0.1:5050

This is the only place a CRM write can start, and only from an Approve click.
"""
from __future__ import annotations

import secrets

from flask import Flask, flash, redirect, render_template, request, url_for

import applier
import pipeline
import store
from crm import CRM, CRMError

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

TYPE_LABELS = {
    "chow": "Change of ownership (new account, old one preserved)",
    "chow_link": "Change of ownership (link to existing account)",
    "update": "Fix an existing account",
    "duplicate": "Duplicates",
    "create": "New accounts",
    "needs_review": "Not on the website",
}
FIELDS = [("Name", "name", "name"), ("Street", "street", "billing_street"), ("City", "city", "billing_city"),
          ("State", "state", "billing_state"), ("Zip", "zip", "billing_zip"),
          ("Care", "care_offerings", "care_type"), ("Phone", "phone", "phone")]


def view(p: dict) -> dict:
    """Shape one proposal for the template: a comparison table plus plain-language facts."""
    ev, changes = p["evidence"], p["changes"]
    loc, acct = ev.get("location"), ev.get("account")
    new = changes.get("create") if p["type"] == "chow" else (changes if p["type"] == "create" else None)
    rows = []
    if loc or acct or new:
        parent_after = "Bellhaven Senior Living" if (new or "parent_id" in changes) else ""
        rows.append(("Parent", "Bellhaven Senior Living" if loc else "", (acct or {}).get("parent_name") or ("(none)" if acct else ""), parent_after))
        for label, lkey, akey in FIELDS:
            web = (loc or {}).get(lkey, "")
            web = ", ".join(web) if isinstance(web, list) else web
            after = (new or {}).get(akey, "") if new else changes.get(akey, "")
            rows.append((label, web, (acct or {}).get(akey, "") if acct else "", after))
        if acct:
            rows.append(("Status", "", acct.get("status"), changes.get("status", "")))
            rows.append(("Revenue / AR", "", f"${float(acct.get('lifetime_revenue') or 0):,.0f} / ${float(acct.get('outstanding_ar') or 0):,.0f}", ""))
    facts = []
    if ev.get("match"):
        m = ev["match"]
        facts.append(f"Match: {m['rule']} (score {m['score']}; name {m['name_similarity']}%, street {m['street_similarity']}%, phone {'matches' if m['phone_match'] else 'differs'}).")
    if ev.get("sop"):
        facts.append("Billing SOP: " + ev["sop"] + ".")
    if ev.get("survivor"):
        s = ev["survivor"]
        facts.append(f"Points at: {s['name']} ({s['account_id']}), {s.get('billing_street')}, {s.get('billing_city')} - parent {s.get('parent_name') or '(none)'}.")
    if ev.get("why_survivor"):
        facts.append(ev["why_survivor"])
    for o in ev.get("others", []):
        facts.append(f"Other account at this address: {o['name']} ({o['account_id']}), parent {o.get('parent_name') or '(none)'} - has its own proposal.")
    for n in ev.get("near_misses", []):
        facts.append(f"Not matched: {n['name']} ({n['account_id']}), {n['address']}, parent {n['parent_name']}. {n['reason']}")
    if p["type"] == "chow":
        facts.append("Old account is left exactly as it is; only chow_current_account is set on it after the new account exists.")
    return {**p, "rows": rows, "facts": facts, "warnings": ev.get("warnings", []),
            "target_header": "New account" if new else "After approval", "url": (loc or {}).get("url")}


def decide_one(db, crm, key: str, action: str) -> str:
    p = store.get(db, key)
    if not p or p["status"] not in ("pending", "failed"):
        return f"Skipped {key}: already {p['status'] if p else 'gone'}."
    if action == "reject":
        store.set_status(db, key, "rejected")
        return f"Rejected: {p['title']}"
    store.set_status(db, key, "approved")
    try:
        result = applier.apply(crm, p, save_progress=lambda r: store.set_status(db, key, "approved", r))
        store.set_status(db, key, "applied", result)
        return f"Applied: {p['title']}"
    except applier.Stale as exc:
        store.set_status(db, key, "stale", {"error": str(exc)})
        return f"NOT applied (out of date): {p['title']} - {exc}"
    except Exception as exc:  # API or network error: keep it retryable
        store.set_status(db, key, "failed", {**(store.get(db, key)["result"] or {}), "error": str(exc)})
        return f"FAILED: {p['title']} - {exc}"


@app.get("/")
def index():
    db = store.connect()
    status = request.args.get("status", "pending")
    groups = {}
    for p in store.list_proposals(db, status):
        groups.setdefault(p["type"], []).append(view(p))
    return render_template("index.html", groups=groups, labels=TYPE_LABELS, status=status,
                           counts=store.counts(db), run=store.latest_run(db))


@app.post("/decide")
def decide():
    db = store.connect()
    try:
        crm = CRM()
        keys = request.form.getlist("key")
        for key in keys:
            flash(decide_one(db, crm, key, request.form["action"]))
    except CRMError as exc:
        flash(f"CRM error: {exc}")
    return redirect(url_for("index", status=request.form.get("status", "pending")))


@app.post("/run")
def run_pipeline():
    try:
        r = pipeline.run()
        flash(f"Pipeline ran: {r['locations']} locations, {r['accounts']} accounts, {r['new']} new proposals, "
              f"{r['already_known']} already known, {r['stale']} marked stale.")
    except Exception as exc:
        flash(f"Pipeline failed: {exc}")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False)
