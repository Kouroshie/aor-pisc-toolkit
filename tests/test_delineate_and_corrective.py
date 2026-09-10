"""AoR delineation geometry, corrective action screening and exports."""

import json

import numpy as np
import pytest

from aorpisc import corrective, delineate
from aorpisc import units as U
from aorpisc.io import exporters


def _radial_field(x, y, radius, peak=1.0, cx=0.0, cy=0.0):
    """A smooth radially symmetric bump that crosses ``0.5 * peak`` at ``radius``."""
    X, Y = np.meshgrid(x, y)
    r = np.hypot(X - cx, Y - cy)
    return peak * np.exp(-np.log(2.0) * (r / radius) ** 2)


# ==========================================================================
def test_contour_of_a_disc_has_the_right_area():
    x = np.linspace(-5000, 5000, 401)
    y = np.linspace(-5000, 5000, 401)
    R = 2000.0
    z = _radial_field(x, y, R)
    poly = delineate.field_to_polygons(x, y, z, 0.5)
    assert poly.area == pytest.approx(np.pi * R ** 2, rel=0.01)


def test_envelope_takes_the_maximum_over_time():
    a = np.zeros((3, 4, 4))
    a[0, 0, 0] = 5.0
    a[2, 3, 3] = 7.0
    env = delineate.envelope(a)
    assert env[0, 0] == 5.0 and env[3, 3] == 7.0 and env[1, 1] == 0.0


def test_aor_is_the_union_not_the_larger_area():
    """Two offset discs: the AoR must exceed either one alone."""
    x = np.linspace(-8000, 8000, 321)
    y = np.linspace(-8000, 8000, 321)
    plume = _radial_field(x, y, 2000.0, cx=-1500.0)
    press = _radial_field(x, y, 2000.0, cx=+1500.0)
    r = delineate.delineate(
        x, y, dp_field=press, threshold_pressure=0.5,
        plume_field=plume, plume_level=0.5)
    a_plume = r.plume.area
    a_press = r.pressure_front.area
    assert r.area_m2 > max(a_plume, a_press)
    assert r.area_m2 < a_plume + a_press          # they overlap
    assert "mixed" in r.controlling_component()


def test_plume_inside_pressure_front_is_reported_as_such():
    x = np.linspace(-9000, 9000, 301)
    y = np.linspace(-9000, 9000, 301)
    r = delineate.delineate(
        x, y, dp_field=_radial_field(x, y, 4000.0), threshold_pressure=0.5,
        plume_field=_radial_field(x, y, 1200.0), plume_level=0.5)
    assert "pressure front everywhere" in r.controlling_component()
    assert r.area_m2 == pytest.approx(r.pressure_front.area, rel=1e-9)


def test_no_pressure_front_is_a_warning_not_a_crash():
    x = np.linspace(-4000, 4000, 161)
    y = np.linspace(-4000, 4000, 161)
    r = delineate.delineate(
        x, y, dp_field=np.zeros((161, 161)), threshold_pressure=100.0,
        plume_field=_radial_field(x, y, 1000.0), plume_level=0.5)
    assert r.pressure_front.is_empty
    assert r.area_m2 > 0
    assert any("does not contribute" in w for w in r.warnings)
    assert "plume only" in r.controlling_component()


def test_domain_too_small_is_flagged():
    x = np.linspace(-2000, 2000, 121)
    y = np.linspace(-2000, 2000, 121)
    z = _radial_field(x, y, 5000.0)      # far larger than the domain
    r = delineate.delineate(x, y, dp_field=z, threshold_pressure=0.5)
    assert any("edge of the model domain" in w or "% of the model domain" in w
               for w in r.warnings)


def test_units_of_area_agree():
    x = np.linspace(-5000, 5000, 301)
    y = np.linspace(-5000, 5000, 301)
    r = delineate.delineate(x, y, plume_field=_radial_field(x, y, 2000.0),
                            plume_level=0.5)
    assert r.area_acres == pytest.approx(U.area_out(r.area_m2, "acres"), rel=1e-12)
    assert r.area_sq_mi == pytest.approx(r.area_acres / 640.0, rel=1e-6)


def test_extent_by_azimuth_matches_a_circle():
    x = np.linspace(-6000, 6000, 401)
    y = np.linspace(-6000, 6000, 401)
    R = 2500.0
    r = delineate.delineate(x, y, plume_field=_radial_field(x, y, R),
                            plume_level=0.5)
    az = r.extent_by_azimuth(0.0, 0.0, 8)
    assert len(az) == 8
    assert all(abs(v - R) / R < 0.03 for v in az.values())
    assert r.max_radius_from(0.0, 0.0) == pytest.approx(R, rel=0.03)


