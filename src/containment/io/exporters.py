"""Write AoR polygons and tables out in formats a permit reviewer can open.

An AoR that exists only inside a Python session is not much use.  These
writers produce GeoJSON (for web maps and QGIS/ArcGIS), KML (for Google
Earth, which is what most landmen and field staff actually have), plain CSV
vertex lists (for a surveyor or a plat), and ``.npz`` archives (for handing
the raw fields to somebody else's tool).

Coordinates
-----------
The solver works in a local metric frame with the origin wherever the user
put it.  :class:`LocalCRS` converts that frame to longitude/latitude.  If
``pyproj`` is installed it uses a proper projected CRS -- give it an EPSG code
(a Texas State Plane zone, say) and the transform is exact.  Without pyproj it
falls back to a local tangent-plane approximation about an origin lat/lon,
which is accurate to well under a metre over an AoR-sized area but is *not* a
survey-grade transform, and says so in the file it writes.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass

import numpy as np

from .. import units as U

try:
    from pyproj import Transformer

    HAVE_PYPROJ = True
except Exception:  # pragma: no cover
    Transformer = None
    HAVE_PYPROJ = False


def _axis_metres(epsg: int) -> float:
    """How many metres one unit of this CRS's horizontal axis is.

    Returns 1.0 for a metric CRS and about 0.3048 for a foot-based one. Falls
    back to metres, with no exception, if the CRS cannot be interrogated.
    """
    try:
        from pyproj import CRS

        ax = CRS.from_epsg(int(epsg)).axis_info
        conv = [a.unit_conversion_factor for a in ax
                if getattr(a, "unit_name", "").lower() not in ("degree", "metre")
                or getattr(a, "abbrev", "") in ("E", "N", "X", "Y")]
        for a in ax:
            if a.abbrev in ("E", "N", "X", "Y") or "asting" in a.name or "orthing" in a.name:
                return float(a.unit_conversion_factor)
        return float(conv[0]) if conv else 1.0
    except Exception:  # pragma: no cover
        return 1.0


# ==========================================================================
@dataclass
class LocalCRS:
    """Map model (x, y) in metres to longitude/latitude.

    Supply either ``epsg`` (with pyproj installed) for an exact transform, or
    ``origin_lon``/``origin_lat`` for the tangent-plane approximation.

    Model coordinates are always metres; ``x_offset``/``y_offset`` are in the
    projected CRS's own units, because that is how a user reads an easting off
    a plat. Those units are not always metres -- the Texas State Plane and BLM
    zones an operator is most likely to quote are in US survey feet -- so the
    axis unit is read from the CRS and applied here. Getting this wrong scales
    the whole model by 3.28, which no other check would catch.
    """

    epsg: int | None = None
    origin_lon: float | None = None
    origin_lat: float | None = None
    x_offset: float = 0.0
    y_offset: float = 0.0
    unit_to_m: float = 1.0

    def __post_init__(self):
        self._tf = None
        self._inv = None
        if self.epsg is not None:
            if not HAVE_PYPROJ:
                raise ImportError(
                    "pyproj is required for an EPSG-based transform; "
                    "install it, or give origin_lon/origin_lat instead")
            self._tf = Transformer.from_crs(f"EPSG:{self.epsg}", "EPSG:4326",
                                            always_xy=True)
            self._inv = Transformer.from_crs("EPSG:4326", f"EPSG:{self.epsg}",
                                             always_xy=True)
            self.unit_to_m = _axis_metres(self.epsg)

    @property
    def exact(self) -> bool:
        return self._tf is not None

    def to_lonlat(self, x, y):
        x = np.asarray(x, float) / self.unit_to_m + self.x_offset
        y = np.asarray(y, float) / self.unit_to_m + self.y_offset
        if self._tf is not None:
            lon, lat = self._tf.transform(x, y)
            return np.asarray(lon), np.asarray(lat)
        if self.origin_lon is None or self.origin_lat is None:
            # no georeferencing available: pass model metres through unchanged
            return x, y
        lat0 = math.radians(self.origin_lat)
        m_per_deg_lat = 111132.92 - 559.82 * math.cos(2 * lat0) \
            + 1.175 * math.cos(4 * lat0)
        m_per_deg_lon = 111412.84 * math.cos(lat0) - 93.5 * math.cos(3 * lat0)
        return (self.origin_lon + x / m_per_deg_lon,
                self.origin_lat + y / m_per_deg_lat)

    def from_lonlat(self, lon, lat):
        """Inverse of :meth:`to_lonlat`: longitude/latitude to model metres.

        Lets a project give well locations in latitude and longitude and have
        the local frame built for it, which is how site data actually arrives.
        """
        lon = np.asarray(lon, float)
        lat = np.asarray(lat, float)
        if self._inv is not None:
            x, y = self._inv.transform(lon, lat)
            return ((np.asarray(x) - self.x_offset) * self.unit_to_m,
                    (np.asarray(y) - self.y_offset) * self.unit_to_m)
        if self.origin_lon is None or self.origin_lat is None:
            return lon, lat
        lat0 = math.radians(self.origin_lat)
        m_per_deg_lat = (111132.92 - 559.82 * math.cos(2 * lat0)
                         + 1.175 * math.cos(4 * lat0))
        m_per_deg_lon = 111412.84 * math.cos(lat0) - 93.5 * math.cos(3 * lat0)
        return ((lon - self.origin_lon) * m_per_deg_lon - self.x_offset,
                (lat - self.origin_lat) * m_per_deg_lat - self.y_offset)

    def describe(self) -> dict:
        if self._tf is not None:
            return {"kind": "pyproj", "source_epsg": self.epsg,
                    "target": "EPSG:4326",
                    "crs_unit_in_metres": round(self.unit_to_m, 9)}
        if self.origin_lon is None:
            return {"kind": "none", "note": "coordinates written in model metres"}
        return {"kind": "local tangent plane (approximate)",
                "origin_lon": self.origin_lon, "origin_lat": self.origin_lat,
                "note": "accurate to well under a metre at AoR scale; not a "
                        "survey-grade transform"}


def _reproject(geom, crs: LocalCRS | None):
    if crs is None:
        return geom
    from shapely.ops import transform

    return transform(lambda x, y, z=None: crs.to_lonlat(x, y), geom)


def _geoms(geom):
    if geom is None or geom.is_empty:
        return []
    return list(geom.geoms) if hasattr(geom, "geoms") else [geom]


# ==========================================================================
def to_geojson(result, crs: LocalCRS | None = None,
               properties: dict | None = None) -> dict:
    """GeoJSON FeatureCollection with the AoR, plume and pressure-front rings."""
    from shapely.geometry import mapping

    feats = []
    base = dict(properties or {})
    for name, geom in (("aor", result.aor), ("plume", result.plume),
                       ("pressure_front", result.pressure_front)):
        if geom is None or geom.is_empty:
            continue
        g = _reproject(geom, crs)
        feats.append({
            "type": "Feature",
            "properties": {
                **base,
                "component": name,
                "area_acres": U.area_out(geom.area, "acres"),
                "area_sq_mi": U.area_out(geom.area, "mi2"),
                "threshold_pressure_psi": U.pressure_out(result.threshold_pressure, "psi"),
                "plume_criterion": result.plume_criterion,
                "method": result.method,
            },
            "geometry": mapping(g),
        })
    fc = {"type": "FeatureCollection", "features": feats,
          "containment": {"crs": (crs.describe() if crs else {"kind": "none"}),
                      "summary": result.summary()}}
    if crs is not None and crs.exact is False and crs.origin_lon is not None:
        fc["containment"]["warning"] = (
            "coordinates were converted with a local tangent-plane "
            "approximation; install pyproj and supply an EPSG code for a "
            "survey-grade transform")
    return fc


def write_polygons(result, path: str, crs: LocalCRS | None = None,
                   properties: dict | None = None) -> str:
    """Write the AoR as GeoJSON (``.geojson``/``.json``) or KML (``.kml``)."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".geojson", ".json"):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(to_geojson(result, crs, properties), fh, indent=2)
    elif ext == ".kml":
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(to_kml(result, crs))
    elif ext == ".csv":
        to_csv(result, path, crs)
    else:
        raise ValueError(f"unsupported extension {ext!r}; use .geojson, .kml or .csv")
    return path


