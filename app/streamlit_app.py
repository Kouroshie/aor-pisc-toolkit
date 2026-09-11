"""Browser front end for the AoR / PISC toolkit.

    streamlit run app/streamlit_app.py      (or: aorpisc app)

Everything the app does goes through :mod:`aorpisc.workflow`, so what you see
here is exactly what the CLI and the report produce.  The app is a way to turn
the knobs and watch the AoR move; the project YAML remains the record of what
was actually run.
"""

from __future__ import annotations

import hashlib
import inspect
import io
import json
import os
import pathlib
import sys
import tempfile

import numpy as np
import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from aorpisc import pisc as pisc_mod  # noqa: E402
from aorpisc import report, viz, workflow
from aorpisc import units as U  # noqa: E402
from aorpisc.config import Project  # noqa: E402
from aorpisc.io import exporters  # noqa: E402

st.set_page_config(page_title="AoR / PISC toolkit", page_icon="*",
                   layout="wide", initial_sidebar_state="expanded")


# --------------------------------------------------------------------------
# Streamlit moved on: `use_container_width` became `width=`, and
# `st.components.v1.html` became `st.iframe`, which takes a source rather than
# a string. Both old spellings still work but warn on every rerun, which
# buries real messages in the app's log. These two helpers use whichever API
# the installed version has, so the package keeps its loose Streamlit floor.
_FULL_WIDTH = ({"width": "stretch"}
               if "width" in inspect.signature(st.button).parameters
               else {"use_container_width": True})


def _embed_html(html: str, height: int = 640) -> None:
    """Put a self-contained HTML document (the folium map) in the page.

    Folium sizes its map div at ``height: 100%``, which needs a parent of
    known height. ``st.iframe`` sizes itself to its content, so 100% collapses
    and Leaflet computes its ``fitBounds`` against a container of no height --
    the map comes up zoomed out to the whole world. The embedded copy
    therefore gets an explicit pixel height; the string handed to the download
    button is left alone so the standalone file still fills its window.
    """
    if hasattr(st, "iframe"):
        doc = html.replace(
            "</head>",
            f"<style>html,body{{height:{height}px;overflow:hidden}}</style></head>",
            1)
        d = st.session_state.get("_embed_dir")
        if d is None:
            d = st.session_state["_embed_dir"] = tempfile.mkdtemp(prefix="aorpisc-")
        path = pathlib.Path(d) / (
            hashlib.sha1(doc.encode("utf-8")).hexdigest()[:16] + ".html")
        if not path.exists():
            path.write_text(doc, encoding="utf-8")
            # keep the session's scratch directory from growing without bound
            kept = sorted(pathlib.Path(d).glob("*.html"),
                          key=lambda q: q.stat().st_mtime, reverse=True)
            for stale in kept[6:]:
                stale.unlink(missing_ok=True)
        st.iframe(path, height=height)
    else:                                     # Streamlit without st.iframe
        import streamlit.components.v1 as components

        components.html(html, height=height, scrolling=False)


EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "examples")


# ==========================================================================
def _num(label, value, unit, **kw):
    """Sidebar number input, labelled with its unit."""
    return st.sidebar.number_input(f"{label} ({unit})", value=float(value), **kw)


