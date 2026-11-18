import pytest

from renkolcum.colorimetry import (N_POINTS, WAVELENGTHS, delta_e2000, lab_to_srgb, reflectance_to_lab,
                                   validate_reflectance)


def test_wavelength_grid():
    assert WAVELENGTHS[0] == 360 and WAVELENGTHS[-1] == 740 and N_POINTS == 39


def test_perfect_white_and_black():
    L, a, b = reflectance_to_lab([100.0] * 39)
    assert L == pytest.approx(100, abs=1e-9) and abs(a) < 1e-9 and abs(b) < 1e-9
    assert reflectance_to_lab([0.0] * 39)[0] == pytest.approx(0, abs=1e-9)


def test_neutral_grey_is_neutral():
    L, a, b = reflectance_to_lab([18.0] * 39)
    assert L == pytest.approx(49.5, abs=0.1) and abs(a) < 1e-6 and abs(b) < 1e-6


# Sharma, Wu & Dalal (2005) test verisi
@pytest.mark.parametrize("lab1,lab2,expected", [
    ((50, 2.6772, -79.7751), (50, 0, -82.7485), 2.0425),
    ((50, 0, 0), (50, -1, 2), 2.3669),
    ((50, 2.5, 0), (73, 25, -18), 27.1492),
    ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
    ((22.7233, 20.0904, -46.694), (23.0331, 14.973, -42.5619), 2.0373),
    ((50, -0.001, 2.49), (50, 0.0011, -2.49), 4.7461),
])
def test_ciede2000(lab1, lab2, expected):
    assert delta_e2000(lab1, lab2) == pytest.approx(expected, abs=1e-4)
    assert delta_e2000(lab2, lab1) == pytest.approx(expected, abs=1e-4)


def test_validation():
    with pytest.raises(ValueError):
        validate_reflectance([50.0] * 38)
    with pytest.raises(ValueError):
        validate_reflectance([50.0] * 38 + [-1.0])


def test_srgb_white():
    assert lab_to_srgb((100, 0, 0)) == (255, 255, 255)