def to_kml(result, crs: LocalCRS | None = None) -> str:
    """KML document with one styled polygon per component."""
    style = {
        "aor": ("ff0000ff", "330000ff"),
        "plume": ("ffff8800", "33ff8800"),
        "pressure_front": ("ff00aa00", "3300aa00"),
    }
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
             f"<name>Area of Review - {result.method}</name>"]
    for name, (line, fill) in style.items():
        parts.append(f'<Style id="{name}"><LineStyle><color>{line}</color>'
                     f"<width>2</width></LineStyle>"
                     f"<PolyStyle><color>{fill}</color></PolyStyle></Style>")

    for name, geom in (("pressure_front", result.pressure_front),
                       ("plume", result.plume), ("aor", result.aor)):
        for k, g in enumerate(_geoms(geom)):
            gg = _reproject(g, crs)
            rings = []
            coords = " ".join(f"{px:.8f},{py:.8f},0"
                              for px, py in gg.exterior.coords)
            rings.append(f"<outerBoundaryIs><LinearRing><coordinates>{coords}"
                         "</coordinates></LinearRing></outerBoundaryIs>")
            for interior in gg.interiors:
                ic = " ".join(f"{px:.8f},{py:.8f},0" for px, py in interior.coords)
                rings.append(f"<innerBoundaryIs><LinearRing><coordinates>{ic}"
                             "</coordinates></LinearRing></innerBoundaryIs>")
            parts.append(
                f"<Placemark><name>{name} {k + 1}</name>"
                f"<styleUrl>#{name}</styleUrl>"
                f"<description>{U.area_out(g.area, 'acres'):,.0f} acres</description>"
                f"<Polygon>{''.join(rings)}</Polygon></Placemark>")
    parts.append("</Document></kml>")
    return "\n".join(parts)


