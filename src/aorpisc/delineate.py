"""Turn model fields into an Area of Review polygon.

EPA's rule is short and unambiguous (816-R-13-005, Section 3.4, Box 3-2):

  1. compute the threshold pressure that defines the pressure front;
  2. map the **maximum** extent of the pressure front over the whole
     simulation;
  3. map the **maximum** extent of the separate-phase plume over the whole
     simulation;
  4. the AoR is the contour that encompasses whichever is larger, direction by
     direction -- *not* the larger of the two areas, and *not* the pressure
     front alone, because "separate-phase fluids may migrate beyond the extent
     of the pressure front".

Step 4 is a geometric union, and it is where hand-drawn AoRs most often go
wrong.  :func:`delineate` does the union properly and reports the two
components separately, which is what the guidance asks operators to submit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import units as U

try:
    from shapely.geometry import MultiPolygon, Point, Polygon, mapping
    from shapely.ops import unary_union

    HAVE_SHAPELY = True
except Exception as exc:  # pragma: no cover
    HAVE_SHAPELY = False
    _SHAPELY_ERR = exc


def _require_shapely():
    if not HAVE_SHAPELY:
        raise ImportError(
            "shapely is required for AoR delineation; install with "
            "`pip install shapely` or `pip install aorpisc[full]`"
        ) from _SHAPELY_ERR


# ==========================================================================
# contouring
# ==========================================================================
def _contour_lines(x: np.ndarray, y: np.ndarray, z: np.ndarray, level: float):
    """Closed contour polylines of ``z`` at ``level``.  Returns list of arrays."""
    try:
        from contourpy import contour_generator

        cg = contour_generator(x=x, y=y, z=z, line_type="SeparateCode")
        lines, _codes = cg.lines(level)
        return [np.asarray(seg) for seg in lines if len(seg) >= 4]
    except Exception:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig = plt.figure()
        try:
            cs = plt.contour(x, y, z, levels=[level])
            segs = [np.asarray(s) for s in cs.allsegs[0] if len(s) >= 4]
        finally:
            plt.close(fig)
        return segs


def field_to_polygons(x: np.ndarray, y: np.ndarray, z: np.ndarray,
                      level: float, min_area: float = 0.0):
    """Polygonise the region where ``z >= level``.

    Nested contours are resolved by containment parity, so a ring inside a
    ring becomes a hole rather than a second island.  Regions smaller than
    ``min_area`` (m^2) are dropped -- useful for shaking off single-cell
    numerical speckle around a wellbore.
    """
    _require_shapely()
    segs = _contour_lines(x, y, z, level)
    rings = []
    for s in segs:
        if not np.allclose(s[0], s[-1]):
            s = np.vstack([s, s[0]])
        try:
            p = Polygon(s)
            if not p.is_valid:
                p = p.buffer(0)
            if p.is_empty:
                continue
            rings.append(p)
        except Exception:
            continue
    if not rings:
        # the whole field may sit above the level with no crossing contour
        if np.nanmax(z) >= level and np.nanmin(z) >= level:
            return MultiPolygon([Polygon([
                (x.min(), y.min()), (x.max(), y.min()),
                (x.max(), y.max()), (x.min(), y.max())])])
        return MultiPolygon()

    rings.sort(key=lambda p: p.area, reverse=True)
    depth = []
    for i, p in enumerate(rings):
        d = sum(1 for j, q in enumerate(rings) if j < i and q.contains(p.representative_point()))
        depth.append(d)

    shells = [(p, i) for i, p in enumerate(rings) if depth[i] % 2 == 0]
    out = []
    for shell, si in shells:
        holes = [rings[j].exterior.coords for j, d in enumerate(depth)
                 if d == depth[si] + 1 and shell.contains(rings[j].representative_point())]
        try:
            poly = Polygon(shell.exterior.coords, holes)
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.area >= min_area and not poly.is_empty:
                out.append(poly)
        except Exception:
            if shell.area >= min_area:
                out.append(shell)

    merged = unary_union(out) if out else MultiPolygon()
    return merged if not merged.is_empty else MultiPolygon()


def circles_to_polygon(centres, radii, quad_segs: int = 64):
    """Union of circles: the analytical multi-well plume footprint."""
    _require_shapely()

    def _disc(cx, cy, r):
        try:
            return Point(cx, cy).buffer(r, quad_segs=quad_segs)
        except TypeError:            # shapely < 2.1 spelled it 'resolution'
            return Point(cx, cy).buffer(r, resolution=quad_segs)

    polys = [_disc(cx, cy, r)
             for (cx, cy), r in zip(centres, radii, strict=False) if r > 0]
    return unary_union(polys) if polys else MultiPolygon()


# ==========================================================================
# results
# ==========================================================================
@dataclass
class AoRResult:
    """A delineated Area of Review and its two components."""

    plume: object                    # shapely geometry, may be empty
    pressure_front: object           # shapely geometry, may be empty
    aor: object                      # union of the two
    threshold_pressure: float        # Pa, the dP_c used
    plume_criterion: str = ""
    method: str = ""
    injection_wells: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    # ---------------------------------------------------------------- #
    @staticmethod
    def _area(geom) -> float:
        return 0.0 if geom is None or geom.is_empty else float(geom.area)

    @property
    def area_m2(self) -> float:
        return self._area(self.aor)

    @property
    def area_acres(self) -> float:
        return U.area_out(self.area_m2, "acres")

    @property
    def area_sq_mi(self) -> float:
        return U.area_out(self.area_m2, "mi2")

    @property
    def area_km2(self) -> float:
        return U.area_out(self.area_m2, "km2")

    def controlling_component(self) -> str:
        """Which component sets the AoR, and by how much."""
        a_p, a_f = self._area(self.plume), self._area(self.pressure_front)
        a_t = self.area_m2
        if a_t == 0:
            return "empty"
        if a_f == 0:
            return "plume only (pressure front does not exceed the threshold anywhere)"
        extra_plume = a_t - a_f
        extra_press = a_t - a_p
        if extra_press <= 1e-6 * a_t:
            return "plume everywhere (pressure front lies entirely inside the plume)"
        if extra_plume <= 1e-6 * a_t:
            return "pressure front everywhere (plume lies entirely inside the front)"
        return (f"mixed: pressure front adds {U.area_out(extra_press, 'acres'):,.0f} acres "
                f"outside the plume, plume adds "
                f"{U.area_out(extra_plume, 'acres'):,.0f} acres outside the front")

    def coincident_with(self, tol: float = 1e-9) -> str:
        """Which component the AoR boundary is drawn exactly on top of.

        Returns ``"plume"``, ``"pressure front"``, ``"both"`` or ``""``.

        The AoR is a union, so whenever one component contains the other the
        union *is* that component and the two boundaries are the same line. A
        map that draws the AoR over a coincident component hides it completely,
        and the reader cannot tell whether the component is missing, empty or
        underneath. Drawing code uses this to get out of its own way.
        """
        if self.aor is None or self.aor.is_empty:
            return ""
        a = self.area_m2
        hits = []
        for name, geom in (("plume", self.plume),
                           ("pressure front", self.pressure_front)):
            if geom is None or geom.is_empty:
                continue
            if self.aor.symmetric_difference(geom).area <= tol * max(a, 1.0):
                hits.append(name)
        if len(hits) == 2:
            return "both"
        return hits[0] if hits else ""

    def max_radius_from(self, x: float, y: float) -> float:
        """Greatest distance (m) from a point to the AoR boundary."""
        if self.aor is None or self.aor.is_empty:
            return 0.0
        pts = []
        geoms = self.aor.geoms if hasattr(self.aor, "geoms") else [self.aor]
        for g in geoms:
            pts.append(np.asarray(g.exterior.coords))
        allpts = np.vstack(pts)
        return float(np.max(np.hypot(allpts[:, 0] - x, allpts[:, 1] - y)))

    def extent_by_azimuth(self, x: float, y: float, n: int = 16) -> dict:
        """Distance to the AoR boundary along ``n`` compass azimuths.

        A table of these is far more informative in a permit than a single
        area, because it shows the direction the model is pushing the boundary
        -- up-dip, along a high-permeability trend, or toward a fault.
        """
        if self.aor is None or self.aor.is_empty:
            return {}
        from shapely.geometry import LineString

        far = 10.0 * max(self.aor.bounds[2] - self.aor.bounds[0],
                         self.aor.bounds[3] - self.aor.bounds[1], 1.0)
        out = {}
        for k in range(n):
            az = 360.0 * k / n
            a = np.radians(az)
            ray = LineString([(x, y), (x + far * np.sin(a), y + far * np.cos(a))])
            inter = ray.intersection(self.aor)
            if inter.is_empty:
                out[round(az, 1)] = 0.0
                continue
            coords = np.asarray(inter.coords) if hasattr(inter, "coords") else np.vstack(
                [np.asarray(g.coords) for g in inter.geoms])
            d = np.hypot(coords[:, 0] - x, coords[:, 1] - y)
            out[round(az, 1)] = float(d.max())
        return out

    def summary(self) -> dict:
        return {
            "method": self.method,
            "threshold_pressure_psi": U.pressure_out(self.threshold_pressure, "psi"),
            "plume_criterion": self.plume_criterion,
            "aor_area_acres": self.area_acres,
            "aor_area_sq_mi": self.area_sq_mi,
            "aor_area_km2": self.area_km2,
            "plume_area_acres": U.area_out(self._area(self.plume), "acres"),
            "pressure_front_area_acres": U.area_out(self._area(self.pressure_front), "acres"),
            "controlling_component": self.controlling_component(),
            "warnings": list(self.warnings),
            **self.metadata,
        }

    def geo_interface(self) -> dict:
        return {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "properties": {"component": name},
                 "geometry": mapping(geom)}
                for name, geom in (("aor", self.aor), ("plume", self.plume),
                                   ("pressure_front", self.pressure_front))
                if geom is not None and not geom.is_empty
            ],
        }


# ==========================================================================
# the main entry points
# ==========================================================================
def envelope(fields: np.ndarray) -> np.ndarray:
    """Cell-wise maximum over a ``(nt, ny, nx)`` stack.

    This one line is the difference between an AoR built on a snapshot and one
    built on "the maximum extent ... over the lifetime of the project and
    entire timeframe of the model simulations" (EPA Section 3.4).
    """
    return np.asarray(fields).max(axis=0)


def delineate(x: np.ndarray, y: np.ndarray, *,
              dp_field: np.ndarray | None = None,
              threshold_pressure: float = 0.0,
              plume_field: np.ndarray | None = None,
              plume_level: float = 1e-6,
              plume_criterion: str = "",
              min_area: float = 0.0,
              smooth_buffer: float = 0.0,
              method: str = "",
              wells: list | None = None,
              metadata: dict | None = None) -> AoRResult:
    """Delineate the AoR from maximum-over-time pressure and plume fields.

    Parameters
    ----------
    x, y
        1-D cell-centre coordinates (m).
    dp_field
        Maximum-over-time pressure **increase** field (Pa), shape ``(ny, nx)``.
    threshold_pressure
        The ``dP_c`` from :mod:`aorpisc.threshold`, in Pa.
    plume_field
        Maximum-over-time plume indicator, e.g. CO2 column thickness (m) or
        column-averaged saturation.  Contoured at ``plume_level``.
    plume_criterion
        Free text recording exactly what the plume outline means, e.g.
        "CO2 saturation >= 0.01 in any layer" -- this belongs in the permit.
    min_area
        Drop islands smaller than this (m^2).
    smooth_buffer
        Positive-then-negative buffer distance (m) to round off staircase
        artefacts from the grid.  Purely cosmetic; keep it well below a cell.
    """
    _require_shapely()
    warnings: list[str] = []

    plume_poly = MultiPolygon()
    press_poly = MultiPolygon()

    if plume_field is not None:
        plume_poly = field_to_polygons(x, y, plume_field, plume_level, min_area)
        if plume_poly.is_empty and np.nanmax(plume_field) > 0:
            warnings.append(
                "plume field is non-zero but no closed contour was found at the "
                "requested level; check plume_level and grid resolution")

    if dp_field is not None:
        if threshold_pressure <= 0:
            warnings.append(
                "threshold pressure is not positive, so no pressure front was "
                "delineated; see aorpisc.threshold")
        else:
            press_poly = field_to_polygons(x, y, dp_field, threshold_pressure, min_area)
            if press_poly.is_empty:
                warnings.append(
                    f"no cell exceeds the {U.pressure_out(threshold_pressure, 'psi'):,.0f} psi "
                    "threshold: the pressure front does not contribute to the AoR. "
                    "This is a legitimate outcome and should be stated explicitly "
                    "in the AoR plan.")

    aor = unary_union([g for g in (plume_poly, press_poly)
                       if g is not None and not g.is_empty])
    if aor.is_empty:
        aor = MultiPolygon()
    elif smooth_buffer > 0:
        aor = aor.buffer(smooth_buffer).buffer(-smooth_buffer)

    xa, ya = np.asarray(x, float), np.asarray(y, float)
    if _touches_bounds(aor, xa, ya, tol_frac=0.05):
        warnings.append(
            "the AoR boundary reaches the edge of the model domain. Per EPA "
            "Section 3.3.3.2 the domain must extend beyond the plume and "
            "pressure front; enlarge the grid and re-run, or the AoR is only "
            "a lower bound.")
    domain_area = abs((xa[-1] - xa[0]) * (ya[-1] - ya[0]))
    if domain_area > 0 and not aor.is_empty and aor.area > 0.4 * domain_area:
        warnings.append(
            f"the AoR fills {100 * aor.area / domain_area:.0f} % of the model "
            "domain. Boundary conditions are shaping the result: a no-flow "
            "edge inflates the pressure front and a constant-pressure edge "
            "truncates it. Enlarge the domain until the AoR is a small "
            "fraction of it, then confirm the answer stops changing.")

    return AoRResult(
        plume=plume_poly, pressure_front=press_poly, aor=aor,
        threshold_pressure=threshold_pressure,
        plume_criterion=plume_criterion,
        method=method or "maximum-over-time field contouring",
        injection_wells=list(wells or []),
        metadata=metadata or {},
        warnings=warnings,
    )


def _touches_bounds(geom, x, y, tol_frac: float = 0.02) -> bool:
    """True if a geometry runs into the edge of the evaluation grid."""
    if geom is None or geom.is_empty:
        return False
    tx = tol_frac * (x[-1] - x[0])
    ty = tol_frac * (y[-1] - y[0])
    xmin, ymin, xmax, ymax = geom.bounds
    return (xmin <= x[0] + tx or xmax >= x[-1] - tx
            or ymin <= y[0] + ty or ymax >= y[-1] - ty)


def delineate_analytical(model, wells, threshold_pressure: float,
                         times: np.ndarray,
                         padding: float = 1.6,
                         n: int = 241,
                         max_expansions: int = 6,
                         plume_criterion: str = "Buckley-Leverett leading front"
                         ) -> AoRResult:
    """Delineate an AoR from the analytical superposition model.

    The evaluation grid is sized automatically and then **grown until the
    pressure-front contour closes inside it**.  That check matters: a
    superposed multi-well front reaches far beyond any single-well radius of
    investigation, and a domain sized from one well silently truncates the
    AoR.  EPA Section 3.3.3.2 asks for exactly this test.
    """
    from .analytical.pressure import radius_of_investigation

    times = np.asarray(times, float)
    # bound the front with the *total* injected volume rate, not one well's
    q_tot = max((sum(abs(model.reservoir_rate(w, float(t))) for w in wells)
                 for t in times), default=0.0)
    r_press = max((radius_of_investigation(model, float(t), threshold_pressure, q_tot)
                   for t in times), default=0.0)

    radii = [max((model.front_radius(w, float(t)) for t in times), default=0.0)
             if w.kind == "injector" else 0.0 for w in wells]
    r_plume = max(radii) if radii else 0.0

    xs = [w.x for w in wells] or [0.0]
    ys = [w.y for w in wells] or [0.0]
    reach = padding * max(r_press, r_plume, model.thickness, 1.0)

    plume = circles_to_polygon([(w.x, w.y) for w in wells], radii)
    warnings: list[str] = []
    press = MultiPolygon()
    x = y = None
    for _attempt in range(max_expansions):
        x = np.linspace(min(xs) - reach, max(xs) + reach, n)
        y = np.linspace(min(ys) - reach, max(ys) + reach, n)
        _, dp_max = model.pressure_grid(x, y, times, wells)
        press = field_to_polygons(x, y, dp_max, threshold_pressure)
        if not _touches_bounds(press, x, y) and not _touches_bounds(plume, x, y):
            break
        reach *= 1.8
    else:
        warnings.append(
            "the pressure-front contour still reaches the edge of the "
            "evaluation domain after expansion; the AoR is a lower bound")

    aor = unary_union([g for g in (plume, press) if not g.is_empty]) \
        if (not plume.is_empty or not press.is_empty) else MultiPolygon()

    return AoRResult(
        plume=plume, pressure_front=press, aor=aor,
        threshold_pressure=threshold_pressure,
        plume_criterion=plume_criterion,
        method="analytical superposition (Theis + image wells) with radial "
               "Buckley-Leverett plume",
        injection_wells=[w.name for w in wells],
        metadata={
            "max_plume_radius_ft": U.length_out(r_plume, "ft"),
            "all_well_pressure_radius_ft": U.length_out(r_press, "ft"),
            "evaluation_half_width_mi": U.length_out(reach, "mi"),
            "grid_nodes": n,
            "model": model.describe(),
        },
        warnings=warnings,
    )


# ==========================================================================
# stacked injection zones, and the AoR through time
# ==========================================================================
def combine(parts, *, labels=None, method: str = "") -> AoRResult:
    """Union the AoRs of several injection zones into one project AoR.

    An operator may complete a single wellbore in two or more formations.
    Each one has its own pressure regime, its own threshold pressure and so
    its own AoR, and the project AoR is the union of them: the rule protects a
    USDW from fluid movement out of *any* injection zone, so a region that
    only the deeper zone reaches is still in the Area of Review.

    The union is geometric, not an area sum. Stacked zones normally overlap
    heavily, so adding acreages double-counts the overlap and overstates the
    AoR, sometimes by a factor approaching the number of zones.

    Each component is unioned with its own kind, so the returned result still
    separates plume from pressure front and can still say which one controls.
    """
    _require_shapely()
    parts = [a for a in parts if a is not None]
    if not parts:
        raise ValueError("combine() needs at least one AoRResult")
    if len(parts) == 1 and labels is None:
        return parts[0]

    names = list(labels or [a.metadata.get("zone", f"zone {i + 1}")
                            for i, a in enumerate(parts)])

    def _u(attr):
        geoms = [getattr(a, attr) for a in parts
                 if getattr(a, attr) is not None and not getattr(a, attr).is_empty]
        return unary_union(geoms) if geoms else MultiPolygon()

    plume, press = _u("plume"), _u("pressure_front")
    aor = unary_union([g for g in (plume, press) if not g.is_empty]) or MultiPolygon()
    if aor.is_empty:
        aor = MultiPolygon()

    by_zone = {n: {"area_acres": a.area_acres,
                   "threshold_psi": U.pressure_out(a.threshold_pressure, "psi"),
                   "controlling_component": a.controlling_component()}
               for n, a in zip(names, parts, strict=False)}
    total = U.area_out(aor.area, "acres")
    largest = max(parts, key=lambda a: a.area_m2)
    warnings = [w for a in parts for w in a.warnings]
    if len(parts) > 1:
        summed = sum(a.area_acres for a in parts)
        if summed > 0:
            warnings.append(
                f"{len(parts)} injection zones were delineated separately and "
                f"unioned: {total:,.0f} acres, against {summed:,.0f} acres if "
                f"the zone AoRs were added. State the union in the permit and "
                f"show the per-zone areas behind it [40 CFR 146.84(c)].")

    return AoRResult(
        plume=plume, pressure_front=press, aor=aor,
        threshold_pressure=largest.threshold_pressure,
        plume_criterion=largest.plume_criterion,
        method=method or f"union of {len(parts)} injection-zone delineations",
        injection_wells=sorted({w for a in parts for w in a.injection_wells}),
        metadata={"zones": names, "by_zone": by_zone,
                  "governing_zone": names[parts.index(largest)],
                  "union_area_acres": total,
                  "sum_of_zone_areas_acres": sum(a.area_acres for a in parts)},
        warnings=list(dict.fromkeys(warnings)),
    )


@dataclass
class AoRSnapshot:
    """The AoR as it would be delineated with the model stopped at ``time``."""

    time: float                      # s since the start of injection
    aor: AoRResult

    @property
    def year(self) -> float:
        return U.time_out(self.time, "yr")

    @property
    def area_acres(self) -> float:
        return self.aor.area_acres

    def summary(self) -> dict:
        return {"year": self.year, "area_acres": self.area_acres,
                "plume_area_acres": U.area_out(
                    0.0 if self.aor.plume.is_empty else self.aor.plume.area, "acres"),
                "pressure_front_area_acres": U.area_out(
                    0.0 if self.aor.pressure_front.is_empty
                    else self.aor.pressure_front.area, "acres"),
                "controlling_component": self.aor.controlling_component()}


def aor_series(x, y, times, *, dp_fields=None, plume_fields=None,
               threshold_pressure: float = 0.0, plume_level: float = 1e-6,
               plume_criterion: str = "", interval: float | None = None,
               at_times=None, mode: str = "cumulative",
               method: str = "", wells=None) -> list[AoRSnapshot]:
    """Delineate the AoR at intervals through the simulation.

    Why this exists: 40 CFR 146.84(e) requires the AoR to be re-evaluated at
    least every five years, and each re-evaluation asks whether the AoR has
    expanded into ground that has not been screened for artificial
    penetrations. A series of AoRs on that cadence is the re-evaluation
    schedule drawn in advance, and the growth between consecutive snapshots is
    exactly the area 146.84(e)(2) makes subject to corrective action.

    ``mode="cumulative"`` (the default) delineates each snapshot from the
    maximum-over-time fields up to that date, which is how an AoR is defined:
    the snapshot is the AoR a reviewer would approve if the project were
    evaluated then. ``mode="instantaneous"`` contours the fields at that date
    alone, which shows the pressure front relaxing after shut-in but is not an
    AoR in the regulatory sense and is offered only for diagnosis.

    ``interval`` is in seconds (use ``U.time(5, "yr")``); pass ``at_times``
    instead to choose the dates directly.
    """
    _require_shapely()
    t = np.asarray(times, float)
    if t.size == 0:
        return []

    if at_times is not None:
        wanted = np.asarray(at_times, float)
    else:
        step = interval if interval else U.time(5.0, "yr")
        n = max(1, int(np.floor(t[-1] / step)))
        wanted = np.arange(1, n + 1) * step
        if wanted.size == 0 or wanted[-1] < t[-1] - 1e-9:
            wanted = np.append(wanted, t[-1])   # always finish on the last date

    out: list[AoRSnapshot] = []
    seen: set[int] = set()
    for want in wanted:
        i = int(np.searchsorted(t, want, side="right")) - 1
        if i < 0 or i in seen:
            # Two requested dates can fall between the same pair of model
            # output times. Emitting the snapshot twice would show a
            # re-evaluation that added nothing, which is an artefact of the
            # output schedule rather than a fact about the AoR.
            continue
        seen.add(i)
        if mode.startswith("inst"):
            dp = None if dp_fields is None else np.asarray(dp_fields)[i]
            pl = None if plume_fields is None else np.asarray(plume_fields)[i]
        else:
            dp = None if dp_fields is None else envelope(np.asarray(dp_fields)[:i + 1])
            pl = (None if plume_fields is None
                  else envelope(np.asarray(plume_fields)[:i + 1]))
        snap = delineate(
            x, y, dp_field=dp, threshold_pressure=threshold_pressure,
            plume_field=pl, plume_level=plume_level,
            plume_criterion=plume_criterion,
            method=method or f"{mode} delineation at {U.time_out(t[i], 'yr'):.0f} yr",
            wells=list(wells or []),
            metadata={"year": U.time_out(t[i], "yr"), "mode": mode})
        # A snapshot that does not reach the domain edge is not evidence about
        # the final AoR, and repeating the full-run warnings once per snapshot
        # would bury the ones that matter.
        snap.warnings = []
        out.append(AoRSnapshot(time=float(t[i]), aor=snap))
    return out


def series_growth(series: list[AoRSnapshot]) -> list[dict]:
    """Area added between consecutive snapshots: the re-evaluation ledger."""
    rows = []
    prev = None
    for snap in series:
        row = {"year": snap.year, "area_acres": snap.area_acres}
        if prev is None:
            row.update({"added_acres": snap.area_acres, "growth_percent": float("nan"),
                        "newly_included_acres": snap.area_acres})
        else:
            added = snap.aor.aor.difference(prev.aor.aor)
            row.update({
                "added_acres": snap.area_acres - prev.area_acres,
                "growth_percent": (100.0 * (snap.area_acres - prev.area_acres)
                                   / prev.area_acres if prev.area_acres else float("nan")),
                "newly_included_acres": U.area_out(added.area, "acres")})
        rows.append(row)
        prev = snap
    return rows


def compare_aors(a: AoRResult, b: AoRResult, label_a="A", label_b="B") -> dict:
    """Quantify how two AoR delineations differ.

    Built for AoR reevaluation [40 CFR 146.84(e)]: the newly added region is
    exactly the area that "must be subjected to the artificial penetration
    identification, assessment, and corrective action procedures".
    """
    _require_shapely()
    added = b.aor.difference(a.aor)
    removed = a.aor.difference(b.aor)
    inter = a.aor.intersection(b.aor)
    union = a.aor.union(b.aor)
    return {
        f"{label_a}_area_acres": a.area_acres,
        f"{label_b}_area_acres": b.area_acres,
        "change_acres": b.area_acres - a.area_acres,
        "change_percent": (100.0 * (b.area_acres - a.area_acres) / a.area_acres
                           if a.area_acres else float("nan")),
        "newly_included_acres": U.area_out(added.area, "acres"),
        "no_longer_included_acres": U.area_out(removed.area, "acres"),
        "jaccard_overlap": (inter.area / union.area) if union.area else float("nan"),
        "newly_included_geometry": added,
        "verdict": ("AoR expanded -- new area requires artificial-penetration "
                    "identification, assessment and corrective action "
                    "[40 CFR 146.84(e)(2)-(3)]"
                    if added.area > 0.01 * max(a.area_m2, 1.0)
                    else "no material expansion; a demonstration that no amendment "
                         "is needed may be submitted [40 CFR 146.84(e)(4)]"),
    }


__all__ = [
    "HAVE_SHAPELY", "field_to_polygons", "circles_to_polygon", "envelope",
    "AoRResult", "delineate", "delineate_analytical", "compare_aors",
    "combine", "AoRSnapshot", "aor_series", "series_growth",
]
