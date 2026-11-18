"""Spektrofotometre sürücü katmanı (dummy).

Gerçek cihaz yerine `SimulatedSpectrophotometer` kullanılır. Ölçümler
360-740 nm, 10 nm aralıklarla % yansıma verisi döndürür (39 nokta).
`parse_device_csv` ise cihazın klasöre bıraktığı dışa aktarma dosyalarını okur
(`renkolcum izle` komutu bu dosyaları otomatik algılar).
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import random
from dataclasses import dataclass, field

from .colorimetry import N_POINTS, WAVELENGTHS, validate_reflectance
from .kubelka_munk import DEFAULT_COLORANTS, mix_reflectance

_COLORANTS = {c.code: c for c in DEFAULT_COLORANTS}

# Simülatörde "ölçülebilecek" hazır numuneler (gizli reçeteleriyle)
SAMPLE_LIBRARY: dict[str, dict[str, float]] = {
    "beyaz": {},
    "kirmizi": {"R03": 1.8, "Y01": 0.3},
    "bordo": {"R03": 2.5, "B05": 0.4, "K07": 0.05},
    "turuncu": {"O02": 1.5, "Y01": 0.6},
    "sari": {"Y01": 1.2},
    "yesil": {"G06": 1.0, "Y01": 0.4},
    "mavi": {"B05": 1.4, "V04": 0.2},
    "lacivert": {"B05": 3.0, "V04": 0.6, "K07": 0.1},
    "mor": {"V04": 1.5, "R03": 0.3},
    "gri": {"K07": 0.08},
    "bej": {"Y01": 0.15, "O02": 0.08, "K07": 0.01},
}


@dataclass
class Reading:
    reflectance: list[float]
    instrument_serial: str
    instrument_model: str
    measured_at: str
    meta: dict = field(default_factory=dict)


class SimulatedSpectrophotometer:
    model = "ArgeSpec-600 (Simülatör)"
    aperture = "LAV 25mm"
    geometry = "d/8° SCI"

    def __init__(self, serial: str = "SIM-0001", noise_pct: float = 0.08, seed: int | None = None):
        self.serial = serial
        self.noise_pct = noise_pct
        self.rng = random.Random(seed)
        self.calibrated = False

    def detect(self) -> dict:
        return {"serial": self.serial, "model": self.model, "geometry": self.geometry,
                "aperture": self.aperture, "range": f"{WAVELENGTHS[0]}-{WAVELENGTHS[-1]} nm / 10 nm"}

    def calibrate(self) -> None:
        """Beyaz/siyah kalibrasyon (simüle)."""
        self.calibrated = True

    def measure(self, sample: str | None = None, recipe: dict[str, float] | None = None) -> Reading:
        if not self.calibrated:
            self.calibrate()
        if recipe is None:
            if sample is None:
                sample = self.rng.choice([k for k in SAMPLE_LIBRARY if k != "beyaz"])
                base = dict(SAMPLE_LIBRARY[sample])
                # her numune biraz farklı boyanmış olsun
                recipe = {k: v * self.rng.uniform(0.85, 1.15) for k, v in base.items()}
            else:
                if sample not in SAMPLE_LIBRARY:
                    raise ValueError(f"Bilinmeyen numune: {sample}. Seçenekler: {', '.join(SAMPLE_LIBRARY)}")
                recipe = SAMPLE_LIBRARY[sample]
        refl = mix_reflectance(recipe, _COLORANTS)
        refl = [round(min(max(r + self.rng.gauss(0, self.noise_pct), 0.0), 100.0), 3) for r in refl]
        return Reading(
            reflectance=refl,
            instrument_serial=self.serial,
            instrument_model=self.model,
            measured_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            meta={"sample_hint": sample, "geometry": self.geometry, "aperture": self.aperture},
        )


def to_device_csv(reading: Reading, sample_name: str) -> str:
    buf = io.StringIO()
    buf.write(f"# Numune: {sample_name}\n# Cihaz: {reading.instrument_model} {reading.instrument_serial}\n")
    buf.write(f"# Tarih: {reading.measured_at}\n")
    w = csv.writer(buf)
    w.writerow(["nm", "R%"])
    for nm, r in zip(WAVELENGTHS, reading.reflectance):
        w.writerow([nm, f"{r:.3f}"])
    return buf.getvalue()


def parse_device_csv(text: str) -> tuple[str | None, Reading]:
    """Cihaz CSV'sini okur. Satırlar: `nm,R%` (yorumlar # ile)."""
    name = serial = model = when = None
    values: dict[int, float] = {}
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            key, _, val = s[1:].partition(":")
            key, val = key.strip().lower(), val.strip()
            if key == "numune":
                name = val
            elif key == "cihaz":
                model, _, serial = val.rpartition(" ")
            elif key == "tarih":
                when = val
            continue
        parts = [p.strip() for p in s.replace(";", ",").split(",")]
        try:
            nm, r = int(float(parts[0])), float(parts[1].replace("%", ""))
        except (ValueError, IndexError):
            continue  # başlık satırı
        values[nm] = r
    missing = [w for w in WAVELENGTHS if w not in values]
    if missing:
        raise ValueError(f"CSV'de eksik dalga boyları: {missing[:5]}... ({len(missing)} adet)")
    refl = validate_reflectance([values[w] for w in WAVELENGTHS])
    assert len(refl) == N_POINTS
    return name, Reading(
        reflectance=refl,
        instrument_serial=serial or "BILINMIYOR",
        instrument_model=model or "Harici cihaz",
        measured_at=when or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    )
