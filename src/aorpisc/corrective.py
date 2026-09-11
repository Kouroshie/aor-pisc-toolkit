"""Artificial penetrations inside the AoR, and corrective action planning.

Delineating the AoR is only half of 40 CFR 146.84.  The other half is finding
every penetration inside it that may reach the confining zone, deciding which
ones need corrective action, and -- where the Director allows phased
corrective action -- deciding *when*.

What this module adds beyond a point-in-polygon query:

* the EPA well-evaluation decision tree (Figure 4-3 of 816-R-13-005) applied
  automatically from record completeness, plugging depth, plug material and
  abandonment date, with the reasoning attached to every well;
* **phased corrective action scheduling** -- for each well, the year the
  modelled plume or pressure front first reaches it, so corrective action can
  be sequenced by arrival time rather than by distance.  40 CFR
  146.84(b)(2)(iv) permits phasing but nothing tells an operator how to phase
  it; arrival time is the defensible criterion, and it falls straight out of
  the same model that produced the AoR;
* an AoR-reevaluation differencing helper so newly included wells are flagged
  as requiring assessment under 146.84(e)(2)-(3).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

import numpy as np

from . import units as U

# The API standard for oil-well cements dates from 1952; EPA notes that "it is
# likely that any wells abandoned before 1952 may have inadequate plugs"
# (816-R-13-005 Section 4.2, citing Ide et al. 2006).
API_CEMENT_STANDARD_YEAR = 1952

CO2_INCOMPATIBLE_PLUGS = {
    "mechanical", "bridge plug", "cast iron bridge plug", "cibp",
    "mud", "drilling mud", "none", "unknown",
}


@dataclass
class ArtificialPenetration:
    """One well, mine or other man-made penetration.

    Only ``name``, ``x`` and ``y`` are required.  Everything else improves the
    screening; missing information is treated as *unknown*, which is what
    pushes a well toward field testing rather than toward "no action".
    """

    name: str
    x: float
    y: float
    api: str = ""
    kind: str = "unknown"              # oil, gas, injection, water, dry hole, mine...
    status: str = "unknown"            # active, shut-in, plugged, abandoned, unknown
    total_depth: float = float("nan")  # m
    year_drilled: int | None = None
    year_abandoned: int | None = None
    plug_depths: tuple[float, ...] = ()     # m, cement plug tops
    plug_material: str = "unknown"
    cased: bool | None = None
    records_complete: bool | None = None
    mit_passed: bool | None = None
    notes: str = ""
    latitude: float = float("nan")
    longitude: float = float("nan")

    # populated by the screen
    in_aor: bool = False
    penetrates_confining_zone: bool | None = None
    action: str = ""
    action_reason: str = ""
    priority: int = 0
    arrival_year_plume: float = float("nan")
    arrival_year_pressure: float = float("nan")
    distance_to_nearest_injector: float = float("nan")

    def as_row(self) -> dict:
        return {
            "name": self.name,
            "api": self.api,
            "x_m": self.x, "y_m": self.y,
            "type": self.kind,
            "status": self.status,
            "total_depth_ft": U.length_out(self.total_depth, "ft"),
            "year_drilled": self.year_drilled,
            "year_abandoned": self.year_abandoned,
            "plug_material": self.plug_material,
            "in_aor": self.in_aor,
            "penetrates_confining_zone": self.penetrates_confining_zone,
            "distance_to_injector_ft": U.length_out(self.distance_to_nearest_injector, "ft"),
            "action": self.action,
            "reason": self.action_reason,
            "priority": self.priority,
            "plume_arrival_yr": self.arrival_year_plume,
            "pressure_arrival_yr": self.arrival_year_pressure,
            "notes": self.notes,
        }


# ==========================================================================
# EPA Figure 4-3 decision tree
# ==========================================================================
def evaluate_well(w: ArtificialPenetration, confining_zone_top: float,
                  confining_zone_base: float,
                  injection_zone_top: float | None = None) -> ArtificialPenetration:
    """Apply EPA's well-evaluation decision tree to one penetration.

    The outcome is one of:

    ``no action``
        does not reach the confining zone, or is adequately plugged across it
        with CO2-compatible cement and complete records;
    ``field testing``
        records are missing, incomplete or ambiguous -- EPA Section 4.3.2
        requires field tests before the well can be cleared;
    ``corrective action``
        records positively show inadequate plugging, an unplugged hole, a
        failed MIT, or plug material that will not survive contact with CO2;
    ``monitor``
        an active well under the operator's control, tracked but not plugged.

    Depths are metres below the same datum as the AoR model.
    """
    d = w.total_depth
    if np.isfinite(d) and d < confining_zone_top:
        w.penetrates_confining_zone = False
        w.action = "no action"
        w.action_reason = (
            f"total depth {U.length_out(d, 'ft'):,.0f} ft is above the confining "
            f"zone top at {U.length_out(confining_zone_top, 'ft'):,.0f} ft "
            "[40 CFR 146.84(c)(2) applies to penetrations that may penetrate "
            "the confining zone]")
        w.priority = 0
        return w

    w.penetrates_confining_zone = True if np.isfinite(d) else None

    if w.status.lower() in ("active", "producing", "injecting", "shut-in", "shut in"):
        w.action = "monitor"
        w.action_reason = (
            "active or shut-in well penetrating the confining zone; confirm "
            "mechanical integrity and CO2-compatible construction, and include "
            "in the testing and monitoring plan")
        w.priority = 2
        return w

    if w.mit_passed is False:
        w.action = "corrective action"
        w.action_reason = "a mechanical integrity test on record failed and the leak was not shown to be repaired"
        w.priority = 5
        return w

    if w.records_complete is False or w.records_complete is None:
        w.action = "field testing"
        w.action_reason = (
            "plugging records are absent or incomplete, so adequacy cannot be "
            "demonstrated from records alone [EPA Section 4.3.1]; run the "
            "non-destructive log sequence before deciding")
        w.priority = 4
        return w

    if not w.plug_depths:
        w.action = "corrective action"
        w.action_reason = "records show no cement plug in the wellbore"
        w.priority = 5
        return w

    plugs = np.asarray(w.plug_depths, float)
    across_confining = np.any((plugs >= confining_zone_top - 1.0)
                              & (plugs <= confining_zone_base + 1.0))
    if not across_confining:
        w.action = "corrective action"
        w.action_reason = (
            "no cement plug at a depth corresponding to the primary confining "
            "zone; EPA recommends setting one there to prevent cross-migration "
            "[Section 4.4.1, Figure 4-2]")
        w.priority = 5
        return w

    mat = (w.plug_material or "unknown").strip().lower()
    if any(bad in mat for bad in CO2_INCOMPATIBLE_PLUGS):
        w.action = "corrective action"
        w.action_reason = (
            f"plug material recorded as {w.plug_material!r}; mechanical plugs "
            "and unknown materials are not adequate for long-term CO2 "
            "isolation [EPA Section 4.3.1, citing Randhol et al. 2007], and "
            "40 CFR 146.84(d) requires CO2-compatible materials")
        w.priority = 5
        return w

    yr = w.year_abandoned or w.year_drilled
    if yr is not None and yr < API_CEMENT_STANDARD_YEAR:
        w.action = "field testing"
        w.action_reason = (
            f"abandoned in {yr}, before the 1952 API cement standard; EPA notes "
            "such plugs may not have set properly and warrants verification")
        w.priority = 4
        return w

    if w.cased is False:
        w.action = "field testing"
        w.action_reason = (
            "open-hole abandonment; EPA notes open holes are susceptible to "
            "cross-migration and recommends confirming plug integrity")
        w.priority = 3
        return w

    w.action = "no action"
    w.action_reason = (
        "records show a CO2-compatible cement plug across the primary "
        "confining zone, post-1952 abandonment, and no adverse test results")
    w.priority = 1
    return w


# ==========================================================================
# the screen
# ==========================================================================
@dataclass
class CorrectiveActionPlan:
    """Result of screening a well list against a delineated AoR."""

    wells: list[ArtificialPenetration]
    confining_zone_top: float
    confining_zone_base: float
    aor_area_acres: float = float("nan")
    warnings: list[str] = field(default_factory=list)

    @property
    def inside(self) -> list[ArtificialPenetration]:
        return [w for w in self.wells if w.in_aor]

    def by_action(self, action: str) -> list[ArtificialPenetration]:
        return [w for w in self.inside if w.action == action]

    def table(self) -> list[dict]:
        return [w.as_row() for w in sorted(
            self.inside, key=lambda w: (-w.priority, w.arrival_year_plume))]

    def phases(self, phase_boundaries_years: Sequence[float] = (5, 10, 20)) -> dict:
        """Group wells needing action into phases by modelled arrival time.

        Wells the plume or pressure front never reaches within the simulation
        fall into a final ``"beyond model horizon"`` bucket; EPA nonetheless
        expects all identified deficient wells to receive corrective action
        "before the end of the injection phase" (Section 4.4).
        """
        need = [w for w in self.inside if w.action in ("corrective action", "field testing")]
        out: dict[str, list[str]] = {}
        bounds = list(phase_boundaries_years)
        for i, b in enumerate(bounds):
            lo = 0.0 if i == 0 else bounds[i - 1]
            key = f"phase {i + 1}: arrival {lo:g}-{b:g} yr"
            out[key] = []
        out[f"phase {len(bounds) + 1}: arrival after {bounds[-1]:g} yr"] = []
        out["beyond model horizon"] = []

        for w in need:
            arrival = np.nanmin([w.arrival_year_plume, w.arrival_year_pressure])
            if not np.isfinite(arrival):
                out["beyond model horizon"].append(w.name)
                continue
            placed = False
            for i, b in enumerate(bounds):
                lo = 0.0 if i == 0 else bounds[i - 1]
                if lo <= arrival < b:
                    out[f"phase {i + 1}: arrival {lo:g}-{b:g} yr"].append(w.name)
                    placed = True
                    break
            if not placed:
                out[f"phase {len(bounds) + 1}: arrival after {bounds[-1]:g} yr"].append(w.name)
        return out

    def summary(self) -> dict:
        inside = self.inside
        return {
            "aor_area_acres": self.aor_area_acres,
            "penetrations_evaluated": len(self.wells),
            "penetrations_inside_aor": len(inside),
            "penetrating_confining_zone": sum(
                1 for w in inside if w.penetrates_confining_zone is not False),
            "corrective_action_required": len(self.by_action("corrective action")),
            "field_testing_required": len(self.by_action("field testing")),
            "monitor": len(self.by_action("monitor")),
            "no_action": len(self.by_action("no action")),
            "warnings": list(self.warnings),
        }


def screen(wells: Iterable[ArtificialPenetration], aor_result,
           confining_zone_top: float, confining_zone_base: float,
           injectors: Sequence[tuple[float, float]] = (),
           ) -> CorrectiveActionPlan:
    """Flag which penetrations lie inside the AoR and what to do about each."""
    from shapely.geometry import Point

    geom = aor_result.aor if hasattr(aor_result, "aor") else aor_result
    wells = list(wells)
    warnings: list[str] = []

    for w in wells:
        w.in_aor = bool(geom is not None and not geom.is_empty
                        and geom.contains(Point(w.x, w.y)))
        if injectors:
            w.distance_to_nearest_injector = float(min(
                np.hypot(w.x - ix, w.y - iy) for ix, iy in injectors))
        if w.in_aor:
            evaluate_well(w, confining_zone_top, confining_zone_base)

    unknown_depth = [w.name for w in wells if w.in_aor and not np.isfinite(w.total_depth)]
    if unknown_depth:
        warnings.append(
            f"{len(unknown_depth)} well(s) inside the AoR have no recorded total "
            "depth, so whether they penetrate the confining zone is unknown; "
            "40 CFR 146.84(c)(2) requires depth to be reported for each: "
            + ", ".join(unknown_depth[:10]) + ("..." if len(unknown_depth) > 10 else ""))

    return CorrectiveActionPlan(
        wells=wells,
        confining_zone_top=confining_zone_top,
        confining_zone_base=confining_zone_base,
        aor_area_acres=getattr(aor_result, "area_acres", float("nan")),
        warnings=warnings,
    )


# ==========================================================================
# arrival times for phased corrective action
# ==========================================================================
def arrival_times(plan: CorrectiveActionPlan, x: np.ndarray, y: np.ndarray,
                  times: np.ndarray,
                  plume_fields: np.ndarray | None = None,
                  plume_level: float = 1e-6,
                  dp_fields: np.ndarray | None = None,
                  threshold_pressure: float = float("inf")
                  ) -> CorrectiveActionPlan:
    """Stamp each well with the year the plume / pressure front first reaches it.

    ``plume_fields`` and ``dp_fields`` are ``(nt, ny, nx)`` stacks on the
    ``(y, x)`` grid, matching ``times`` (seconds).  Values are sampled at the
    well location by nearest cell.
    """
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    times = np.asarray(times, float)

    for w in plan.wells:
        if not w.in_aor:
            continue
        i = int(np.argmin(np.abs(x - w.x)))
        j = int(np.argmin(np.abs(y - w.y)))

        if plume_fields is not None:
            series = np.asarray(plume_fields)[:, j, i]
            hit = np.nonzero(series > plume_level)[0]
            w.arrival_year_plume = (U.time_out(float(times[hit[0]]), "yr")
                                    if hit.size else float("nan"))
        if dp_fields is not None and np.isfinite(threshold_pressure):
            series = np.asarray(dp_fields)[:, j, i]
            hit = np.nonzero(series >= threshold_pressure)[0]
            w.arrival_year_pressure = (U.time_out(float(times[hit[0]]), "yr")
                                       if hit.size else float("nan"))
    return plan


def newly_included(previous: CorrectiveActionPlan, current: CorrectiveActionPlan
                   ) -> list[str]:
    """Wells inside the reevaluated AoR that were not inside the previous one.

    These are the wells that "must be subjected to the artificial penetration
    identification, assessment, and corrective action procedures"
    [40 CFR 146.84(e)(2) and (3)].
    """
    before = {w.name for w in previous.inside}
    return [w.name for w in current.inside if w.name not in before]


def load_wells_csv(path: str, *, x_col="x", y_col="y", name_col="name",
                   unit: str = "m", crs=None, **column_map
                   ) -> list[ArtificialPenetration]:
    """Read a well table from CSV.

    Column names are configurable; anything matching an
    :class:`ArtificialPenetration` field is picked up automatically.
    ``unit`` converts the coordinate and depth columns (``"m"`` or ``"ft"``).
    Semicolon-separated plug depths in a ``plug_depths`` column are parsed.

    If the file has ``latitude`` and ``longitude`` columns and ``crs`` is a
    :class:`aorpisc.io.exporters.LocalCRS`, those are used in preference to
    ``x``/``y`` and converted into the model frame. State well lists come out
    of RRC, TWDB and commercial databases in latitude and longitude, so this
    is usually the path of least resistance.
    """
    import csv

    scale = U.length(1.0, unit)
    out: list[ArtificialPenetration] = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            row = {(column_map.get(k, k) or k).strip(): (v.strip() if isinstance(v, str) else v)
                   for k, v in row.items() if k}
            lat = row.get("latitude") or row.get("lat")
            lon = row.get("longitude") or row.get("lon") or row.get("long")
            if crs is not None and lat and lon:
                import numpy as _np
                gx, gy = crs.from_lonlat(_np.array([float(lon)]), _np.array([float(lat)]))
                wx, wy = float(gx[0]), float(gy[0])
            else:
                wx = float(row[x_col]) * scale
                wy = float(row[y_col]) * scale
            w = ArtificialPenetration(
                name=row.get(name_col) or row.get("name") or row.get("api") or "unnamed",
                x=wx, y=wy,
            )
            if lat and lon:
                w.latitude, w.longitude = float(lat), float(lon)
            for f in ("api", "kind", "status", "plug_material", "notes"):
                if row.get(f):
                    setattr(w, f, row[f])
            if row.get("type") and w.kind == "unknown":
                w.kind = row["type"]
            for f, conv in (("total_depth", lambda v: float(v) * scale),
                            ("year_drilled", int), ("year_abandoned", int)):
                if row.get(f):
                    try:
                        setattr(w, f, conv(row[f]))
                    except ValueError:
                        pass
            if row.get("plug_depths"):
                w.plug_depths = tuple(
                    float(p) * scale for p in row["plug_depths"].replace(",", ";").split(";")
                    if p.strip())
            for f in ("cased", "records_complete", "mit_passed"):
                v = (row.get(f) or "").lower()
                if v in ("true", "yes", "y", "1"):
                    setattr(w, f, True)
                elif v in ("false", "no", "n", "0"):
                    setattr(w, f, False)
            out.append(w)
    return out


__all__ = [
    "ArtificialPenetration", "CorrectiveActionPlan", "evaluate_well", "screen",
    "arrival_times", "newly_included", "load_wells_csv",
    "API_CEMENT_STANDARD_YEAR",
]
