"""Thin client for the CRM sandbox API. The only place that talks to the CRM."""
from __future__ import annotations

import requests

import config


class CRMError(RuntimeError):
    pass


class CRM:
    def __init__(self, token: str = "", base_url: str = ""):
        self.base = (base_url or config.API_URL).rstrip("/")
        token = token or config.API_TOKEN
        if not token:
            raise CRMError("No API token. Put BELLHAVEN_API_TOKEN=... in the .env file.")
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"

    def _call(self, method: str, path: str, **kwargs):
        r = self.session.request(method, self.base + path, timeout=30, **kwargs)
        if r.status_code >= 400:
            raise CRMError(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
        return r.json()

    def list_accounts(self, **filters) -> list:
        accounts, page = [], 1
        while True:
            body = self._call("GET", "/accounts", params={**filters, "page": page, "page_size": 100})
            rows = body.get("data", [])
            accounts += rows
            if not rows or len(accounts) >= body.get("total", 0):
                return accounts
            page += 1

    def get_account(self, account_id: str) -> dict:
        body = self._call("GET", f"/accounts/{account_id}")
        return body.get("data", body) if isinstance(body.get("data"), dict) else body

    def create_account(self, fields: dict) -> dict:
        body = self._call("POST", "/accounts", json=fields)
        return body.get("data", body) if isinstance(body.get("data"), dict) else body

    def update_account(self, account_id: str, changes: dict) -> dict:
        body = self._call("PATCH", f"/accounts/{account_id}", json=changes)
        return body.get("data", body) if isinstance(body.get("data"), dict) else body