def to_csv(result, path: str, crs: LocalCRS | None = None) -> str:
    """Vertex list, one row per point: component, ring, index, x/lon, y/lat."""
    import csv

    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["component", "part", "ring", "vertex", "x_or_lon", "y_or_lat"])
        for name, geom in (("aor", result.aor), ("plume", result.plume),
                           ("pressure_front", result.pressure_front)):
            for pi, g in enumerate(_geoms(geom)):
                gg = _reproject(g, crs)
                for ri, ring in enumerate([gg.exterior, *gg.interiors]):
                    for vi, (px, py) in enumerate(ring.coords):
                        w.writerow([name, pi, ri, vi, f"{px:.6f}", f"{py:.6f}"])
    return path


def save_npz(path: str, x, y, times, dp=None, plume=None, **extra) -> str:
    """Archive gridded fields for reuse or hand-off."""
    payload = {"x": np.asarray(x), "y": np.asarray(y), "times": np.asarray(times)}
    if dp is not None:
        payload["dp"] = np.asarray(dp)
    if plume is not None:
        payload["plume"] = np.asarray(plume)
    payload.update({k: np.asarray(v) for k, v in extra.items()})
    np.savez_compressed(path, **payload)
    return path


def table_to_csv(rows: list[dict], path: str) -> str:
    """Write a list of dicts as CSV, using the union of keys as the header."""
    import csv

    if not rows:
        open(path, "w", encoding="utf-8").close()
        return path
    keys: list[str] = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path


__all__ = ["LocalCRS", "HAVE_PYPROJ", "to_geojson", "write_polygons", "to_kml",
           "to_csv", "save_npz", "table_to_csv"]
