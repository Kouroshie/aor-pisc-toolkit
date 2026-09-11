"""End-to-end AoR + PISC run driven by a project file.

One function, :func:`run`, walks the whole sequence a Class VI submittal
needs and keeps every intermediate result attached to the output so nothing
has to be recomputed differently in a second place:

1. evaluate CO2 and brine properties at in-situ conditions;
2. compute the threshold pressure by every applicable method and select one;
3. run the chosen flow model (analytical superposition, vertical-equilibrium
   numerical, or an imported simulation);
4. delineate the AoR from the maximum-over-time plume and pressure fields;
5. screen artificial penetrations and stage corrective action by arrival time;
6. compute the PISC metrics and the 146.93(c) checklist;
7. optionally run tornado and Monte Carlo uncertainty.

The CLI, the browser app and the report generator all go through here, so the
number in the report is by construction the number the model produced.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from . import corrective, delineate, fluids, pisc, threshold
from . import units as U
from .analytical import (
    AquiferModel,
    Boundary,
    BuckleyLeverettPlume,
    NordbottenCeliaPlume,
    PlumeInputs,
    VolumetricPlume,
    Well,
    endpoint_mobility_ratio,
    gravity_number,
    residual_trapping_limit_radius,
)
from .config import Project
from .numerical import Grid, GridProperties, VESolver, VEWell


@dataclass
class ProjectResult:
    """Everything one project run produced."""

    project: Project
    fluid: fluids.FluidState
    thresholds: list[threshold.ThresholdResult]
    selected_threshold: threshold.ThresholdResult
    aor: delineate.AoRResult
    x: np.ndarray
    y: np.ndarray
    times: np.ndarray
    dp_fields: np.ndarray
    plume_fields: np.ndarray
    pisc: pisc.PISCResult | None = None
    corrective: corrective.CorrectiveActionPlan | None = None
    ve: object = None
    analytical_checks: dict = field(default_factory=dict)
    uncertainty: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def cell_area(self) -> float:
        dx = float(np.median(np.diff(self.x)))
        dy = float(np.median(np.diff(self.y)))
        return abs(dx * dy)

    def summary(self) -> dict:
        out = {
            "project": self.project.summary(),
            "fluids": self.fluid.summary(),
            "threshold": self.selected_threshold.summary(),
            "threshold_all_methods": [t.summary() for t in self.thresholds],
            "aor": self.aor.summary(),
            "analytical_checks": self.analytical_checks,
            "warnings": list(self.warnings),
        }
        if self.pisc is not None:
            out["pisc"] = self.pisc.summary()
        if self.corrective is not None:
            out["corrective_action"] = self.corrective.summary()
        if self.ve is not None:
            out["ve_solver"] = self.ve.summary()
        if self.uncertainty:
            out["uncertainty"] = self.uncertainty
        return out


# ==========================================================================
def select_threshold(p: Project, results: list[threshold.ThresholdResult]
                     ) -> threshold.ThresholdResult:
    """Pick the threshold the project asked for, or the protective default."""
    if np.isfinite(p.threshold_override):
        return threshold.ThresholdResult(
            method="user override",
            delta_p_critical=p.threshold_override,
            p_threshold_abs=p.injection_zone.initial_pressure + p.threshold_override,
            initial_pressure=p.injection_zone.initial_pressure,
            regime="n/a",
            citation="value supplied in the project file",
            warnings=["threshold pressure was supplied directly and not "
                      "derived; record the basis in the AoR plan"],
        )
    key = p.threshold_method
    if key in ("auto", "", "recommended"):
        return threshold.recommended(results)
    aliases = {
        "method1": "Method 1", "thornhill": "Method 1",
        "method2": "Method 2", "nicot": "Method 2",
        "method2b": "Method 2b", "variable_density": "Method 2b",
        "mud_column": "Method 3", "method3": "Method 3", "tceq": "Method 3",
        "overpressured": "Over-pressurised",
    }
    want = aliases.get(key)
    if want:
        for r in results:
            if r.method.startswith(want):
                return r
    raise ValueError(f"unknown threshold method {p.threshold_method!r}; "
                     f"use one of {sorted(aliases) + ['auto']}")


# ==========================================================================
def _analytical_model(p: Project) -> AquiferModel:
    fs = p.fluid_state()
    iz = p.injection_zone
    half_x = 0.5 * p.grid_nx * p.cell_size
    half_y = 0.5 * p.grid_ny * p.cell_size
    xs = [w.x for w in p.wells] or [0.0]
    ys = [w.y for w in p.wells] or [0.0]
    cx, cy = float(np.mean(xs)), float(np.mean(ys))

    if p.boundary in ("infinite", "open"):
        bc = Boundary(kind="infinite")
    else:
        side = ("constant_pressure" if p.boundary.startswith("constant")
                else "noflow")
        bc = Boundary(kind="rectangle",
                      xmin=cx - half_x, xmax=cx + half_x,
                      ymin=cy - half_y, ymax=cy + half_y,
                      sides=(side,) * 4)
    return AquiferModel(
        permeability=iz.permeability, thickness=iz.thickness,
        porosity=iz.porosity, total_compressibility=p.total_compressibility(),
        mu_brine=fs.mu_brine, mu_co2=fs.mu_co2, rho_co2=fs.rho_co2,
        initial_pressure=iz.initial_pressure, relperm=p.relperm, boundary=bc)


def _to_analytical_wells(p: Project) -> list[Well]:
    return [Well(name=w.name, x=w.x, y=w.y, schedule=list(w.schedule),
                 kind=w.kind, radius=w.radius) for w in p.wells]


def _to_ve_wells(p: Project) -> list[VEWell]:
    return [VEWell(name=w.name, x=w.x, y=w.y, schedule=list(w.schedule),
                   kind=w.kind, radius=w.radius, max_bhp=w.max_bhp)
            for w in p.wells]


def _grid(p: Project, plume_radius: float = 0.0,
          pressure_radius: float = 0.0) -> Grid:
    """Build the VE grid, telescoping outward when the project asks for it.

    A uniform grid cannot serve both masters: the plume needs cells small
    enough to resolve a buoyant tongue, and the pressure front needs a domain
    that reaches well past it.  When ``half_width`` is given (or can be
    inferred from the estimated pressure radius), the grid keeps ``cell_size``
    cells over the well field and grows geometrically outward, which is the
    mesh refinement EPA describes in Section 2.3.1.
    """
    xs = [w.x for w in p.wells] or [0.0]
    ys = [w.y for w in p.wells] or [0.0]
    cx, cy = float(np.mean(xs)), float(np.mean(ys))
    spread = max([abs(w.x - cx) for w in p.wells] + [abs(w.y - cy) for w in p.wells] + [0.0])

    half = p.grid_half_width
    if not np.isfinite(half):
        if pressure_radius > 0:
            half = 1.35 * (spread + max(pressure_radius, plume_radius))
        else:
            return Grid(nx=p.grid_nx, ny=p.grid_ny, dx=p.cell_size, dy=p.cell_size,
                        x0=cx - 0.5 * p.grid_nx * p.cell_size,
                        y0=cy - 0.5 * p.grid_ny * p.cell_size)
    fine = p.grid_fine_half_width
    if not np.isfinite(fine):
        fine = min(spread + 1.6 * max(plume_radius, p.cell_size * 5), half)
    return Grid.telescoping(center=(cx, cy), fine_cell=p.cell_size,
                            fine_half_width=fine, total_half_width=half,
                            growth=p.grid_growth)


def _ve_boundary_check(ve, threshold_pressure: float) -> dict:
    """How much of the pressure signal is reaching the VE model boundary.

    EPA Section 3.3.3.2 asks that the domain and boundary conditions be tested
    so they "do not result in numerical artifacts that impact the model
    results".  This measures the buildup on the four edge rows over the whole
    run and compares it with the AoR threshold.  Both failure modes matter: a
    no-flow edge that is too close inflates the pressure front, and a
    constant-pressure edge that is too close drains it and truncates the AoR.
    """
    dp = np.asarray(ve.dp)
    faces = {
        "xmin": float(dp[:, :, 0].max()), "xmax": float(dp[:, :, -1].max()),
        "ymin": float(dp[:, 0, :].max()), "ymax": float(dp[:, -1, :].max()),
    }
    worst = max(faces.values())
    frac = worst / threshold_pressure if threshold_pressure else float("nan")
    return {
        "max_dp_on_faces_psi": {k: U.pressure_out(v, "psi") for k, v in faces.items()},
        "threshold_psi": U.pressure_out(threshold_pressure, "psi"),
        "fraction_of_threshold": frac,
        "verdict": (
            "boundary influence negligible" if frac < 0.05 else
            f"ENLARGE THE DOMAIN: pressure buildup at the model edge reaches "
            f"{100 * frac:.0f} % of the AoR threshold, so the boundary "
            "condition is shaping the pressure front"),
    }


def analytical_cross_checks(p: Project) -> dict:
    """Closed-form sanity numbers that should accompany any AoR.

    EPA suggests analytical models as "a relatively simple comparative check
    on numerical modeling results" (Section 2.3.2).  These are cheap, they
    take five seconds to explain, and if the numerical AoR disagrees with all
    of them by a large factor something is wrong with the numerical model.
    """
    fs = p.fluid_state()
    iz = p.injection_zone
    inp = PlumeInputs(iz.thickness, iz.porosity, iz.permeability,
                      fs.rho_co2, fs.mu_co2, fs.rho_brine, fs.mu_brine,
                      relperm=p.relperm)
    m = p.total_injected_mass()
    q_res = (m / max(p.injection_end(), 1e-9)) / fs.rho_co2 if m else 0.0
    gamma = endpoint_mobility_ratio(p.relperm, fs.mu_co2, fs.mu_brine)
    return {
        "co2_density_kg_m3": fs.rho_co2,
        "endpoint_mobility_ratio_gamma": gamma,
        "gravity_number": gravity_number(iz.permeability, iz.thickness,
                                         fs.delta_rho, fs.mu_co2, max(q_res, 1e-30)),
        "volumetric_radius_ft": U.length_out(VolumetricPlume(inp).radius(m), "ft"),
        "nordbotten_celia_radius_ft": U.length_out(
            NordbottenCeliaPlume(inp, gamma).radius(m), "ft"),
        "buckley_leverett_radius_ft": U.length_out(
            BuckleyLeverettPlume(inp).radius(m), "ft"),
        "residual_trapping_limit_radius_ft": U.length_out(
            residual_trapping_limit_radius(m, fs.rho_co2, iz.porosity,
                                           iz.thickness, p.relperm.sgr), "ft"),
        "note": (
            "These are single-well, homogeneous, horizontal estimates for the "
            "total injected mass. They bracket rather than replace the model: "
            "the volumetric radius is a floor, the Nordbotten-Celia nose "
            "accounts for the unfavourable mobility ratio, and the "
            "residual-trapping radius is the mass-balance ceiling on the "
            "ultimate footprint."),
    }


# ==========================================================================
def run(p: Project, *, penetrations: list | None = None,
        progress: Callable[[str], None] | None = None,
        run_uncertainty: bool | None = None) -> ProjectResult:
    """Execute the whole AoR/PISC workflow for a project."""
    say = progress or (lambda _msg: None)
    warnings = list(p.warnings)

    say("evaluating fluid properties")
    fs = p.fluid_state()
    warnings.extend(fs.notes)

    say("computing threshold pressure")
    th_all = threshold.compare_methods(
        p_usdw=(p.usdw.initial_pressure if np.isfinite(p.usdw.initial_pressure)
                else fluids.hydrostatic_pressure(p.usdw.base_depth)),
        p_inj=p.injection_zone.initial_pressure,
        depth_usdw=p.usdw.base_depth,
        depth_inj=p.threshold_depth,
        temperature_inj=p.injection_zone.temperature,
        temperature_usdw=(p.usdw.temperature if np.isfinite(p.usdw.temperature)
                          else U.temperature(70, "F")),
        salinity_inj=p.injection_zone.salinity,
        salinity_usdw=(p.usdw.salinity if np.isfinite(p.usdw.salinity) else 0.0005),
        mud_weight_ppg=p.mud_weight_ppg, gel_strength=p.gel_strength,
        mud_datum_depth=(p.mud_datum_depth if np.isfinite(p.mud_datum_depth)
                         else None))
    th = select_threshold(p, th_all)
    warnings.extend(th.warnings)

    say("running the flow model")
    checks = analytical_cross_checks(p)
    ve_result = None
    _grid_areas = None

    if p.engine == "ve":
        from .analytical.pressure import radius_of_investigation
        _m = _analytical_model(p)
        _q = max((sum(abs(_m.reservoir_rate(w, float(t))) for w in _to_analytical_wells(p))
                  for t in p.output_times), default=0.0)
        _r_press = max((radius_of_investigation(_m, float(t), th.delta_p_critical, _q)
                        for t in p.output_times), default=0.0)
        g = _grid(p, plume_radius=U.length(checks["nordbotten_celia_radius_ft"], "ft"),
                  pressure_radius=_r_press)
        iz = p.injection_zone
        props = GridProperties(
            g, permeability=iz.permeability, porosity=iz.porosity,
            thickness=iz.thickness,
            anisotropy_y_over_x=1.0)
        if iz.dip_degrees:
            props.add_dip(iz.dip_degrees, iz.dip_azimuth)
        solver = VESolver(
            props, rho_co2=fs.rho_co2, mu_co2=fs.mu_co2, rho_brine=fs.rho_brine,
            mu_brine=fs.mu_brine, total_compressibility=p.total_compressibility(),
            reference_pressure=iz.initial_pressure, relperm=p.relperm,
            # a VE grid is finite, so an "infinite" project maps to a
            # far-field constant-pressure edge, the closest finite analogue
            boundary=("noflow" if p.boundary.startswith("noflow")
                      else "constant_pressure"))
        ve_result = solver.run(_to_ve_wells(p), end_time=p.end_time,
                               output_times=p.output_times)
        warnings.extend(ve_result.warnings)
        x, y = g.xc, g.yc
        _grid_areas = g.areas
        times = ve_result.times
        dp_fields = ve_result.dp
        plume_fields = np.array([
            ve_result.saturation_proxy(i, props, p.relperm)
            for i in range(len(times))])
        xs0 = [w.x for w in p.wells] or [0.0]
        ys0 = [w.y for w in p.wells] or [0.0]
        res_check = g.resolution_check(
            U.length(checks["nordbotten_celia_radius_ft"], "ft"),
            center=(float(np.mean(xs0)), float(np.mean(ys0))))
        checks["grid_resolution"] = res_check
        if res_check["verdict"] != "adequate":
            warnings.append(res_check["verdict"])
        checks["boundary_influence"] = _ve_boundary_check(
            ve_result, th.delta_p_critical)
        if checks["boundary_influence"]["verdict"] != "boundary influence negligible":
            warnings.append(checks["boundary_influence"]["verdict"])

    elif p.engine in ("analytical", "analytic"):
        model = _analytical_model(p)
        wells = _to_analytical_wells(p)
        times = p.output_times
        aor_prelim = delineate.delineate_analytical(
            model, wells, th.delta_p_critical, times,
            plume_criterion=p.plume_criterion)
        warnings.extend(aor_prelim.warnings)
        # rebuild the fields on the grid the delineation settled on so the
        # PISC and corrective-action steps see the same numbers
        reach = U.length(aor_prelim.metadata["evaluation_half_width_mi"], "mi")
        xs = [w.x for w in p.wells] or [0.0]
        ys = [w.y for w in p.wells] or [0.0]
        x = np.linspace(min(xs) - reach, max(xs) + reach, p.grid_nx)
        y = np.linspace(min(ys) - reach, max(ys) + reach, p.grid_ny)
        dp_fields, _ = model.pressure_grid(x, y, times, wells)
        X, Y = np.meshgrid(x, y)
        plume_fields = np.zeros((len(times), len(y), len(x)))
        for i, t in enumerate(times):
            f = np.zeros_like(X)
            for w in wells:
                if w.kind != "injector":
                    continue
                r = model.front_radius(w, float(t))
                if r > 0:
                    f = np.maximum(f, (np.hypot(X - w.x, Y - w.y) <= r).astype(float))
            plume_fields[i] = f
        checks["boundary_influence"] = model.influence_check(
            wells, float(times[-1]), th.delta_p_critical)
    else:
        raise ValueError(
            f"engine {p.engine!r} is not run by this function; import the "
            "simulation with aorpisc.io.load_grid_csv and call "
            "aorpisc.delineate.delineate directly")

    say("delineating the AoR")
    plume_level = (p.plume_cutoff if p.engine == "ve" else 0.5)
    aor = delineate.delineate(
        x, y,
        dp_field=delineate.envelope(dp_fields),
        threshold_pressure=th.delta_p_critical,
        plume_field=delineate.envelope(plume_fields),
        plume_level=plume_level,
        plume_criterion=p.plume_criterion,
        method=("vertical-equilibrium numerical model" if p.engine == "ve"
                else "analytical superposition"),
        wells=[w.name for w in p.wells if w.kind == "injector"],
        metadata={"engine": p.engine, "threshold_method": th.method},
    )
    warnings.extend(aor.warnings)

    say("computing PISC metrics")
    pisc_res = pisc.analyse(
        times, plume_fields=plume_fields, plume_level=plume_level,
        dp_fields=dp_fields, threshold_pressure=th.delta_p_critical,
        cell_area=(_grid_areas if _grid_areas is not None
                   else abs(float(np.median(np.diff(x))) * float(np.median(np.diff(y))))),
        injection_end=p.injection_end(), x=x, y=y,
        origins=[(w.x, w.y) for w in p.wells if w.kind == "injector"])
    warnings.extend(pisc_res.warnings)

    ca = None
    if penetrations is None and p.penetrations_csv:
        say("loading artificial penetrations")
        penetrations = corrective.load_wells_csv(
            p.penetrations_csv, unit=p.penetrations_unit)
    if penetrations:
        say("screening artificial penetrations")
        cz_top = (p.confining_zone.top_depth if np.isfinite(p.confining_zone.top_depth)
                  else p.injection_zone.top_depth - U.length(100, "ft"))
        cz_base = (p.confining_zone.base_depth if np.isfinite(p.confining_zone.base_depth)
                   else p.injection_zone.top_depth)
        ca = corrective.screen(
            penetrations, aor, cz_top, cz_base,
            injectors=[(w.x, w.y) for w in p.wells if w.kind == "injector"])
        ca = corrective.arrival_times(
            ca, x, y, times, plume_fields=plume_fields, plume_level=plume_level,
            dp_fields=dp_fields, threshold_pressure=th.delta_p_critical)
        warnings.extend(ca.warnings)

    result = ProjectResult(
        project=p, fluid=fs, thresholds=th_all, selected_threshold=th,
        aor=aor, x=x, y=y, times=times, dp_fields=dp_fields,
        plume_fields=plume_fields, pisc=pisc_res, corrective=ca,
        ve=ve_result, analytical_checks=checks, warnings=warnings,
    )

    do_unc = (p.uncertainty.get("enabled", False)
              if run_uncertainty is None else run_uncertainty)
    if do_unc:
        say("running uncertainty analysis")
        result.uncertainty = run_uncertainty_analysis(p, th, progress=progress)
    return result


# ==========================================================================
def run_uncertainty_analysis(p: Project, th: threshold.ThresholdResult,
                             progress: Callable[[str], None] | None = None
                             ) -> dict:
    """Tornado + Monte Carlo on AoR area, using the fast analytical engine.

    The analytical engine is used deliberately: a few hundred realisations of
    a vertical-equilibrium model is hours, a few hundred analytical
    realisations is seconds, and the *ranking* of parameter importance and the
    *spread* of AoR area are what the sensitivity requirement asks for.
    Re-run the two or three most influential cases through the VE model to
    confirm.
    """
    from . import uncertainty as unc

    cfg = p.uncertainty or {}
    n = int(cfg.get("realisations", 200))
    spread = float(cfg.get("spread", 0.5))
    seed = cfg.get("seed", 0)

    iz = p.injection_zone
    params = unc.default_parameters(
        permeability_md=U.permeability_out(iz.permeability, "mD"),
        porosity=iz.porosity,
        thickness_ft=U.length_out(iz.thickness, "ft"),
        compressibility_1_psi=U.compressibility_out(p.total_compressibility(), "1/psi"),
        spread=spread)

    base_times = p.output_times
    wells = _to_analytical_wells(p)
    xs = [w.x for w in wells] or [0.0]
    ys = [w.y for w in wells] or [0.0]

    def build(case: dict) -> AquiferModel:
        fs = p.fluid_state()
        return AquiferModel(
            permeability=U.permeability(case["permeability_md"], "mD"),
            thickness=U.length(case["thickness_ft"], "ft"),
            porosity=case["porosity"],
            total_compressibility=U.compressibility(case["compressibility_1_psi"], "1/psi"),
            mu_brine=fs.mu_brine, mu_co2=fs.mu_co2, rho_co2=fs.rho_co2,
            initial_pressure=iz.initial_pressure, relperm=p.relperm,
            boundary=Boundary(kind="infinite"))

    def area_of(case: dict) -> float:
        m = build(case)
        r = delineate.delineate_analytical(m, wells, th.delta_p_critical,
                                           base_times, n=121, max_expansions=4)
        return r.area_acres

    say = progress or (lambda _m: None)
    say("  tornado (one parameter at a time)")
    tor = unc.tornado(area_of, params, metric="AoR area (acres)")

    say(f"  Monte Carlo ({n} Latin-hypercube realisations)")
    # One fixed grid for every realisation, so the cell-wise inclusion
    # probability is comparable across the ensemble.  Size it from the widest
    # AoR the tornado produced, with room to spare.
    widest = max([tor.base_value] + [max(r["low_value"], r["high_value"])
                                     for r in tor.rows])
    reach = 2.5 * float(np.sqrt(U.area(max(widest, 1.0), "acres") / np.pi))
    grid_x = np.linspace(min(xs) - reach, max(xs) + reach, 121)
    grid_y = np.linspace(min(ys) - reach, max(ys) + reach, 121)
    GX, GY = np.meshgrid(grid_x, grid_y)

    def evaluate(case: dict) -> dict:
        m = build(case)
        _, dp_max = m.pressure_grid(grid_x, grid_y, base_times, wells)
        inside = dp_max >= th.delta_p_critical
        for w in wells:
            if w.kind != "injector":
                continue
            r = max(m.front_radius(w, float(t)) for t in base_times)
            inside |= np.hypot(GX - w.x, GY - w.y) <= r
        area = float(inside.sum()) * abs(
            (grid_x[1] - grid_x[0]) * (grid_y[1] - grid_y[0]))
        return {"aor_area_acres": U.area_out(area, "acres"), "inside": inside}

    mc = unc.monte_carlo(evaluate, params, n=n, seed=seed,
                         grid_x=grid_x, grid_y=grid_y)

    # Spread relative to the ensemble's own base case, which is the number
    # that transfers across engines. The absolute acreages do not.
    pct = mc.percentiles("aor_area_acres")
    base = tor.base_value or float("nan")
    ratios = {k: (v / base if base else float("nan")) for k, v in pct.items()}

    caveat = (
        "This ensemble was run on the ANALYTICAL engine (homogeneous, "
        "horizontal, injection period only), because a few hundred "
        "vertical-equilibrium realisations is hours of compute. Its absolute "
        "areas are therefore NOT directly comparable to a vertical-equilibrium "
        "AoR, which additionally carries dip, heterogeneity and post-injection "
        "buoyant migration. What transfers is the ranking of parameter "
        "importance and the RELATIVE spread (see percentile_ratio_to_base). "
        "Re-run the two or three most influential cases through the chosen "
        "engine before quoting a probabilistic boundary."
        if p.engine != "analytical" else
        "This ensemble was run on the same analytical engine as the base case, "
        "so its absolute areas are directly comparable.")

    return {
        "engine_used": "analytical",
        "project_engine": p.engine,
        "comparability": caveat,
        "base_case_area_acres": base,
        "percentile_ratio_to_base": ratios,
        "tornado": tor.summary(),
        "monte_carlo": mc.summary(),
        "_tornado_obj": tor,
        "_monte_carlo_obj": mc,
    }


__all__ = ["ProjectResult", "run", "select_threshold", "analytical_cross_checks",
           "run_uncertainty_analysis"]
