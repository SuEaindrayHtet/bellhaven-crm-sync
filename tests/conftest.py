import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
FIX = Path(__file__).parent / "fixtures"


class FakeCRM:
    """In-memory stand-in for the CRM API, loaded with a snapshot of the real sandbox."""

    def __init__(self, accounts):
        self.accounts = {a["account_id"]: copy.deepcopy(a) for a in accounts}
        self.writes = []

    def list_accounts(self, **filters):
        rows = list(self.accounts.values())
        if filters.get("parent_id"):
            rows = [a for a in rows if a["parent_id"] == filters["parent_id"]]
        return copy.deepcopy(rows)

    def get_account(self, account_id):
        return copy.deepcopy(self.accounts[account_id])

    def create_account(self, fields):
        new_id = f"NEW{len(self.accounts):04d}"
        base = {"account_id": new_id, "lifetime_revenue": 0, "outstanding_ar": 0, "chow_current_account": "",
                "duplicate_of_account": "", "note": "", "created_by_candidate": True}
        parent = self.accounts.get(fields.get("parent_id"), {})
        self.accounts[new_id] = {**base, **fields, "parent_name": parent.get("name", "")}
        self.writes.append(("POST", new_id, fields))
        return self.get_account(new_id)

    def update_account(self, account_id, changes):
        self.accounts[account_id].update(changes)
        if "parent_id" in changes:
            self.accounts[account_id]["parent_name"] = self.accounts[changes["parent_id"]]["name"]
        self.writes.append(("PATCH", account_id, changes))
        return self.get_account(account_id)


@pytest.fixture
def accounts():
    return json.loads((FIX / "accounts.json").read_text())


@pytest.fixture
def locations():
    return json.loads((FIX / "locations.json").read_text())


@pytest.fixture
def crm(accounts):
    return FakeCRM(accounts)
