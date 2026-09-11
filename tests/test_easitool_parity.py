"""Four capabilities added after reading EASiTool 5.1 side by side with this.

EASiTool (UT Austin BEG) is the tool this one is most often compared with. It
does several things well that were missing here, and each is tested below:

* an ESRI shapefile export, which is what a state agency asks for even though
  GeoJSON is the better format;
* a sensitivity study that varies the fluid and relative-permeability inputs,
  not only the four storage properties;
* a per-well bottomhole-pressure verdict against a declared limit, so a rate
  schedule that cannot be injected is caught before its AoR is believed;
* calendar dates, because permits are written in dates rather than in years
  from an unnamed origin.
"""

from __future__ import annotations

import copy
import os
import zipfile

import numpy as np
import pytest

from containment import uncertainty as unc
from containment import workflow
from containment.config import Project
from containment.io import exporters

pytest.importorskip("shapely")


BASE = {
    "project": {"name": "parity case", "start_date": "2027-04-01"},
    "units": {"length": "ft", "depth": "ft", "pressure": "psi",
              "temperature": "F", "permeability": "mD", "rate": "MMT/yr",
              "time": "yr", "compressibility": "1/psi"},
    "formation": {
        "injection_zone": {"top_depth": 6000, "thickness": 250, "porosity": 0.18,
                           "permeability": 150, "temperature": 150,
                           "salinity_ppm": 90000, "initial_pressure": 2600,
                           "rock_compressibility": 5e-6},
        "confining_zone": {"top_depth": 5700, "base_depth": 6000},
        "usdw": {"base_depth": 1200, "initial_pressure": 520,
                 "temperature": 80, "salinity_ppm": 800},
    },
    "model": {"engine": "analytical", "end_year": 30,
              "aor_reevaluation_years": 10,
              "grid": {"cell_size": 1000, "half_width": 60000}},
    "wells": [
        {"name": "INJ-1", "x": 0, "y": 0, "rate": 0.7,
         "start_date": "2027-04-01", "stop_date": "2042-04-01", "max_bhp": 3200},
        {"name": "INJ-2", "x": 6000, "y": 0, "rate": 0.7,
         "start_date": "2030-01-01", "stop_date": "2042-04-01", "max_bhp": 2900},
    ],
}


def _project(**over) -> Project:
    d = copy.deepcopy(BASE)
    for k, v in over.items():
        d[k] = v
    return Project.from_dict(d)


# --------------------------------------------------------------- shapefile
def test_the_shapefile_carries_all_three_components():
    shapefile = pytest.importorskip("shapefile")
    res = workflow.run(_project())

    data = exporters.shapefile_bytes(res.aor, workflow.project_crs(res.project))
    assert len(data) > 500

    import io as _io

    with zipfile.ZipFile(_io.BytesIO(data)) as z:
        assert "aor.shp" in z.namelist()

    # read it back the way a GIS would
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "aor.zip")
        with open(path, "wb") as fh:
            fh.write(data)
        with zipfile.ZipFile(path) as z:
            z.extractall(tmp)
        reader = shapefile.Reader(os.path.join(tmp, "aor"))
        try:
            components = [rec[0] for rec in reader.records()]
            assert "aor" in components
            fields = [f[0] for f in reader.fields[1:]]
            assert {"component", "area_acre", "dpc_psi"} <= set(fields)
            assert len(reader.shapes()) == len(components)
        finally:
            reader.close()          # Windows keeps the .dbf open otherwise


def test_the_shapefile_is_written_in_lon_lat_when_georeferenced():
    shapefile = pytest.importorskip("shapefile")
    import tempfile

    d = copy.deepcopy(BASE)
    d["wells"] = [{"name": "INJ-1", "latitude": 31.9686, "longitude": -99.9018,
                   "rate": 0.7, "start_year": 0, "stop_year": 15}]
    res = workflow.run(Project.from_dict(d))

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "aor.zip")
        exporters.to_shapefile(res.aor, path, workflow.project_crs(res.project))
        with zipfile.ZipFile(path) as z:
            assert "aor.prj" in z.namelist()      # a GIS needs to be told the frame
            z.extractall(tmp)
        reader = shapefile.Reader(os.path.join(tmp, "aor"))
        try:
            x, y = reader.shapes()[0].points[0]
        finally:
            reader.close()
    assert -101 < x < -99 and 31 < y < 33         # lon/lat, not model metres


def test_write_polygons_accepts_a_zip():
    pytest.importorskip("shapefile")
    import tempfile

    res = workflow.run(_project())
    with tempfile.TemporaryDirectory() as tmp:
        out = exporters.write_polygons(res.aor, os.path.join(tmp, "x.zip"))
        assert os.path.exists(out)


