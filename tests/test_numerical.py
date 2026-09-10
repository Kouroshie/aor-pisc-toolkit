"""Vertical-equilibrium solver: conservation, physics and convergence."""

import numpy as np
import pytest

from aorpisc import fluids
from aorpisc import units as U
from aorpisc.analytical import BrooksCorey, NordbottenCeliaPlume, PlumeInputs
from aorpisc.numerical import Grid, GridProperties, VESolver, VEWell
from aorpisc.numerical.grid import lognormal_permeability


@pytest.fixture(scope="module")
def fs():
    return fluids.evaluate(U.pressure(2500, "psi"), U.temperature(140, "F"),
                           fluids.salinity_to_mass_fraction(60000, "ppm"))


def _solver(fs, grid, *, thickness=U.length(150, "ft"), perm=U.permeability(100, "mD"),
            porosity=0.20, sgr=0.20, boundary="constant_pressure", dip=0.0,
            azimuth=0.0, ct=U.compressibility(6e-6, "1/psi")):
    props = GridProperties(grid, permeability=perm, porosity=porosity,
                           thickness=thickness)
    if dip:
        props.add_dip(dip, azimuth)
    rp = BrooksCorey(swr=0.35, sgr=sgr, krg0=0.30)
    return VESolver(props, rho_co2=fs.rho_co2, mu_co2=fs.mu_co2,
                    rho_brine=fs.rho_brine, mu_brine=fs.mu_brine,
                    total_compressibility=ct,
                    reference_pressure=U.pressure(2500, "psi"),
                    relperm=rp, boundary=boundary), props, rp


def _well(rate_mmt=0.5, stop_yr=10):
    return [VEWell("I1", 0.0, 0.0,
                   [(0.0, U.mass_rate(rate_mmt, "MMT/yr")),
                    (U.time(stop_yr, "yr"), 0.0)])]


