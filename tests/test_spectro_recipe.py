import pytest

from renkolcum.colorimetry import delta_e2000, reflectance_to_lab
from renkolcum.kubelka_munk import DEFAULT_COLORANTS
from renkolcum.recipe import compute_recipe
from renkolcum.spectro import SAMPLE_LIBRARY, SimulatedSpectrophotometer, parse_device_csv, to_device_csv


def test_measurement_shape():
    r = SimulatedSpectrophotometer(seed=1).measure("mavi")
    assert len(r.reflectance) == 39
    assert all(0 <= v <= 100 for v in r.reflectance)


def test_repeatability_small_noise():
    dev = SimulatedSpectrophotometer(seed=2)
    a = reflectance_to_lab(dev.measure("kirmizi").reflectance)
    b = reflectance_to_lab(dev.measure("kirmizi").reflectance)
    assert delta_e2000(a, b) < 0.3  # cihaz tekrarlanabilirliği


def test_csv_roundtrip():
    dev = SimulatedSpectrophotometer(seed=3)
    r = dev.measure("yesil")
    name, back = parse_device_csv(to_device_csv(r, "Yeşil-42"))
    assert name == "Yeşil-42"
    assert back.instrument_serial == "SIM-0001"
    assert back.reflectance == pytest.approx(r.reflectance, abs=1e-3)


def test_csv_semicolon_and_missing():
    text = "nm;R%\n" + "\n".join(f"{w};{50}" for w in range(360, 750, 10))
    _, r = parse_device_csv(text)
    assert r.reflectance == [50.0] * 39
    with pytest.raises(ValueError):
        parse_device_csv("nm,R%\n360,50\n")


@pytest.mark.parametrize("sample", [s for s in SAMPLE_LIBRARY])
def test_recipe_recovers_hidden_formula(sample):
    dev = SimulatedSpectrophotometer(seed=4, noise_pct=0.05)
    reading = dev.measure(sample)
    res = compute_recipe(reading.reflectance, DEFAULT_COLORANTS)
    assert res.delta_e2000 < 0.3
    hidden = SAMPLE_LIBRARY[sample]
    for code, c in hidden.items():
        assert res.components.get(code, 0) == pytest.approx(c, rel=0.15, abs=0.01)
