"""Unit conversions and PVT correlations."""


import numpy as np
import pytest

from containment import fluids
from containment import units as U


# ==========================================================================
@pytest.mark.parametrize("value,unit,to_si,back", [
    (1.0, "ft", U.length, U.length_out),
    (5000.0, "psi", U.pressure, U.pressure_out),
    (100.0, "mD", U.permeability, U.permeability_out),
    (0.5, "cP", U.viscosity, U.viscosity_out),
    (30.0, "yr", U.time, U.time_out),
    (2.5, "MMT", U.mass, U.mass_out),
    (640.0, "acres", U.area, U.area_out),
    (62.4, "lb/ft3", U.density, U.density_out),
])
def test_round_trip(value, unit, to_si, back):
    assert back(to_si(value, unit), unit) == pytest.approx(value, rel=1e-12)


def test_known_conversions():
    assert U.length(1.0, "mi") == pytest.approx(5280 * U.FT, rel=1e-12)
    assert U.pressure(14.6959488, "psi") == pytest.approx(101325.0, rel=1e-6)
    assert U.area(1.0, "mi2") == pytest.approx(640 * U.ACRE, rel=1e-9)
    assert U.temperature(32.0, "F") == pytest.approx(273.15)
    assert U.temperature(212.0, "F") == pytest.approx(373.15)
    # 1 MMT/yr is about 2,740 tonnes/day
    assert U.mass_rate_out(U.mass_rate(1.0, "MMT/yr"), "tonne/day") == pytest.approx(
        1e6 / 365.25, rel=1e-9)


def test_mud_weight_gradient():
    """9.0 ppg is the familiar 0.468 psi/ft."""
    grad = U.ppg_to_gradient_si(9.0)
    assert U.pressure_gradient_out(grad, "psi/ft") == pytest.approx(0.4675, abs=5e-4)


def test_unknown_unit_raises():
    with pytest.raises(ValueError):
        U.length(1.0, "furlong")


# ==========================================================================
def test_co2_density_supercritical():
    """CO2 at 100 bar / 40 C is a dense supercritical fluid, ~630 kg/m3."""
    rho = fluids.co2_density(U.pressure(100, "bar"), U.temperature(40, "C"),
                             backend="builtin")
    assert 560 < rho < 700


def test_co2_density_monotonic_in_pressure():
    T = U.temperature(60, "C")
    ps = U.pressure(np.array([80, 100, 150, 200, 300.0]), "bar")
    rhos = [fluids.co2_density(float(p), T, backend="builtin") for p in ps]
    assert all(b > a for a, b in zip(rhos, rhos[1:], strict=False))


def test_co2_viscosity_reference_point():
    """Fenghour et al. (1998) at 100 bar / 40 C gives about 0.049 cP."""
    P, T = U.pressure(100, "bar"), U.temperature(40, "C")
    mu = fluids.co2_viscosity(P, T, backend="builtin")
    assert U.viscosity_out(mu, "cP") == pytest.approx(0.049, abs=0.006)


def test_co2_saturation_pressure_at_critical():
    assert fluids.co2_saturation_pressure(fluids.TC_CO2) == pytest.approx(fluids.PC_CO2)
    # 20 C saturation pressure is about 57 bar
    ps = fluids.co2_saturation_pressure(U.temperature(20, "C"))
    assert U.pressure_out(ps, "bar") == pytest.approx(57.3, abs=1.5)


@pytest.mark.skipif(not fluids.HAVE_COOLPROP, reason="CoolProp not installed")
def test_builtin_eos_tracks_coolprop():
    """The fallback EOS should stay within a few percent of Span-Wagner."""
    for p_bar, t_c in [(100, 40), (150, 60), (250, 80), (200, 50)]:
        P, T = U.pressure(p_bar, "bar"), U.temperature(t_c, "C")
        a = fluids.co2_density(P, T, backend="builtin")
        b = fluids.co2_density(P, T, backend="coolprop")
        assert abs(a - b) / b < 0.06, f"{p_bar} bar / {t_c} C: {a:.1f} vs {b:.1f}"


def test_brine_density_increases_with_salinity():
    P, T = U.pressure(2500, "psi"), U.temperature(140, "F")
    fresh = fluids.brine_density(P, T, 0.0)
    salty = fluids.brine_density(P, T, 0.15)
    assert 950 < fresh < 1010
    assert salty > fresh + 80


def test_brine_viscosity_falls_with_temperature():
    s = 0.05
    assert (fluids.brine_viscosity(U.temperature(200, "F"), s)
            < fluids.brine_viscosity(U.temperature(80, "F"), s))


def test_salinity_conversions():
    assert fluids.salinity_to_mass_fraction(50000, "ppm") == pytest.approx(0.05)
    assert fluids.salinity_to_mass_fraction(5, "wt%") == pytest.approx(0.05)
    # 1 molal NaCl is about 5.5 wt%
    assert fluids.salinity_to_mass_fraction(1.0, "molal") == pytest.approx(0.0554, abs=1e-3)


def test_fluid_state_summary_is_physical():
    fs = fluids.evaluate(U.pressure(2500, "psi"), U.temperature(140, "F"),
                         fluids.salinity_to_mass_fraction(60000, "ppm"))
    assert fs.delta_rho > 250          # buoyant CO2
    assert fs.viscosity_ratio > 5      # unfavourable mobility
    assert 1e-10 < fs.c_brine < 1e-9        # ~2-4 x 10^-6 /psi
    assert set(fs.summary()) >= {"rho_co2_kg_m3", "mu_brine_cP", "eos_backend"}