def _project_from_form() -> dict:
    """Build a project dict from the sidebar and main-panel controls."""
    st.sidebar.header("Project")
    name = st.sidebar.text_input("Name", "New storage project")
    operator = st.sidebar.text_input("Operator", "")
    permit = st.sidebar.text_input("Permit number", "")

    st.sidebar.header("Injection zone")
    top = _num("top depth", 6000, "ft", key="iz_top", step=100.0)
    thick = _num("net thickness", 250, "ft", key="iz_h", step=10.0)
    poro = st.sidebar.number_input("porosity (-)", value=0.18, min_value=0.01,
                                   max_value=0.45, step=0.01, key="iz_phi")
    perm = _num("permeability", 150, "mD", key="iz_k", step=10.0)
    temp = _num("temperature", 150, "degF", key="iz_t", step=5.0)
    sal = _num("salinity", 90000, "ppm", key="iz_s", step=5000.0)
    pini = _num("initial pressure", 2600, "psi", key="iz_p", step=50.0)
    cr = st.sidebar.number_input("rock compressibility (1/psi)", value=5.0e-6,
                                 format="%.2e", key="iz_cr")
    dip = st.sidebar.number_input("dip (deg)", value=0.5, step=0.1, key="iz_dip")
    az = st.sidebar.number_input("dip azimuth (deg, direction of dip)",
                                 value=180.0, step=15.0, key="iz_az")

    st.sidebar.header("Confining zone")
    cz_top = _num("top depth", 5700, "ft", key="cz_top", step=50.0)
    cz_base = _num("base depth", 6000, "ft", key="cz_base", step=50.0)

    st.sidebar.header("Lowermost USDW")
    usdw_base = _num("base depth", 1200, "ft", key="us_d", step=50.0)
    usdw_p = _num("initial pressure", 520, "psi", key="us_p", step=10.0)
    usdw_t = _num("temperature", 80, "degF", key="us_t", step=5.0)
    usdw_s = _num("salinity", 800, "ppm", key="us_s", step=100.0)

    st.sidebar.header("Relative permeability")
    swr = st.sidebar.slider("residual brine Swr", 0.05, 0.6, 0.35, 0.01)
    sgr = st.sidebar.slider("residual CO2 Sgr", 0.0, 0.4, 0.20, 0.01)
    krg0 = st.sidebar.slider("CO2 end-point krg0", 0.05, 1.0, 0.30, 0.01)
    corey = st.sidebar.slider("Corey exponents (m = n)", 1.5, 5.0, 3.0, 0.1)

    st.sidebar.header("Threshold pressure")
    method = st.sidebar.selectbox(
        "method", ["auto", "method1", "method2", "method2b", "mud_column"],
        help="auto compares every method and takes the most protective one "
             "that applies to this pressure regime")
    ppg = st.sidebar.number_input("mud weight (ppg)", value=9.0, step=0.1)
    gel = st.sidebar.number_input("gel strength (psi)", value=10.0, step=1.0)

    st.sidebar.header("Model")
    engine = st.sidebar.radio("engine", ["ve", "analytical"], index=0,
                              help="ve = vertical-equilibrium numerical solver "
                                   "(dip, heterogeneity, post-injection "
                                   "migration); analytical = superposition")
    boundary = st.sidebar.selectbox("boundary", ["infinite", "constant_pressure",
                                                 "noflow"])
    cell = _num("fine cell size", 500, "ft", key="dx", step=50.0)
    half = _num("domain half-width", 15, "mi", key="hw", step=1.0)
    end_year = st.sidebar.number_input("simulation end (years)", value=100.0,
                                       step=10.0)
    cutoff = st.sidebar.number_input("plume saturation cutoff", value=0.01,
                                     step=0.005, format="%.3f")

    return {
        "project": {"name": name, "operator": operator, "permit": permit,
                    "datum": "ground surface, depths positive downward"},
        "units": {"length": "ft", "depth": "ft", "pressure": "psi",
                  "temperature": "F", "permeability": "mD", "rate": "MMT/yr",
                  "time": "yr", "compressibility": "1/psi"},
        "formation": {
            "injection_zone": {
                "top_depth": top, "thickness": thick, "porosity": poro,
                "permeability": perm, "temperature": temp, "salinity_ppm": sal,
                "initial_pressure": pini, "rock_compressibility": cr,
                "dip_degrees": dip, "dip_azimuth": az},
            "confining_zone": {"top_depth": cz_top, "base_depth": cz_base},
            "usdw": {"base_depth": usdw_base, "initial_pressure": usdw_p,
                     "temperature": usdw_t, "salinity_ppm": usdw_s},
        },
        "relative_permeability": {"model": "brooks_corey", "swr": swr,
                                  "sgr": sgr, "krg0": krg0, "m": corey, "n": corey},
        "threshold": {"method": method, "mud_weight_ppg": ppg, "gel_strength": gel},
        "model": {"engine": engine, "boundary": boundary, "end_year": end_year,
                  "grid": {"cell_size": cell,
                           "half_width": half * 5280.0,
                           "fine_half_width": min(half * 5280.0, 25000.0)}},
        "plume": {"cutoff": cutoff,
                  "criterion": f"column-averaged CO2 saturation >= {cutoff:g}"},
    }


def _well_editor() -> list[dict]:
    st.subheader("Injection wells")
    st.caption("Give either x/y in feet from an arbitrary origin, or latitude "
               "and longitude. Latitude/longitude builds the local frame for "
               "you and unlocks the GIS map. Rates are million tonnes of CO2 "
               "per year.")
    default = [
        {"name": "INJ-1", "latitude": 31.9686, "longitude": -99.9018,
         "rate": 0.5, "start_year": 0.0, "stop_year": 20.0},
        {"name": "INJ-2", "latitude": 31.9686, "longitude": -99.8890,
         "rate": 0.5, "start_year": 0.0, "stop_year": 20.0},
    ]
    edited = st.data_editor(default, num_rows="dynamic", key="wells")
    return [dict(r, kind="injector") for r in edited if r.get("name")]


