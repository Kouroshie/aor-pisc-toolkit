"""PISC metrics, the 146.93(c) checklist, importers and the end-to-end run."""

import os

import numpy as np
import pytest

from containment import pisc, uncertainty
from containment import units as U
from containment.config import Project
from containment.io import importers

EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(__file__)), "examples")


def _synthetic_pisc(growth_after_shutin=0.0, pressure_tail=0.0):
    """A plume that grows during injection then (optionally) creeps on."""
    years = np.array([0, 2, 5, 10, 15, 20, 25, 30, 40, 60, 80, 100.0])
    inj_end = 20.0
    radius = np.where(years <= inj_end,
                      500.0 * np.sqrt(np.maximum(years, 0.0)),
                      500.0 * np.sqrt(inj_end)
                      + growth_after_shutin * (years - inj_end))
    area = np.pi * radius ** 2
    # pressure builds then decays exponentially after shut-in
    dp = np.where(years <= inj_end, 40.0 * years,
                  800.0 * np.exp(-(years - inj_end) / 6.0) + pressure_tail)
    return pisc.PISCResult(
        times_years=years, plume_area_m2=area,
        pressure_area_m2=area * 1.4, max_dp=U.pressure(dp, "psi"),
        mean_dp_in_plume=U.pressure(dp * 0.5, "psi"),
        injection_end_year=inj_end,
        threshold_pressure=U.pressure(100.0, "psi"))


# ==========================================================================
def test_effective_radius_and_rates_are_consistent():
    r = _synthetic_pisc()
    assert r.effective_radius[0] == pytest.approx(0.0)
    # r_eff must match the radius that generated the areas
    assert r.effective_radius[5] == pytest.approx(500.0 * np.sqrt(20.0), rel=1e-9)
    assert r.peak_migration_rate() > 0
    assert np.isfinite(r.migration_rate[1:]).all()


def test_stable_plume_stabilises():
    r = _synthetic_pisc(growth_after_shutin=0.0)
    assert np.isfinite(r.stabilisation_year())
    assert r.stabilisation_year() >= r.injection_end_year


def test_creeping_plume_does_not_stabilise():
    """A plume still expanding measurably must not be declared stable."""
    r = _synthetic_pisc(growth_after_shutin=30.0)
    assert not np.isfinite(r.stabilisation_year())
    rec = r.recommended_timeframe()
    assert "plume stabilisation" in rec["unmet_criteria"]
    assert "CAUTION" in rec["verdict"]


def test_pressure_below_threshold_year():
    r = _synthetic_pisc()
    yr = r.pressure_below_threshold_year()
    assert 20.0 < yr < 45.0
    i = int(np.searchsorted(r.times_years, yr))
    assert float(r.max_dp[i]) < r.threshold_pressure


def test_pressure_that_never_falls_is_reported_as_nan():
    r = _synthetic_pisc(pressure_tail=500.0)     # stays above the 100 psi threshold
    assert not np.isfinite(r.pressure_below_threshold_year())


def test_recommendation_flags_a_long_pisc():
    r = _synthetic_pisc(growth_after_shutin=0.0, pressure_tail=0.0)
    rec = r.recommended_timeframe(default_years=5.0)
    assert rec["recommended_years"] > 5.0
    assert "longer PISC period" in rec["verdict"]


def test_pisc_table_and_summary_shapes():
    r = _synthetic_pisc()
    rows = r.table()
    assert len(rows) == len(r.times_years)
    assert {"year", "plume_area_acres", "max_dp_psi"} <= set(rows[0])
    s = r.summary()
    assert s["peak_plume_area_acres"] > 0
    assert "recommended_pisc" in s


def test_alternative_timeframe_checklist_is_honest():
    r = _synthetic_pisc()
    rows = pisc.alternative_timeframe_checklist(r)
    assert len(rows) == 18            # 146.93(c)(1) i-x plus (c)(2) i-viii
    by_cite = {row["citation"]: row for row in rows}
    assert by_cite["40 CFR 146.93(c)(1)(ii)"]["satisfied_by_model"] is True
    # trapping narrative and lab studies cannot be answered by a flow model
    assert by_cite["40 CFR 146.93(c)(1)(iv)"]["satisfied_by_model"] is False
    assert by_cite["40 CFR 146.93(c)(1)(vi)"]["satisfied_by_model"] is False
    assert by_cite["40 CFR 146.93(c)(2)(vii)"]["satisfied_by_model"] is False


