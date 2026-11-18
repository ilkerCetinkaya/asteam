"""Reçete hesaplama (renk eşleme).

Hedef yansıma eğrisine en yakın boyarmadde kombinasyonunu (1-3 bileşen)
Kubelka-Munk modeliyle bulur ve tahmini ΔE2000 değerini verir.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass

from .colorimetry import WAVELENGTHS, delta_e2000, reflectance_to_lab
from .kubelka_munk import SUBSTRATE_KS, Colorant, ks_from_r, mix_reflectance

# 400-700 nm arası (görünür bölge) eşleme için kullanılır
_IDX = [i for i, w in enumerate(WAVELENGTHS) if 400 <= w <= 700]


@dataclass
class RecipeResult:
    components: dict[str, float]          # boyarmadde kodu -> konsantrasyon (%)
    predicted_reflectance: list[float]
    predicted_lab: tuple[float, float, float]
    delta_e2000: float

    def as_rows(self, colorants: dict[str, Colorant]) -> list[dict]:
        return [{"colorant_code": k, "colorant_name": colorants[k].name if k in colorants else k,
                 "amount_pct": round(v, 4)} for k, v in sorted(self.components.items(), key=lambda kv: -kv[1])]


def _solve(A: list[list[float]], b: list[float]) -> list[float] | None:
    """Küçük doğrusal sistem: (AᵀA) x = Aᵀb, Gauss eliminasyonu."""
    n = len(A[0])
    M = [[sum(A[r][i] * A[r][j] for r in range(len(A))) for j in range(n)] for i in range(n)]
    v = [sum(A[r][i] * b[r] for r in range(len(A))) for i in range(n)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-12:
            return None
        M[col], M[piv] = M[piv], M[col]
        v[col], v[piv] = v[piv], v[col]
        for r in range(n):
            if r != col:
                f = M[r][col] / M[col][col]
                M[r] = [a - f * c for a, c in zip(M[r], M[col])]
                v[r] -= f * v[col]
    return [v[i] / M[i][i] for i in range(n)]


def _fit(codes: tuple[str, ...], target_ks: list[float], colorants: dict[str, Colorant],
         substrate_ks: list[float]) -> dict[str, float] | None:
    active = list(codes)
    while active:
        # ağırlık: K/S büyük olduğunda hassasiyet düşer -> 1/(1+K/S) ile ölçekle
        A, b = [], []
        for i in _IDX:
            w = 1.0 / (1.0 + target_ks[i])
            A.append([w * colorants[c].ks[i] for c in active])
            b.append(w * (target_ks[i] - substrate_ks[i]))
        x = _solve(A, b)
        if x is None:
            return None
        if all(v >= 0 for v in x):
            return {c: v for c, v in zip(active, x) if v > 5e-4}
        active = [c for c, v in zip(active, x) if v > 0]  # negatifleri at, tekrar çöz
    return None


def compute_recipe(target_reflectance: list[float], colorants: list[Colorant],
                   max_components: int = 3, substrate_ks: list[float] = SUBSTRATE_KS) -> RecipeResult:
    lib = {c.code: c for c in colorants}
    target_ks = [ks_from_r(r) for r in target_reflectance]
    target_lab = reflectance_to_lab(target_reflectance)

    best: RecipeResult | None = None
    if all(t <= s * 1.02 for t, s in zip(target_ks, substrate_ks)):
        pred = mix_reflectance({}, lib, substrate_ks)
        lab = reflectance_to_lab(pred)
        best = RecipeResult({}, pred, lab, delta_e2000(target_lab, lab))
    for n in range(1, max_components + 1):
        for combo in itertools.combinations(sorted(lib), n):
            conc = _fit(combo, target_ks, lib, substrate_ks)
            if conc is None:
                continue
            pred = mix_reflectance(conc, lib, substrate_ks)
            lab = reflectance_to_lab(pred)
            de = delta_e2000(target_lab, lab)
            # daha az bileşenli reçeteyi küçük bir farkla tercih et
            if best is None or de < best.delta_e2000 - 0.05:
                best = RecipeResult(conc, pred, lab, de)
    if best is None:
        raise RuntimeError("Reçete bulunamadı")
    return best
