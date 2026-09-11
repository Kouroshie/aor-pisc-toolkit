"""Put the AoR on a real map.

A polygon in model coordinates is an engineering result. A polygon on
satellite imagery, with the injectors and every legacy well on it, is
something a landman, a field inspector, a surface owner or a hearings
examiner can act on. This module produces the second one: a self-contained
HTML file that opens in any browser, with no server, no account and no API
key.

Basemaps offered, all free and keyless:

``satellite``  Esri World Imagery - what the AoR figures in most Class VI
               applications are drawn on
``streets``    OpenStreetMap - roads, parcels, place names
``topo``       Esri World Topographic
``terrain``    Esri World Shaded Relief

All four are added as switchable layers, so the reader can flip between
imagery and roads without regenerating anything.

Georeferencing
--------------
The solver works in a local metric frame. Getting onto a real map needs a
transform, and there are two ways in:

* give the wells ``latitude`` and ``longitude`` in the project file, and the
  local frame is built around them automatically; or
* give ``project.crs.epsg`` (exact, needs pyproj) or
  ``project.crs.origin_lon`` / ``origin_lat`` (a local tangent-plane
  approximation, good to well under a metre at AoR scale).

Whichever is used is written into the map's own caption, because a map with
an unstated datum is not evidence.
"""

from __future__ import annotations

import json

from dataclasses import dataclass

import numpy as np

from . import units as U
from .io.exporters import LocalCRS

try:
    import folium
    from folium.plugins import Fullscreen, MeasureControl, MiniMap

    HAVE_FOLIUM = True
except Exception:  # pragma: no cover
    folium = None
    HAVE_FOLIUM = False


BASEMAPS = {
    "satellite": dict(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/"
              "World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri, Maxar, Earthstar Geographics", name="Satellite imagery"),
    "streets": dict(tiles="OpenStreetMap", attr=None, name="Streets (OSM)"),
    "topo": dict(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/"
              "World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
        attr="Esri, USGS, NOAA", name="Topographic"),
    "terrain": dict(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/"
              "World_Shaded_Relief/MapServer/tile/{z}/{y}/{x}",
        attr="Esri", name="Shaded relief"),
}

# Matches aorpisc.viz: pressure front blue, plume orange, AoR ink.
STYLE = {
    "aor": dict(color="#0b0b0b", weight=4, fill=False, dashArray=None),
    "plume": dict(color="#eb6834", weight=2.5, fill=True, fillOpacity=0.25),
    "pressure_front": dict(color="#2a78d6", weight=2.5, fill=True, fillOpacity=0.12),
}
ACTION_STYLE = {
    "corrective action": ("#d03b3b", "xmark", "Corrective action required"),
    "field testing": ("#fab219", "wrench", "Field testing required"),
    "monitor": ("#52514e", "eye", "Monitor"),
    "no action": ("#8a8983", "circle", "No action"),
}


def _require():
    if not HAVE_FOLIUM:
        raise ImportError(
            "folium is required for the GIS map; install with "
            "`pip install folium` or `pip install aorpisc[gis]`")


# ==========================================================================
@dataclass
class MapContext:
    """Everything needed to place a run on a real map."""

    crs: LocalCRS
    note: str = ""

    @classmethod
    def from_project(cls, project) -> MapContext:
        """Build the transform a project implies, or raise a useful error."""
        from .workflow import project_crs

        crs_cfg = getattr(project, "crs", None) or {}
        crs = project_crs(project)
        if crs is not None and crs.exact:
            return cls(crs, f"EPSG:{crs_cfg['epsg']} to WGS84, exact (pyproj)"
                            + (f" - {crs_cfg['note']}" if crs_cfg.get("note") else ""))
        if crs is not None:
            return cls(crs, f"local tangent plane about "
                            f"{float(crs_cfg['origin_lat']):.5f} N, "
                            f"{float(crs_cfg['origin_lon']):.5f} E (approximate)")
        raise ValueError(
            "this project has no georeferencing, so it cannot be put on a map. "
            "Either give the wells `latitude` and `longitude`, or set "
            "`project.crs.epsg`, or set `project.crs.origin_lon` and "
            "`origin_lat`. See docs/input_schema.md.")

    def lonlat(self, x, y):
        return self.crs.to_lonlat(x, y)

    def latlon_pairs(self, coords) -> list[list[float]]:
        xy = np.asarray(coords, float)
        lon, lat = self.lonlat(xy[:, 0], xy[:, 1])
        return [[float(a), float(b)] for a, b in zip(lat, lon, strict=True)]