def test_analyse_warns_about_coarse_output_spacing():
    times = U.time(np.array([0.0, 10.0, 30.0, 80.0, 200.0]), "yr")
    fields = np.zeros((5, 8, 8))
    fields[:, 3:5, 3:5] = 1.0
    res = pisc.analyse(times, plume_fields=fields, plume_level=0.5,
                       dp_fields=np.zeros((5, 8, 8)), threshold_pressure=1.0,
                       cell_area=1e6, injection_end=U.time(10, "yr"))
    assert any("spaced about" in w for w in res.warnings)


def test_directional_migration_finds_the_moving_side():
    x = np.linspace(-5000, 5000, 101)
    y = np.linspace(-5000, 5000, 101)
    X, Y = np.meshgrid(x, y)
    times = U.time(np.array([0.0, 10.0, 20.0]), "yr")
    # a plume that only extends northward with time
    fields = np.array([((np.hypot(X, Y) < 500) | ((np.abs(X) < 400) & (Y > 0) & (Y < d)))
                       .astype(float) for d in (500.0, 2000.0, 4000.0)])
    out = pisc.directional_migration(times, fields, 0.5, x, y, [(0.0, 0.0)], azimuths=4)
    d = out["0,0"]
    assert d[0.0]["final_reach_ft"] > 3 * d[180.0]["final_reach_ft"]


# ==========================================================================
def test_uncertainty_tornado_ranks_parameters():
    params = [
        uncertainty.Parameter("a", 10.0, 5.0, 20.0),
        uncertainty.Parameter("b", 1.0, 0.9, 1.1),
    ]
    tor = uncertainty.tornado(lambda c: c["a"] * 100 + c["b"], params)
    assert tor.sorted_rows()[0]["parameter"].startswith("a")
    assert tor.base_value == pytest.approx(1001.0)


def test_latin_hypercube_covers_the_unit_cube():
    u = uncertainty.latin_hypercube(50, 3, seed=1)
    assert u.shape == (50, 3)
    assert u.min() >= 0.0 and u.max() < 1.0
    for j in range(3):
        # one sample per stratum
        assert len(set((u[:, j] * 50).astype(int))) == 50


def test_parameter_sampling_respects_bounds():
    for dist in ("triangular", "uniform", "normal", "lognormal"):
        p = uncertainty.Parameter("k", 100.0, 50.0, 200.0, dist)
        s = p.sample(np.linspace(1e-6, 1 - 1e-6, 500))
        assert np.all(np.isfinite(s))
        if dist in ("triangular", "uniform"):
            assert s.min() >= 50.0 - 1e-6 and s.max() <= 200.0 + 1e-6
        assert s.min() > 0


def test_monte_carlo_collects_metrics_and_grid():
    params = [uncertainty.Parameter("r", 1000.0, 500.0, 2000.0, "uniform")]
    gx = np.linspace(-3000, 3000, 41)
    gy = np.linspace(-3000, 3000, 41)
    GX, GY = np.meshgrid(gx, gy)

    def ev(case):
        inside = np.hypot(GX, GY) <= case["r"]
        return {"area": float(inside.sum()), "inside": inside}

    mc = uncertainty.monte_carlo(ev, params, n=40, seed=3, grid_x=gx, grid_y=gy)
    assert mc.failures == 0
    assert mc.exceedance.max() == pytest.approx(1.0)
    assert mc.exceedance.min() == pytest.approx(0.0)
    pcts = mc.percentiles("area")
    assert pcts["P10"] < pcts["P50"] < pcts["P90"]
    assert mc.correlations("area")[0]["parameter"] == "r"
    poly = mc.probabilistic_aor(0.9)
    assert poly.area > 0