def test_compare_aors_finds_the_new_area():
    x = np.linspace(-9000, 9000, 301)
    y = np.linspace(-9000, 9000, 301)
    small = delineate.delineate(x, y, plume_field=_radial_field(x, y, 2000.0),
                                plume_level=0.5)
    big = delineate.delineate(x, y, plume_field=_radial_field(x, y, 3000.0),
                              plume_level=0.5)
    d = delineate.compare_aors(small, big)
    assert d["change_acres"] > 0
    assert d["newly_included_acres"] == pytest.approx(
        big.area_acres - small.area_acres, rel=0.02)
    assert d["no_longer_included_acres"] < 1.0
    assert "expanded" in d["verdict"]


def test_circles_union():
    poly = delineate.circles_to_polygon([(0.0, 0.0), (500.0, 0.0)], [1000.0, 1000.0])
    assert poly.area < 2 * np.pi * 1000.0 ** 2
    assert poly.area > np.pi * 1000.0 ** 2


# ==========================================================================
def _aor_with_radius(R=3000.0):
    x = np.linspace(-9000, 9000, 241)
    y = np.linspace(-9000, 9000, 241)
    return delineate.delineate(x, y, plume_field=_radial_field(x, y, R),
                               plume_level=0.5, plume_criterion="test disc")


CZ_TOP = U.length(5700, "ft")
CZ_BASE = U.length(6000, "ft")


def _well(**kw):
    base = dict(name="W", x=0.0, y=0.0, total_depth=U.length(6500, "ft"),
                status="plugged", records_complete=True,
                plug_depths=(U.length(5800, "ft"),), plug_material="cement",
                cased=True, year_abandoned=1995)
    base.update(kw)
    return corrective.ArtificialPenetration(**base)


def test_shallow_well_needs_no_action():
    w = corrective.evaluate_well(_well(total_depth=U.length(3000, "ft")),
                                 CZ_TOP, CZ_BASE)
    assert w.action == "no action"
    assert w.penetrates_confining_zone is False


def test_good_modern_plug_needs_no_action():
    w = corrective.evaluate_well(_well(), CZ_TOP, CZ_BASE)
    assert w.action == "no action"
    assert w.penetrates_confining_zone is True


def test_missing_records_go_to_field_testing():
    w = corrective.evaluate_well(_well(records_complete=None), CZ_TOP, CZ_BASE)
    assert w.action == "field testing"


def test_no_plug_across_confining_zone_needs_corrective_action():
    w = corrective.evaluate_well(_well(plug_depths=(U.length(500, "ft"),)),
                                 CZ_TOP, CZ_BASE)
    assert w.action == "corrective action"
    assert "confining zone" in w.action_reason


def test_mechanical_plug_needs_corrective_action():
    w = corrective.evaluate_well(_well(plug_material="cast iron bridge plug"),
                                 CZ_TOP, CZ_BASE)
    assert w.action == "corrective action"
    assert "CO2-compatible" in w.action_reason


def test_pre_1952_abandonment_goes_to_field_testing():
    w = corrective.evaluate_well(_well(year_abandoned=1948), CZ_TOP, CZ_BASE)
    assert w.action == "field testing"
    assert "1952" in w.action_reason


def test_failed_mit_needs_corrective_action():
    w = corrective.evaluate_well(_well(mit_passed=False), CZ_TOP, CZ_BASE)
    assert w.action == "corrective action"


def test_active_well_is_monitored():
    w = corrective.evaluate_well(_well(status="active"), CZ_TOP, CZ_BASE)
    assert w.action == "monitor"


def test_screen_flags_only_wells_inside():
    aor = _aor_with_radius(3000.0)
    wells = [_well(name="inside", x=1000.0, y=0.0, plug_depths=()),
             _well(name="outside", x=8000.0, y=0.0, plug_depths=())]
    plan = corrective.screen(wells, aor, CZ_TOP, CZ_BASE, injectors=[(0.0, 0.0)])
    assert [w.name for w in plan.inside] == ["inside"]
    assert plan.summary()["corrective_action_required"] == 1
    assert plan.wells[0].distance_to_nearest_injector == pytest.approx(1000.0)


def test_unknown_depth_is_warned_about():
    aor = _aor_with_radius()
    plan = corrective.screen([_well(name="mystery", total_depth=float("nan"))],
                             aor, CZ_TOP, CZ_BASE)
    assert any("no recorded total depth" in w for w in plan.warnings)


