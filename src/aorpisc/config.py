"""Project definition: one YAML file that fully describes an AoR/PISC run.

Everything the toolkit needs comes from a single, readable, version-
controllable file.  That is not a convenience feature: 40 CFR 146.84(g)
requires modelling inputs to be retained for ten years, and EPA asks that a
submittal contain "all necessary information for the UIC Program Director to
evaluate the AoR delineation results and replicate the computational modeling
exercise" (Section 3.5).  A project file plus a version number is that.

Values are written in whatever units the permit uses -- ``psi``, ``ft``,
``mD``, ``MMT/yr`` -- and converted to SI once, here, so no downstream code
has to guess.  See ``docs/input_schema.md`` for the annotated schema and
``examples/`` for complete files.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from . import fluids
from . import units as U
from .analytical.relperm import BrooksCorey, RelPerm, VanGenuchten


# ==========================================================================
def _get(d: dict, path: str, default=None):
    cur: Any = d
    for key in path.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def _need(d: dict, path: str):
    v = _get(d, path, None)
    if v is None:
        raise ValueError(f"project file is missing required entry {path!r}")
    return v


# ==========================================================================
@dataclass
class Units:
    """Units the project file is written in."""

    length: str = "ft"
    depth: str = "ft"
    pressure: str = "psi"
    temperature: str = "F"
    permeability: str = "mD"
    rate: str = "MMT/yr"
    brine_rate: str = "bbl/day"
    time: str = "yr"
    compressibility: str = "1/psi"

    @classmethod
    def from_dict(cls, d: dict | None) -> Units:
        return cls(**{k: v for k, v in (d or {}).items() if k in cls.__annotations__})


@dataclass
class Zone:
    """A stratigraphic interval in SI units."""

    name: str = ""
    top_depth: float = float("nan")     # m below datum
    base_depth: float = float("nan")
    thickness: float = float("nan")     # m net
    porosity: float = float("nan")
    permeability: float = float("nan")  # m^2
    temperature: float = float("nan")   # K
    salinity: float = float("nan")      # NaCl mass fraction
    initial_pressure: float = float("nan")   # Pa
    rock_compressibility: float = float("nan")  # 1/Pa
    dip_degrees: float = 0.0
    dip_azimuth: float = 0.0
    anisotropy_kv_kh: float = 0.1

    @property
    def mid_depth(self) -> float:
        if np.isfinite(self.top_depth) and np.isfinite(self.base_depth):
            return 0.5 * (self.top_depth + self.base_depth)
        if np.isfinite(self.top_depth) and np.isfinite(self.thickness):
            return self.top_depth + 0.5 * self.thickness
        return self.top_depth


@dataclass
class WellSpec:
    """One project well, in SI units."""

    name: str
    x: float
    y: float
    kind: str = "injector"
    schedule: list[tuple[float, float]] = field(default_factory=list)
    radius: float = 0.1
    max_bhp: float = float("inf")

    def total_mass(self) -> float:
        total, prev_t, prev_q = 0.0, None, 0.0
        for t0, q in sorted(self.schedule):
            if prev_t is not None:
                total += prev_q * (t0 - prev_t)
            prev_t, prev_q = t0, q
        return max(total, 0.0)

    def stop_time(self) -> float:
        stops = [t for t, q in sorted(self.schedule) if q == 0.0]
        return max(stops) if stops else max((t for t, _ in self.schedule), default=0.0)


# ==========================================================================
@dataclass
class Project:
    """A complete AoR/PISC project definition, converted to SI."""

    name: str = "Unnamed project"
    operator: str = ""
    permit: str = ""
    datum: str = "ground level"
    notes: str = ""

    injection_zone: Zone = field(default_factory=Zone)
    confining_zone: Zone = field(default_factory=Zone)
    usdw: Zone = field(default_factory=Zone)

    relperm: RelPerm = field(default_factory=BrooksCorey)
    wells: list[WellSpec] = field(default_factory=list)

    threshold_method: str = "auto"
    mud_weight_ppg: float = 9.0
    gel_strength: float = U.pressure(10.0, "psi")
    mud_datum_depth: float = float("nan")
    threshold_datum_depth: float = float("nan")  # m; where dP_c is evaluated
    threshold_override: float = float("nan")   # Pa

    engine: str = "analytical"       # analytical | ve | import
    grid_nx: int = 121
    grid_ny: int = 121
    cell_size: float = U.length(500.0, "ft")
    grid_half_width: float = float("nan")       # m, total domain half-width
    grid_fine_half_width: float = float("nan")  # m, extent of the fine cells
    grid_growth: float = 1.12
    boundary: str = "infinite"
    end_time: float = U.time(70.0, "yr")
    output_times: np.ndarray = field(default_factory=lambda: U.time(
        np.array([0, 1, 2, 5, 10, 15, 20, 25, 30, 40, 50, 60, 70.0]), "yr"))

    plume_criterion: str = "CO2 column-averaged saturation >= 0.01"
    plume_cutoff: float = 0.01

    penetrations_csv: str = ""
    penetrations_unit: str = "m"

    crs: dict = field(default_factory=dict)
    uncertainty: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)
    units: Units = field(default_factory=Units)
    warnings: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    @classmethod
    def from_dict(cls, d: dict) -> Project:
        d = copy.deepcopy(d)
        un = Units.from_dict(d.get("units"))
        p = cls(raw=copy.deepcopy(d), units=un)

        pr = d.get("project", {})
        p.name = pr.get("name", p.name)
        p.operator = pr.get("operator", "")
        p.permit = pr.get("permit", "")
        p.datum = pr.get("datum", p.datum)
        p.notes = pr.get("notes", "")
        p.crs = pr.get("crs", {}) or {}

        def zone(key: str, name: str) -> Zone:
            z = d.get("formation", {}).get(key, {}) or {}
            out = Zone(name=name)
            if "top_depth" in z:
                out.top_depth = U.length(float(z["top_depth"]), un.depth)
            if "base_depth" in z:
                out.base_depth = U.length(float(z["base_depth"]), un.depth)
            if "thickness" in z:
                out.thickness = U.length(float(z["thickness"]), un.length)
            elif np.isfinite(out.top_depth) and np.isfinite(out.base_depth):
                out.thickness = out.base_depth - out.top_depth
            for src, dst, conv in (
                ("porosity", "porosity", lambda v: float(v)),
                ("permeability", "permeability", lambda v: U.permeability(float(v), un.permeability)),
                ("temperature", "temperature", lambda v: U.temperature(float(v), un.temperature)),
                ("initial_pressure", "initial_pressure", lambda v: U.pressure(float(v), un.pressure)),
                ("rock_compressibility", "rock_compressibility",
                 lambda v: U.compressibility(float(v), un.compressibility)),
                ("dip_degrees", "dip_degrees", float),
                ("dip_azimuth", "dip_azimuth", float),
                ("anisotropy_kv_kh", "anisotropy_kv_kh", float),
            ):
                if src in z and z[src] is not None:
                    setattr(out, dst, conv(z[src]))
            if "salinity_ppm" in z:
                out.salinity = fluids.salinity_to_mass_fraction(float(z["salinity_ppm"]), "ppm")
            elif "salinity" in z:
                out.salinity = fluids.salinity_to_mass_fraction(
                    float(z["salinity"]), z.get("salinity_unit", "ppm"))
            return out

        p.injection_zone = zone("injection_zone", "injection zone")
        p.confining_zone = zone("confining_zone", "confining zone")
        p.usdw = zone("usdw", "lowermost USDW")

        rp = d.get("relative_permeability", {}) or {}
        if str(rp.get("model", "brooks_corey")).lower().startswith("van"):
            p.relperm = VanGenuchten(
                swr=float(rp.get("swr", 0.30)), sgr=float(rp.get("sgr", 0.05)),
                lam=float(rp.get("lambda", 0.457)), krg0=float(rp.get("krg0", 1.0)))
        else:
            p.relperm = BrooksCorey(
                swr=float(rp.get("swr", 0.30)), sgr=float(rp.get("sgr", 0.20)),
                krw0=float(rp.get("krw0", 1.0)), krg0=float(rp.get("krg0", 0.30)),
                m=float(rp.get("m", 3.0)), n=float(rp.get("n", 3.0)))

        for w in d.get("wells", []) or []:
            p.wells.append(_well_from_dict(w, un))

        th = d.get("threshold", {}) or {}
        p.threshold_method = str(th.get("method", "auto")).lower()
        p.mud_weight_ppg = float(th.get("mud_weight_ppg", 9.0))
        p.gel_strength = U.pressure(float(th.get("gel_strength", 10.0)), un.pressure)
        if th.get("mud_datum_depth") is not None:
            p.mud_datum_depth = U.length(float(th["mud_datum_depth"]), un.depth)
        if th.get("datum_depth") is not None:
            p.threshold_datum_depth = U.length(float(th["datum_depth"]), un.depth)
        elif th.get("datum") in ("top", "top_of_injection_zone"):
            p.threshold_datum_depth = p.injection_zone.top_depth
        if th.get("override") is not None:
            p.threshold_override = U.pressure(float(th["override"]), un.pressure)

        mo = d.get("model", {}) or {}
        p.engine = str(mo.get("engine", "analytical")).lower()
        grid = mo.get("grid", {}) or {}
        p.grid_nx = int(grid.get("nx", 121))
        p.grid_ny = int(grid.get("ny", 121))
        p.cell_size = U.length(float(grid.get("cell_size", 500.0)), un.length)
        if grid.get("half_width") is not None:
            p.grid_half_width = U.length(float(grid["half_width"]), un.length)
        if grid.get("fine_half_width") is not None:
            p.grid_fine_half_width = U.length(float(grid["fine_half_width"]), un.length)
        p.grid_growth = float(grid.get("growth", 1.12))
        p.boundary = str(mo.get("boundary", "infinite")).lower()
        p.end_time = U.time(float(mo.get("end_year", 70.0)), un.time)
        if mo.get("output_years"):
            p.output_times = U.time(np.asarray(mo["output_years"], float), un.time)
        else:
            p.output_times = _default_output_times(p.end_time, p.wells)

        pl = d.get("plume", {}) or {}
        p.plume_cutoff = float(pl.get("cutoff", 0.01))
        p.plume_criterion = pl.get(
            "criterion", f"CO2 column-averaged saturation >= {p.plume_cutoff:g}")

        pen = d.get("penetrations", {}) or {}
        p.penetrations_csv = pen.get("csv", "")
        p.penetrations_unit = pen.get("coordinate_unit", "m")

        p.uncertainty = d.get("uncertainty", {}) or {}
        p.validate()
        return p

    @classmethod
    def from_yaml(cls, path: str) -> Project:
        import yaml

        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(yaml.safe_load(fh) or {})

    # ------------------------------------------------------------------ #
    def validate(self) -> list[str]:
        """Check the things that silently ruin an AoR if they are wrong."""
        w = self.warnings
        iz, cz, us = self.injection_zone, self.confining_zone, self.usdw

        if not self.wells:
            w.append("no wells defined: there is nothing to model")
        if not any(x.kind == "injector" for x in self.wells):
            w.append("no injector defined")

        if np.isfinite(iz.top_depth) and np.isfinite(us.base_depth) \
                and iz.top_depth <= us.base_depth:
            w.append(
                "the injection zone is not below the lowermost USDW; check the "
                "depth datum and sign convention (depths are positive downward)")
        if np.isfinite(cz.base_depth) and np.isfinite(iz.top_depth) \
                and cz.base_depth > iz.top_depth + 1.0:
            w.append("the confining zone base is below the injection zone top; "
                     "these intervals overlap")
        if not np.isfinite(iz.initial_pressure):
            w.append("injection-zone initial pressure is missing; the threshold "
                     "pressure cannot be computed")
        if not np.isfinite(us.initial_pressure):
            w.append("USDW initial pressure is missing; EPA Method 1 needs it "
                     "(hydrostatic at the USDW base is a common substitute -- "
                     "state the assumption)")
        if not np.isfinite(iz.thickness) or iz.thickness <= 0:
            w.append("injection-zone net thickness is missing or non-positive")
        if np.isfinite(iz.porosity) and not 0 < iz.porosity < 1:
            w.append(f"porosity {iz.porosity} is outside (0, 1)")

        domain = (2.0 * self.grid_half_width if np.isfinite(self.grid_half_width)
                  else self.grid_nx * self.cell_size)
        if self.engine == "ve" and domain < U.length(5.0, "mi"):
            w.append(
                f"the VE grid spans only {U.length_out(domain, 'mi'):.1f} mi; "
                "confirm the domain extends well beyond the pressure front "
                "[EPA Section 3.3.3.2]")
        if self.engine == "ve" and self.boundary == "noflow" \
                and self.end_time > U.time(30, "yr"):
            w.append(
                "a fully closed (no-flow) domain never lets pressure dissipate, "
                "so the post-injection pressure front will never shrink. Use a "
                "larger domain or constant-pressure boundaries for PISC work "
                "unless the reservoir really is compartmentalised.")
        return w

    # ------------------------------------------------------------------ #
    def fluid_state(self) -> fluids.FluidState:
        iz = self.injection_zone
        return fluids.evaluate(iz.initial_pressure, iz.temperature, iz.salinity)

    def usdw_fluid_state(self) -> fluids.FluidState:
        us = self.usdw
        t = us.temperature if np.isfinite(us.temperature) else U.temperature(70, "F")
        s = us.salinity if np.isfinite(us.salinity) else 0.0005
        p = (us.initial_pressure if np.isfinite(us.initial_pressure)
             else fluids.hydrostatic_pressure(us.base_depth))
        return fluids.evaluate(p, t, s)

    def total_compressibility(self) -> float:
        fs = self.fluid_state()
        rock = (self.injection_zone.rock_compressibility
                if np.isfinite(self.injection_zone.rock_compressibility)
                else U.compressibility(4e-6, "1/psi"))
        return rock + fs.c_brine

    @property
    def threshold_depth(self) -> float:
        """Depth at which the threshold pressure is evaluated.

        Defaults to the mid-point of the injection zone.  Applications
        commonly quote it at the **top** of the injection zone instead, which
        is where the topmost perforation and the shallowest possible conduit
        connection are.  The difference is not cosmetic: moving the datum from
        the mid-perforation to the top of a 300 ft interval changes dP_c by
        the weight of 150 ft of brine, which on a typical under-pressurised
        site is 10 % or more of the answer.  Set ``threshold.datum_depth``
        (or ``threshold.datum: top``) to control it, and state the choice.
        """
        return (self.threshold_datum_depth
                if np.isfinite(self.threshold_datum_depth)
                else self.injection_zone.mid_depth)

    def injection_end(self) -> float:
        return max((w.stop_time() for w in self.wells if w.kind == "injector"),
                   default=0.0)

    def total_injected_mass(self) -> float:
        return sum(w.total_mass() for w in self.wells if w.kind == "injector")

    def summary(self) -> dict:
        iz = self.injection_zone
        return {
            "project": self.name,
            "operator": self.operator,
            "permit": self.permit,
            "datum": self.datum,
            "injectors": sum(1 for w in self.wells if w.kind == "injector"),
            "extractors": sum(1 for w in self.wells if w.kind == "extractor"),
            "total_injected_MMT": U.mass_out(self.total_injected_mass(), "MMT"),
            "injection_end_year": U.time_out(self.injection_end(), "yr"),
            "simulation_end_year": U.time_out(self.end_time, "yr"),
            "injection_zone_top_ft": U.length_out(iz.top_depth, "ft"),
            "injection_zone_thickness_ft": U.length_out(iz.thickness, "ft"),
            "injection_zone_permeability_mD": U.permeability_out(iz.permeability, "mD"),
            "injection_zone_porosity": iz.porosity,
            "usdw_base_ft": U.length_out(self.usdw.base_depth, "ft"),
            "threshold_datum_ft": U.length_out(self.threshold_depth, "ft"),
            "engine": self.engine,
            "plume_criterion": self.plume_criterion,
            "warnings": list(self.warnings),
        }

    def to_dict(self) -> dict:
        return copy.deepcopy(self.raw)


# ==========================================================================
def _well_from_dict(w: dict, un: Units) -> WellSpec:
    kind = str(w.get("kind", "injector")).lower()
    x = U.length(float(w.get("x", 0.0)), w.get("coordinate_unit", un.length))
    y = U.length(float(w.get("y", 0.0)), w.get("coordinate_unit", un.length))

    sched: list[tuple[float, float]] = []
    if w.get("schedule"):
        for step in w["schedule"]:
            t = U.time(float(step["year"]), un.time)
            if kind == "injector":
                q = U.mass_rate(float(step["rate"]), step.get("unit", un.rate))
            else:
                q = U.volume_rate(float(step["rate"]), step.get("unit", un.brine_rate))
            sched.append((t, q))
    else:
        start = U.time(float(w.get("start_year", 0.0)), un.time)
        stop = U.time(float(w.get("stop_year", 0.0)), un.time)
        rate = float(w.get("rate", 0.0))
        q = (U.mass_rate(rate, w.get("rate_unit", un.rate)) if kind == "injector"
             else U.volume_rate(rate, w.get("rate_unit", un.brine_rate)))
        sched = [(start, q), (stop, 0.0)]

    return WellSpec(
        name=str(w.get("name", "well")), x=x, y=y, kind=kind, schedule=sched,
        radius=U.length(float(w.get("radius", 0.33)), w.get("radius_unit", "ft")),
        max_bhp=(U.pressure(float(w["max_bhp"]), un.pressure)
                 if w.get("max_bhp") is not None else float("inf")),
    )


def _default_output_times(end_time: float, wells: list[WellSpec]) -> np.ndarray:
    """Output times that resolve the injection period and the long tail.

    Dense early (the plume moves fastest then), a point on every rate change,
    and logarithmically spaced afterwards so a 500-year run does not need 500
    snapshots.
    """
    end_yr = U.time_out(end_time, "yr")
    inj_end = max((U.time_out(w.stop_time(), "yr") for w in wells), default=end_yr)
    early = list(np.unique(np.round(np.concatenate([
        [0.0], np.linspace(0.25, min(inj_end, end_yr), 12)]), 3)))
    late = []
    if end_yr > inj_end:
        late = list(inj_end + np.unique(np.round(np.geomspace(
            0.5, max(end_yr - inj_end, 1.0), 14), 3)))
    changes = [U.time_out(t, "yr") for w in wells for t, _ in w.schedule]
    all_t = sorted({round(t, 4) for t in early + late + changes + [end_yr]
                    if 0.0 <= t <= end_yr})
    return U.time(np.array(all_t, float), "yr")


__all__ = ["Project", "Zone", "WellSpec", "Units"]
