"""Supabase bulut istemcisi (Auth + PostgREST), sadece `requests` kullanır.

- Giriş: e-posta + şifre (Supabase Auth, /auth/v1/token?grant_type=password)
- Veri: /rest/v1/<tablo>  — erişim Row Level Security ile sınırlandırılır.
"""
from __future__ import annotations

import time
from typing import Any

import requests

from . import config


class CloudError(RuntimeError):
    pass


class NotLoggedIn(CloudError):
    pass


class SupabaseClient:
    def __init__(self, url: str, anon_key: str, session: dict | None = None, timeout: float = 15.0):
        if not url or not anon_key:
            raise CloudError("Bulut ayarı yok. `renkolcum ayar --url ... --anahtar ...` ile yapılandırın.")
        self.url = url.rstrip("/")
        self.anon_key = anon_key
        self.session = session or {}
        self.timeout = timeout
        self.http = requests.Session()

    # ---------- yapılandırmadan oluştur ----------
    @classmethod
    def from_config(cls) -> "SupabaseClient":
        cfg = config.load_config()
        return cls(cfg["supabase_url"], cfg["supabase_anon_key"], config.load_session())

    # ---------- Auth ----------
    def _auth(self, grant: str, body: dict) -> dict:
        r = self.http.post(f"{self.url}/auth/v1/token", params={"grant_type": grant}, json=body,
                           headers={"apikey": self.anon_key}, timeout=self.timeout)
        if r.status_code != 200:
            try:
                msg = r.json().get("error_description") or r.json().get("msg") or r.text
            except ValueError:
                msg = r.text
            if "Invalid login" in msg:
                msg = "E-posta veya şifre hatalı"
            raise CloudError(f"Giriş başarısız: {msg}")
        d = r.json()
        self.session = {
            "access_token": d["access_token"],
            "refresh_token": d["refresh_token"],
            "expires_at": int(d.get("expires_at") or time.time() + int(d.get("expires_in", 3600))),
            "user_id": d["user"]["id"],
            "email": d["user"].get("email"),
        }
        config.save_session(self.session)
        return self.session

    def login(self, email: str, password: str) -> dict:
        return self._auth("password", {"email": email, "password": password})

    def refresh(self) -> dict:
        if not self.session.get("refresh_token"):
            raise NotLoggedIn("Oturum yok. Önce `renkolcum giris` çalıştırın.")
        return self._auth("refresh_token", {"refresh_token": self.session["refresh_token"]})

    def logout(self) -> None:
        if self.session.get("access_token"):
            try:
                self.http.post(f"{self.url}/auth/v1/logout", headers=self._headers(), timeout=self.timeout)
            except requests.RequestException:
                pass
        self.session = {}
        config.clear_session()

    @property
    def logged_in(self) -> bool:
        return bool(self.session.get("refresh_token"))

    def _headers(self) -> dict:
        return {"apikey": self.anon_key, "Authorization": f"Bearer {self.session['access_token']}"}

    # ---------- REST ----------
    def _rest(self, method: str, table: str, *, params: dict | None = None, json: Any = None,
              prefer: str | None = None) -> Any:
        if not self.logged_in:
            raise NotLoggedIn("Oturum yok. Önce `renkolcum giris` çalıştırın.")
        if self.session.get("expires_at", 0) - 60 < time.time():
            self.refresh()
        for attempt in (1, 2):
            headers = self._headers()
            if prefer:
                headers["Prefer"] = prefer
            r = self.http.request(method, f"{self.url}/rest/v1/{table}", params=params, json=json,
                                  headers=headers, timeout=self.timeout)
            if r.status_code == 401 and attempt == 1:
                self.refresh()
                continue
            break
        if r.status_code >= 400:
            try:
                d = r.json()
                msg = d.get("message") or d.get("msg") or r.text
            except ValueError:
                msg = r.text
            raise CloudError(f"Bulut hatası ({r.status_code}): {msg}")
        return r.json() if r.content else None

    def select(self, table: str, **params) -> list[dict]:
        params.setdefault("select", "*")
        return self._rest("GET", table, params=params)

    def insert(self, table: str, rows: dict | list[dict], *, upsert_on: str | None = None) -> list[dict]:
        params = {"on_conflict": upsert_on} if upsert_on else None
        prefer = "return=representation"
        if upsert_on:
            prefer += ",resolution=ignore-duplicates"
        return self._rest("POST", table, params=params, json=rows, prefer=prefer) or []

    def update(self, table: str, match: dict, values: dict) -> list[dict]:
        params = {k: f"eq.{v}" for k, v in match.items()}
        return self._rest("PATCH", table, params=params, json=values, prefer="return=representation")

    # ---------- Kısayollar ----------
    def me(self) -> dict | None:
        rows = self.select("profiles", id=f"eq.{self.session.get('user_id')}")
        return rows[0] if rows else None