# ==========================================================================
st.title("Area of Review and Post-Injection Site Care")
st.caption("UIC Class VI, following 40 CFR 146.84 / 146.93 and EPA 816-R-13-005. "
           "An engineering analysis, not a regulatory determination.")

mode = st.radio("Start from", ["Form", "Upload project YAML", "Shipped example"],
                horizontal=True, label_visibility="collapsed")

proj_dict = None
if mode == "Upload project YAML":
    up = st.file_uploader("project file", type=["yaml", "yml"])
    if up is not None:
        import yaml
        proj_dict = yaml.safe_load(up.getvalue().decode("utf-8"))
elif mode == "Shipped example":
    files = sorted(f for f in os.listdir(EXAMPLES) if f.endswith((".yaml", ".yml")))
    pick = st.selectbox("example", files)
    import yaml
    with open(os.path.join(EXAMPLES, pick), encoding="utf-8") as fh:
        proj_dict = yaml.safe_load(fh)
else:
    proj_dict = _project_from_form()
    proj_dict["wells"] = _well_editor()

if not proj_dict:
    st.stop()

try:
    project = Project.from_dict(proj_dict)
except Exception as exc:
    st.error(f"Could not read the project: {exc}")
    st.stop()

for w in project.warnings:
    st.warning(w)

col_a, col_b = st.columns([1, 3])
with col_a:
    run_unc = st.checkbox("run uncertainty analysis", value=False,
                          help="Tornado plus a Latin-hypercube Monte Carlo on "
                               "the fast analytical engine, producing a "
                               "probabilistic AoR")
    n_real = st.number_input("realisations", 40, 1000, 150, 10,
                             disabled=not run_unc)
    go = st.button("Run", type="primary", **_FULL_WIDTH)
with col_b:
    st.json(project.summary(), expanded=False)

if go:
    if run_unc:
        project.uncertainty = {"enabled": True, "realisations": int(n_real),
                               "spread": 0.5, "seed": 0}
    bar = st.progress(0.0, text="starting")
    steps = {"evaluating fluid properties": 0.1,
             "computing threshold pressure": 0.2,
             "running the flow model": 0.5,
             "delineating the AoR": 0.7,
             "computing PISC metrics": 0.85,
             "running uncertainty analysis": 0.95}
    try:
        with st.spinner("running"):
            res = workflow.run(
                project, run_uncertainty=run_unc,
                progress=lambda m: bar.progress(steps.get(m, 0.5), text=m))
        bar.progress(1.0, text="done")
        st.session_state["result"] = res
    except Exception as exc:
        bar.empty()
        st.exception(exc)
        st.stop()

res = st.session_state.get("result")
if res is None:
    st.info("Set up the project and press Run.")
    st.stop()

# ==========================================================================
s = res.summary()
m1, m2, m3, m4 = st.columns(4)
m1.metric("AoR area", f"{s['aor']['aor_area_acres']:,.0f} acres",
          f"{s['aor']['aor_area_sq_mi']:,.1f} sq mi")
m2.metric("Threshold dP", f"{s['threshold']['delta_p_critical_psi']:,.0f} psi",
          s["threshold"]["method"].split(" - ")[0])
m3.metric("CO2 injected", f"{U.mass_out(project.total_injected_mass(), 'MMT'):,.1f} MMT")
if res.pisc:
    rec = s["pisc"]["recommended_pisc"].get("recommended_years", float("nan"))
    m4.metric("PISC supported by model",
              f"{rec:,.0f} yr" if np.isfinite(rec) else "not demonstrated",
              s["pisc"]["recommended_pisc"].get("basis", ""))

if res.warnings:
    with st.expander(f"{len(set(res.warnings))} model-integrity item(s) to review",
                     expanded=True):
        for w in dict.fromkeys(res.warnings):
            st.warning(w)
else:
    st.success("Domain size, grid resolution, boundary influence, mass balance "
               "and pressure-regime applicability all passed their checks.")

tabs = st.tabs(["AoR map", "GIS map", "Threshold", "PISC", "Corrective action",
                "Uncertainty", "Export"])