# ==========================================================================
def _add_geometry(group, geom, ctx: MapContext, style: dict, tooltip: str,
                  popup_html: str | None = None):
    if geom is None or geom.is_empty:
        return 0
    geoms = geom.geoms if hasattr(geom, "geoms") else [geom]
    n = 0
    for g in geoms:
        shell = ctx.latlon_pairs(g.exterior.coords)
        holes = [ctx.latlon_pairs(r.coords) for r in g.interiors]
        poly = folium.Polygon(
            locations=[shell] + holes if holes else shell,
            tooltip=tooltip,
            popup=folium.Popup(popup_html, max_width=380) if popup_html else None,
            **style)
        poly.add_to(group)
        n += 1
    return n


def _bounds(ctx: MapContext, *geoms):
    pts = []
    for g in geoms:
        if g is None or getattr(g, "is_empty", True):
            continue
        x0, y0, x1, y1 = g.bounds
        lon, lat = ctx.lonlat(np.array([x0, x1, x0, x1]), np.array([y0, y0, y1, y1]))
        pts += list(zip(lat, lon, strict=True))
    if not pts:
        return None
    lats = [p[0] for p in pts]
    lons = [p[1] for p in pts]
    return [[min(lats), min(lons)], [max(lats), max(lons)]]


def _legend_html(result, plan, ctx: MapContext, title: str) -> str:
    coincident = result.coincident_with()
    rows = [
        ("#0b0b0b", "dashed" if coincident else "solid",
         f"AoR &mdash; {result.area_acres:,.0f} acres "
         f"({result.area_sq_mi:,.2f} sq mi)"),
        ("#eb6834", "solid", f"CO2 plume ({result.plume_criterion or 'modelled extent'})"),
        ("#2a78d6", "solid", f"Pressure front (dP &ge; "
                             f"{U.pressure_out(result.threshold_pressure, 'psi'):,.0f} psi)"),
    ]
    items = "".join(
        f"<div style='margin:3px 0'><span style='display:inline-block;width:22px;"
        f"border-top:3px {st} {c};vertical-align:middle'></span>"
        f"<span style='margin-left:8px'>{lab}</span></div>"
        for c, st, lab in rows)
    if coincident:
        what = ("the CO2 plume and the pressure front" if coincident == "both"
                else f"the {coincident}")
        items += (f"<div style='margin:5px 0 0;color:#8a8983;font-size:11px'>"
                  f"The AoR boundary lies exactly on {what}, so it is dashed "
                  f"here to leave that line visible.</div>")
    if plan is not None:
        counts = {}
        for w in plan.inside:
            counts[w.action] = counts.get(w.action, 0) + 1
        items += "<div style='margin-top:7px;font-weight:600'>Artificial penetrations</div>"
        for action, (colour, _icon, label) in ACTION_STYLE.items():
            if counts.get(action):
                items += (f"<div style='margin:2px 0'><span style='display:inline-block;"
                          f"width:10px;height:10px;border-radius:50%;background:{colour}'>"
                          f"</span><span style='margin-left:10px'>{label} "
                          f"({counts[action]})</span></div>")
    return f"""
<div style="position:fixed;bottom:22px;left:12px;z-index:9999;background:rgba(252,252,251,.94);
border:1px solid #d8d7d2;border-radius:8px;padding:11px 14px;max-width:330px;
font:12.5px/1.45 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
color:#0b0b0b;box-shadow:0 1px 4px rgba(0,0,0,.12)">
<div style="font-weight:600;margin-bottom:6px">{title}</div>
{items}
<div style="margin-top:8px;color:#8a8983;font-size:11px">
Georeferencing: {ctx.note}<br>
Engineering analysis, not a regulatory determination.</div>
</div>"""


