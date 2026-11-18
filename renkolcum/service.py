"""Uygulama mantığı: ölçümü işle, yerelde sakla, buluta senkronla, reçete hesapla."""
from __future__ import annotations

import uuid

import requests

from .cloud import CloudError, NotLoggedIn, SupabaseClient
from .colorimetry import WAVELENGTHS, delta_e2000, reflectance_to_lab
from .kubelka_munk import DEFAULT_COLORANTS, Colorant
from .recipe import RecipeResult, compute_recipe
from .spectro import Reading
from .store import LocalStore


class RenkOlcumService:
    def __init__(self, store: LocalStore, cloud: SupabaseClient | None):
        self.store = store
        self.cloud = cloud

    # ---------- bulut durumu ----------
    def cloud_ready(self) -> bool:
        return self.cloud is not None and self.cloud.logged_in

    # ---------- standartlar / boyarmaddeler ----------
    def standards(self, refresh: bool = True) -> list[dict]:
        if refresh and self.cloud_ready():
            try:
                rows = self.cloud.select("standards", order="name.asc")
                self.store.cache_put("standards", rows)
                return rows
            except (CloudError, requests.RequestException):
                pass
        return self.store.cache_get("standards")

    def find_standard(self, key: str) -> dict | None:
        key_l = key.lower()
        for s in self.standards():
            if str(s["id"]).startswith(key) or s["name"].lower() == key_l or s["name"].lower().startswith(key_l):
                return s
        return None

    def colorants(self) -> list[Colorant]:
        if self.cloud_ready():
            try:
                rows = self.cloud.select("colorants", active="eq.true", order="code.asc")
                self.store.cache_put("colorants", rows)
            except (CloudError, requests.RequestException):
                rows = self.store.cache_get("colorants")
        else:
            rows = self.store.cache_get("colorants")
        return [Colorant(r["code"], r["name"], list(r["ks"])) for r in rows] or list(DEFAULT_COLORANTS)

    # ---------- ölçüm ----------
    def record_measurement(self, reading: Reading, sample_name: str, standard: dict | None = None) -> dict:
        L, a, b = reflectance_to_lab(reading.reflectance)
        payload = {
            "client_uuid": str(uuid.uuid4()),
            "sample_name": sample_name,
            "reflectance": reading.reflectance,
            "wl_start": WAVELENGTHS[0],
            "wl_step": WAVELENGTHS[1] - WAVELENGTHS[0],
            "l_star": round(L, 4), "a_star": round(a, 4), "b_star": round(b, 4),
            "instrument_serial": reading.instrument_serial,
            "instrument_model": reading.instrument_model,
            "measured_at": reading.measured_at,
            "meta": {k: v for k, v in reading.meta.items() if v is not None},
        }
        if standard:
            de = delta_e2000((standard["l_star"], standard["a_star"], standard["b_star"]), (L, a, b))
            payload |= {"standard_id": standard["id"], "delta_e2000": round(de, 4),
                        "pass_fail": "GEÇTİ" if de <= standard.get("tolerance_de", 1.0) else "KALDI"}
        self.store.enqueue("measurement", payload["client_uuid"], payload)
        return payload

    # ---------- reçete ----------
    def make_recipe(self, measurement: dict) -> RecipeResult:
        return compute_recipe(measurement["reflectance"], self.colorants())

    def record_recipe(self, measurement_entry: dict, result: RecipeResult, name: str | None = None) -> dict:
        m = measurement_entry["payload"]
        cols = {c.code: c for c in self.colorants()}
        payload = {
            "client_uuid": str(uuid.uuid4()),
            "name": name or f"Reçete - {m['sample_name']}",
            "measurement_client_uuid": m["client_uuid"],
            "standard_id": m.get("standard_id"),
            "components": result.as_rows(cols),
            "predicted_l": round(result.predicted_lab[0], 4),
            "predicted_a": round(result.predicted_lab[1], 4),
            "predicted_b": round(result.predicted_lab[2], 4),
            "predicted_de": round(result.delta_e2000, 4),
        }
        self.store.enqueue("recipe", payload["client_uuid"], payload)
        return payload

    # ---------- senkronizasyon ----------
    def sync(self) -> dict:
        """Bekleyen kayıtları buluta gönderir. Dönen: {'gonderilen': n, 'hata': n, 'bekleyen': n}"""
        res = {"gonderilen": 0, "hata": 0, "bekleyen": len(self.store.pending())}
        if not self.cloud_ready():
            return res
        for kind, table in (("measurement", "measurements"), ("recipe", "recipes")):
            for item in self.store.pending(kind):
                body = dict(item["payload"])
                try:
                    if kind == "recipe":
                        mcu = body.pop("measurement_client_uuid", None)
                        if mcu:
                            m = self.store.get(mcu)
                            if not m or not m["cloud_id"]:
                                continue  # önce ölçüm gitmeli
                            body["measurement_id"] = m["cloud_id"]
                    rows = self.cloud.insert(table, body, upsert_on="client_uuid")
                    if not rows:  # daha önce gönderilmiş (çift kayıt engellendi)
                        rows = self.cloud.select(table, client_uuid=f"eq.{body['client_uuid']}", select="id")
                    self.store.mark_synced(item["client_uuid"], rows[0]["id"] if rows else None)
                    res["gonderilen"] += 1
                except requests.RequestException as e:  # ağ yok -> sonra tekrar dene
                    self.store.mark_error(item["client_uuid"], f"ağ: {e.__class__.__name__}")
                    res["hata"] += 1
                    res["bekleyen"] = len(self.store.pending())
                    return res
                except NotLoggedIn:
                    raise
                except CloudError as e:
                    self.store.mark_error(item["client_uuid"], str(e))
                    res["hata"] += 1
        res["bekleyen"] = len(self.store.pending())
        return res