# ==========================================================================
def test_grid_geometry_uniform_and_graded():
    g = Grid(nx=4, ny=3, dx=100.0, dy=200.0, x0=-200.0, y0=-300.0)
    assert g.uniform
    assert g.areas.shape == (3, 4)
    assert np.allclose(g.areas, 20000.0)
    assert g.xc[0] == pytest.approx(-150.0)
    assert g.extent == (-200.0, 200.0, -300.0, 300.0)
    assert g.index(-190.0, -290.0) == (0, 0)
    assert g.index(1e6, 0.0) is None

    tg = Grid.telescoping(center=(0.0, 0.0), fine_cell=100.0,
                          fine_half_width=500.0, total_half_width=5000.0)
    assert not tg.uniform
    assert tg.dxs.min() == pytest.approx(100.0)
    assert tg.dxs.max() > 100.0
    assert tg.dxs.sum() >= 10000.0
    # symmetric about the centre
    assert np.allclose(tg.dxs, tg.dxs[::-1])
    assert abs(tg.xc[tg.nx // 2]) < tg.dxs.min()
    # face coordinates are strictly increasing and consistent with widths
    assert np.all(np.diff(tg.xf) > 0)
    assert np.allclose(np.diff(tg.xf), tg.dxs)


def test_ve_conserves_co2_mass(fs):
    g = Grid(nx=61, ny=61, dx=300.0, dy=300.0, x0=-9150.0, y0=-9150.0)
    s, _, _ = _solver(fs, g)
    r = s.run(_well(), end_time=U.time(30, "yr"),
              output_times=U.time(np.array([0, 10, 30.0]), "yr"),
              dt_max=U.time(1, "yr"))
    assert r.mass_balance_error < 1e-6
    assert not any("mass-balance" in w for w in r.warnings)


def test_ve_conserves_mass_on_a_graded_grid(fs):
    g = Grid.telescoping(center=(0.0, 0.0), fine_cell=250.0,
                         fine_half_width=3000.0, total_half_width=15000.0)
    s, _, _ = _solver(fs, g)
    r = s.run(_well(), end_time=U.time(30, "yr"),
              output_times=U.time(np.array([0, 10, 30.0]), "yr"),
              dt_max=U.time(1, "yr"))
    assert r.mass_balance_error < 1e-6


def test_closed_system_pressurisation_matches_volume_balance(fs):
    """dP = injected volume / (pore volume * total compressibility)."""
    g = Grid(nx=41, ny=41, dx=400.0, dy=400.0, x0=-8200.0, y0=-8200.0)
    ct = U.compressibility(6e-6, "1/psi")
    s, props, _ = _solver(fs, g, boundary="noflow", ct=ct)
    wells = _well(rate_mmt=0.2, stop_yr=10)
    r = s.run(wells, end_time=U.time(60, "yr"),
              output_times=U.time(np.array([0, 10, 60.0]), "yr"),
              dt_max=U.time(1, "yr"))
    injected_vol = wells[0].cumulative_mass(U.time(10, "yr")) / fs.rho_co2
    pore_vol = float(props.pore_volume.sum())
    expected = injected_vol / (pore_vol * ct)
    # long after shut-in the box has equilibrated to a uniform buildup
    assert float(r.dp[-1].mean()) == pytest.approx(expected, rel=0.05)


def test_ve_profile_converges_to_nordbotten_celia(fs):
    """Refining the grid should bring the VE interface toward the analytic one.

    Compared at a 5 % column-thickness cutoff, which is where a sharp-interface
    solution and a numerically smeared nose can be compared like with like.
    """
    H = U.length(150, "ft")
    rp = BrooksCorey(swr=0.35, sgr=0.0, krg0=0.30)   # Sgr = 0 matches NCB
    inp = PlumeInputs(H, 0.20, U.permeability(100, "mD"), fs.rho_co2, fs.mu_co2,
                      fs.rho_brine, fs.mu_brine, relperm=rp)
    ncb = NordbottenCeliaPlume(inp)
    mass = U.mass(5, "MMT")

    errors = []
    for n, dx in ((81, 250.0), (121, 170.0)):
        g = Grid(nx=n, ny=n, dx=dx, dy=dx, x0=-n * dx / 2, y0=-n * dx / 2)
        props = GridProperties(g, permeability=U.permeability(100, "mD"),
                               porosity=0.20, thickness=H)
        s = VESolver(props, rho_co2=fs.rho_co2, mu_co2=fs.mu_co2,
                     rho_brine=fs.rho_brine, mu_brine=fs.mu_brine,
                     total_compressibility=U.compressibility(6e-6, "1/psi"),
                     reference_pressure=U.pressure(2500, "psi"),
                     relperm=rp, boundary="constant_pressure")
        w = [VEWell("I1", 0.0, 0.0, [(0.0, U.mass_rate(0.5, "MMT/yr")),
                                     (U.time(10, "yr"), 0.0)])]
        r = s.run(w, end_time=U.time(10, "yr"),
                  output_times=U.time(np.array([10.0]), "yr"),
                  dt_max=U.time(0.5, "yr"))
        area = float((r.h[-1] > 0.05 * H).sum() * g.cell_area)
        r_eq = np.sqrt(area / np.pi)
        errors.append(abs(r_eq - ncb.radius(mass)) / ncb.radius(mass))

    assert errors[-1] < 0.15, f"VE nose is {errors[-1]:.0%} from the analytic one"
    assert errors[-1] <= errors[0] + 0.02, "refinement made the match worse"


def test_dip_drives_the_plume_updip(fs):
    """A formation dipping south must push CO2 north after shut-in."""
    g = Grid(nx=81, ny=81, dx=250.0, dy=250.0, x0=-10125.0, y0=-10125.0)
    s, props, rp = _solver(fs, g, dip=1.5, azimuth=180.0)
    r = s.run(_well(rate_mmt=0.4, stop_yr=10), end_time=U.time(120, "yr"),
              output_times=U.time(np.array([10.0, 120.0]), "yr"),
              dt_max=U.time(2, "yr"))
    Y = g.meshgrid()[1]
    for idx in (0, 1):
        mask = r.hmax[idx] > 1e-6
        assert mask.any()
    centroid_end = float(Y[r.hmax[-1] > 1e-6].mean())
    centroid_inj = float(Y[r.hmax[0] > 1e-6].mean())
    assert centroid_end > centroid_inj + 100.0, "plume did not migrate up-dip"


def test_sealing_fault_blocks_the_plume(fs):
    g = Grid(nx=81, ny=81, dx=200.0, dy=200.0, x0=-8100.0, y0=-8100.0)
    props = GridProperties(g, permeability=U.permeability(150, "mD"),
                           porosity=0.20, thickness=U.length(150, "ft"))
    props.add_sealing_fault([(1200.0, -8000.0), (1200.0, 8000.0)], multiplier=0.0)
    rp = BrooksCorey(swr=0.35, sgr=0.20, krg0=0.30)
    s = VESolver(props, rho_co2=fs.rho_co2, mu_co2=fs.mu_co2,
                 rho_brine=fs.rho_brine, mu_brine=fs.mu_brine,
                 total_compressibility=U.compressibility(6e-6, "1/psi"),
                 reference_pressure=U.pressure(2500, "psi"),
                 relperm=rp, boundary="constant_pressure")
    r = s.run(_well(rate_mmt=0.5, stop_yr=15), end_time=U.time(15, "yr"),
              output_times=U.time(np.array([15.0]), "yr"), dt_max=U.time(1, "yr"))
    X = g.meshgrid()[0]
    beyond = (r.hmax[-1] > 1e-6) & (X > 1600.0)
    near_side = (r.hmax[-1] > 1e-6) & (X < -1600.0)
    assert near_side.sum() > 0
    assert beyond.sum() == 0, "CO2 crossed a fully sealing fault"


def test_residual_trapping_leaves_co2_behind(fs):
    """After shut-in the swept footprint must exceed the mobile footprint."""
    g = Grid(nx=81, ny=81, dx=250.0, dy=250.0, x0=-10125.0, y0=-10125.0)
    s, _, _ = _solver(fs, g, sgr=0.25, dip=1.5, azimuth=180.0)
    r = s.run(_well(rate_mmt=0.4, stop_yr=10), end_time=U.time(150, "yr"),
              output_times=U.time(np.array([10.0, 150.0]), "yr"),
              dt_max=U.time(2, "yr"))
    swept = (r.hmax[-1] > 1e-6).sum()
    mobile = (r.h[-1] > 1e-6).sum()
    assert swept > mobile


def test_heterogeneity_changes_the_footprint(fs):
    g = Grid(nx=61, ny=61, dx=300.0, dy=300.0, x0=-9150.0, y0=-9150.0)
    k_het = lognormal_permeability(g, mean_md=100.0, sigma_ln=1.2,
                                   correlation_length=1500.0, seed=7)
    out = []
    for k in (U.permeability(100, "mD"), k_het):
        props = GridProperties(g, permeability=k, porosity=0.20,
                               thickness=U.length(150, "ft"))
        s = VESolver(props, rho_co2=fs.rho_co2, mu_co2=fs.mu_co2,
                     rho_brine=fs.rho_brine, mu_brine=fs.mu_brine,
                     total_compressibility=U.compressibility(6e-6, "1/psi"),
                     reference_pressure=U.pressure(2500, "psi"),
                     relperm=BrooksCorey(swr=0.35, sgr=0.20, krg0=0.30),
                     boundary="constant_pressure")
        r = s.run(_well(rate_mmt=0.4, stop_yr=10), end_time=U.time(10, "yr"),
                  output_times=U.time(np.array([10.0]), "yr"),
                  dt_max=U.time(1, "yr"))
        out.append(int((r.hmax[-1] > 1e-6).sum()))
    assert out[0] != out[1]


def test_pressure_dissipates_with_open_boundaries(fs):
    g = Grid(nx=61, ny=61, dx=400.0, dy=400.0, x0=-12200.0, y0=-12200.0)
    s, _, _ = _solver(fs, g, boundary="constant_pressure")
    r = s.run(_well(rate_mmt=0.4, stop_yr=10), end_time=U.time(200, "yr"),
              output_times=U.time(np.array([10.0, 200.0]), "yr"),
              dt_max=U.time(4, "yr"))
    assert float(r.dp[-1].max()) < 0.15 * float(r.dp[0].max())


def test_well_outside_grid_raises(fs):
    g = Grid(nx=21, ny=21, dx=200.0, dy=200.0, x0=-2100.0, y0=-2100.0)
    s, _, _ = _solver(fs, g)
    bad = [VEWell("far", 1e6, 0.0, [(0.0, U.mass_rate(0.1, "MMT/yr"))])]
    with pytest.raises(ValueError):
        s.run(bad, end_time=U.time(1, "yr"))


def test_saturation_proxy_is_bounded(fs):
    g = Grid(nx=41, ny=41, dx=300.0, dy=300.0, x0=-6150.0, y0=-6150.0)
    s, props, rp = _solver(fs, g)
    r = s.run(_well(rate_mmt=0.3, stop_yr=8), end_time=U.time(20, "yr"),
              output_times=U.time(np.array([8.0, 20.0]), "yr"),
              dt_max=U.time(1, "yr"))
    sat = r.saturation_proxy(-1, props, rp)
    assert sat.min() >= 0.0
    assert sat.max() <= 1.0 - rp.swr + 1e-9
