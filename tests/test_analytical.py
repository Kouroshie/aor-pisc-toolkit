"""Analytical plume and pressure models."""

import numpy as np
import pytest
from scipy.special import exp1

from aorpisc import fluids
from aorpisc import units as U
from aorpisc.analytical import (
    AquiferModel,
    Boundary,
    BrooksCorey,
    BuckleyLeverett,
    BuckleyLeverettPlume,
    NordbottenCeliaPlume,
    PlumeInputs,
    VolumetricPlume,
    Well,
    constant_rate_well,
    endpoint_mobility_ratio,
    fractional_flow,
    radius_of_investigation,
)
from aorpisc.analytical.plume import residual_trapping_limit_radius


@pytest.fixture
def state():
    fs = fluids.evaluate(U.pressure(2500, "psi"), U.temperature(140, "F"),
                         fluids.salinity_to_mass_fraction(60000, "ppm"))
    rp = BrooksCorey(swr=0.35, sgr=0.20, krg0=0.30, m=3.0, n=3.0)
    inp = PlumeInputs(thickness=U.length(150, "ft"), porosity=0.20,
                      permeability=U.permeability(100, "mD"),
                      rho_co2=fs.rho_co2, mu_co2=fs.mu_co2,
                      rho_brine=fs.rho_brine, mu_brine=fs.mu_brine, relperm=rp)
    return fs, rp, inp


# ==========================================================================
def test_relperm_endpoints():
    rp = BrooksCorey(swr=0.3, sgr=0.2, krw0=1.0, krg0=0.4, m=3, n=3)
    assert float(rp.krw(0.0)) == pytest.approx(1.0)
    assert float(rp.krg(rp.sgr)) == pytest.approx(0.0)
    assert float(rp.krg(1.0 - rp.swr)) == pytest.approx(0.4)
    assert float(rp.krw(1.0 - rp.swr)) == pytest.approx(0.0, abs=1e-12)


def test_relperm_rejects_impossible_residuals():
    with pytest.raises(ValueError):
        BrooksCorey(swr=0.7, sgr=0.4)


def test_fractional_flow_is_monotonic_and_bounded():
    rp = BrooksCorey(swr=0.3, sgr=0.15, krg0=0.3)
    sg = np.linspace(0.0, 1.0 - rp.swr, 200)
    f = fractional_flow(sg, rp, 0.05e-3, 0.6e-3)
    assert f.min() >= 0.0 and f.max() <= 1.0
    assert np.all(np.diff(f) >= -1e-12)


def test_buckley_leverett_shock_is_a_tangent(state):
    _, rp, inp = state
    bl = BuckleyLeverett(rp, inp.mu_co2, inp.mu_brine)
    assert rp.sgr < bl.shock_saturation < 1.0 - rp.swr
    # Welge: the chord slope at the shock equals the local derivative
    from aorpisc.analytical.relperm import dfg_dsg
    local = float(dfg_dsg(np.array([bl.shock_saturation]), rp,
                          inp.mu_co2, inp.mu_brine)[0])
    assert local == pytest.approx(bl.shock_slope, rel=0.03)
    assert bl.average_saturation() > bl.shock_saturation


# ==========================================================================
def test_nordbotten_celia_conserves_volume_exactly(state):
    """The interface profile must integrate to the injected volume."""
    fs, _, inp = state
    ncb = NordbottenCeliaPlume(inp)
    m = U.mass(10, "MMT")
    vol = m / fs.rho_co2
    r = np.linspace(0.0, ncb.radius(m) * 1.0001, 400001)
    h = ncb.interface_height(r, vol)
    integ = np.trapezoid(2 * np.pi * r * inp.effective_porosity * h, r)
    assert integ / vol == pytest.approx(1.0, rel=2e-5)


def test_nordbotten_celia_is_sqrt_gamma_times_volumetric(state):
    fs, _, inp = state
    ncb = NordbottenCeliaPlume(inp)
    vol_model = VolumetricPlume(inp, average_saturation=1.0 - inp.relperm.swr)
    m = U.mass(5, "MMT")
    assert ncb.radius(m) / vol_model.radius(m) == pytest.approx(
        np.sqrt(ncb.gamma), rel=1e-9)


