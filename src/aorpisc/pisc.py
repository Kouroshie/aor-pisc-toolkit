"""Post-Injection Site Care: plume stabilisation, pressure decline, timeframe.

The default post-injection site care period is 50 years [40 CFR 146.93(b)(1)].
An operator may ask the Director for a different timeframe, but only with
"substantial evidence that the geologic sequestration project will no longer
pose a risk of endangerment to USDWs at the end of the alternative
post-injection site care timeframe" [146.93(c)].

Reading through Class VI PISC plans, the same four quantitative arguments
recur, always computed by hand in a spreadsheet from a handful of exported
plume outlines:

1. plume area versus time, and its instantaneous expansion rate;
2. an effective-radius migration rate in ft/yr, and the year it falls to a
   small fraction of its peak;
3. the same thing resolved by direction, along rays from the injectors;
4. the year the pressure everywhere drops back below the AoR threshold, and
   the year it returns to within a few percent of pre-injection.

This module computes all four directly from the model output that already
produced the AoR, so the PISC demonstration and the AoR delineation cannot
drift apart -- which is the usual failure mode when they are built in
different tools by different people.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import units as U


# ==========================================================================
@dataclass
class PISCResult:
    """Quantitative PISC metrics derived from a time-stepped model."""

    times_years: np.ndarray
    plume_area_m2: np.ndarray
    pressure_area_m2: np.ndarray
    max_dp: np.ndarray                     # Pa, maximum buildup anywhere
    mean_dp_in_plume: np.ndarray           # Pa
    injection_end_year: float
    threshold_pressure: float              # Pa

    # derived
    effective_radius: np.ndarray = field(default=None)      # m
    migration_rate: np.ndarray = field(default=None)        # m/yr
    area_expansion_rate: np.ndarray = field(default=None)   # m^2/yr
    directional: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self):
        t = self.times_years
        a = self.plume_area_m2
        self.effective_radius = np.sqrt(np.maximum(a, 0.0) / np.pi)
        dt = np.diff(t)
        dt[dt == 0] = np.nan
        self.area_expansion_rate = np.concatenate([[np.nan], np.diff(a) / dt])
        self.migration_rate = np.concatenate(
            [[np.nan], np.diff(self.effective_radius) / dt])

    # ---------------------------------------------------------------- #
    def post_injection_mask(self) -> np.ndarray:
        return self.times_years >= self.injection_end_year - 1e-9

    def peak_migration_rate(self) -> float:
        r = self.migration_rate[np.isfinite(self.migration_rate)]
        return float(np.max(r)) if r.size else float("nan")

    def stabilisation_year(self, rate_fraction: float = 0.05,
                           absolute_rate: float = U.length(50.0, "ft"),
                           area_growth_per_year: float = 0.001) -> float:
        """First year (from start of injection) at which the plume is stable.

        Three tests, all of which must hold and keep holding to the end of the
        simulation:

        * the effective-radius migration rate has fallen below
          ``rate_fraction`` of its peak;
        * it is also below ``absolute_rate`` (default 50 ft/yr) -- a project
          with a slow peak rate would otherwise "stabilise" while still
          moving meaningfully;
        * the footprint is growing by less than ``area_growth_per_year`` of
          its own area per year (default 0.1 %/yr, which still compounds to
          roughly +22 % over a 200-year horizon; anything looser is not
          stability on the timescales PISC deals with).

        The third test is what stops a plume that is creeping outward over a
        long, sparsely sampled tail from being declared stable on the strength
        of a small ft/yr number.
        """
        peak = self.peak_migration_rate()
        if not np.isfinite(peak) or peak <= 0:
            return float(self.times_years[0])
        with np.errstate(divide="ignore", invalid="ignore"):
            frac_growth = self.area_expansion_rate / np.maximum(self.plume_area_m2, 1e-9)
        ok = ((self.migration_rate <= rate_fraction * peak)
              & (self.migration_rate <= absolute_rate)
              & (~np.isfinite(frac_growth) | (frac_growth <= area_growth_per_year))
              & self.post_injection_mask())
        # require it to hold for the remainder of the simulation
        idx = None
        for i in range(len(ok)):
            if ok[i] and np.all(ok[i:] | ~np.isfinite(self.migration_rate[i:])):
                idx = i
                break
        return float(self.times_years[idx]) if idx is not None else float("nan")

    def pressure_below_threshold_year(self) -> float:
        """First year at which no cell anywhere exceeds the AoR threshold.

        This is the moment the pressure-front component of the AoR vanishes
        and, per 146.93(c)(1)(ii), the moment "formation fluids may not be
        forced into any USDWs".
        """
        ok = (self.max_dp < self.threshold_pressure) & self.post_injection_mask()
        for i in range(len(ok)):
            if ok[i] and np.all(ok[i:]):
                return float(self.times_years[i])
        return float("nan")

    def pressure_recovery_year(self, tolerance_fraction: float = 0.05) -> float:
        """First year the maximum buildup falls within ``tolerance`` of the peak-free state.

        Expressed as a fraction of the peak buildup, so 0.05 means "back to
        within 5 % of pre-injection pressure", the phrasing used in most PISC
        plans.
        """
        peak = float(np.nanmax(self.max_dp))
        if peak <= 0:
            return float(self.times_years[0])
        ok = (self.max_dp <= tolerance_fraction * peak) & self.post_injection_mask()
        for i in range(len(ok)):
            if ok[i] and np.all(ok[i:]):
                return float(self.times_years[i])
        return float("nan")

    def recommended_timeframe(self, default_years: float = 50.0) -> dict:
        """Recommend a PISC duration and say what drives it."""
        stab = self.stabilisation_year()
        pres = self.pressure_below_threshold_year()
        end = self.injection_end_year
        candidates = {
            "plume stabilisation": (stab - end) if np.isfinite(stab) else np.nan,
            "pressure below AoR threshold": (pres - end) if np.isfinite(pres) else np.nan,
        }
        finite = {k: v for k, v in candidates.items() if np.isfinite(v)}
        unmet = [k for k, v in candidates.items() if not np.isfinite(v)]
        if not finite:
            return {
                "recommended_years": float("nan"),
                "basis": "neither criterion is met inside the simulated horizon",
                "criteria_years_after_injection": candidates,
                "verdict": (
                    "EXTEND THE SIMULATION. Neither plume stabilisation nor "
                    "pressure decline below the AoR threshold occurs before the "
                    "end of the model. 40 CFR 146.84(c)(1) requires the model to "
                    "run until plume movement ceases and the pressure "
                    "differential is no longer sufficient to move fluids into a "
                    "USDW."),
            }
        driver = max(finite, key=finite.get)
        need = finite[driver]
        caveat = ""
        if unmet:
            caveat = (
                " CAUTION: " + " and ".join(unmet) + " is not achieved anywhere "
                "in the simulated horizon, so this number rests on the "
                "remaining criterion alone and cannot by itself support an "
                "alternative timeframe. 40 CFR 146.84(c)(1) expects the model "
                "to run until plume movement ceases AND the pressure "
                "differential is no longer sufficient to move fluids into a "
                "USDW; extend the horizon, or propose monitoring that covers "
                "the criterion that is still open.")
        return {
            "recommended_years": float(max(need, 0.0)),
            "basis": driver,
            "criteria_years_after_injection": candidates,
            "unmet_criteria": unmet,
            "default_years": default_years,
            "verdict": (
                f"Model support exists for a PISC period of about "
                f"{need:,.0f} years after injection ceases, governed by "
                f"{driver}.{caveat} "
                + ("This is shorter than the 50-year default, so an alternative "
                   "timeframe under 40 CFR 146.93(c) could be supported -- the "
                   "demonstration still requires the site-specific trapping, "
                   "monitoring and sensitivity content listed in 146.93(c)(1) "
                   "and the QA criteria in 146.93(c)(2)."
                   if need < default_years else
                   "This exceeds the 50-year default, so the default period is "
                   "not sufficient on its own and a longer PISC period, or "
                   "additional monitoring, should be proposed.")),
        }

    # ---------------------------------------------------------------- #
    def table(self) -> list[dict]:
        rows = []
        for i, t in enumerate(self.times_years):
            rows.append({
                "year": float(t),
                "years_post_injection": float(t - self.injection_end_year),
                "plume_area_acres": U.area_out(float(self.plume_area_m2[i]), "acres"),
                "plume_area_sq_mi": U.area_out(float(self.plume_area_m2[i]), "mi2"),
                "effective_radius_ft": U.length_out(float(self.effective_radius[i]), "ft"),
                "migration_rate_ft_per_yr": (
                    U.length_out(float(self.migration_rate[i]), "ft")
                    if np.isfinite(self.migration_rate[i]) else None),
                "area_expansion_rate_acres_per_yr": (
                    U.area_out(float(self.area_expansion_rate[i]), "acres")
                    if np.isfinite(self.area_expansion_rate[i]) else None),
                "pressure_front_area_acres": U.area_out(
                    float(self.pressure_area_m2[i]), "acres"),
                "max_dp_psi": U.pressure_out(float(self.max_dp[i]), "psi"),
            })
        return rows

    def summary(self) -> dict:
        rec = self.recommended_timeframe()
        return {
            "injection_end_year": self.injection_end_year,
            "simulation_end_year": float(self.times_years[-1]),
            "peak_plume_area_acres": U.area_out(float(np.nanmax(self.plume_area_m2)), "acres"),
            "final_plume_area_acres": U.area_out(float(self.plume_area_m2[-1]), "acres"),
            "peak_migration_rate_ft_per_yr": U.length_out(self.peak_migration_rate(), "ft"),
            "final_migration_rate_ft_per_yr": U.length_out(
                float(self.migration_rate[-1]) if np.isfinite(self.migration_rate[-1]) else 0.0,
                "ft"),
            "plume_stabilisation_year": self.stabilisation_year(),
            "pressure_below_threshold_year": self.pressure_below_threshold_year(),
            "pressure_within_5pct_year": self.pressure_recovery_year(0.05),
            "peak_max_dp_psi": U.pressure_out(float(np.nanmax(self.max_dp)), "psi"),
            "final_max_dp_psi": U.pressure_out(float(self.max_dp[-1]), "psi"),
            "recommended_pisc": rec,
            "warnings": list(self.warnings),
        }


# ==========================================================================
def analyse(times: np.ndarray, *,
            plume_fields: np.ndarray, plume_level: float,
            dp_fields: np.ndarray, threshold_pressure: float,
            cell_area, injection_end: float,
            x: np.ndarray | None = None, y: np.ndarray | None = None,
            origins: list[tuple[float, float]] | None = None,
            azimuths: int = 8) -> PISCResult:
    """Compute PISC metrics from gridded model output.

    Parameters
    ----------
    times
        Model times in seconds, ascending.
    plume_fields, dp_fields
        ``(nt, ny, nx)`` stacks of the plume indicator and the pressure
        increase (Pa).
    plume_level, threshold_pressure
        Contour levels defining plume presence and the pressure front.
    cell_area
        Grid cell area in m^2: a scalar for a uniform grid, or a ``(ny, nx)``
        array of per-cell areas for a graded one.
    injection_end
        Time injection ceases, seconds.
    x, y, origins
        Supplying these adds a directional migration analysis along rays from
        each origin (normally the injectors).
    """
    times = np.asarray(times, float)
    plume_fields = np.asarray(plume_fields)
    dp_fields = np.asarray(dp_fields)

    area_w = np.asarray(cell_area, float)
    if area_w.ndim == 0:
        plume_area = (plume_fields > plume_level).sum(axis=(1, 2)) * float(area_w)
        press_area = (dp_fields >= threshold_pressure).sum(axis=(1, 2)) * float(area_w)
    else:
        plume_area = ((plume_fields > plume_level) * area_w).sum(axis=(1, 2))
        press_area = ((dp_fields >= threshold_pressure) * area_w).sum(axis=(1, 2))
    max_dp = dp_fields.reshape(len(times), -1).max(axis=1)

    in_plume = plume_fields > plume_level
    with np.errstate(invalid="ignore"):
        mean_dp = np.array([
            float(dp_fields[i][in_plume[i]].mean()) if in_plume[i].any() else 0.0
            for i in range(len(times))])

    warnings: list[str] = []
    if len(times) > 3 and plume_area[-1] > 0:
        k = max(len(times) - 3, 0)
        span = U.time_out(float(times[-1] - times[k]), "yr")
        grow = (plume_area[-1] - plume_area[k]) / plume_area[-1]
        if grow > 0.02 and span > 0:
            warnings.append(
                f"the plume footprint grew {100 * grow:.1f} % over the last "
                f"{span:,.0f} years of the simulation "
                f"({100 * grow / span:.3f} %/yr) and has not stopped moving. "
                "Extend the model horizon before claiming stabilisation "
                "[40 CFR 146.84(c)(1)].")

    t_yr = U.time_out(times, "yr")
    post = t_yr[t_yr >= U.time_out(injection_end, "yr")]
    if len(post) > 2:
        gap = float(np.median(np.diff(post)))
        if gap > 5.0:
            warnings.append(
                f"post-injection output times are spaced about {gap:,.0f} years "
                "apart, so migration rates are averages over long intervals and "
                "will understate the true instantaneous rate. Request more "
                "frequent output before using the rate to argue for an "
                "alternative PISC timeframe.")
    if len(post) < 4:
        warnings.append(
            "fewer than four post-injection output times; the stabilisation "
            "test has almost nothing to work with")

    res = PISCResult(
        times_years=U.time_out(times, "yr"),
        plume_area_m2=plume_area.astype(float),
        pressure_area_m2=press_area.astype(float),
        max_dp=max_dp.astype(float),
        mean_dp_in_plume=mean_dp,
        injection_end_year=U.time_out(injection_end, "yr"),
        threshold_pressure=threshold_pressure,
        warnings=warnings,
    )

    if x is not None and y is not None and origins:
        res.directional = directional_migration(
            times, plume_fields, plume_level, x, y, origins, azimuths)
    return res


def directional_migration(times: np.ndarray, plume_fields: np.ndarray,
                          plume_level: float, x: np.ndarray, y: np.ndarray,
                          origins: list[tuple[float, float]],
                          azimuths: int = 8) -> dict:
    """Plume reach and migration rate along compass rays from each origin.

    This is the "linear segments" method used in PISC plans: rather than
    averaging the plume into one effective radius, it tracks how far the front
    has moved in each direction, which is what reveals a plume that has
    stopped in three directions but is still running up-dip in the fourth.
    """
    times = np.asarray(times, float)
    t_yr = U.time_out(times, "yr")
    X, Y = np.meshgrid(np.asarray(x, float), np.asarray(y, float))
    out: dict = {}

    for (ox, oy) in origins:
        R = np.hypot(X - ox, Y - oy)
        AZ = (np.degrees(np.arctan2(X - ox, Y - oy)) + 360.0) % 360.0
        per_az: dict = {}
        half = 180.0 / azimuths
        for k in range(azimuths):
            az = 360.0 * k / azimuths
            d = np.abs(((AZ - az + 180.0) % 360.0) - 180.0)
            sector = d <= half
            reach = np.array([
                float(R[sector & (plume_fields[i] > plume_level)].max())
                if np.any(sector & (plume_fields[i] > plume_level)) else 0.0
                for i in range(len(times))])
            dt = np.diff(t_yr)
            dt[dt == 0] = np.nan
            rate = np.concatenate([[np.nan], np.diff(reach) / dt])
            per_az[round(az, 1)] = {
                "reach_ft": U.length_out(reach, "ft"),
                "rate_ft_per_yr": U.length_out(rate, "ft"),
                "final_reach_ft": U.length_out(float(reach[-1]), "ft"),
                "peak_rate_ft_per_yr": U.length_out(
                    float(np.nanmax(rate)) if np.any(np.isfinite(rate)) else np.nan, "ft"),
                "final_rate_ft_per_yr": U.length_out(
                    float(rate[-1]) if np.isfinite(rate[-1]) else np.nan, "ft"),
            }
        out[f"{ox:.0f},{oy:.0f}"] = per_az
    return out


# ==========================================================================
# 40 CFR 146.93 checklist
# ==========================================================================
_C1_ITEMS = [
    ("i", "The results of computational modeling performed pursuant to "
          "delineation of the area of review under 146.84"),
    ("ii", "The predicted timeframe for pressure decline within the injection "
           "zone, and any other zones, such that formation fluids may not be "
           "forced into any USDWs; and/or the timeframe for pressure decline "
           "to pre-injection pressures"),
    ("iii", "The predicted rate of carbon dioxide plume migration within the "
            "injection zone, and the predicted timeframe for the cessation of "
            "migration"),
    ("iv", "A description of the site-specific processes that will result in "
           "carbon dioxide trapping including immobilization by capillary "
           "trapping, dissolution, and mineralization at the site"),
    ("v", "The predicted rate of carbon dioxide trapping in the immobile "
          "capillary phase, dissolved phase, and/or mineral phase"),
    ("vi", "The results of laboratory, field or research studies used to "
           "verify the information required in items (iii) through (v)"),
    ("vii", "A characterization of the confining zone(s) including a "
            "demonstration that it is free of transmissive faults, fractures "
            "and micro-fractures and of appropriate thickness, permeability "
            "and integrity to impede fluid movement"),
    ("viii", "The presence of potential conduits for fluid movement including "
             "planned injection wells and project monitoring wells associated "
             "with the project or any other projects in proximity to the "
             "predicted/modeled final extent of the plume and area of elevated "
             "pressure"),
    ("ix", "A description of the well construction and an assessment of the "
           "quality of plugs of all abandoned wells within the area of review"),
    ("x", "The distance between the injection zone and the nearest USDWs above "
          "and/or below the injection zone"),
]

_C2_ITEMS = [
    ("i", "All analyses and tests performed to support the demonstration must "
          "be accurate, reproducible, and performed in accordance with the "
          "established quality assurance standards"),
    ("ii", "Estimation techniques must be appropriate and EPA-certified test "
           "protocols must be used where available"),
    ("iii", "Predictive models must be appropriate and tailored to the site "
            "conditions, composition of the carbon dioxide stream and injection "
            "and site conditions over the life of the project"),
    ("iv", "Predictive models must be calibrated using existing information "
           "where sufficient data are available"),
    ("v", "Reasonably conservative values and modeling assumptions must be used "
          "and disclosed to the Director whenever values are estimated on the "
          "basis of known, historical information instead of site-specific "
          "measurements"),
    ("vi", "An analysis must be performed to identify and assess aspects of the "
           "demonstration that contribute significantly to uncertainty, "
           "including sensitivity analyses"),
    ("vii", "An approved quality assurance and quality control plan must "
            "address all aspects of the demonstration"),
    ("viii", "Any additional criteria required by the Director"),
]


def alternative_timeframe_checklist(result: PISCResult, *,
                                    trapping_described: bool = False,
                                    trapping_rates_quantified: bool = False,
                                    lab_or_field_studies: bool = False,
                                    confining_zone_characterised: bool = False,
                                    conduits_identified: bool = False,
                                    abandoned_wells_assessed: bool = False,
                                    usdw_separation: float = float("nan"),
                                    sensitivity_analysis_done: bool = False,
                                    model_calibrated: bool = False,
                                    qa_plan: bool = False) -> list[dict]:
    """Populate the 40 CFR 146.93(c) demonstration checklist.

    Items the toolkit can answer from the model are filled in with the
    computed number.  The rest are flagged as requiring project evidence --
    the point being that a modelling tool cannot, by itself, satisfy
    146.93(c), and a checklist that pretends otherwise is worse than none.

    The regulatory text quoted here is transcribed from a Class VI permit
    application's own crosswalk table; verify against the current CFR before
    submitting anything.
    """
    dp_year = result.pressure_below_threshold_year()
    rec_year = result.pressure_recovery_year(0.05)
    stab = result.stabilisation_year()
    end = result.injection_end_year

    computed = {
        "i": (True, "AoR delineation model results are attached; see the AoR "
                    "section of this report"),
        "ii": (np.isfinite(dp_year),
               (f"pressure everywhere falls below the AoR threshold at year "
                f"{dp_year:,.0f} ({dp_year - end:,.0f} yr post-injection); "
                f"within 5 % of pre-injection at year {rec_year:,.0f}"
                if np.isfinite(dp_year) else
                "pressure does not fall below the AoR threshold within the "
                "simulated horizon")),
        "iii": (np.isfinite(stab),
                (f"peak migration rate "
                 f"{U.length_out(result.peak_migration_rate(), 'ft'):,.0f} ft/yr; "
                 f"stabilises at year {stab:,.0f} "
                 f"({stab - end:,.0f} yr post-injection)"
                 if np.isfinite(stab) else
                 "plume migration has not ceased within the simulated horizon")),
        "iv": (trapping_described, "requires site-specific narrative on structural, "
                                   "residual, solubility and mineral trapping"),
        "v": (trapping_rates_quantified,
              "requires quantified trapping rates by mechanism; the "
              "vertical-equilibrium model reports residually trapped volume, "
              "but dissolution and mineralisation need a compositional or "
              "reactive-transport model"),
        "vi": (lab_or_field_studies, "requires laboratory / field / research study results"),
        "vii": (confining_zone_characterised, "requires confining-zone characterisation"),
        "viii": (conduits_identified, "requires the corrective-action well inventory"),
        "ix": (abandoned_wells_assessed, "requires plugging-record assessment"),
        "x": (np.isfinite(usdw_separation),
              (f"{U.length_out(usdw_separation, 'ft'):,.0f} ft between the "
               "injection zone and the nearest USDW"
               if np.isfinite(usdw_separation) else "not supplied")),
    }

    rows = []
    for tag, text in _C1_ITEMS:
        ok, note = computed[tag]
        rows.append({
            "citation": f"40 CFR 146.93(c)(1)({tag})",
            "requirement": text,
            "satisfied_by_model": bool(ok),
            "evidence": note,
        })

    c2_state = {
        "i": (True, "all calculations are scripted and reproducible from the "
                    "input file recorded with this run"),
        "ii": (True, "methods and citations are recorded per calculation"),
        "iii": (True, "model inputs are site-specific; see the input record"),
        "iv": (model_calibrated, "model calibration against site monitoring data"),
        "v": (True, "estimated values are flagged in the input record; run the "
                    "uncertainty module to bound them"),
        "vi": (sensitivity_analysis_done,
               "run aorpisc.uncertainty for tornado and Monte Carlo results"),
        "vii": (qa_plan, "requires an approved QASP"),
        "viii": (False, "ask the Director"),
    }
    for tag, text in _C2_ITEMS:
        ok, note = c2_state[tag]
        rows.append({
            "citation": f"40 CFR 146.93(c)(2)({tag})",
            "requirement": text,
            "satisfied_by_model": bool(ok),
            "evidence": note,
        })
    return rows


def pressure_differential_table(bhp: dict[str, np.ndarray], times: np.ndarray,
                                initial_pressure: dict[str, float] | float
                                ) -> list[dict]:
    """Pre- vs post-injection pressure differential per well.

    Required by 40 CFR 146.93(a)(2)(i) and 16 TAC 5.203(m)(2), and normally
    presented as a year-by-year table of maximum differential at each injector.
    """
    t_yr = U.time_out(np.asarray(times, float), "yr")
    rows = []
    for i, t in enumerate(t_yr):
        row = {"year": float(t)}
        for name, series in bhp.items():
            p0 = (initial_pressure[name] if isinstance(initial_pressure, dict)
                  else initial_pressure)
            row[f"{name}_dP_psi"] = U.pressure_out(float(series[i]) - p0, "psi")
        rows.append(row)
    return rows


__all__ = [
    "PISCResult", "analyse", "directional_migration",
    "alternative_timeframe_checklist", "pressure_differential_table",
]
