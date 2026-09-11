"""Run the showcase project and emit every artefact the toolkit can produce.

This is the run behind the user guide. It exists so the guide's numbers and
figures are generated rather than written by hand: if the toolkit changes, the
guide is rebuilt and the change shows up in it.

    python scripts/build_showcase.py [output_dir]

Everything lands in ``output_dir`` (default ``~/Documents/Containment_Guide``):
``figures/`` holds the PNGs, ``exports/`` the deliverables, and ``data.json``
the numbers the document builder reads back.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import matplotlib
import numpy as np

matplotlib.use("Agg")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))

from containment import (  # noqa: E402  # noqa: E402
    corrective,
    delineate,
    report,
    viz,
    workflow,
)
from containment import pisc as pisc_mod  # noqa: E402
from containment import units as U  # noqa: E402
from containment.config import Project  # noqa: E402
from containment.io import exporters, importers  # noqa: E402

OUT = (sys.argv[1] if len(sys.argv) > 1
       else os.path.join(os.path.expanduser("~"), "Documents", "Containment_Guide"))
FIG = os.path.join(OUT, "figures")
EXP = os.path.join(OUT, "exports")
for d in (OUT, FIG, EXP):
    os.makedirs(d, exist_ok=True)

used: list[str] = []          # every toolkit function this run exercised


def note(fn: str) -> None:
    used.append(fn)


def fig(name: str, figure) -> str:
    path = os.path.join(FIG, name + ".png")
    viz.save(figure, path, dpi=150)
    matplotlib.pyplot.close(figure)
    print(f"   figure  {name}")
    return path


def say(msg: str) -> None:
    print(f"-> {msg}", flush=True)


# ==========================================================================
t0 = time.perf_counter()
say("loading the project")
os.chdir(REPO)                       # the penetrations path is repo-relative
project = Project.from_yaml("examples/showcase_full.yaml")
note("config.Project.from_yaml")
note("config.Project.validate")

say("running the full workflow (two zones, VE engine, uncertainty)")
res = workflow.run(project, progress=lambda m: print(f"     {m}", flush=True))
note("workflow.run")
note("workflow.run_zone")
note("workflow.reevaluation_times")
note("workflow.well_pressure_check")
note("threshold.compare_methods")
note("delineate.delineate")
note("delineate.combine")
note("delineate.aor_series")
note("delineate.series_growth")
note("pisc.analyse")
note("corrective.screen")
note("corrective.arrival_times")
note("uncertainty.tornado")
note("uncertainty.monte_carlo")
runtime = time.perf_counter() - t0
say(f"workflow finished in {runtime:,.0f} s")

s = res.summary()
inj = [w for w in project.wells if w.kind == "injector"]
crs = workflow.project_crs(project)
note("workflow.project_crs")

# ---------------------------------------------------------------- figures
say("drawing figures")
fig("aor_map", viz.aor_map(res.aor, x=res.x, y=res.y,
                           dp_field=res.dp_fields.max(axis=0),
                           threshold=res.selected_threshold.delta_p_critical,
                           wells=project.wells,
                           penetrations=(res.corrective.wells if res.corrective else None)))
note("viz.aor_map")

fig("zone_map", viz.zone_map(res.zones, res.aor, wells=inj))
note("viz.zone_map")

fig("aor_series_map", viz.aor_series_map(res.series, wells=inj))
note("viz.aor_series_map")

fig("aor_growth", viz.aor_growth_chart(res.series, injection_end=project.injection_end()))
note("viz.aor_growth_chart")

fig("threshold_comparison",
    viz.threshold_comparison(res.thresholds, res.selected_threshold))
note("viz.threshold_comparison")

fig("plume_evolution", viz.evolution_map(
    res.x, res.y, res.plume_fields, res.times, project.plume_cutoff,
    wells=inj, title="CO2 plume through time"))
note("viz.evolution_map")

if res.pisc is not None:
    fig("pisc_panels", viz.pisc_panels(res.pisc))
    note("viz.pisc_panels")
    if res.pisc.directional:
        fig("migration_rose", viz.migration_rose(res.pisc.directional))
        note("viz.migration_rose")

unc = res.uncertainty or {}
if unc:
    fig("tornado", viz.tornado_chart(unc["_tornado_obj"]))
    note("viz.tornado_chart")
    fig("monte_carlo", viz.monte_carlo_histogram(unc["_monte_carlo_obj"]))
    note("viz.monte_carlo_histogram")
    fig("probabilistic_aor", viz.probabilistic_aor_map(unc["_monte_carlo_obj"], wells=inj))
    note("viz.probabilistic_aor_map")

if res.ve is not None:
    try:
        from containment.numerical import GridProperties  # noqa: F401
        fig("cross_section", viz.cross_section(res.ve, getattr(res.ve, "props", None), index=-1))
        note("viz.cross_section")
    except Exception as exc:            # the solver may not carry props
        print("     (cross-section skipped:", exc, ")")

# -------------------------------------------------- AoR re-evaluation pair
say("differencing two re-evaluations [146.84(e)]")
early = next(sn for sn in res.series if sn.year >= 25)
late = res.series[-1]
delta = delineate.compare_aors(early.aor, late.aor,
                               label_a=f"year {early.year:.0f}",
                               label_b=f"year {late.year:.0f}")
note("delineate.compare_aors")
fig("comparison_map", viz.comparison_map(early.aor, late.aor, wells=inj))
note("viz.comparison_map")

newly = []
if res.corrective:
    pens = corrective.load_wells_csv(project.penetrations_csv,
                                     unit=project.penetrations_unit, crs=crs)
    note("corrective.load_wells_csv")
    early_plan = corrective.screen(
        pens, early.aor,
        project.seals[0].top_depth, project.seals[0].base_depth,
        injectors=[(w.x, w.y) for w in inj])
    newly = corrective.newly_included(early_plan, res.corrective)
    note("corrective.newly_included")

# --------------------------------------------------------------- exports
say("writing exports")
exporters.write_polygons(res.aor, os.path.join(EXP, "aor.geojson"), crs)
exporters.write_polygons(res.aor, os.path.join(EXP, "aor.kml"), crs)
exporters.write_polygons(res.aor, os.path.join(EXP, "aor_shapefile.zip"), crs)
exporters.to_csv(res.aor, os.path.join(EXP, "aor_boundary.csv"), crs)
note("io.exporters.write_polygons")
note("io.exporters.to_geojson")
note("io.exporters.to_kml")
note("io.exporters.to_shapefile")
note("io.exporters.to_csv")

exporters.save_npz(os.path.join(EXP, "fields.npz"), res.x, res.y, res.times,
                   dp=res.dp_fields, plume=res.plume_fields)
note("io.exporters.save_npz")

report.write_html(res, os.path.join(EXP, "containment_report.html"),
                  basemaps=True)   # all four maps open the report
note("report.build_html")
report.write_json(res, os.path.join(EXP, "summary.json"))
note("report.write_json")

import yaml as _yaml  # noqa: E402

with open(os.path.join(EXP, "project.yaml"), "w", encoding="utf-8") as fh:
    _yaml.safe_dump(project.to_dict(), fh, sort_keys=False)
note("config.Project.to_dict")

exporters.table_to_csv(
    [dict(r) for r in (res.corrective.table() if res.corrective else [])],
    os.path.join(EXP, "corrective_action.csv"))
note("io.exporters.table_to_csv")

# ------------------------------------------------------------- GIS map
gis_ok, gis_note = False, ""
try:
    from containment import gis

    ctx = gis.MapContext.from_project(project)
    html = gis.map_html(res.aor, ctx, wells=project.wells,
                        penetrations=res.corrective, basemap="satellite",
                        title=f"{project.name} - Area of Review")
    with open(os.path.join(EXP, "aor_map.html"), "w", encoding="utf-8") as fh:
        fh.write(html)
    gis_ok = True
    gis_note = ctx.note
    note("gis.MapContext.from_project")
    note("gis.map_html")

    # The same delineation on each basemap, as figures a document can hold.
    for key in gis.BASEMAPS:
        try:
            fig(f"gis_{key}", gis.static_map(
                res.aor, ctx, basemap=key, wells=project.wells,
                penetrations=res.corrective))
        except Exception as exc:
            print(f"     (static {key} map skipped: {exc})")
    note("gis.static_map")
    note("gis.static_map_set")
except Exception as exc:
    print("     (GIS map skipped:", exc, ")")

# ------------------------------------------------ the simulator import path
say("demonstrating the simulator-import path")
imp = {}
try:
    sim_csv = os.path.join(EXP, "simulator_output.csv")
    X, Y = np.meshgrid(res.x, res.y)
    dp = res.dp_fields.max(axis=0)
    sg = res.plume_fields.max(axis=0)
    with open(sim_csv, "w", encoding="utf-8") as fh:
        fh.write("x,y,dp,sg\n")
        for xi, yi, d, g in zip(X.ravel(), Y.ravel(), dp.ravel(), sg.ravel(),
                                strict=True):
            fh.write(f"{xi:.2f},{yi:.2f},{U.pressure_out(float(d), 'psi'):.4f},"
                     f"{float(g):.5f}\n")
    grid = importers.load_grid_csv(
        sim_csv, x_col="x", y_col="y", time_col=None,
        dp_col="dp", plume_col="sg",
        pressure_unit="psi", length_unit="m")
    note("io.importers.load_grid_csv")
    imported = delineate.delineate(
        grid.x, grid.y, dp_field=delineate.envelope(grid.dp),
        threshold_pressure=res.selected_threshold.delta_p_critical,
        plume_field=delineate.envelope(grid.plume),
        plume_level=project.plume_cutoff,
        plume_criterion=project.plume_criterion,
        method="imported simulator output")
    imp = {"area_acres": imported.area_acres,
           "native_area_acres": res.aor.area_acres}
except Exception as exc:
    print("     (import path skipped:", exc, ")")

# ------------------------------------------------------------------- CLI
say("capturing CLI output")
cli = {}
env = dict(os.environ, PYTHONPATH=os.path.join(REPO, "src"))
for key, args in (("help", ["--help"]),
                  ("threshold", ["threshold", "examples/showcase_full.yaml"]),
                  ("reevaluate_help", ["reevaluate", "--help"]),
                  ("import_help", ["import", "--help"])):
    try:
        out = subprocess.run([sys.executable, "-m", "containment.cli", *args],
                             capture_output=True, text=True, timeout=900, env=env)
        cli[key] = (out.stdout or out.stderr)[:4000]
    except Exception as exc:
        cli[key] = f"(not captured: {exc})"
note("cli.main")

# ------------------------------------------------------------------ data
say("collecting the numbers")
tor_rows, mc_pct, mc_corr = [], {}, []
if unc:
    tor_rows = [dict(r) for r in unc["_tornado_obj"].rows]
    mc = unc["_monte_carlo_obj"]
    mc_pct = mc.percentiles("aor_area_acres")
    try:
        mc_corr = [dict(r) for r in mc.correlations("aor_area_acres")]
    except Exception:
        mc_corr = []

az = {}
if inj:
    az = {k: U.length_out(v, "mi")
          for k, v in res.aor.extent_by_azimuth(inj[0].x, inj[0].y, 8).items()}
    note("delineate.AoRResult.extent_by_azimuth")

checklist = []
if res.pisc is not None:
    checklist = [dict(r) for r in pisc_mod.alternative_timeframe_checklist(
        res.pisc,
        abandoned_wells_assessed=bool(res.corrective),
        conduits_identified=bool(res.corrective),
        sensitivity_analysis_done=bool(res.uncertainty),
        usdw_separation=(project.zones[0].top_depth - project.usdw.base_depth))]
    note("pisc.alternative_timeframe_checklist")
    try:
        pdt = pisc_mod.pressure_differential_table(res.pisc)
        note("pisc.pressure_differential_table")
    except Exception:
        pdt = []
else:
    pdt = []

data = {
    "generated": time.strftime("%Y-%m-%d %H:%M"),
    "runtime_s": runtime,
    "project": {
        "name": project.name, "operator": project.operator,
        "start_date": project.start_date,
        "zones": [z.name for z in project.zones],
        "injectors": len(inj),
        "extractors": sum(1 for w in project.wells if w.kind == "extractor"),
        "end_year": U.time_out(project.end_time, "yr"),
        "reevaluation_years": project.aor_reevaluation_years,
        "total_mass_MMT": U.mass_out(project.total_injected_mass(), "MMT"),
        "crs": (crs.describe() if crs else {}),
        "gis_note": gis_note,
    },
    "summary": report._clean(s),
    "aor": {
        "area_acres": res.aor.area_acres, "area_sq_mi": res.aor.area_sq_mi,
        "controlling": res.aor.controlling_component(),
        "metadata": report._clean(res.aor.metadata),
    },
    "zones": [z.summary() for z in res.zones],
    "zone_allocation": project.zone_allocation(),
    "thresholds": [t.summary() for t in res.thresholds],
    "selected_threshold": res.selected_threshold.summary(),
    "series": delineate.series_growth(res.series),
    "series_dates": [str(project.calendar(sn.time)) for sn in res.series],
    "well_pressure": res.well_pressure,
    "corrective": (report._clean(res.corrective.summary()) if res.corrective else {}),
    "corrective_table": ([dict(r) for r in res.corrective.table()]
                         if res.corrective else []),
    "corrective_phases": (report._clean(res.corrective.phases())
                          if res.corrective else {}),
    "newly_included": newly,
    "reevaluation_delta": report._clean(
        {k: v for k, v in delta.items() if k != "newly_included_geometry"}),
    "pisc": (report._clean(res.pisc.summary()) if res.pisc else {}),
    "pisc_table": ([dict(r) for r in res.pisc.table()] if res.pisc else []),
    "pisc_checklist": checklist,
    "pressure_differential": [dict(r) for r in pdt] if pdt else [],
    "tornado": tor_rows,
    "monte_carlo_percentiles": mc_pct,
    "monte_carlo_correlations": mc_corr,
    "uncertainty_note": unc.get("comparability", ""),
    "azimuth_mi": az,
    "warnings": list(res.warnings),
    "analytical_checks": report._clean(res.analytical_checks),
    "import_check": imp,
    "cli": cli,
    "exports": sorted(os.listdir(EXP)),
    "figures": sorted(f[:-4] for f in os.listdir(FIG) if f.endswith(".png")),
    "functions_used": sorted(set(used)),
}
with open(os.path.join(OUT, "data.json"), "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2, default=str)

print()
print(f"AoR {res.aor.area_acres:,.0f} acres | {len(data['functions_used'])} toolkit "
      f"entry points exercised | {len(data['figures'])} figures | "
      f"{len(data['exports'])} exports")
print(f"wrote {OUT}")
