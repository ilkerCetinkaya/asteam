"""Tek-sabitli Kubelka-Munk modeli ve dummy boyarmadde (colorant) kütüphanesi.

K/S = (1-R)^2 / 2R          (R: 0-1 arası yansıma)
K/S_karışım = K/S_zemin + Σ c_i · k_i(λ)   (c_i: konsantrasyon, %)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .colorimetry import WAVELENGTHS


def ks_from_r(r_pct: float) -> float:
    r = min(max(r_pct / 100.0, 1e-4), 0.9999)
    return (1 - r) ** 2 / (2 * r)


def r_from_ks(ks: float) -> float:
    ks = max(ks, 0.0)
    return 100.0 * (1 + ks - math.sqrt(ks * ks + 2 * ks))


def _gauss(wl: float, center: float, width: float) -> float:
    return math.exp(-0.5 * ((wl - center) / width) ** 2)


@dataclass
class Colorant:
    code: str
    name: str
    ks: list[float] = field(repr=False)  # %1 konsantrasyon başına K/S (39 nokta)


def _make(code: str, name: str, bands: list[tuple[float, float, float]], base: float = 0.02) -> Colorant:
    ks = [base + sum(a * _gauss(w, c, s) for a, c, s in bands) for w in WAVELENGTHS]
    return Colorant(code, name, [round(v, 5) for v in ks])


# Beyaz zemin (kumaş / substrat) yansıması, %
SUBSTRATE_R = [round(60 + 29 * (1 - math.exp(-(w - 360) / 30)), 3) for w in WAVELENGTHS]
SUBSTRATE_KS = [ks_from_r(r) for r in SUBSTRATE_R]

DEFAULT_COLORANTS: list[Colorant] = [
    _make("Y01", "Sarı",       [(9.0, 430, 35)]),
    _make("O02", "Turuncu",    [(8.0, 470, 40)]),
    _make("R03", "Kırmızı",    [(9.0, 520, 35), (2.0, 420, 30)]),
    _make("V04", "Mor",        [(7.0, 560, 40)]),
    _make("B05", "Mavi",       [(9.0, 610, 45), (1.5, 450, 30)]),
    _make("G06", "Yeşil",      [(6.0, 640, 45), (6.0, 430, 30)]),
    _make("K07", "Siyah",      [(0.0, 550, 1)], base=4.0),
]


def mix_reflectance(conc: dict[str, float], colorants: dict[str, Colorant],
                    substrate_ks: list[float] = SUBSTRATE_KS) -> list[float]:
    out = []
    for i, ks0 in enumerate(substrate_ks):
        ks = ks0 + sum(c * colorants[code].ks[i] for code, c in conc.items())
        out.append(r_from_ks(ks))
    return out
