"""Georeferencing and the GIS map."""

import math

import numpy as np
import pytest

from containment import delineate, gis
from containment import units as U
from containment.config import Project
from containment.io.exporters import HAVE_PYPROJ, LocalCRS

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
    from containment import corrective

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
    from containment import corrective

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


@pytest.mark.skipif(not HAVE_PYPROJ, reason="pyproj not installed")
def test_foot_based_crs_is_converted_to_metres():
    """A State Plane or BLM zone quoted in US survey feet must not scale the model.

    Operators commonly pin the model to a foot-based CRS such as EPSG:32064,
    NAD27 / BLM 14N ftUS. Treating its eastings as metres would inflate every
    distance by 3.28 and every area by 10.8, and nothing else in the toolkit
    would notice. The coordinates below are synthetic.
    """
    from containment.io.exporters import _axis_metres

    assert _axis_metres(32064) == pytest.approx(0.3048006, abs=1e-6)
    assert _axis_metres(2278) == pytest.approx(0.3048006, abs=1e-6)   # TX SP S Central
    assert _axis_metres(32614) == pytest.approx(1.0)                  # UTM, metres

    ft = LocalCRS(epsg=32064, x_offset=1361000.0, y_offset=11605000.0)
    m = LocalCRS(epsg=32614)
    lon = np.array([-99.9018, -99.903718])
    lat = np.array([31.9686, 31.949648])
    fx, fy = ft.from_lonlat(lon, lat)
    mx, my = m.from_lonlat(lon, lat)
    sep_ft_crs = float(np.hypot(fx[0] - fx[1], fy[0] - fy[1]))
    sep_utm = float(np.hypot(mx[0] - mx[1], my[0] - my[1]))
    assert sep_ft_crs == pytest.approx(sep_utm, rel=2e-3)   # both in metres now
    assert 2050 < sep_ft_crs < 2150

    blon, blat = ft.to_lonlat(fx, fy)
    assert np.allclose(blon, lon, atol=1e-7)
    assert np.allclose(blat, lat, atol=1e-7)


@pytest.mark.skipif(not HAVE_PYPROJ, reason="pyproj not installed")
def test_project_on_a_foot_based_crs_places_wells_in_metres():
    p = Project.from_dict({
        "project": {"crs": {"epsg": 32064}},
        "units": {"depth": "ft", "length": "ft", "pressure": "psi",
                  "temperature": "F", "rate": "MMT/yr"},
        "formation": FORMATION,
        "wells": [
            {"name": "A", "latitude": 31.9686, "longitude": -99.9018,
             "rate": 1.0, "start_year": 0, "stop_year": 10},
            {"name": "B", "latitude": 31.949648, "longitude": -99.903718,
             "rate": 1.0, "start_year": 0, "stop_year": 10},
        ],
    })
    sep = math.hypot(p.wells[0].x - p.wells[1].x, p.wells[0].y - p.wells[1].y)
    assert 2050 < sep < 2150, sep      # metres, not 6,900 feet


def test_faults_are_read_from_the_project_file():
    """A sealing fault often *sets* the AoR boundary, so it has to be expressible."""
    p = _project(faults=[
        {"name": "Fault A", "multiplier": 0.0,
         "latlon": [[31.95, -99.90], [31.99, -99.86]]},
        {"name": "partial", "multiplier": 0.05, "points": [[-3000, 0], [3000, 500]]},
    ])
    assert [f["name"] for f in p.faults] == ["Fault A", "partial"]
    assert p.faults[0]["multiplier"] == 0.0
    assert len(p.faults[0]["points"]) == 2
    # the lat/lon trace landed in the model frame, near the well field
    xs = [q[0] for q in p.faults[0]["points"]]
    assert all(abs(x) < 60000 for x in xs), xs
    # the local trace was converted from feet to metres
    assert p.faults[1]["points"][0][0] == pytest.approx(U.length(-3000, "ft"))
    assert p.warnings == []


def test_a_fault_with_one_point_is_reported_not_silently_dropped():
    p = _project(faults=[{"name": "stub", "points": [[0, 0]]}])
    assert p.faults == []
    assert any("at least two points" in w for w in p.warnings)


# ==========================================================================
def _nested():
    """An AoR whose pressure front sits wholly inside its plume.

    This is the common case, not an edge case: EPA expects the separate-phase
    plume to run past the pressure front at many sites, and then the union
    *is* the plume and the two boundaries are the same line.
    """
    from shapely.geometry import Point

    plume = Point(0, 0).buffer(1500.0)
    front = Point(0, 0).buffer(600.0)
    return delineate.AoRResult(plume=plume, pressure_front=front,
                               aor=plume.union(front), threshold_pressure=1.1e6,
                               plume_criterion="test")


def test_a_contained_component_makes_the_aor_coincident():
    r = _nested()
    assert r.coincident_with() == "plume"
    assert r.aor.equals(r.plume)


def test_a_genuine_union_is_not_coincident():
    from shapely.geometry import Point

    a = Point(-900, 0).buffer(1500.0)
    b = Point(900, 0).buffer(1500.0)
    r = delineate.AoRResult(plume=a, pressure_front=b, aor=a.union(b),
                            threshold_pressure=1.1e6)
    assert r.coincident_with() == ""


@pytest.mark.skipif(not gis.HAVE_FOLIUM, reason="folium not installed")
def test_map_does_not_paint_out_a_coincident_component():
    """The AoR must not hide the component it is drawn on top of.

    Drawn solid and last, the AoR boundary covers an identical plume boundary
    completely and the reader cannot tell whether the plume is missing, empty
    or underneath. It is dashed instead, and the legend says why.
    """
    ctx = gis.MapContext.from_project(_project())
    html = gis.map_html(_nested(), ctx)
    assert "dashArray" in html and "14,9" in html
    assert "coincides with the plume" in html
    assert "leave that line visible" in html

    # a genuine union keeps the solid boundary
    from shapely.geometry import Point

    a, b = Point(-900, 0).buffer(1500.0), Point(900, 0).buffer(1500.0)
    union = delineate.AoRResult(plume=a, pressure_front=b, aor=a.union(b),
                                threshold_pressure=1.1e6)
    solid = gis.map_html(union, ctx)
    assert "14,9" not in solid
    assert "coincides with" not in solid


def test_static_and_plotly_maps_also_dash_a_coincident_aor():
    from containment import viz

    r = _nested()
    fig = viz.aor_map(r)
    labels = [t.get_label() for a in fig.axes for t in a.patches]
    assert any("on the plume" in str(s) for s in labels), labels

    pf = viz.plotly_aor_map(r)
    aor_traces = [t for t in pf.data if "AoR" in (t.name or "")]
    assert aor_traces and aor_traces[0].line.dash == "dash"
    assert "on the plume" in aor_traces[0].name


@pytest.mark.skipif(not gis.HAVE_FOLIUM, reason="folium not installed")
def test_map_refits_itself_once_the_host_has_laid_out():
    """Leaflet sizes from its container, which a host may not have sized yet.

    An iframe that sizes to its content, a tab that starts hidden, a print
    stylesheet: any of them can leave the container at zero height when the
    script runs, and the map then opens zoomed out to the whole world with no
    error reported anywhere. The document re-measures and re-fits on load.
    """
    ctx = gis.MapContext.from_project(_project())
    html = gis.map_html(_disc(radius_m=1800.0), ctx)
    assert "invalidateSize()" in html
    assert "fitBounds(" in html
    assert 'addEventListener("load"' in html
    assert 'addEventListener("resize"' in html
