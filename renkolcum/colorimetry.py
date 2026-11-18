"""Kolorimetri: yansıma (%) -> XYZ -> CIELAB, LCh, ΔE*ab ve ΔE2000.

Spektral aralık: 360–740 nm, 10 nm adım (39 nokta).
Aydınlatıcı D65, CIE 1964 10° standart gözlemci.
"""
from __future__ import annotations

import math
from typing import Sequence

WAVELENGTHS: list[int] = list(range(360, 750, 10))
N_POINTS = len(WAVELENGTHS)  # 39

# (nm, D65 SPD, x̄10, ȳ10, z̄10)
_TABLE = [
    (360, 46.6383, 0.000000, 0.000000, 0.000001),
    (370, 52.0891, 0.000006, 0.000001, 0.000026),
    (380, 49.9755, 0.000160, 0.000017, 0.000705),
    (390, 54.6482, 0.002362, 0.000253, 0.010482),
    (400, 82.7549, 0.019110, 0.002004, 0.086011),
    (410, 91.4860, 0.084736, 0.008756, 0.389366),
    (420, 93.4318, 0.204492, 0.021391, 0.972542),
    (430, 86.6823, 0.314679, 0.038676, 1.553480),
    (440, 104.8650, 0.383734, 0.062077, 1.967280),
    (450, 117.0080, 0.370702, 0.089456, 1.994800),
    (460, 117.8120, 0.302273, 0.128201, 1.745370),
    (470, 114.8610, 0.195618, 0.185190, 1.317560),
    (480, 115.9230, 0.080507, 0.253589, 0.772125),
    (490, 108.8110, 0.016172, 0.339133, 0.415254),
    (500, 109.3540, 0.003816, 0.460777, 0.218502),
    (510, 107.8020, 0.037465, 0.606741, 0.112044),
    (520, 104.7900, 0.117749, 0.761757, 0.060709),
    (530, 107.6890, 0.236491, 0.875211, 0.030451),
    (540, 104.4050, 0.376772, 0.961988, 0.013676),
    (550, 104.0460, 0.529826, 0.991761, 0.003988),
    (560, 100.0000, 0.705224, 0.997340, 0.000000),
    (570, 96.3342, 0.878655, 0.955552, 0.000000),
    (580, 95.7880, 1.014160, 0.868934, 0.000000),
    (590, 88.6856, 1.118520, 0.777405, 0.000000),
    (600, 90.0062, 1.123990, 0.658341, 0.000000),
    (610, 89.5991, 1.030480, 0.527963, 0.000000),
    (620, 87.6987, 0.856297, 0.398057, 0.000000),
    (630, 83.2886, 0.647467, 0.283493, 0.000000),
    (640, 83.6992, 0.431567, 0.179828, 0.000000),
    (650, 80.0268, 0.268329, 0.107633, 0.000000),
    (660, 80.2146, 0.152568, 0.060281, 0.000000),
    (670, 82.2778, 0.081261, 0.031800, 0.000000),
    (680, 78.2842, 0.040851, 0.015905, 0.000000),
    (690, 69.7213, 0.019941, 0.007749, 0.000000),
    (700, 71.6091, 0.009577, 0.003718, 0.000000),
    (710, 74.3490, 0.004553, 0.001768, 0.000000),
    (720, 61.6040, 0.002175, 0.000846, 0.000000),
    (730, 69.8856, 0.001045, 0.000407, 0.000000),
    (740, 75.0870, 0.000508, 0.000199, 0.000000),
]

_K = 100.0 / sum(s * y for _, s, _, y, _ in _TABLE)
_WX = [_K * s * x for _, s, x, _, _ in _TABLE]
_WY = [_K * s * y for _, s, _, y, _ in _TABLE]
_WZ = [_K * s * z for _, s, _, _, z in _TABLE]
WHITE_XYZ = (sum(_WX), sum(_WY), sum(_WZ))  # R=%100 için (Y=100)


def validate_reflectance(refl: Sequence[float]) -> list[float]:
    if len(refl) != N_POINTS:
        raise ValueError(f"Yansıma verisi {N_POINTS} nokta olmalı (360-740 nm, 10 nm); gelen: {len(refl)}")
    out = [float(v) for v in refl]
    for v in out:
        if math.isnan(v) or v < 0 or v > 200:
            raise ValueError(f"Geçersiz yansıma değeri: {v}")
    return out


