"""web/demo-data.js dosyasını üretir (portalın Demo modu için örnek veri)."""
import datetime as dt
import json
import random
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from renkolcum.colorimetry import delta_e2000, reflectance_to_lab  # noqa: E402
from renkolcum.kubelka_munk import DEFAULT_COLORANTS  # noqa: E402
from renkolcum.recipe import compute_recipe  # noqa: E402
from renkolcum.spectro import SimulatedSpectrophotometer  # noqa: E402

rnd = random.Random(7)
users = [
    {"id": str(uuid.UUID(int=i + 1)), "email": e, "full_name": n, "role": r,
     "created_at": "2026-11-01T09:00:00Z"}
    for i, (e, n, r) in enumerate([
        ("ayse@demo.local", "Ayşe Yılmaz", "admin"), ("mehmet@demo.local", "Mehmet Kaya", "operator"),
        ("zeynep@demo.local", "Zeynep Demir", "operator"), ("can@demo.local", "Can Öztürk", "operator"),
        ("elif@demo.local", "Elif Şahin", "viewer")])
]
dev = SimulatedSpectrophotometer(noise_pct=0, seed=0)
standards = []
for name, cust, sample in [("STD-001 Kırmızı", "ABC Konfeksiyon", "kirmizi"),
                           ("STD-002 Lacivert", "ABC Konfeksiyon", "lacivert"),
                           ("STD-003 Bej", "XYZ Home", "bej"), ("STD-004 Yeşil", "Örnek Tekstil", "yesil")]:
    r = dev.measure(sample).reflectance
    L, a, b = reflectance_to_lab(r)
    standards.append({"id": str(uuid.uuid4()), "name": name, "customer": cust, "reflectance": r,
                      "l_star": L, "a_star": a, "b_star": b, "tolerance_de": 1.0, "sample": sample})

measurements, recipes = [], []
t = dt.datetime(2026, 11, 18, 8, 0, tzinfo=dt.timezone.utc)
for i in range(18):
    st = rnd.choice(standards)
    u = rnd.choice(users[:4])
    d = SimulatedSpectrophotometer(serial=f"SIM-000{rnd.randint(1, 3)}", seed=i)
    base = {"kirmizi": {"R03": 1.8, "Y01": 0.3}, "lacivert": {"B05": 3.0, "V04": 0.6, "K07": 0.1},
            "bej": {"Y01": 0.15, "O02": 0.08, "K07": 0.01}, "yesil": {"G06": 1.0, "Y01": 0.4}}[st["sample"]]
    rd = d.measure(recipe={k: v * rnd.uniform(0.84, 1.17) for k, v in base.items()})
    L, a, b = reflectance_to_lab(rd.reflectance)
    de = delta_e2000((st["l_star"], st["a_star"], st["b_star"]), (L, a, b))
    t += dt.timedelta(minutes=rnd.randint(7, 40))
    m = {"id": str(uuid.uuid4()), "sample_name": f"Parti {2400 + i} - {st['name'].split(' ', 1)[1]}",
         "reflectance": rd.reflectance, "l_star": L, "a_star": a, "b_star": b, "standard_id": st["id"],
         "standard_name": st["name"], "delta_e2000": de, "pass_fail": "GEÇTİ" if de <= 1 else "KALDI",
         "instrument_serial": rd.instrument_serial, "instrument_model": rd.instrument_model,
         "measured_at": t.isoformat(), "measured_by": u["id"], "measured_by_name": u["full_name"]}
    measurements.append(m)
    if m["pass_fail"] == "KALDI" or i % 5 == 0:
        res = compute_recipe(st["reflectance"], DEFAULT_COLORANTS)
        cols = {c.code: c for c in DEFAULT_COLORANTS}
        recipes.append({"id": str(uuid.uuid4()), "name": f"Reçete {st['name']}", "measurement_id": m["id"],
                        "sample_name": m["sample_name"], "standard_id": st["id"], "standard_name": st["name"],
                        "components": res.as_rows(cols), "predicted_l": res.predicted_lab[0],
                        "predicted_a": res.predicted_lab[1], "predicted_b": res.predicted_lab[2],
                        "predicted_de": res.delta_e2000, "status": rnd.choice(["taslak", "onaylı"]),
                        "version": 1, "created_by": u["id"], "created_by_name": u["full_name"],
                        "created_at": t.isoformat()})
for s in standards:
    s.pop("sample")
measurements.reverse()
recipes.reverse()
data = {"settings": {"company": "Demo Tekstil A.Ş.", "max_users": 10}, "profiles": users,
        "standards": standards, "measurements": measurements, "recipes": recipes}
(ROOT / "web/demo-data.js").write_text(
    "// Otomatik üretildi: python scripts/gen_web_demo.py\nwindow.RENKOLCUM_DEMO = "
    + json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=float) + ";\n", "utf-8")
print("web/demo-data.js yazıldı")
