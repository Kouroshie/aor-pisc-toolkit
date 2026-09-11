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

import io
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

# Matches containment.viz: pressure front blue, plume orange, AoR ink.
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
            "`pip install folium` or `pip install containment[gis]`")


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

    ``result`` is an :class:`containment.delineate.AoRResult`; ``wells`` a list of
    project wells with ``x``/``y``/``name``; ``penetrations`` a
    :class:`containment.corrective.CorrectiveActionPlan` or a list of
    :class:`containment.corrective.ArtificialPenetration`.
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


# ==========================================================================
# a static map, for documents that cannot hold a web page
# ==========================================================================
_OSM_TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
_TILE_SIZE = 256


def _deg2num(lon: float, lat: float, z: int) -> tuple[float, float]:
    """Longitude and latitude to fractional slippy-map tile coordinates."""
    lat_r = np.radians(lat)
    n = 2.0 ** z
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - np.log(np.tan(lat_r) + 1.0 / np.cos(lat_r)) / np.pi) / 2.0 * n
    return x, y


def _num2deg(x: float, y: float, z: int) -> tuple[float, float]:
    n = 2.0 ** z
    lon = x / n * 360.0 - 180.0
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1.0 - 2.0 * y / n))))
    return lon, lat


def _tile_url(basemap: str, z: int, x: int, y: int) -> str:
    spec = BASEMAPS.get(basemap, BASEMAPS["satellite"])
    tiles = spec["tiles"]
    if not isinstance(tiles, str) or tiles.lower() == "openstreetmap":
        tiles = _OSM_TILES
    return (tiles.replace("{z}", str(z)).replace("{x}", str(x))
            .replace("{y}", str(y)).replace("{s}", "a"))