# ---------------------------------------------------------------- AoR map
with tabs[0]:
    try:
        import plotly.graph_objects as go  # noqa: F401

        fig = viz.plotly_aor_map(
            res.aor, x=res.x, y=res.y, dp_field=res.dp_fields.max(axis=0),
            wells=project.wells,
            penetrations=(res.corrective.wells if res.corrective else None))
        st.plotly_chart(fig)
    except ImportError:
        st.pyplot(viz.aor_map(res.aor, x=res.x, y=res.y,
                              dp_field=res.dp_fields.max(axis=0),
                              wells=project.wells))
    c1, c2 = st.columns(2)
    c1.write("**Components**")
    c1.json({k: s["aor"][k] for k in
             ("plume_area_acres", "pressure_front_area_acres",
              "controlling_component", "plume_criterion")})
    c2.write("**Closed-form cross-checks**")
    c2.json({k: v for k, v in s["analytical_checks"].items() if k != "note"})
    st.caption(s["analytical_checks"]["note"])

    inj = [w for w in project.wells if w.kind == "injector"]
    if inj:
        az = res.aor.extent_by_azimuth(inj[0].x, inj[0].y, 16)
        st.write(f"**AoR extent by azimuth from {inj[0].name}**")
        st.dataframe(
            [{"azimuth (deg)": k, "distance (ft)": U.length_out(v, "ft"),
              "distance (mi)": U.length_out(v, "mi")} for k, v in az.items()], hide_index=True)

# ---------------------------------------------------------------- GIS map
with tabs[1]:
    try:
        from aorpisc import gis

        ctx = gis.MapContext.from_project(project)
        c1, c2 = st.columns([2, 3])
        base = c1.selectbox("basemap", list(gis.BASEMAPS),
                            format_func=lambda k: gis.BASEMAPS[k]["name"])
        c2.caption(f"Georeferencing: {ctx.note}")
        html = gis.map_html(res.aor, ctx, wells=project.wells,
                            penetrations=res.corrective, basemap=base,
                            title=f"{project.name} - Area of Review")
        _embed_html(html, height=640)
        st.download_button("Download this map as a standalone HTML file", html,
                           "aor_map.html", "text/html")
        st.caption("The downloaded file opens offline in any browser, with the "
                   "basemaps, the layer switcher and the measuring tool intact. "
                   "It is the artefact to send to a landman, a field inspector "
                   "or a surface owner.")
    except ImportError as exc:
        st.warning(str(exc))
    except ValueError as exc:
        st.info(str(exc))

# -------------------------------------------------------------- threshold
with tabs[2]:
    st.pyplot(viz.threshold_comparison(res.thresholds, res.selected_threshold))
    st.dataframe([t.summary() for t in res.thresholds], hide_index=True)
    st.info("The threshold pressure is the largest single discretionary lever "
            "in an AoR delineation. A method that does not apply to the site's "
            "pressure regime is drawn hatched and is excluded from the "
            "automatic choice.")

# ------------------------------------------------------------------- PISC
with tabs[3]:
    if res.pisc is None:
        st.info("No PISC analysis for this run.")
    else:
        try:
            st.plotly_chart(viz.plotly_pisc(res.pisc))
        except ImportError:
            st.pyplot(viz.pisc_panels(res.pisc))
        st.write("**Recommendation**")
        st.write(s["pisc"]["recommended_pisc"]["verdict"])
        st.dataframe(res.pisc.table(), hide_index=True)
        if res.pisc.directional:
            st.pyplot(viz.migration_rose(res.pisc.directional))
        st.write("**40 CFR 146.93(c) demonstration checklist**")
        st.dataframe(pisc_mod.alternative_timeframe_checklist(
            res.pisc,
            abandoned_wells_assessed=bool(res.corrective),
            conduits_identified=bool(res.corrective),
            sensitivity_analysis_done=bool(res.uncertainty),
            usdw_separation=(project.injection_zone.top_depth
                             - project.usdw.base_depth)), hide_index=True)

