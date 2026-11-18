"""supabase/seed.sql dosyasını üretir (boyarmadde kütüphanesi + örnek standartlar).

Kullanım: python scripts/gen_seed.py > supabase/seed.sql
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from renkolcum.colorimetry import reflectance_to_lab  # noqa: E402
from renkolcum.kubelka_munk import DEFAULT_COLORANTS  # noqa: E402
from renkolcum.spectro import SimulatedSpectrophotometer  # noqa: E402


def arr(v):
    return "'{" + ",".join(f"{x:g}" for x in v) + "}'"


print("-- Otomatik üretildi: python scripts/gen_seed.py > supabase/seed.sql")
print("-- Boyarmadde kütüphanesi (dummy K/S verileri, %1 konsantrasyon başına)")
for c in DEFAULT_COLORANTS:
    print(f"insert into public.colorants (code, name, ks, created_by) values ('{c.code}', '{c.name}', {arr(c.ks)}, null)"
          " on conflict (code) do update set name = excluded.name, ks = excluded.ks;")

print("\n-- Örnek müşteri renk standartları")
dev = SimulatedSpectrophotometer(noise_pct=0, seed=0)
for name, customer, sample in [("STD-001 Kırmızı", "ABC Konfeksiyon", "kirmizi"),
                               ("STD-002 Lacivert", "ABC Konfeksiyon", "lacivert"),
                               ("STD-003 Bej", "XYZ Home", "bej")]:
    r = dev.measure(sample).reflectance
    L, a, b = reflectance_to_lab(r)
    print(f"insert into public.standards (name, customer, reflectance, l_star, a_star, b_star, created_by) "
          f"select '{name}', '{customer}', {arr(r)}, {L:.3f}, {a:.3f}, {b:.3f}, null "
          f"where not exists (select 1 from public.standards where name = '{name}');")