def test_plume_radius_ordering(state):
    """Volumetric floor < Buckley-Leverett < sharp-interface nose."""
    _, _, inp = state
    m = U.mass(10, "MMT")
    rv = VolumetricPlume(inp).radius(m)
    rb = BuckleyLeverettPlume(inp).radius(m)
    rn = NordbottenCeliaPlume(inp).radius(m)
    assert rv < rb < rn


def test_plume_radius_scales_as_sqrt_mass(state):
    _, _, inp = state
    ncb = NordbottenCeliaPlume(inp)
    assert ncb.radius(U.mass(4, "MMT")) / ncb.radius(U.mass(1, "MMT")) == \
        pytest.approx(2.0, rel=1e-12)


def test_mobility_ratio_is_unfavourable_for_co2(state):
    fs, rp, _ = state
    assert endpoint_mobility_ratio(rp, fs.mu_co2, fs.mu_brine) > 1.0


def test_residual_trapping_limit_is_a_mass_balance(state):
    fs, rp, inp = state
    m = U.mass(10, "MMT")
    r = residual_trapping_limit_radius(m, fs.rho_co2, inp.porosity,
                                       inp.thickness, rp.sgr)
    swept_volume = np.pi * r ** 2 * inp.porosity * inp.thickness * rp.sgr
    assert swept_volume == pytest.approx(m / fs.rho_co2, rel=1e-9)


# ==========================================================================
def _model(state, boundary=None):
    fs, rp, _ = state
    return AquiferModel(
        permeability=U.permeability(100, "mD"), thickness=U.length(150, "ft"),
        porosity=0.20, total_compressibility=U.compressibility(6e-6, "1/psi"),
        mu_brine=fs.mu_brine, mu_co2=fs.mu_co2, rho_co2=fs.rho_co2,
        initial_pressure=U.pressure(2500, "psi"), relperm=rp,
        boundary=boundary or Boundary(kind="infinite"),
        include_two_phase_skin=False)


def test_single_well_matches_theis_exactly(state):
    m = _model(state)
    q_mass = U.mass_rate(1.0, "MMT/yr")
    w = constant_rate_well("I1", 0.0, 0.0, q_mass, 0.0, U.time(50, "yr"))
    t = U.time(10, "yr")
    r = U.length(1.0, "mi")
    q_res = q_mass / m.rho_co2
    expected = (q_res * m.mu_brine / (4 * np.pi * m.permeability * m.thickness)
                * exp1(r ** 2 / (4 * m.diffusivity * t)))
    got = float(m.delta_p(r, 0.0, t, [w])[0])
    assert got == pytest.approx(expected, rel=1e-10)


def test_superposition_is_additive(state):
    m = _model(state)
    q = U.mass_rate(0.5, "MMT/yr")
    t = U.time(10, "yr")
    a = constant_rate_well("A", -1000.0, 0.0, q, 0.0, U.time(30, "yr"))
    b = constant_rate_well("B", 1000.0, 0.0, q, 0.0, U.time(30, "yr"))
    pa = float(m.delta_p(0.0, 0.0, t, [a])[0])
    pb = float(m.delta_p(0.0, 0.0, t, [b])[0])
    pab = float(m.delta_p(0.0, 0.0, t, [a, b])[0])
    assert pab == pytest.approx(pa + pb, rel=1e-12)


def test_time_superposition_reproduces_shut_in(state):
    """After shut-in, buildup must decay below the value at shut-in."""
    m = _model(state)
    w = constant_rate_well("I1", 0.0, 0.0, U.mass_rate(1.0, "MMT/yr"),
                           0.0, U.time(20, "yr"))
    at_stop = float(m.delta_p(U.length(0.5, "mi"), 0.0, U.time(20, "yr"), [w])[0])
    later = float(m.delta_p(U.length(0.5, "mi"), 0.0, U.time(200, "yr"), [w])[0])
    assert 0.0 < later < at_stop