# ---------------------------------------------------------------- tornado
def test_the_sensitivity_set_covers_fluids_relperm_and_the_threshold():
    params = unc.default_parameters(
        permeability_md=150, porosity=0.18, thickness_ft=250,
        compressibility_1_psi=9e-6, initial_pressure_psi=2600,
        temperature_f=150, salinity_ppm=90000, swr=0.35, sgr=0.20,
        krg0=0.30, corey=3.0, threshold_psi=165)
    names = [p.name for p in params]
    assert names[:4] == ["permeability_md", "porosity", "thickness_ft",
                         "compressibility_1_psi"]
    for extra in ("initial_pressure_psi", "temperature_f", "salinity_ppm",
                  "swr", "sgr", "krg0", "corey", "threshold_psi"):
        assert extra in names, extra
    assert all(p.low <= p.base <= p.high for p in params)


def test_the_four_parameter_study_is_still_available():
    """A caller that wants the original set must not silently get twelve."""
    params = unc.default_parameters(
        permeability_md=150, porosity=0.18, thickness_ft=250,
        compressibility_1_psi=9e-6)
    assert len(params) == 4


def test_relative_permeability_moves_the_plume():
    """Sgr is documented as the strongest control on whether the plume stops,
    so a sensitivity study that could not move it would be misleading."""
    from containment import fluids
    from containment import units as U
    from containment.analytical import AquiferModel, Boundary, Well
    from containment.analytical.relperm import BrooksCorey

    fs = fluids.evaluate(U.pressure(2600, "psi"), U.temperature(150, "F"), 0.09)
    w = Well(name="INJ", x=0, y=0,
             schedule=[(0.0, U.mass_rate(1.0, "MMT/yr")), (U.time(10, "yr"), 0.0)])

    def radius(sgr):
        m = AquiferModel(
            permeability=U.permeability(150, "mD"), thickness=U.length(250, "ft"),
            porosity=0.18, total_compressibility=U.compressibility(9e-6, "1/psi"),
            mu_brine=fs.mu_brine, mu_co2=fs.mu_co2, rho_co2=fs.rho_co2,
            initial_pressure=U.pressure(2600, "psi"),
            relperm=BrooksCorey(swr=0.35, sgr=sgr, krg0=0.30, m=3.0, n=3.0),
            boundary=Boundary(kind="infinite"))
        return m.front_radius(w, U.time(10, "yr"))

    assert radius(0.05) > radius(0.35) * 1.05


# ------------------------------------------------------------ well pressure
def test_a_well_over_its_limit_is_called_out():
    res = workflow.run(_project())
    rows = {r["well"]: r for r in res.well_pressure}
    assert set(rows) == {"INJ-1", "INJ-2"}

    assert rows["INJ-1"]["verdict"] == "pass"
    assert rows["INJ-1"]["margin_psi"] > 0

    # INJ-2 carries the lower limit and the same rate, so it must fail
    assert rows["INJ-2"]["verdict"] == "EXCEEDS LIMIT"
    assert rows["INJ-2"]["margin_psi"] < 0
    assert any("EXCEEDS" in w or "not injectable" in w for w in res.warnings)


def test_a_well_without_a_limit_gets_no_verdict_rather_than_a_pass():
    d = copy.deepcopy(BASE)
    for w in d["wells"]:
        w.pop("max_bhp")
    res = workflow.run(Project.from_dict(d))
    assert all(r["verdict"] == "no limit declared" for r in res.well_pressure)
    assert all(np.isfinite(r["max_bhp_psi"]) for r in res.well_pressure)


# ------------------------------------------------------------------- dates
def test_calendar_dates_become_model_time():
    p = _project()
    assert p.start_date == "2027-04-01"
    # INJ-2 starts 2030-01-01, which is 2.75 years after the project start
    start_yr = p.wells[1].schedule[0][0] / (365.25 * 86400)
    assert start_yr == pytest.approx(2.75, abs=0.02)


def test_the_project_start_defaults_to_the_earliest_well():
    d = copy.deepcopy(BASE)
    d["project"].pop("start_date")
    p = Project.from_dict(d)
    assert p.start_date == "2027-04-01"


def test_years_still_work_and_stay_undated():
    d = copy.deepcopy(BASE)
    d["project"].pop("start_date")
    d["wells"] = [{"name": "INJ-1", "x": 0, "y": 0, "rate": 0.7,
                   "start_year": 0, "stop_year": 15}]
    p = Project.from_dict(d)
    assert p.start_date == ""
    assert p.calendar(0.0) is None


def test_the_reevaluation_table_carries_dates():
    res = workflow.run(_project())
    rows = res.summary()["aor_by_reevaluation_year"]
    assert rows and all("date" in r for r in rows)
    assert rows[0]["date"].startswith("2037")       # 10 years after 2027-04-01
