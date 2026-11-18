"""Test .mdb dosyalarını üretir (Java + Jackcess gerekir; üretilen dosyalar repoda hazır durur).

Kullanım: python tests/mdb/olustur.py <jackcess-jar-klasoru>
Jar'lar: jackcess-4.0.5, commons-lang3-3.14.0, commons-logging-1.3.0 (Maven Central)
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from renkolcum.colorimetry import reflectance_to_lab  # noqa: E402
from renkolcum.spectro import SimulatedSpectrophotometer  # noqa: E402

JARS = sys.argv[1]
dev = SimulatedSpectrophotometer(seed=42, noise_pct=0)


def row(i, name, sample, std="", lab_override=None, spectrum=True, when=None):
    r = dev.measure(sample).reflectance
    L, a, b = lab_override or reflectance_to_lab(r)
    return "\t".join([str(i), name, when or f"2026-11-18 09:{i:02d}:00", "AHMET", f"{L:.2f}", f"{a:.2f}", f"{b:.2f}",
                      "0.42", std, ",".join(map(str, r)) if spectrum else ""])


def make(out, mode, rows):
    p = HERE / out
    p.unlink(missing_ok=True)
    subprocess.run(["java", "-cp", f"{JARS}/*", str(HERE / "MdbOlustur.java"), str(p), mode],
                   input="\n".join(rows) + "\n", text=True, check=True)
    print("yazıldı:", p.name, p.stat().st_size)


r1 = row(1, "Parti 2401 Kırmızı", "kirmizi", "STD-001 Kırmızı")
r2 = row(2, "Parti 2402 Lacivert", "lacivert", "STD-002 Lacivert")
r3 = row(3, "Parti 2403 Bej", "bej", "STANDART-YOK")
r1_changed = row(1, "Parti 2401 Kırmızı (düzeltildi)", "kirmizi", "STD-001 Kırmızı")
r4_broken = row(4, "Spektrumsuz kayıt", "gri", spectrum=False)

make("genis_v1.mdb", "genis", [r1, r2])                       # uygulama ilk 2 ölçümü yazdı
make("genis_v2.mdb", "genis", [r1_changed, r2, r3, r4_broken])  # sonra 1. satırı düzeltti, 2 satır ekledi
make("tek_olcum_a.mdb", "uzun", [row(1, "Tekli A", "yesil")])  # her ölçüm ayrı dosya, ikisinde de OLCUM_NO=1
make("tek_olcum_b.mdb", "uzun", [row(1, "Tekli B", "mor")])