def test_noflow_boundary_raises_pressure_above_infinite(state):
    """A no-flow box has nowhere to put the fluid, so buildup is larger."""
    half = U.length(2.0, "mi")
    inf = _model(state)
    closed = _model(state, Boundary(kind="rectangle", xmin=-half, xmax=half,
                                    ymin=-half, ymax=half, order=4))
    w = constant_rate_well("I1", 0.0, 0.0, U.mass_rate(1.0, "MMT/yr"),
                           0.0, U.time(30, "yr"))
    t = U.time(20, "yr")
    assert (float(closed.delta_p(0.0, 0.0, t, [w])[0])
            > float(inf.delta_p(0.0, 0.0, t, [w])[0]))


def test_constant_pressure_boundary_pins_the_edge(state):
    half = U.length(2.0, "mi")
    m = _model(state, Boundary(kind="rectangle", xmin=-half, xmax=half,
                               ymin=-half, ymax=half,
                               sides=("constant_pressure",) * 4, order=5))
    w = constant_rate_well("I1", 0.0, 0.0, U.mass_rate(1.0, "MMT/yr"),
                           0.0, U.time(30, "yr"))
    edge = float(m.delta_p(half, 0.0, U.time(20, "yr"), [w])[0])
    centre = float(m.delta_p(0.0, 0.0, U.time(20, "yr"), [w])[0])
    assert abs(edge) < 0.02 * centre


def test_image_lattice_is_symmetric(state):
    half = U.length(2.0, "mi")
    m = _model(state, Boundary(kind="rectangle", xmin=-half, xmax=half,
                               ymin=-half, ymax=half, order=3))
    w = constant_rate_well("I1", 0.0, 0.0, U.mass_rate(1.0, "MMT/yr"),
                           0.0, U.time(30, "yr"))
    t = U.time(10, "yr")
    d = U.length(0.7, "mi")
    vals = [float(m.delta_p(x, y, t, [w])[0])
            for x, y in ((d, 0), (-d, 0), (0, d), (0, -d))]
    assert max(vals) - min(vals) < 1e-6 * max(vals)


def test_two_phase_skin_is_negative_for_co2(state):
    """CO2 is far less viscous than brine, so the bank improves injectivity."""
    fs, rp, _ = state
    m = AquiferModel(
        permeability=U.permeability(100, "mD"), thickness=U.length(150, "ft"),
        porosity=0.20, total_compressibility=U.compressibility(6e-6, "1/psi"),
        mu_brine=fs.mu_brine, mu_co2=fs.mu_co2, rho_co2=fs.rho_co2,
        initial_pressure=U.pressure(2500, "psi"), relperm=rp)
    w = constant_rate_well("I1", 0.0, 0.0, U.mass_rate(1.0, "MMT/yr"),
                           0.0, U.time(30, "yr"), radius=U.length(0.33, "ft"))
    assert m.apparent_skin(w, U.time(10, "yr")) < 0.0
    # and it grows in magnitude as the bank widens
    assert (abs(m.apparent_skin(w, U.time(20, "yr")))
            > abs(m.apparent_skin(w, U.time(2, "yr"))))


def test_radius_of_investigation_inverts_theis(state):
    m = _model(state)
    q = U.mass_rate(1.0, "MMT/yr") / m.rho_co2
    t, dp = U.time(20, "yr"), U.pressure(200, "psi")
    r = radius_of_investigation(m, t, dp, q)
    back = (q * m.mu_brine / (4 * np.pi * m.permeability * m.thickness)
            * exp1(r ** 2 / (4 * m.diffusivity * t)))
    assert back == pytest.approx(dp, rel=1e-6)


def test_well_cumulative_mass_and_stop_time():
    w = Well("I", 0, 0, schedule=[(0.0, 2.0), (U.time(10, "yr"), 1.0),
                                  (U.time(20, "yr"), 0.0)])
    assert w.cumulative_mass(U.time(10, "yr")) == pytest.approx(2.0 * U.time(10, "yr"))
    assert w.cumulative_mass(U.time(20, "yr")) == pytest.approx(
        2.0 * U.time(10, "yr") + 1.0 * U.time(10, "yr"))
    assert w.cumulative_mass(U.time(50, "yr")) == w.cumulative_mass(U.time(20, "yr"))
    assert w.rate_at(U.time(15, "yr")) == 1.0
    assert w.rate_at(U.time(25, "yr")) == 0.0
