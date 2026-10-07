"""The billing SOP, kept tiny and separate so it is easy to read, test and change.

Rule: when an account has to move to a different parent, check billing first.
  revenue history AND outstanding AR > 0  -> do NOT touch the account (CHOW):
        create a new account under the right parent and point the old one at
        it with chow_current_account.
  otherwise                               -> re-parent the existing account.
"""
from __future__ import annotations


def _money(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def must_preserve(account: dict) -> bool:
    """True when billing needs this account left exactly as it is."""
    return _money(account.get("lifetime_revenue")) > 0 and _money(account.get("outstanding_ar")) > 0


def parent_move_action(account: dict) -> str:
    """'chow' or 'reparent' for an account that belongs under a different parent."""
    return "chow" if must_preserve(account) else "reparent"


def explain(account: dict) -> str:
    rev, ar = _money(account.get("lifetime_revenue")), _money(account.get("outstanding_ar"))
    verdict = "CHOW: keep the old account, create a new one" if must_preserve(account) else "re-parent directly"
    return f"lifetime revenue ${rev:,.0f}, outstanding AR ${ar:,.0f} -> {verdict}"