def reflectance_to_xyz(refl_pct: Sequence[float]) -> tuple[float, float, float]:
    r = validate_reflectance(refl_pct)
    f = [v / 100.0 for v in r]
    return (
        sum(w * v for w, v in zip(_WX, f)),
        sum(w * v for w, v in zip(_WY, f)),
        sum(w * v for w, v in zip(_WZ, f)),
    )


def xyz_to_lab(xyz: Sequence[float], white: Sequence[float] = WHITE_XYZ) -> tuple[float, float, float]:
    def f(t: float) -> float:
        d = 6 / 29
        return t ** (1 / 3) if t > d ** 3 else t / (3 * d * d) + 4 / 29

    fx, fy, fz = (f(c / w) for c, w in zip(xyz, white))
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def lab_to_lch(lab: Sequence[float]) -> tuple[float, float, float]:
    L, a, b = lab
    h = math.degrees(math.atan2(b, a)) % 360
    return L, math.hypot(a, b), h


def reflectance_to_lab(refl_pct: Sequence[float]) -> tuple[float, float, float]:
    return xyz_to_lab(reflectance_to_xyz(refl_pct))


def delta_e76(lab1: Sequence[float], lab2: Sequence[float]) -> float:
    return math.dist(lab1, lab2)


def delta_e2000(lab1: Sequence[float], lab2: Sequence[float], kL=1.0, kC=1.0, kH=1.0) -> float:
    """CIEDE2000 (Sharma, Wu, Dalal 2005)."""
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2
    C1, C2 = math.hypot(a1, b1), math.hypot(a2, b2)
    Cbar = (C1 + C2) / 2
    G = 0.5 * (1 - math.sqrt(Cbar ** 7 / (Cbar ** 7 + 25 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360 if C1p else 0.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360 if C2p else 0.0

    dLp = L2 - L1
    dCp = C2p - C1p
    if C1p * C2p == 0:
        dhp = 0.0
    else:
        dhp = h2p - h1p
        if dhp > 180:
            dhp -= 360
        elif dhp < -180:
            dhp += 360
    dHp = 2 * math.sqrt(C1p * C2p) * math.sin(math.radians(dhp / 2))

    Lbp = (L1 + L2) / 2
    Cbp = (C1p + C2p) / 2
    if C1p * C2p == 0:
        hbp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hbp = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        hbp = (h1p + h2p + 360) / 2
    else:
        hbp = (h1p + h2p - 360) / 2

    T = (1 - 0.17 * math.cos(math.radians(hbp - 30)) + 0.24 * math.cos(math.radians(2 * hbp))
         + 0.32 * math.cos(math.radians(3 * hbp + 6)) - 0.20 * math.cos(math.radians(4 * hbp - 63)))
    dtheta = 30 * math.exp(-(((hbp - 275) / 25) ** 2))
    Rc = 2 * math.sqrt(Cbp ** 7 / (Cbp ** 7 + 25 ** 7))
    Sl = 1 + 0.015 * (Lbp - 50) ** 2 / math.sqrt(20 + (Lbp - 50) ** 2)
    Sc = 1 + 0.045 * Cbp
    Sh = 1 + 0.015 * Cbp * T
    Rt = -math.sin(math.radians(2 * dtheta)) * Rc
    return math.sqrt((dLp / (kL * Sl)) ** 2 + (dCp / (kC * Sc)) ** 2 + (dHp / (kH * Sh)) ** 2
                     + Rt * (dCp / (kC * Sc)) * (dHp / (kH * Sh)))


def lab_to_srgb(lab: Sequence[float]) -> tuple[int, int, int]:
    """Ekran önizlemesi için yaklaşık sRGB (0-255)."""
    L, a, b = lab
    fy = (L + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200

    def finv(t: float) -> float:
        return t ** 3 if t > 6 / 29 else 3 * (6 / 29) ** 2 * (t - 4 / 29)

    X = finv(fx) * 0.95047
    Y = finv(fy)
    Z = finv(fz) * 1.08883
    rl = 3.2406 * X - 1.5372 * Y - 0.4986 * Z
    gl = -0.9689 * X + 1.8758 * Y + 0.0415 * Z
    bl = 0.0557 * X - 0.2040 * Y + 1.0570 * Z

    def gamma(c: float) -> int:
        c = min(max(c, 0.0), 1.0)
        c = 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
        return round(c * 255)

    return gamma(rl), gamma(gl), gamma(bl)