def test_arrival_times_and_phasing():
    aor = _aor_with_radius(4000.0)
    x = np.linspace(-9000, 9000, 121)
    y = np.linspace(-9000, 9000, 121)
    times = U.time(np.array([0.0, 5.0, 10.0, 20.0]), "yr")
    # a plume that grows outward with time
    fields = np.array([_radial_field(x, y, R) for R in (500.0, 1500.0, 2500.0, 3500.0)])
    wells = [_well(name="near", x=800.0, y=0.0, plug_depths=()),
             _well(name="far", x=3000.0, y=0.0, plug_depths=())]
    plan = corrective.screen(wells, aor, CZ_TOP, CZ_BASE)
    plan = corrective.arrival_times(plan, x, y, times,
                                    plume_fields=fields, plume_level=0.5)
    near = next(w for w in plan.wells if w.name == "near")
    far = next(w for w in plan.wells if w.name == "far")
    assert near.arrival_year_plume < far.arrival_year_plume
    phases = plan.phases((5, 10, 20))
    placed = [n for names in phases.values() for n in names]
    assert set(placed) == {"near", "far"}


def test_newly_included_wells():
    small = _aor_with_radius(1500.0)
    big = _aor_with_radius(4000.0)
    wells = [_well(name="A", x=500.0, plug_depths=()),
             _well(name="B", x=3000.0, plug_depths=())]
    p1 = corrective.screen([_well(name="A", x=500.0, plug_depths=()),
                            _well(name="B", x=3000.0, plug_depths=())],
                           small, CZ_TOP, CZ_BASE)
    p2 = corrective.screen(wells, big, CZ_TOP, CZ_BASE)
    assert corrective.newly_included(p1, p2) == ["B"]


def test_load_wells_csv(tmp_path):
    path = tmp_path / "wells.csv"
    path.write_text(
        "name,x,y,total_depth,plug_depths,plug_material,records_complete\n"
        "A,1000,2000,6500,5800;6400,cement,true\n"
        "B,-500,0,3000,,unknown,false\n", encoding="utf-8")
    wells = corrective.load_wells_csv(str(path), unit="ft")
    assert len(wells) == 2
    assert wells[0].x == pytest.approx(U.length(1000, "ft"))
    assert len(wells[0].plug_depths) == 2
    assert wells[1].records_complete is False


# ==========================================================================
def test_geojson_and_kml_export(tmp_path):
    r = _aor_with_radius(2500.0)
    gj = tmp_path / "aor.geojson"
    exporters.write_polygons(r, str(gj))
    doc = json.loads(gj.read_text(encoding="utf-8"))
    assert doc["type"] == "FeatureCollection"
    assert any(f["properties"]["component"] == "aor" for f in doc["features"])
    assert doc["features"][0]["properties"]["area_acres"] > 0

    kml = tmp_path / "aor.kml"
    exporters.write_polygons(r, str(kml))
    text = kml.read_text(encoding="utf-8")
    assert "<Polygon>" in text and "coordinates" in text

    csv_path = tmp_path / "aor.csv"
    exporters.write_polygons(r, str(csv_path))
    assert csv_path.read_text(encoding="utf-8").count("\n") > 10


def test_local_crs_round_trip_is_plausible():
    crs = exporters.LocalCRS(origin_lon=-97.5, origin_lat=27.5)
    lon, lat = crs.to_lonlat(np.array([0.0, 1000.0]), np.array([0.0, 1000.0]))
    assert lon[0] == pytest.approx(-97.5)
    assert lat[0] == pytest.approx(27.5)
    assert 0.008 < lon[1] + 97.5 < 0.012      # ~1 km east
    assert 0.008 < lat[1] - 27.5 < 0.010


@pytest.mark.skipif(not exporters.HAVE_PYPROJ, reason="pyproj not installed")
def test_epsg_crs_is_exact():
    crs = exporters.LocalCRS(epsg=32614)       # UTM zone 14N
    assert crs.exact
    lon, lat = crs.to_lonlat(np.array([500000.0]), np.array([3000000.0]))
    assert -100 < float(lon[0]) < -98
    assert 26 < float(lat[0]) < 28


def test_save_and_reload_npz(tmp_path):
    from aorpisc.io import importers

    x = np.linspace(0, 1000, 11)
    y = np.linspace(0, 2000, 21)
    times = U.time(np.array([0.0, 10.0]), "yr")
    dp = np.zeros((2, 21, 11))
    dp[1] = 100.0
    path = tmp_path / "f.npz"
    exporters.save_npz(str(path), x, y, times, dp=dp)
    sim = importers.load_field_npz(str(path))
    assert sim.dp.shape == (2, 21, 11)
    assert float(sim.dp_max().max()) == 100.0