# ==========================================================================
def test_importer_reads_long_format_csv(tmp_path):
    path = tmp_path / "sim.csv"
    lines = ["x,y,layer,time,PRES,SGAS"]
    for t in (0, 10):
        for j in range(4):
            for i in range(4):
                for k in range(2):
                    p = 2500 + (100 if (t and i == j) else 0) + 10 * k
                    sg = 0.2 if (t and i == 1 and j == 1 and k == 0) else 0.0
                    lines.append(f"{i * 500},{j * 500},{k},{t},{p},{sg}")
    path.write_text("\n".join(lines), encoding="utf-8")

    sim = importers.load_grid_csv(
        str(path), dp_col="PRES", plume_col="SGAS", length_unit="ft",
        pressure_unit="psi", time_unit="yr", aggregate="max",
        dp_is_absolute=True, initial_pressure=2500.0)
    assert sim.dp.shape == (2, 4, 4)
    assert sim.times.size == 2
    # layer aggregation is "max", so the +10 psi lower layer wins at t = 0
    assert U.pressure_out(float(sim.dp[0].max()), "psi") == pytest.approx(10.0, abs=1e-6)
    assert U.pressure_out(float(sim.dp[1].max()), "psi") == pytest.approx(110.0, abs=1e-6)
    assert float(sim.plume_max().max()) == pytest.approx(0.2)
    assert sim.cell_area == pytest.approx(U.length(500, "ft") ** 2, rel=1e-9)


def test_importer_warns_on_wrong_pressure_convention(tmp_path):
    path = tmp_path / "sim.csv"
    path.write_text("x,y,time,PRES\n0,0,0,2500\n500,0,0,2400\n"
                    "0,500,0,2500\n500,500,0,2500\n", encoding="utf-8")
    sim = importers.load_grid_csv(str(path), dp_col="PRES", pressure_unit="psi",
                                  length_unit="ft", dp_is_absolute=False)
    assert any("absolute pressure" in n for n in sim.notes)


def test_eclipse_ascii_reader(tmp_path):
    path = tmp_path / "poro.grdecl"
    path.write_text("PORO\n  4*0.20  4*0.25 /\n", encoding="utf-8")
    a = importers.load_eclipse_ascii(str(path), "PORO", nx=2, ny=2, nz=2,
                                     aggregate="max")
    assert a.shape == (2, 2)
    assert np.allclose(a, 0.25)
    b = importers.load_eclipse_ascii(str(path), "PORO", nx=2, ny=2, nz=2,
                                     aggregate="top")
    assert np.allclose(b, 0.20)


# ==========================================================================
def test_project_parses_the_shipped_example():
    p = Project.from_yaml(os.path.join(EXAMPLES, "epa_hypothetical_site.yaml"))
    assert p.name.startswith("EPA hypothetical")
    assert len(p.wells) == 3
    assert U.mass_out(p.total_injected_mass(), "MMT") == pytest.approx(60.0, rel=1e-3)
    assert U.time_out(p.injection_end(), "yr") == pytest.approx(30.0)
    assert U.length_out(p.injection_zone.top_depth, "m") == pytest.approx(1800.0)
    assert p.injection_zone.salinity == pytest.approx(0.05)
    assert p.warnings == []


def test_project_flags_a_usdw_below_the_injection_zone():
    p = Project.from_dict({
        "units": {"depth": "ft", "pressure": "psi", "temperature": "F"},
        "formation": {
            "injection_zone": {"top_depth": 1000, "thickness": 100,
                               "porosity": 0.2, "permeability": 50,
                               "temperature": 120, "salinity_ppm": 50000,
                               "initial_pressure": 450},
            "usdw": {"base_depth": 5000, "initial_pressure": 2000},
        },
        "wells": [{"name": "I", "x": 0, "y": 0, "rate": 1.0,
                   "start_year": 0, "stop_year": 10}],
    })
    assert any("not below the lowermost USDW" in w for w in p.warnings)


def test_project_flags_a_closed_domain_for_long_runs():
    p = Project.from_dict({
        "formation": {"injection_zone": {"top_depth": 6000, "thickness": 200,
                                         "porosity": 0.2, "permeability": 50,
                                         "temperature": 140, "salinity_ppm": 50000,
                                         "initial_pressure": 2600},
                      "usdw": {"base_depth": 1000, "initial_pressure": 430}},
        "wells": [{"name": "I", "x": 0, "y": 0, "rate": 1.0,
                   "start_year": 0, "stop_year": 10}],
        "model": {"engine": "ve", "boundary": "noflow", "end_year": 100,
                  "grid": {"nx": 41, "ny": 41, "cell_size": 2000}},
    })
    assert any("never lets pressure dissipate" in w for w in p.warnings)