# ==========================================================================
def build_map(result, ctx: MapContext, *, wells=None, penetrations=None,
              basemap: str = "satellite", title: str = "Area of Review",
              extra_geojson: dict | None = None, zoom_padding: float = 0.12):
    """Build a folium map of the AoR, its components, and the wells.

    ``result`` is an :class:`aorpisc.delineate.AoRResult`; ``wells`` a list of
    project wells with ``x``/``y``/``name``; ``penetrations`` a
    :class:`aorpisc.corrective.CorrectiveActionPlan` or a list of
    :class:`aorpisc.corrective.ArtificialPenetration`.
    """
    _require()
    centre = _bounds(ctx, result.aor, result.plume, result.pressure_front)
    if centre is None:
        raise ValueError("nothing to map: the AoR and both components are empty")
    lat0 = 0.5 * (centre[0][0] + centre[1][0])
    lon0 = 0.5 * (centre[0][1] + centre[1][1])

    # Build the map with no base tiles, then add every basemap as a named
    # layer with the requested one first. Passing tiles= to folium.Map labels
    # the layer with its raw URL and leaves the last-added layer selected,
    # which is how you end up looking at shaded relief when you asked for
    # satellite imagery.
    m = folium.Map(location=[lat0, lon0], zoom_start=13, control_scale=True,
                   tiles=None)
    order = [basemap] + [k for k in BASEMAPS if k != basemap]
    for key in order:
        spec = BASEMAPS.get(key)
        if spec is None:
            continue
        folium.TileLayer(tiles=spec["tiles"], attr=spec["attr"],
                         name=spec["name"], overlay=False, control=True,
                         show=(key == order[0])).add_to(m)

    # ---- AoR components, each its own toggleable layer -------------------
    g_press = folium.FeatureGroup(name="Pressure front", show=True)
    _add_geometry(g_press, result.pressure_front, ctx, STYLE["pressure_front"],
                  tooltip=f"Pressure front &ge; "
                          f"{U.pressure_out(result.threshold_pressure, 'psi'):,.0f} psi",
                  popup_html=f"<b>Pressure front</b><br>threshold "
                             f"{U.pressure_out(result.threshold_pressure, 'psi'):,.0f} psi"
                             f"<br>{U.area_out(result.pressure_front.area, 'acres'):,.0f} acres"
                             if not result.pressure_front.is_empty else None)
    g_press.add_to(m)

    g_plume = folium.FeatureGroup(name="CO2 plume", show=True)
    _add_geometry(g_plume, result.plume, ctx, STYLE["plume"],
                  tooltip="CO2 plume",
                  popup_html=f"<b>CO2 plume</b><br>{result.plume_criterion}<br>"
                             f"{U.area_out(result.plume.area, 'acres'):,.0f} acres"
                             if not result.plume.is_empty else None)
    g_plume.add_to(m)

    # The AoR is a union, so when one component contains the other the union
    # *is* that component and the two boundaries are the same line. Drawn
    # solid and on top, the AoR would paint over the component underneath and
    # the reader could not tell whether that component was missing, empty or
    # hidden. Dashes let the colour beneath show through the gaps.
    coincident = result.coincident_with()
    aor_style = dict(STYLE["aor"])
    if coincident:
        aor_style["dashArray"] = "14,9"
    aor_note = (f"<br>boundary coincides with the {coincident}"
                if coincident and coincident != "both" else
                "<br>boundary coincides with both components" if coincident else "")
    g_aor = folium.FeatureGroup(name="Area of Review", show=True)
    _add_geometry(g_aor, result.aor, ctx, aor_style,
                  tooltip=f"AoR - {result.area_acres:,.0f} acres",
                  popup_html=(f"<b>Area of Review</b><br>"
                              f"{result.area_acres:,.0f} acres "
                              f"({result.area_sq_mi:,.2f} sq mi)<br>"
                              f"controlled by: {result.controlling_component()}"
                              f"{aor_note}<br>"
                              f"<span style='color:#8a8983'>{result.method}</span>"))
    g_aor.add_to(m)

    # ---- wells -----------------------------------------------------------
    if wells:
        g = folium.FeatureGroup(name="Project wells", show=True)
        for w in wells:
            kind = getattr(w, "kind", "injector")
            lon, lat = ctx.lonlat(np.array([w.x]), np.array([w.y]))
            colour = "#0b0b0b" if kind == "injector" else "#1baf7a"
            mass = getattr(w, "total_mass", None)
            detail = ""
            if kind == "injector" and callable(mass):
                detail = f"<br>{U.mass_out(mass(), 'MMT'):,.2f} MMT total"
            folium.Marker(
                [float(lat[0]), float(lon[0])],
                tooltip=f"{w.name} ({kind})",
                popup=folium.Popup(f"<b>{w.name}</b><br>{kind}{detail}", max_width=280),
                icon=folium.Icon(color="black" if kind == "injector" else "green",
                                 icon="arrow-down" if kind == "injector" else "arrow-up",
                                 prefix="fa")).add_to(g)
            folium.CircleMarker([float(lat[0]), float(lon[0])], radius=4,
                                color=colour, fill=True, fillOpacity=1,
                                weight=2).add_to(g)
        g.add_to(m)

    # ---- artificial penetrations ----------------------------------------
    pens = getattr(penetrations, "wells", penetrations) if penetrations else None
    if pens:
        groups = {}
        for action, (_colour, _icon, label) in ACTION_STYLE.items():
            groups[action] = folium.FeatureGroup(
                name=f"Penetrations: {label}", show=action != "no action")
        other = folium.FeatureGroup(name="Penetrations: outside the AoR", show=False)
        for w in pens:
            lon, lat = ctx.lonlat(np.array([w.x]), np.array([w.y]))
            depth = (f"{U.length_out(w.total_depth, 'ft'):,.0f} ft"
                     if np.isfinite(w.total_depth) else "depth not recorded")
            body = (f"<b>{w.name}</b>"
                    + (f" &middot; {w.api}" if w.api else "")
                    + f"<br>{w.kind}, {w.status}<br>TD {depth}")
            if w.in_aor:
                colour = ACTION_STYLE.get(w.action, ("#8a8983",))[0]
                body += (f"<br><b style='color:{colour}'>{w.action}</b>"
                         f"<br><span style='color:#52514e'>{w.action_reason}</span>")
                if np.isfinite(w.arrival_year_plume):
                    body += (f"<br>plume arrives year "
                             f"{w.arrival_year_plume:,.0f}")
                target = groups.get(w.action, other)
            else:
                colour = "#c3c2b7"
                body += "<br>outside the AoR"
                target = other
            folium.CircleMarker(
                [float(lat[0]), float(lon[0])], radius=6, color=colour,
                weight=2, fill=True, fillOpacity=0.85,
                tooltip=f"{w.name}: {w.action or 'outside the AoR'}",
                popup=folium.Popup(body, max_width=340)).add_to(target)
        for g in list(groups.values()) + [other]:
            g.add_to(m)

    if extra_geojson:
        folium.GeoJson(extra_geojson, name="Additional layer").add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    MeasureControl(primary_length_unit="feet", secondary_length_unit="miles",
                   primary_area_unit="acres", secondary_area_unit="sqmiles").add_to(m)
    Fullscreen().add_to(m)
    MiniMap(toggle_display=True, position="bottomright").add_to(m)

    pad = zoom_padding
    dlat = (centre[1][0] - centre[0][0]) * pad
    dlon = (centre[1][1] - centre[0][1]) * pad
    bounds = [[centre[0][0] - dlat, centre[0][1] - dlon],
              [centre[1][0] + dlat, centre[1][1] + dlon]]
    m.fit_bounds(bounds)

    # Leaflet works out the zoom from the size of its container, and a host
    # that lays the page out after the script runs -- an iframe that sizes to
    # its content, a tab that starts hidden, a print stylesheet -- gives it a
    # container of no height. The map then comes up zoomed out to the whole
    # world with no error anywhere. Re-measuring and re-fitting once the
    # window has finished loading costs nothing and makes the map independent
    # of how it is embedded.
    m.get_root().script.add_child(folium.Element(f"""
        (function () {{
            var refit = function () {{
                var mp = {m.get_name()};
                if (!mp) return;
                mp.invalidateSize();
                mp.fitBounds({json.dumps(bounds)});
            }};
            window.addEventListener("load", function () {{ setTimeout(refit, 120); }});
            window.addEventListener("resize", refit);
        }})();"""))
    m.get_root().html.add_child(folium.Element(
        _legend_html(result, penetrations, ctx, title)))
    return m


def write_map(result, path: str, ctx: MapContext, **kw) -> str:
    """Write a self-contained HTML map. Opens offline in any browser."""
    build_map(result, ctx, **kw).save(path)
    return path


def map_html(result, ctx: MapContext, **kw) -> str:
    """Return the map as an HTML string, for embedding."""
    return build_map(result, ctx, **kw).get_root().render()


__all__ = ["HAVE_FOLIUM", "BASEMAPS", "MapContext", "build_map", "write_map",
           "map_html"]