def _fetch_tiles(bounds, basemap: str, width_px: int = 1100, timeout: float = 20.0):
    """Download and stitch the basemap tiles covering ``bounds``.

    ``bounds`` is (west, south, east, north) in degrees. Returns the mosaic as
    an array together with its extent in degrees, or None when the tiles
    cannot be fetched, which is the normal outcome on a machine with no
    network and must not be fatal.
    """
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor

    try:
        import matplotlib.image as mpimg
    except ImportError:
        return None

    west, south, east, north = bounds
    # pick the zoom whose tiles give at least the requested width
    zoom = 2
    for z in range(2, 19):
        x0, _ = _deg2num(west, north, z)
        x1, _ = _deg2num(east, south, z)
        if (x1 - x0) * _TILE_SIZE >= width_px:
            zoom = z
            break
        zoom = z

    x0f, y0f = _deg2num(west, north, zoom)
    x1f, y1f = _deg2num(east, south, zoom)
    x0, x1 = int(np.floor(x0f)), int(np.floor(x1f))
    y0, y1 = int(np.floor(y0f)), int(np.floor(y1f))
    if (x1 - x0 + 1) * (y1 - y0 + 1) > 144:      # keep the request polite
        return None

    def one(args):
        tx, ty = args
        url = _tile_url(basemap, zoom, tx, ty)
        req = urllib.request.Request(
            url, headers={"User-Agent": "containment/0.1 (UIC Class VI toolkit)"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as fh:
                return (tx, ty, mpimg.imread(io.BytesIO(fh.read()), format="png"
                                             if url.endswith(".png") else "jpeg"))
        except Exception:
            return (tx, ty, None)

    coords = [(tx, ty) for tx in range(x0, x1 + 1) for ty in range(y0, y1 + 1)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        tiles = list(pool.map(one, coords))
    if all(t[2] is None for t in tiles):
        return None

    nx, ny = x1 - x0 + 1, y1 - y0 + 1
    mosaic = np.ones((ny * _TILE_SIZE, nx * _TILE_SIZE, 3), dtype=float) * 0.93
    for tx, ty, img in tiles:
        if img is None:
            continue
        arr = np.asarray(img, dtype=float)
        if arr.max() > 1.5:
            arr = arr / 255.0
        arr = arr[..., :3] if arr.ndim == 3 else np.dstack([arr] * 3)
        r0 = (ty - y0) * _TILE_SIZE
        c0 = (tx - x0) * _TILE_SIZE
        mosaic[r0:r0 + arr.shape[0], c0:c0 + arr.shape[1]] = arr

    w_deg, n_deg = _num2deg(x0, y0, zoom)
    e_deg, s_deg = _num2deg(x1 + 1, y1 + 1, zoom)
    return mosaic, (w_deg, e_deg, s_deg, n_deg)


def static_map(result, ctx: MapContext, *, basemap: str = "satellite",
               wells=None, penetrations=None, title: str = "",
               theme: str = "light", figsize=(9.0, 8.0), pad: float = 0.35,
               ax=None):
    """The AoR on a real basemap, as a matplotlib figure.

    The interactive map is the better artefact and cannot be pasted into a
    permit application, a board paper or a Word document. This draws the same
    content on stitched basemap tiles so it can be.

    Requires a network connection for the tiles. Without one the geometry is
    still drawn, on a plain background, and the figure says so rather than
    failing.
    """
    import matplotlib.pyplot as plt

    from . import viz

    p = viz.palette(theme)
    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    else:
        fig = ax.figure

    def to_lonlat(geom):
        from shapely.ops import transform

        return transform(lambda x, y, z=None: ctx.crs.to_lonlat(x, y), geom)

    aor = to_lonlat(result.aor)
    west, south, east, north = aor.bounds
    dx, dy = (east - west) or 0.01, (north - south) or 0.01
    bounds = (west - pad * dx, south - pad * dy, east + pad * dx, north + pad * dy)

    fetched = _fetch_tiles(bounds, basemap)
    if fetched is not None:
        mosaic, (w, e, s, n) = fetched
        ax.imshow(mosaic, extent=(w, e, s, n), origin="upper",
                  interpolation="bilinear", zorder=0)
    else:
        ax.set_facecolor(p["surface"])
        ax.text(0.5, 0.02, "basemap tiles unavailable offline; geometry only",
                transform=ax.transAxes, ha="center", fontsize=8,
                color=p["ink_3"])

    def draw(geom, colour, lw, label, ls="-", fill=None):
        if geom is None or geom.is_empty:
            return
        g = to_lonlat(geom)
        first = True
        for poly in (g.geoms if hasattr(g, "geoms") else [g]):
            xy = np.asarray(poly.exterior.coords)
            if fill:
                ax.fill(xy[:, 0], xy[:, 1], color=fill, zorder=2, lw=0)
            ax.plot(xy[:, 0], xy[:, 1], color=colour, lw=lw, ls=ls, zorder=3,
                    label=label if first else None)
            first = False

    draw(result.pressure_front, p["series"][viz.PRESSURE_COLOR], 2.0,
         "pressure front", fill=(0.16, 0.47, 0.84, 0.12))
    draw(result.plume, p["series"][viz.PLUME_COLOR], 2.0, "CO2 plume",
         fill=(0.92, 0.41, 0.20, 0.16))
    draw(result.aor, p["ink"], 3.0,
         f"AoR - {result.area_acres:,.0f} acres", ls="--")

    if wells:
        for kind, marker, colour, label in (
                ("injector", "v", p["ink"], "CO2 injector"),
                ("extractor", "^", p["series"][2], "brine extractor")):
            sel = [w for w in wells if getattr(w, "kind", "injector") == kind]
            if not sel:
                continue
            lon, lat = zip(*[ctx.crs.to_lonlat(w.x, w.y) for w in sel],
                           strict=True)
            ax.scatter(lon, lat, s=110, marker=marker, color=colour,
                       edgecolor="white", linewidth=1.6, zorder=6, label=label)

    if penetrations is not None:
        colours = {"corrective action": p["critical"],
                   "field testing": p["warning"],
                   "monitor": p["ink_2"], "no action": p["ink_3"]}
        wells_list = getattr(penetrations, "wells", penetrations) or []
        for action, colour in colours.items():
            sel = [w for w in wells_list
                   if getattr(w, "in_aor", False) and getattr(w, "action", "") == action]
            if not sel:
                continue
            lon, lat = zip(*[ctx.crs.to_lonlat(w.x, w.y) for w in sel],
                           strict=True)
            ax.scatter(lon, lat, s=55, marker="X" if action == "corrective action"
                       else "o", color=colour, edgecolor="white", linewidth=1.0,
                       zorder=7, label=f"{action} ({len(sel)})")

    ax.set_xlim(bounds[0], bounds[2])
    ax.set_ylim(bounds[1], bounds[3])
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    name = BASEMAPS.get(basemap, {}).get("name", basemap)
    ax.set_title(title or f"Area of Review on {name}", loc="left",
                 fontsize=12, color=p["ink"])
    attr = BASEMAPS.get(basemap, {}).get("attr") or "OpenStreetMap contributors"
    ax.text(0.995, 0.01, str(attr), transform=ax.transAxes, ha="right",
            fontsize=7, color="white",
            bbox=dict(facecolor="black", alpha=0.35, pad=1.5, edgecolor="none"))
    leg = ax.legend(loc="upper right", fontsize=8, framealpha=0.92)
    leg.set_zorder(8)
    ax.set_aspect(1.0 / np.cos(np.radians(0.5 * (bounds[1] + bounds[3]))))
    fig.tight_layout()
    return fig


def static_map_set(result, ctx: MapContext, *, basemaps=None, **kw):
    """One static map per basemap. Returns {basemap key: figure}."""
    keys = list(basemaps or BASEMAPS)
    return {k: static_map(result, ctx, basemap=k, **kw) for k in keys}


__all__ = ["HAVE_FOLIUM", "BASEMAPS", "MapContext", "build_map", "write_map",
           "map_html", "static_map", "static_map_set"]