def test_default_output_times_land_on_rate_changes():
    p = Project.from_dict({
        "formation": {"injection_zone": {"top_depth": 6000, "thickness": 200,
                                         "porosity": 0.2, "permeability": 50,
                                         "temperature": 140, "salinity_ppm": 50000,
                                         "initial_pressure": 2600},
                      "usdw": {"base_depth": 1000, "initial_pressure": 430}},
        "wells": [{"name": "I", "x": 0, "y": 0, "rate": 1.0,
                   "start_year": 3, "stop_year": 17}],
        "model": {"engine": "analytical", "end_year": 60},
    })
    yrs = U.time_out(p.output_times, "yr")
    assert 3.0 in set(np.round(yrs, 4))
    assert 17.0 in set(np.round(yrs, 4))
    assert yrs[-1] == pytest.approx(60.0)


@pytest.mark.slow
def test_end_to_end_analytical_run():
    from containment import workflow

    p = Project.from_dict({
        "project": {"name": "smoke"},
        "units": {"depth": "ft", "length": "ft", "pressure": "psi",
                  "temperature": "F", "rate": "MMT/yr"},
        "formation": {
            "injection_zone": {"top_depth": 6000, "thickness": 250,
                               "porosity": 0.18, "permeability": 150,
                               "temperature": 150, "salinity_ppm": 90000,
                               "initial_pressure": 2600,
                               "rock_compressibility": 5.0e-6},
            "confining_zone": {"top_depth": 5700, "base_depth": 6000},
            "usdw": {"base_depth": 1200, "initial_pressure": 520,
                     "temperature": 80, "salinity_ppm": 800},
        },
        "wells": [{"name": "INJ-1", "x": 0, "y": 0, "rate": 0.5,
                   "start_year": 0, "stop_year": 15}],
        "model": {"engine": "analytical", "end_year": 40,
                  "grid": {"nx": 81, "ny": 81, "cell_size": 1000}},
    })
    res = workflow.run(p)
    assert res.aor.area_acres > 0
    assert res.selected_threshold.delta_p_critical > 0
    assert res.pisc is not None
    assert res.dp_fields.shape[0] == len(res.times)
    assert res.plume_fields.shape == res.dp_fields.shape
    s = res.summary()
    assert s["aor"]["aor_area_acres"] == pytest.approx(res.aor.area_acres)
    # the cross-checks must bracket the modelled plume
    ck = res.analytical_checks
    assert ck["volumetric_radius_ft"] < ck["nordbotten_celia_radius_ft"]


def test_threshold_datum_is_configurable():
    """The datum the threshold is evaluated at is a real, documented choice.

    Moving it from the mid-point of a thick injection zone to the top changes
    dP_c by the weight of half the interval, which on an under-pressurised
    site is easily 10 % of the answer.
    """
    base = {
        "units": {"depth": "ft", "length": "ft", "pressure": "psi",
                  "temperature": "F", "rate": "MMT/yr"},
        "formation": {
            "injection_zone": {"top_depth": 5862, "thickness": 313.5,
                               "porosity": 0.10, "permeability": 50,
                               "temperature": 100, "salinity_ppm": 180153,
                               "initial_pressure": 1817},
            "usdw": {"base_depth": 1217, "initial_pressure": 289,
                     "temperature": 80, "salinity_ppm": 1500},
        },
        "wells": [{"name": "I", "x": 0, "y": 0, "rate": 0.7,
                   "start_year": 0, "stop_year": 3}],
        "threshold": {"method": "method1"},
    }
    mid = Project.from_dict(base)
    top = Project.from_dict({**base, "threshold": {"method": "method1", "datum": "top"}})
    exp = Project.from_dict({**base,
                             "threshold": {"method": "method1", "datum_depth": 5862}})

    assert U.length_out(mid.threshold_depth, "ft") == pytest.approx(6018.75)
    assert U.length_out(top.threshold_depth, "ft") == pytest.approx(5862.0)
    assert U.length_out(exp.threshold_depth, "ft") == pytest.approx(5862.0)

    from containment import workflow
    dp_mid = workflow.run(mid).selected_threshold.delta_p_psi
    dp_top = workflow.run(top).selected_threshold.delta_p_psi
    assert dp_mid > dp_top
    assert (dp_mid - dp_top) / dp_top > 0.05      # a material difference
