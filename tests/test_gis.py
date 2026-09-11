"""Georeferencing and the GIS map."""

import math

import numpy as np
import pytest

from aorpisc import delineate, gis
from aorpisc import units as U
from aorpisc.config import Project
from aorpisc.io.exporters import HAVE_PYPROJ, LocalCRS

WELLS_LATLON = [
    {"name": "INJ-1", "latitude": 31.9686, "longitude": -99.9018,
     "rate": 0.5, "start_year": 0, "stop_year": 10},
    {"name": "INJ-2", "latitude": 31.9686, "longitude": -99.8890,
     "rate": 0.5, "start_year": 0, "stop_year": 10},
]
FORMATION = {
    "injection_zone": {"top_depth": 6000, "thickness": 250, "porosity": 0.18,
                       "permeability": 150, "temperature": 150,
                       "salinity_ppm": 90000, "initial_pressure": 2600},
    "usdw": {"base_depth": 1200, "initial_pressure": 520},
}


def _project(**extra):
    d = {"units": {"depth": "ft", "length": "ft", "pressure": "psi",
                   "temperature": "F", "rate": "MMT/yr"},
         "formation": FORMATION, "wells": WELLS_LATLON}
    d.update(extra)
    return Project.from_dict(d)


def _disc(radius_m=2000.0, cx=0.0, cy=0.0):
    x = np.linspace(cx - 3 * radius_m, cx + 3 * radius_m, 241)
    y = np.linspace(cy - 3 * radius_m, cy + 3 * radius_m, 241)
    X, Y = np.meshgrid(x, y)
    f = np.exp(-np.log(2.0) * (np.hypot(X - cx, Y - cy) / radius_m) ** 2)
    return delineate.delineate(x, y, plume_field=f, plume_level=0.5,
                               plume_criterion="test disc")


# ==========================================================================
def test_latlon_wells_build_a_local_frame():
    p = _project()
    assert all(np.isfinite(w.x) and np.isfinite(w.y) for w in p.wells)
    # 0.0128 deg of longitude at 32 N is about 1,200 m
    sep = math.hypot(p.wells[0].x - p.wells[1].x, p.wells[0].y - p.wells[1].y)
    assert 1150 < sep < 1260, sep
    # the origin sits at the centre of the well field
    assert abs(np.mean([w.x for w in p.wells])) < 1.0
    assert abs(np.mean([w.y for w in p.wells])) < 1.0
    assert p.warnings == []


@pytest.mark.skipif(not HAVE_PYPROJ, reason="pyproj not installed")
def test_utm_zone_is_chosen_from_the_wells():
    p = _project()
    assert p.crs["epsg"] == 32614           # -99.9 E is UTM zone 14N
    assert "UTM zone 14N" in p.crs["note"]


def test_pinned_frame_is_honoured():
    """Two projects sharing a frame must place the same well identically.

    This is the multi-formation case: one site modelled as several projects,
    whose polygons have to line up when they are combined.
    """
    pinned = ({"crs": {"epsg": 32614, "x_offset": 415000.0, "y_offset": 3537000.0}}
              if HAVE_PYPROJ else
              {"crs": {"origin_lon": -99.9018, "origin_lat": 31.9686,
                       "x_offset": 0.0, "y_offset": 0.0}})
    a = _project(project=pinned)
    b = Project.from_dict({
        "project": pinned,
        "units": {"depth": "ft", "length": "ft", "pressure": "psi",
                  "temperature": "F", "rate": "MMT/yr"},
        "formation": FORMATION,
        "wells": [WELLS_LATLON[0]],
    })
    assert a.wells[0].x == pytest.approx(b.wells[0].x, abs=1e-6)
    assert a.wells[0].y == pytest.approx(b.wells[0].y, abs=1e-6)


def test_round_trip_through_the_local_frame():
    p = _project()
    crs = gis.MapContext.from_project(p).crs
    for w in p.wells:
        lon, lat = crs.to_lonlat(np.array([w.x]), np.array([w.y]))
        assert float(lon[0]) == pytest.approx(w.longitude, abs=1e-6)
        assert float(lat[0]) == pytest.approx(w.latitude, abs=1e-6)


def test_ungeoreferenced_project_says_so_clearly():
    p = Project.from_dict({
        "units": {"depth": "ft", "length": "ft", "pressure": "psi",
                  "temperature": "F", "rate": "MMT/yr"},
        "formation": FORMATION,
        "wells": [{"name": "I", "x": 0, "y": 0, "rate": 0.5,
                   "start_year": 0, "stop_year": 10}],
    })
    with pytest.raises(ValueError, match="no georeferencing"):
        gis.MapContext.from_project(p)


