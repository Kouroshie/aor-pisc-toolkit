"""Static basemap maps: tests added with the feature."""
import matplotlib
import pytest

matplotlib.use("Agg")
pytest.importorskip("shapely")
pytest.importorskip("folium")

from containment import gis, workflow  # noqa: E402
from containment.config import Project  # noqa: E402

BASE = {
    "project": {"name": "static map case"},
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
                 "temperature": 80, "salinity_ppm": 800}},
    "model": {"engine": "analytical", "end_year": 20,
              "grid": {"cell_size": 1000, "half_width": 40000}},
    "wells": [{"name": "INJ-1", "latitude": 29.98, "longitude": -94.13,
               "rate": 0.5, "start_year": 0, "stop_year": 10}],
}


def _result():
    p = Project.from_dict(BASE)
    return p, workflow.run(p)


def test_tile_maths_round_trips():
    for lon, lat, z in ((-94.13, 29.98, 12), (0.0, 51.5, 8), (139.7, 35.7, 14)):
        x, y = gis._deg2num(lon, lat, z)
        back_lon, back_lat = gis._num2deg(x, y, z)
        assert abs(back_lon - lon) < 1e-6
        assert abs(back_lat - lat) < 1e-6


def test_a_static_map_is_drawn_for_every_basemap(monkeypatch):
    """Offline must still produce a figure: the geometry is the point, the
    imagery is the backdrop."""
    monkeypatch.setattr(gis, "_fetch_tiles", lambda *a, **k: None)
    p, res = _result()
    ctx = gis.MapContext.from_project(p)
    for key in gis.BASEMAPS:
        fig = gis.static_map(res.aor, ctx, basemap=key, wells=p.wells)
        assert fig is not None
        ax = fig.axes[0]
        lo, hi = ax.get_xlim()
        assert lo < -94.13 < hi                       # the well's longitude
        assert ax.get_ylim()[0] < 29.98 < ax.get_ylim()[1]      # its latitude
        assert any("AoR" in (t.get_text() or "") for t in ax.get_legend().get_texts())
        matplotlib.pyplot.close(fig)


def test_static_map_set_covers_the_lot(monkeypatch):
    monkeypatch.setattr(gis, "_fetch_tiles", lambda *a, **k: None)
    p, res = _result()
    figs = gis.static_map_set(res.aor, gis.MapContext.from_project(p),
                              wells=p.wells)
    assert set(figs) == set(gis.BASEMAPS)
    for f in figs.values():
        matplotlib.pyplot.close(f)


def test_an_ungeoreferenced_project_says_so():
    d = dict(BASE)
    d["wells"] = [{"name": "INJ-1", "x": 0, "y": 0, "rate": 0.5,
                   "start_year": 0, "stop_year": 10}]
    p = Project.from_dict(d)
    with pytest.raises(ValueError, match="georeferencing"):
        gis.MapContext.from_project(p)
