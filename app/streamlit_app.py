"""Browser front end for the Containment.

    streamlit run app/streamlit_app.py      (or: containment app)

Everything the app does goes through :mod:`containment.workflow`, so what you see
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

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))
# `streamlit run` puts the script's own directory on the path, but a test
# harness need not, so the sibling modules below get it explicitly.
sys.path.insert(0, _HERE)

import guide  # noqa: E402  (sibling module: help text)
import theme  # noqa: E402  (sibling module: page styling)

from containment import delineate, report, viz, workflow  # noqa: E402
from containment import pisc as pisc_mod  # noqa: E402
from containment import units as U  # noqa: E402
from containment.config import Project  # noqa: E402
from containment.io import exporters  # noqa: E402

st.set_page_config(page_title="Containment", page_icon="*",
                   layout="wide", initial_sidebar_state="expanded")
theme.apply()

H = guide.FIELD


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
            d = st.session_state["_embed_dir"] = tempfile.mkdtemp(prefix="containment-")
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
    top = _num("top depth", 6000, "ft", key="iz_top", step=100.0,
               help=H["iz_top"])
    thick = _num("net thickness", 250, "ft", key="iz_h", step=10.0,
                 help=H["iz_h"])
    poro = st.sidebar.number_input("porosity (-)", value=0.18, min_value=0.01,
                                   max_value=0.45, step=0.01, key="iz_phi",
                                   help=H["iz_phi"])
    perm = _num("permeability", 150, "mD", key="iz_k", step=10.0, help=H["iz_k"])
    temp = _num("temperature", 150, "degF", key="iz_t", step=5.0, help=H["iz_t"])
    sal = _num("salinity", 90000, "ppm", key="iz_s", step=5000.0, help=H["iz_s"])
    pini = _num("initial pressure", 2600, "psi", key="iz_p", step=50.0,
                help=H["iz_p"])
    cr = st.sidebar.number_input("rock compressibility (1/psi)", value=5.0e-6,
                                 format="%.2e", key="iz_cr", help=H["iz_cr"])
    dip = st.sidebar.number_input("dip (deg)", value=0.5, step=0.1, key="iz_dip",
                                  help=H["iz_dip"])
    az = st.sidebar.number_input("dip azimuth (deg, direction of dip)",
                                 value=180.0, step=15.0, key="iz_az",
                                 help=H["iz_az"])

    st.sidebar.header("Confining zone")
    cz_top = _num("top depth", 5700, "ft", key="cz_top", step=50.0,
                  help=H["cz_top"])
    cz_base = _num("base depth", 6000, "ft", key="cz_base", step=50.0,
                   help=H["cz_base"])

    st.sidebar.header("Lowermost USDW")
    usdw_base = _num("base depth", 1200, "ft", key="us_d", step=50.0,
                     help=H["usdw_base"])
    usdw_p = _num("initial pressure", 520, "psi", key="us_p", step=10.0,
                  help=H["usdw_p"])
    usdw_t = _num("temperature", 80, "degF", key="us_t", step=5.0,
                  help=H["usdw_t"])
    usdw_s = _num("salinity", 800, "ppm", key="us_s", step=100.0,
                  help=H["usdw_s"])

    st.sidebar.header("Relative permeability")
    swr = st.sidebar.slider("residual brine Swr", 0.05, 0.6, 0.35, 0.01,
                            help=H["swr"])
    sgr = st.sidebar.slider("residual CO2 Sgr", 0.0, 0.4, 0.20, 0.01,
                            help=H["sgr"])
    krg0 = st.sidebar.slider("CO2 end-point krg0", 0.05, 1.0, 0.30, 0.01,
                             help=H["krg0"])
    corey = st.sidebar.slider("Corey exponents (m = n)", 1.5, 5.0, 3.0, 0.1,
                              help=H["corey"])

    st.sidebar.header("Threshold pressure")
    method = st.sidebar.selectbox(
        "method", ["auto", "method1", "method2", "method2b", "mud_column"],
        help=H["method"])
    ppg = st.sidebar.number_input("mud weight (ppg)", value=9.0, step=0.1,
                                  help=H["ppg"])
    gel = st.sidebar.number_input("gel strength (psi)", value=10.0, step=1.0,
                                  help=H["gel"])

    st.sidebar.header("Model")
    engine = st.sidebar.radio("engine", ["ve", "analytical"], index=0,
                              help=H["engine"])
    boundary = st.sidebar.selectbox("boundary", ["infinite", "constant_pressure",
                                                 "noflow"], help=H["boundary"])
    cell = _num("fine cell size", 500, "ft", key="dx", step=50.0, help=H["cell"])
    half = _num("domain half-width", 15, "mi", key="hw", step=1.0, help=H["half"])
    end_year = st.sidebar.number_input("simulation end (years)", value=100.0,
                                       step=10.0, help=H["end_year"])
    cutoff = st.sidebar.number_input("plume saturation cutoff", value=0.01,
                                     step=0.005, format="%.3f",
                                     help=H["cutoff"])

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


def _rows(edited) -> list[dict]:
    """Rows out of st.data_editor, whatever shape this Streamlit hands back.

    The editor returns "the same type as the input", but the exact spelling has
    moved between versions: a list of dicts here, a DataFrame there, and a
    version that skips the first row of a list default. Reading the rows
    through one helper keeps a version difference from quietly costing an
    injection zone, which is how a stacked project collapsed to a single zone
    on the deployed app while passing locally.
    """
    if edited is None:
        return []
    if hasattr(edited, "to_dict"):                    # a pandas DataFrame
        return [dict(r) for r in edited.to_dict("records")]
    out = []
    for r in edited:
        if isinstance(r, dict):
            out.append(dict(r))
        elif hasattr(edited, "loc"):                  # an index, not a row
            out.append(dict(edited.loc[r]))
    return out


_ZONE_COLUMNS = ("name", "top_depth", "thickness", "porosity", "permeability",
                 "temperature", "salinity_ppm", "initial_pressure",
                 "confining_top", "confining_base")


def _zone_editor() -> list[dict] | None:
    """Optional table of stacked injection zones.

    One wellbore completed in several formations is a different project from
    one completed in a thicker single formation: each interval has its own
    pressure, its own threshold pressure and its own AoR. When this table is
    in use it replaces the single zone in the sidebar entirely.
    """
    stacked = st.checkbox(
        "inject into more than one formation (stacked completion)",
        value=False, key="stacked", help=H["stacked"])
    if not stacked:
        return None

    st.caption("One row per injection zone, shallowest first. These replace "
               "the single injection zone in the sidebar; everything else "
               "there (relative permeability, USDW, grid, threshold method) "
               "still applies to every zone. " + H["zone_table"])
    default = [
        {"name": "Upper zone", "top_depth": 5200.0, "thickness": 180.0,
         "porosity": 0.20, "permeability": 220.0, "temperature": 140.0,
         "salinity_ppm": 70000.0, "initial_pressure": 2250.0,
         "confining_top": 5000.0, "confining_base": 5200.0},
        {"name": "Lower zone", "top_depth": 6000.0, "thickness": 250.0,
         "porosity": 0.18, "permeability": 150.0, "temperature": 150.0,
         "salinity_ppm": 90000.0, "initial_pressure": 2600.0,
         "confining_top": 5700.0, "confining_base": 6000.0},
    ]
    rows = _rows(st.data_editor(default, num_rows="dynamic", key="zones"))
    out = []
    for r in rows:
        if not str(r.get("name") or "").strip():
            continue
        z = {k: r.get(k) for k in _ZONE_COLUMNS
             if k not in ("confining_top", "confining_base")
             and r.get(k) is not None}
        if r.get("confining_top") is not None and r.get("confining_base") is not None:
            z["confining_zone"] = {"top_depth": r["confining_top"],
                                   "base_depth": r["confining_base"]}
        out.append(z)

    if len(out) < 2:
        st.warning(
            f"The zone table produced {len(out)} usable row(s), so this is not "
            "a stacked project. Every row needs a name, and a stack needs at "
            "least two. Untick the box above to go back to the single "
            "injection zone in the sidebar.")
    return out or None


def _well_editor(zones: list[dict] | None = None) -> list[dict]:
    st.subheader("Injection wells")
    # st.data_editor takes no `help`, so the table's tooltip text is shown
    # here instead of hanging off a question mark.
    st.caption("Give either x/y in feet from an arbitrary origin, or latitude "
               "and longitude. Latitude/longitude builds the local frame for "
               "you and unlocks the GIS map. " + H["wells"]
               + (" " + H["well_zone"] if zones else ""))
    default = [
        {"name": "INJ-1", "latitude": 31.9686, "longitude": -99.9018,
         "rate": 0.5, "start_year": 0.0, "stop_year": 20.0},
        {"name": "INJ-2", "latitude": 31.9686, "longitude": -99.8890,
         "rate": 0.5, "start_year": 0.0, "stop_year": 20.0},
    ]
    if zones:
        # a blank zone means the completion is open to every zone, and the
        # rate gets split by k*h
        for row in default:
            row["zone"] = ""
    edited = _rows(st.data_editor(default, num_rows="dynamic", key="wells"))
    return [dict(r, kind="injector") for r in edited if r.get("name")]


# ==========================================================================
theme.hero(
    "Containment",
    "Delineate the Area of Review, size the corrective-action list and test a "
    "post-injection site care timeframe, from a project you can hand to a "
    "reviewer and rerun.",
    ("40 CFR 146.84 / 146.93", "EPA 816-R-13-005",
     "Engineering analysis, not a regulatory determination"))

with st.expander("New here? How this works, in one minute", expanded=False):
    st.markdown(
        "Describe the site in the **sidebar**, put the wells in the **table**, "
        "press **Run**. The panels that appear are the delineation, the "
        "georeferenced map, the threshold-pressure basis, the PISC case, the "
        "corrective-action screen, the sensitivity study and the exports. "
        "Every input carries a tooltip; the **Help** panel at the end of the "
        "row has a quick start, a glossary, and an honest account of where "
        "this tool should not be trusted.")

mode = st.radio("Start from", ["Form", "Upload project YAML", "Shipped example"],
                horizontal=True, label_visibility="collapsed",
                help="Form builds a project from the sidebar. Shipped example "
                     "is the fastest way to see a finished run.")

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
    zone_rows = _zone_editor()
    if zone_rows:
        proj_dict["formation"]["injection_zones"] = zone_rows
    proj_dict["wells"] = _well_editor(zone_rows)

if not proj_dict:
    st.stop()

try:
    project = Project.from_dict(proj_dict)
except Exception as exc:
    st.error(f"Could not read the project: {exc}")
    st.stop()

if project.is_stacked:
    st.caption(
        "Stacked completion: "
        + ", ".join(f"**{z.name}** ({U.length_out(z.top_depth, 'ft'):,.0f} ft, "
                    f"{U.length_out(z.thickness, 'ft'):,.0f} ft net)"
                    for z in project.zones)
        + ". Each is delineated separately and the project AoR is their union.")

for w in project.warnings:
    st.warning(w)

col_a, col_b = st.columns([1, 3])
with col_a:
    run_unc = st.checkbox("run uncertainty analysis", value=False,
                          help=H["uncertainty"])
    n_real = st.number_input("realisations", 40, 1000, 150, 10,
                             disabled=not run_unc, help=H["realisations"])
with col_b:
    st.json(project.summary(), expanded=False)

# Run is the page's primary action, so it spans the content width rather than
# sitting in the quarter-width column that holds the uncertainty controls.
go = st.button("Run", type="primary", **_FULL_WIDTH)

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
# The second line of each tile restates the same quantity another way, or
# names the basis for it. None of them is a change, so delta_color="off"
# keeps Streamlit from painting them as a rise.
m1.metric("AoR area", f"{s['aor']['aor_area_acres']:,.0f} acres",
          f"{s['aor']['aor_area_sq_mi']:,.1f} sq mi", delta_color="off")
m2.metric("Threshold dP", f"{s['threshold']['delta_p_critical_psi']:,.0f} psi",
          s["threshold"]["method"].split(" - ")[0], delta_color="off")
m3.metric("CO2 injected", f"{U.mass_out(project.total_injected_mass(), 'MMT'):,.1f} MMT")
if res.pisc:
    rec = s["pisc"]["recommended_pisc"].get("recommended_years", float("nan"))
    m4.metric("PISC supported by model",
              f"{rec:,.0f} yr" if np.isfinite(rec) else "not demonstrated",
              s["pisc"]["recommended_pisc"].get("basis", ""), delta_color="off")

if res.warnings:
    with st.expander(f"{len(set(res.warnings))} model-integrity item(s) to review",
                     expanded=True):
        for w in dict.fromkeys(res.warnings):
            st.warning(w)
else:
    st.success("Domain size, grid resolution, boundary influence, mass balance "
               "and pressure-regime applicability all passed their checks.")

# A result lives in session state, and a session outlives a deployment: after
# an update the page can still be holding a result built by the previous
# version of the code, which has none of the attributes added since. Reading
# those through getattr keeps such a session on the panels it can draw instead
# of failing the whole page, until the next Run replaces the object.
zones = getattr(res, "zones", []) or []
series = getattr(res, "series", []) or []

_labels = ["AoR map", "AoR over time", "GIS map", "Threshold", "PISC",
           "Corrective action", "Uncertainty", "Export", "Help"]
if zones:
    _labels.insert(1, "Zones")          # only earns a panel when there are some
T = dict(zip(_labels, st.tabs(_labels), strict=True))

# ---------------------------------------------------------------- AoR map
with T["AoR map"]:
    theme.lead(guide.LEAD["aor"])
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
    st.caption("Hover any point for its pressure buildup; drag to zoom, "
               "double-click to reset. The camera icon saves a PNG.")

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

# ------------------------------------------------------------ zones
if zones:
    with T["Zones"]:
        theme.lead(guide.LEAD["zones"])
        try:
            st.plotly_chart(viz.plotly_zone_map(zones, res.aor,
                                                wells=project.wells))
        except ImportError:
            st.pyplot(viz.zone_map(zones, res.aor, wells=[
                w for w in project.wells if w.kind == "injector"]))

        st.write("**Each zone on its own terms**")
        st.dataframe([z.summary() for z in zones], hide_index=True)
        st.caption("Each zone is modelled on its own grid, with CO2 properties "
                   "at its own pressure and temperature and a threshold "
                   "pressure from its own depth. Nothing is averaged across "
                   "zones.")

        union = res.aor.metadata.get("union_area_acres", res.aor.area_acres)
        summed = res.aor.metadata.get("sum_of_zone_areas_acres", union)
        c1, c2, c3 = st.columns(3)
        c1.metric("Project AoR (union)", f"{union:,.0f} acres", delta_color="off")
        c2.metric("Zone areas added up", f"{summed:,.0f} acres",
                  "not the AoR: double-counts the overlap", delta_color="off")
        c3.metric("Overlap", f"{summed - union:,.0f} acres",
                  f"{100 * (summed - union) / summed:,.0f} % of the sum"
                  if summed else "", delta_color="off")

        st.write("**How each zone's share of the rate was set**")
        st.dataframe(project.zone_allocation(), hide_index=True)
        st.caption(H["allocation_note"])


# ------------------------------------------------------- AoR over time
with T["AoR over time"]:
    theme.lead(guide.LEAD["series"])
    if not series:
        st.info("No time series for this run.")
    else:
        try:
            st.plotly_chart(viz.plotly_aor_series(series, wells=project.wells))
        except ImportError:
            st.pyplot(viz.aor_series_map(series, wells=[
                w for w in project.wells if w.kind == "injector"]))

        st.pyplot(viz.aor_growth_chart(series,
                                       injection_end=project.injection_end()))

        st.write("**The re-evaluation ledger**")
        st.dataframe(delineate.series_growth(series), hide_index=True)
        st.caption("`newly_included_acres` is ground inside the AoR at that "
                   "date that was outside it at the one before. That is "
                   "precisely the area 40 CFR 146.84(e)(2) makes subject to "
                   "artificial-penetration identification and corrective "
                   "action at each re-evaluation.")

        last, first = series[-1], series[0]
        st.info(
            f"The AoR grows from {first.area_acres:,.0f} acres at year "
            f"{first.year:,.0f} to {last.area_acres:,.0f} acres at year "
            f"{last.year:,.0f}. Each snapshot is delineated from the "
            "maximum-over-time fields up to that date, which is the AoR a "
            "reviewer would approve if the project were evaluated then.")


# ---------------------------------------------------------------- GIS map
with T["GIS map"]:
    theme.lead(guide.LEAD["gis"])
    try:
        from containment import gis

        ctx = gis.MapContext.from_project(project)
        c1, c2 = st.columns([2, 3])
        base = c1.selectbox("basemap", list(gis.BASEMAPS),
                            format_func=lambda k: gis.BASEMAPS[k]["name"],
                            help=H["basemap"])
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
with T["Threshold"]:
    theme.lead(guide.LEAD["threshold"])
    st.pyplot(viz.threshold_comparison(res.thresholds, res.selected_threshold))
    st.dataframe([t.summary() for t in res.thresholds], hide_index=True)
    st.caption("Methods 1 and 2 follow EPA 816-R-13-005 section 3. Method 2b "
               "is the variant for a partially penetrating conduit; "
               "mud_column assumes drilling mud still stands in the hole.")

# ------------------------------------------------------------------- PISC
with T["PISC"]:
    theme.lead(guide.LEAD["pisc"])
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
with T["Corrective action"]:
    theme.lead(guide.LEAD["corrective"])
    st.caption("Upload a CSV of artificial penetrations. Recognised columns: "
               "name, api, type, status, x, y, total_depth, year_drilled, "
               "year_abandoned, plug_depths (semicolon separated), "
               "plug_material, cased, records_complete, mit_passed, notes.")
    up = st.file_uploader("well list", type=["csv"], key="pens",
                          help="Only name and location are required. The more "
                               "columns you supply, the more of the screen "
                               "runs: plug depths and records decide whether a "
                               "well is a candidate for re-entry.")
    unit = st.radio("coordinate and depth unit", ["ft", "m"], horizontal=True,
                    help=H["pens_unit"])
    if up is not None:
        import tempfile

        from containment import corrective

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
with T["Uncertainty"]:
    theme.lead(guide.LEAD["uncertainty"])
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
with T["Export"]:
    theme.lead(guide.LEAD["export"])
    crs = None
    use_crs = st.checkbox("georeference the exports", help=H["georef"])
    if use_crs:
        kind = st.radio("transform", ["EPSG code (exact)",
                                      "origin lon/lat (approximate)"],
                        horizontal=True)
        if kind.startswith("EPSG"):
            epsg = st.number_input("EPSG", value=32614, step=1,
                                   help=H["epsg"])
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
                       "containment_report.html", "text/html")
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

# ------------------------------------------------------------------- help
with T["Help"]:
    theme.lead(guide.LEAD["help"])
    guide.render()