# ==========================================================================
@pytest.mark.skipif(not gis.HAVE_FOLIUM, reason="folium not installed")
def test_map_contains_every_layer(tmp_path):
    p = _project()
    ctx = gis.MapContext.from_project(p)
    aor = _disc()
    path = tmp_path / "m.html"
    gis.write_map(aor, str(path), ctx, wells=p.wells, title="test")
    html = path.read_text(encoding="utf-8")

    for expected in ("Satellite imagery", "Streets (OSM)", "Topographic",
                     "Shaded relief", "Area of Review", "CO2 plume",
                     "Pressure front", "Project wells"):
        assert expected in html, expected
    assert "leaflet" in html.lower()
    assert f"{aor.area_acres:,.0f} acres" in html
    # the requested basemap has to be the one shown first
    assert html.index("World_Imagery") < html.index("World_Topo_Map")


@pytest.mark.skipif(not gis.HAVE_FOLIUM, reason="folium not installed")
def test_map_places_the_polygon_at_the_right_place():
    p = _project()
    ctx = gis.MapContext.from_project(p)
    html = gis.map_html(_disc(radius_m=1500.0), ctx, wells=p.wells)
    assert "31.9" in html
    assert "-99.8" in html or "-99.9" in html


@pytest.mark.skipif(not gis.HAVE_FOLIUM, reason="folium not installed")
def test_penetrations_are_grouped_by_action():
    from aorpisc import corrective

    p = _project()
    ctx = gis.MapContext.from_project(p)
    aor = _disc(radius_m=2500.0)
    wells = [
        corrective.ArtificialPenetration(name="needs-CA", x=300.0, y=0.0,
                                         total_depth=U.length(6500, "ft"),
                                         status="plugged", records_complete=True,
                                         plug_depths=()),
        corrective.ArtificialPenetration(name="clean", x=-400.0, y=200.0,
                                         total_depth=U.length(2000, "ft")),
        corrective.ArtificialPenetration(name="far-away", x=90000.0, y=0.0,
                                         total_depth=U.length(6500, "ft")),
    ]
    plan = corrective.screen(wells, aor, U.length(5700, "ft"), U.length(6000, "ft"))
    html = gis.map_html(aor, ctx, wells=p.wells, penetrations=plan)
    assert "Penetrations: Corrective action required" in html
    assert "Penetrations: outside the AoR" in html
    assert "needs-CA" in html and "far-away" in html
    assert "Corrective action required (1)" in html      # the legend count


@pytest.mark.skipif(not gis.HAVE_FOLIUM, reason="folium not installed")
def test_empty_aor_is_refused():
    from shapely.geometry import MultiPolygon

    ctx = gis.MapContext.from_project(_project())
    empty = delineate.AoRResult(plume=MultiPolygon(), pressure_front=MultiPolygon(),
                                aor=MultiPolygon(), threshold_pressure=1.0)
    with pytest.raises(ValueError, match="nothing to map"):
        gis.map_html(empty, ctx)


def test_local_crs_inverse_round_trip():
    crs = LocalCRS(origin_lon=-97.5, origin_lat=27.5)
    x = np.array([0.0, 1234.0, -5000.0])
    y = np.array([0.0, -987.0, 4200.0])
    lon, lat = crs.to_lonlat(x, y)
    bx, by = crs.from_lonlat(lon, lat)
    assert np.allclose(bx, x, atol=1e-6)
    assert np.allclose(by, y, atol=1e-6)


def test_penetration_csv_reads_latlon(tmp_path):
    from aorpisc import corrective

    path = tmp_path / "w.csv"
    path.write_text("name,latitude,longitude,total_depth\n"
                    "A,31.9686,-99.9018,6500\n"
                    "B,31.9750,-99.8900,3000\n", encoding="utf-8")
    p = _project()
    crs = gis.MapContext.from_project(p).crs
    wells = corrective.load_wells_csv(str(path), unit="ft", crs=crs)
    assert len(wells) == 2
    assert wells[0].latitude == pytest.approx(31.9686)
    # A sits on INJ-1, so it must land on the west well in the model frame
    assert abs(wells[0].x - p.wells[0].x) < 1.0
    assert abs(wells[0].y - p.wells[0].y) < 1.0
