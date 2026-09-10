"""Threshold-pressure methods, including a published-application check."""

import numpy as np
import pytest

from aorpisc import fluids, threshold
from aorpisc import units as U


# ==========================================================================
def test_method1_reproduces_published_class_vi_value():
    """a published Class VI applicant, the first injector (the upper storage formation).

    Inputs are taken verbatim from the published AoR and Corrective Action
    Plan's own input table: USDW pressure 289 psi, storage-formation fluid
    density 69.5 lb/ft3, USDW depth 1,217 ft, injection depth 5,862 ft,
    initial storage-formation pressure 1,817 psi.  The plan reports a
    threshold of 714 psi.
    """
    r = threshold.method1_thornhill(
        p_usdw=U.pressure(289, "psi"),
        p_inj=U.pressure(1817, "psi"),
        rho_inj=U.density(69.5, "lb/ft3"),
        depth_usdw=U.length(1217, "ft"),
        depth_inj=U.length(5862, "ft"))
    assert r.delta_p_psi == pytest.approx(714, abs=2)
    assert r.regime == "underpressured"
    assert r.applicable


def test_method1_second_published_value():
    """Same plan, the second injector (the lower storage formation): reported 590 psi."""
    r = threshold.method1_thornhill(
        p_usdw=U.pressure(289, "psi"),
        p_inj=U.pressure(2881, "psi"),
        rho_inj=U.density(66.8, "lb/ft3"),
        depth_usdw=U.length(1217, "ft"),
        depth_inj=U.length(8076, "ft"))
    assert r.delta_p_psi == pytest.approx(590, abs=3)


def test_mud_column_arithmetic():
    """9.0 ppg over 6,000 ft plus 10 psi gel, minus 2,481 psi initial."""
    r = threshold.method_mud_column(
        p_inj=U.pressure(2481, "psi"), depth_inj=U.length(6000, "ft"),
        mud_weight_ppg=9.0, gel_strength=U.pressure(10, "psi"))
    expected = 0.4675324675 * 6000 + 10 - 2481
    assert r.delta_p_psi == pytest.approx(expected, abs=0.5)


def test_method2_equals_half_g_delta_rho_dz():
    """EPA Eq-3 reduces to 0.5 * g * (rho_i - rho_u) * (z_u - z_i)."""
    rho_i, rho_u = 1100.0, 1000.0
    du, di = U.length(1200, "ft"), U.length(6000, "ft")
    r = threshold.method2_nicot_uniform(rho_i, rho_u, du, di)
    expected = 0.5 * U.G * (rho_i - rho_u) * (di - du)
    assert r.delta_p_critical == pytest.approx(expected, rel=1e-12)


def test_variable_density_column_reduces_to_method2():
    """With a constant lifted-column density, Method 2b must equal Method 2.

    Method 2 assumes the borehole ends up uniformly filled with injection-zone
    fluid; feeding Method 2b that same constant density has to reproduce it.
    """
    rho_i, rho_u = 1100.0, 1000.0
    du, di = U.length(1200, "ft"), U.length(6000, "ft")
    # hydrostatic case: P_i is the initial linear column below P_u
    p_u = U.pressure(520, "psi")
    p_i = p_u + U.G * 0.5 * (rho_i + rho_u) * (di - du)

    m2 = threshold.method2_nicot_uniform(rho_i, rho_u, du, di, p_i, p_u)
    m2b = threshold.method_variable_density_column(
        p_i, p_u, du, di, lambda d, p: np.full_like(np.asarray(d, float), rho_i))
    assert m2b.delta_p_critical == pytest.approx(m2.delta_p_critical, rel=1e-6)


def test_regime_classification():
    du, di = U.length(1200, "ft"), U.length(6000, "ft")
    rho = 1050.0
    p_u = U.pressure(520, "psi")
    hydro = p_u + rho * U.G * (di - du)
    assert threshold.classify_regime(p_u, hydro, rho, du, di)[0] == "hydrostatic"
    assert threshold.classify_regime(p_u, hydro - U.pressure(300, "psi"),
                                     rho, du, di)[0] == "underpressured"
    assert threshold.classify_regime(p_u, hydro + U.pressure(300, "psi"),
                                     rho, du, di)[0] == "overpressured"


def test_method2_flagged_not_applicable_when_underpressured():
    du, di = U.length(1200, "ft"), U.length(6000, "ft")
    rho_i, rho_u = 1100.0, 1000.0
    p_u = U.pressure(520, "psi")
    p_i = p_u + U.G * rho_i * (di - du) - U.pressure(600, "psi")
    r = threshold.method2_nicot_uniform(rho_i, rho_u, du, di, p_i, p_u)
    assert not r.applicable
    assert any("hydrostatic" in w for w in r.warnings)


def test_overpressured_path_flags_itself():
    du, di = U.length(1200, "ft"), U.length(6000, "ft")
    rho_i, rho_u = 1100.0, 1000.0
    p_u = U.pressure(520, "psi")
    p_i = p_u + U.G * rho_i * (di - du) + U.pressure(2000, "psi")
    r = threshold.overpressured_allowance(p_u, p_i, rho_i, rho_u, du, di)
    assert r.regime == "overpressured"
    assert not r.applicable            # 2,000 psi over-pressure swamps the offset
    assert any("numerical" in w for w in r.warnings)


def test_recommended_picks_smallest_applicable():
    res = threshold.compare_methods(
        p_usdw=U.pressure(289, "psi"), p_inj=U.pressure(1817, "psi"),
        depth_usdw=U.length(1217, "ft"), depth_inj=U.length(5862, "ft"),
        temperature_inj=U.temperature(140, "F"),
        temperature_usdw=U.temperature(80, "F"),
        salinity_inj=fluids.salinity_to_mass_fraction(80000, "ppm"))
    best = threshold.recommended(res)
    applicable = [r for r in res if r.applicable and r.delta_p_critical > 0]
    assert best.delta_p_critical == min(r.delta_p_critical for r in applicable)


def test_smaller_threshold_is_the_protective_one():
    """A smaller allowable increase must produce a larger pressure front."""
    from aorpisc.analytical import AquiferModel
    from aorpisc.analytical.pressure import radius_of_investigation

    fs = fluids.evaluate(U.pressure(2500, "psi"), U.temperature(140, "F"), 0.06)
    m = AquiferModel(U.permeability(100, "mD"), U.length(150, "ft"), 0.2,
                     U.compressibility(6e-6, "1/psi"), fs.mu_brine, fs.mu_co2,
                     fs.rho_co2, U.pressure(2500, "psi"))
    q = U.mass_rate(1.0, "MMT/yr") / fs.rho_co2
    t = U.time(20, "yr")
    r_small = radius_of_investigation(m, t, U.pressure(100, "psi"), q)
    r_large = radius_of_investigation(m, t, U.pressure(500, "psi"), q)
    assert r_small > r_large
