"""Command-line interface.

    containment run project.yaml -o out/            # full AoR + PISC + report
    containment threshold project.yaml              # threshold pressure, all methods
    containment reevaluate before.yaml after.yaml   # AoR reevaluation difference
    containment import sim.csv --dp-col PRES ...    # re-delineate somebody's model
    containment app                                 # launch the browser app
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def _p(msg: str):
    print(msg, flush=True)


def _banner(title: str):
    _p("")
    _p(title)
    _p("-" * len(title))


# ==========================================================================
def cmd_run(args) -> int:
    from . import report, workflow
    from .config import Project
    from .io import exporters

    proj = Project.load(args.project)
    if proj.warnings:
        _banner("Project warnings")
        for w in proj.warnings:
            _p(f"  ! {w}")

    res = workflow.run(proj, progress=lambda m: _p(f"  .. {m}"),
                       run_uncertainty=args.uncertainty)

    _banner("Threshold pressure")
    for t in res.thresholds:
        mark = ">>" if t.method == res.selected_threshold.method else "  "
        _p(f"{mark} {t}")

    _banner("Area of Review")
    a = res.aor.summary()
    _p(f"   area            {a['aor_area_acres']:>14,.0f} acres "
       f"({a['aor_area_sq_mi']:,.2f} sq mi)")
    _p(f"   plume component {a['plume_area_acres']:>14,.0f} acres")
    _p(f"   pressure front  {a['pressure_front_area_acres']:>14,.0f} acres")
    _p(f"   controlled by   {a['controlling_component']}")

    _banner("Closed-form cross-checks (single well, homogeneous)")
    for k in ("volumetric_radius_ft", "nordbotten_celia_radius_ft",
              "buckley_leverett_radius_ft", "residual_trapping_limit_radius_ft"):
        _p(f"   {k:38s} {res.analytical_checks[k]:>12,.0f} ft")

    if res.pisc:
        _banner("Post-injection site care")
        ps = res.pisc.summary()
        _p(f"   peak migration rate     {ps['peak_migration_rate_ft_per_yr']:>10,.0f} ft/yr")
        _p(f"   final migration rate    {ps['final_migration_rate_ft_per_yr']:>10,.0f} ft/yr")
        _p(f"   plume stabilises        year {ps['plume_stabilisation_year']:,.1f}")
        _p(f"   pressure < threshold    year {ps['pressure_below_threshold_year']:,.1f}")
        _p(f"   {ps['recommended_pisc']['verdict']}")

    if res.corrective:
        _banner("Artificial penetrations")
        cs = res.corrective.summary()
        for k in ("penetrations_inside_aor", "corrective_action_required",
                  "field_testing_required", "monitor", "no_action"):
            _p(f"   {k:32s} {cs[k]:>6}")

    if res.warnings:
        _banner("Warnings")
        for w in dict.fromkeys(res.warnings):
            _p(f"  ! {w}")

    out = args.output
    if out:
        os.makedirs(out, exist_ok=True)
        crs = None
        if proj.crs:
            crs = exporters.LocalCRS(
                epsg=proj.crs.get("epsg"),
                origin_lon=proj.crs.get("origin_lon"),
                origin_lat=proj.crs.get("origin_lat"))
        stem = os.path.splitext(os.path.basename(args.project))[0]
        exporters.write_polygons(res.aor, os.path.join(out, f"{stem}_aor.geojson"), crs)
        exporters.write_polygons(res.aor, os.path.join(out, f"{stem}_aor.kml"), crs)
        exporters.save_npz(os.path.join(out, f"{stem}_fields.npz"),
                           res.x, res.y, res.times,
                           dp=res.dp_fields, plume=res.plume_fields)
        if res.pisc:
            exporters.table_to_csv(res.pisc.table(),
                                   os.path.join(out, f"{stem}_pisc.csv"))
        if res.corrective:
            exporters.table_to_csv(res.corrective.table(),
                                   os.path.join(out, f"{stem}_wells.csv"))
        try:
            from . import gis

            ctx = gis.MapContext.from_project(proj)
            gis.write_map(res.aor, os.path.join(out, f"{stem}_map.html"), ctx,
                          wells=proj.wells,
                          penetrations=res.corrective,
                          title=f"{proj.name} - Area of Review")
        except ImportError as exc:
            _p(f"   (no GIS map: {exc})")
        except ValueError as exc:
            _p(f"   (no GIS map: {exc})")
        report.write_json(res, os.path.join(out, f"{stem}_summary.json"))
        if not args.no_report:
            report.write_html(res, os.path.join(out, f"{stem}_report.html"))
        _banner("Written")
        for f in sorted(os.listdir(out)):
            _p(f"   {os.path.join(out, f)}")
    return 0


# ==========================================================================
def cmd_threshold(args) -> int:
    from . import threshold
    from .config import Project

    proj = Project.load(args.project)
    res = threshold.compare_methods(
        p_usdw=proj.usdw.initial_pressure,
        p_inj=proj.injection_zone.initial_pressure,
        depth_usdw=proj.usdw.base_depth,
        depth_inj=proj.injection_zone.mid_depth,
        temperature_inj=proj.injection_zone.temperature,
        temperature_usdw=proj.usdw.temperature,
        salinity_inj=proj.injection_zone.salinity,
        salinity_usdw=proj.usdw.salinity,
        mud_weight_ppg=proj.mud_weight_ppg, gel_strength=proj.gel_strength)
    _banner(f"Threshold pressure - {proj.name}")
    for r in res:
        _p(f"  {r}")
        for k, v in r.inputs.items():
            _p(f"       {k:34s} {v}")
        for w in r.warnings:
            _p(f"     ! {w}")
        _p("")
    _p(f"  Most protective applicable method: {threshold.recommended(res)}")
    if args.json:
        print(json.dumps([r.summary() for r in res], indent=2, default=str))
    return 0


# ==========================================================================
def cmd_reevaluate(args) -> int:
    from . import delineate, workflow
    from .config import Project

    a = workflow.run(Project.load(args.before), progress=lambda m: None)
    b = workflow.run(Project.load(args.after), progress=lambda m: None)
    diff = delineate.compare_aors(a.aor, b.aor, "previous", "reevaluated")
    _banner("AoR reevaluation [40 CFR 146.84(e)]")
    for k, v in diff.items():
        if k.endswith("geometry"):
            continue
        _p(f"   {k:32s} {v if isinstance(v, str) else f'{v:,.2f}'}")
    if args.output:
        os.makedirs(args.output, exist_ok=True)
        import matplotlib
        matplotlib.use("Agg")
        from . import viz

        fig = viz.comparison_map(a.aor, b.aor, wells=b.project.wells)
        viz.save(fig, os.path.join(args.output, "aor_reevaluation.png"))
        _p(f"   wrote {os.path.join(args.output, 'aor_reevaluation.png')}")
    return 0


# ==========================================================================
def cmd_import(args) -> int:
    from . import delineate
    from . import units as U
    from .io import exporters, importers

    sim = importers.load_grid_csv(
        args.csv, x_col=args.x_col, y_col=args.y_col, time_col=args.time_col,
        dp_col=args.dp_col, plume_col=args.plume_col,
        length_unit=args.length_unit, pressure_unit=args.pressure_unit,
        time_unit=args.time_unit, aggregate=args.aggregate,
        dp_is_absolute=args.absolute_pressure,
        initial_pressure=args.initial_pressure)
    _banner(f"Imported {args.csv}")
    for k, v in sim.summary().items():
        _p(f"   {k:22s} {v}")

    res = delineate.delineate(
        sim.x, sim.y,
        dp_field=sim.dp_max() if sim.dp is not None else None,
        threshold_pressure=U.pressure(args.threshold, args.pressure_unit),
        plume_field=sim.plume_max() if sim.plume is not None else None,
        plume_level=args.plume_cutoff,
        plume_criterion=f"imported field >= {args.plume_cutoff:g}",
        method=f"re-delineated from {sim.source} (layer aggregation: {sim.aggregate})")
    _banner("Area of Review")
    for k, v in res.summary().items():
        _p(f"   {k:32s} {v}")
    if args.output:
        exporters.write_polygons(res, args.output)
        _p(f"   wrote {args.output}")
    return 0


# ==========================================================================
def cmd_app(args) -> int:
    import subprocess

    here = os.path.dirname(os.path.abspath(__file__))
    app = os.path.normpath(os.path.join(here, "..", "..", "app", "streamlit_app.py"))
    if not os.path.exists(app):
        app = os.path.join(here, "streamlit_app.py")
    if not os.path.exists(app):
        _p("could not locate streamlit_app.py; run it directly with "
           "`streamlit run app/streamlit_app.py` from a source checkout")
        return 1
    return subprocess.call([sys.executable, "-m", "streamlit", "run", app])


# ==========================================================================
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="containment",
        description="The technical demonstrations behind a UIC Class VI "
                    "permit: Area of Review, corrective action and "
                    "post-injection site care.")
    sub = ap.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="run the full AoR + PISC workflow")
    r.add_argument("project", help="project YAML file")
    r.add_argument("-o", "--output", help="directory for exports and the report")
    r.add_argument("--uncertainty", action="store_true", default=None,
                   help="force the sensitivity/Monte Carlo analysis on")
    r.add_argument("--no-report", action="store_true", help="skip the HTML report")
    r.set_defaults(func=cmd_run)

    t = sub.add_parser("threshold", help="threshold pressure by every method")
    t.add_argument("project")
    t.add_argument("--json", action="store_true")
    t.set_defaults(func=cmd_threshold)

    v = sub.add_parser("reevaluate", help="difference two AoR delineations")
    v.add_argument("before")
    v.add_argument("after")
    v.add_argument("-o", "--output")
    v.set_defaults(func=cmd_reevaluate)

    i = sub.add_parser("import", help="re-delineate an AoR from simulator output")
    i.add_argument("csv")
    i.add_argument("--threshold", type=float, required=True,
                   help="threshold pressure in --pressure-unit")
    i.add_argument("--x-col", default="x")
    i.add_argument("--y-col", default="y")
    i.add_argument("--time-col", default="time")
    i.add_argument("--dp-col", default=None)
    i.add_argument("--plume-col", default=None)
    i.add_argument("--plume-cutoff", type=float, default=0.01)
    i.add_argument("--length-unit", default="ft")
    i.add_argument("--pressure-unit", default="psi")
    i.add_argument("--time-unit", default="yr")
    i.add_argument("--aggregate", default="max",
                   choices=["max", "sum", "pv_weighted", "top", "bottom"])
    i.add_argument("--absolute-pressure", action="store_true",
                   help="the pressure column holds absolute pressure, not buildup")
    i.add_argument("--initial-pressure", type=float, default=float("nan"))
    i.add_argument("-o", "--output", help=".geojson, .kml or .csv")
    i.set_defaults(func=cmd_import)

    a = sub.add_parser("app", help="launch the browser app")
    a.set_defaults(func=cmd_app)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        _p("\ninterrupted")
        return 130
    except Exception as exc:
        _p(f"error: {exc}")
        if os.environ.get("CONTAINMENT_TRACEBACK"):
            raise
        _p("(set CONTAINMENT_TRACEBACK=1 for a full traceback)")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