# ----------------------------------------------------- corrective action
with tabs[4]:
    st.caption("Upload a CSV of artificial penetrations. Recognised columns: "
               "name, api, type, status, x, y, total_depth, year_drilled, "
               "year_abandoned, plug_depths (semicolon separated), "
               "plug_material, cased, records_complete, mit_passed, notes.")
    up = st.file_uploader("well list", type=["csv"], key="pens")
    unit = st.radio("coordinate and depth unit", ["ft", "m"], horizontal=True)
    if up is not None:
        import tempfile

        from aorpisc import corrective

        with tempfile.NamedTemporaryFile("wb", suffix=".csv", delete=False) as fh:
            fh.write(up.getvalue())
            tmp = fh.name
        try:
            wells = corrective.load_wells_csv(tmp, unit=unit)
            cz_top = (project.confining_zone.top_depth
                      if np.isfinite(project.confining_zone.top_depth)
                      else project.injection_zone.top_depth - U.length(100, "ft"))
            cz_base = (project.confining_zone.base_depth
                       if np.isfinite(project.confining_zone.base_depth)
                       else project.injection_zone.top_depth)
            plan = corrective.screen(
                wells, res.aor, cz_top, cz_base,
                injectors=[(w.x, w.y) for w in project.wells if w.kind == "injector"])
            plan = corrective.arrival_times(
                plan, res.x, res.y, res.times,
                plume_fields=res.plume_fields,
                plume_level=(project.plume_cutoff if project.engine == "ve" else 0.5),
                dp_fields=res.dp_fields,
                threshold_pressure=res.selected_threshold.delta_p_critical)
            res.corrective = plan
            st.json(plan.summary())
            st.dataframe(plan.table(), hide_index=True)
            st.write("**Phased corrective action by modelled arrival time**")
            st.json(plan.phases())
        finally:
            os.unlink(tmp)
    elif res.corrective:
        st.json(res.corrective.summary())
        st.dataframe(res.corrective.table(),
                     hide_index=True)
        st.json(res.corrective.phases())
    else:
        st.info("No well list loaded yet.")

# ------------------------------------------------------------ uncertainty
with tabs[5]:
    unc = res.uncertainty or {}
    if not unc:
        st.info("Tick 'run uncertainty analysis' before running to produce a "
                "tornado chart and a probabilistic AoR. "
                "40 CFR 146.93(c)(2)(vi) requires a sensitivity analysis to "
                "support an alternative PISC timeframe.")
    else:
        st.warning(unc.get("comparability", ""))
        st.pyplot(viz.tornado_chart(unc["_tornado_obj"]))
        mc = unc["_monte_carlo_obj"]
        c1, c2 = st.columns(2)
        with c1:
            st.pyplot(viz.monte_carlo_histogram(mc))
        with c2:
            st.pyplot(viz.probabilistic_aor_map(mc, wells=project.wells))
        st.write("**Rank correlation with AoR area**")
        st.dataframe(mc.correlations("aor_area_acres"), hide_index=True)
        st.json({"percentiles (acres)": mc.percentiles("aor_area_acres"),
                 "ratio to the ensemble base case":
                     unc.get("percentile_ratio_to_base", {})})

# ----------------------------------------------------------------- export
with tabs[6]:
    st.write("Everything below is generated from this run.")
    crs = None
    use_crs = st.checkbox("georeference the exports")
    if use_crs:
        kind = st.radio("transform", ["EPSG code (exact)",
                                      "origin lon/lat (approximate)"],
                        horizontal=True)
        if kind.startswith("EPSG"):
            epsg = st.number_input("EPSG", value=32614, step=1)
            try:
                crs = exporters.LocalCRS(epsg=int(epsg))
            except ImportError as exc:
                st.error(str(exc))
        else:
            lon = st.number_input("origin longitude", value=-97.5, format="%.5f")
            lat = st.number_input("origin latitude", value=27.5, format="%.5f")
            crs = exporters.LocalCRS(origin_lon=lon, origin_lat=lat)
            st.caption(exporters.LocalCRS(origin_lon=lon, origin_lat=lat)
                       .describe()["note"])

    gj = json.dumps(exporters.to_geojson(res.aor, crs), indent=2)
    st.download_button("AoR GeoJSON", gj, "aor.geojson", "application/geo+json")
    st.download_button("AoR KML", exporters.to_kml(res.aor, crs),
                       "aor.kml", "application/vnd.google-earth.kml+xml")
    st.download_button("Full HTML report", report.build_html(res),
                       "aor_pisc_report.html", "text/html")
    st.download_button("Result summary (JSON)",
                       json.dumps(report._clean(s), indent=2, default=str),
                       "summary.json", "application/json")
    import yaml as _yaml

    st.download_button("Project file (YAML)",
                       _yaml.safe_dump(project.to_dict(), sort_keys=False),
                       "project.yaml", "text/yaml")
    buf = io.BytesIO()
    np.savez_compressed(buf, x=res.x, y=res.y, times=res.times,
                        dp=res.dp_fields, plume=res.plume_fields)
    st.download_button("Gridded fields (.npz)", buf.getvalue(),
                       "fields.npz", "application/octet-stream")
    st.caption("40 CFR 146.84(g) requires modelling inputs supporting an AoR "
               "delineation to be retained for ten years. The project YAML "
               "plus the field archive is that record.")
