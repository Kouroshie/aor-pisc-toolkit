"""Assemble a run into a self-contained HTML report.

The report is organised the way a Class VI AoR and Corrective Action Plan and
a PISC and Site Closure Plan are organised, with the regulatory citation
attached to each section, so its content can be lifted straight into the
submittal (or, from the regulator's side, compared section by section against
what an operator submitted).

Everything is embedded: figures as base64 PNGs, tables as HTML, the full input
record as JSON.  One file, no assets directory, opens offline.  40 CFR
146.84(g) requires modelling inputs to be retained for ten years; a single
self-describing file is the cheapest way to satisfy that.
"""

from __future__ import annotations

import base64
import html
import io
import json
from datetime import datetime, timezone

import numpy as np

from . import delineate, viz
from . import units as U


# --------------------------------------------------------------------------
def _fig_to_b64(fig, dpi=140) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    import matplotlib.pyplot as plt

    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _fmt(v) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        if not np.isfinite(v):
            return "n/a"
        if abs(v) >= 1000:
            return f"{v:,.0f}"
        if abs(v) >= 1:
            return f"{v:,.2f}"
        return f"{v:,.4g}"
    if isinstance(v, (list, tuple)):
        return ", ".join(_fmt(i) for i in v)
    if isinstance(v, dict):
        return "; ".join(f"{k}: {_fmt(x)}" for k, x in v.items())
    return html.escape(str(v))


def _kv_table(d: dict, drop=()) -> str:
    rows = "".join(
        f"<tr><th>{html.escape(str(k).replace('_', ' '))}</th>"
        f"<td>{_fmt(v)}</td></tr>"
        for k, v in d.items() if k not in drop and not str(k).startswith("_"))
    return f"<table class='kv'>{rows}</table>"


def _rows_table(rows: list[dict], limit: int | None = None) -> str:
    if not rows:
        return "<p class='muted'>none</p>"
    shown = rows[:limit] if limit else rows
    keys: list[str] = []
    for r in shown:
        for k in r:
            if k not in keys:
                keys.append(k)
    head = "".join(f"<th>{html.escape(k.replace('_', ' '))}</th>" for k in keys)
    body = "".join(
        "<tr>" + "".join(f"<td>{_fmt(r.get(k))}</td>" for k in keys) + "</tr>"
        for r in shown)
    more = (f"<p class='muted'>showing {len(shown)} of {len(rows)} rows</p>"
            if limit and len(rows) > limit else "")
    return f"<div class='scroll'><table class='grid'><thead><tr>{head}</tr></thead>" \
           f"<tbody>{body}</tbody></table></div>{more}"


def _callout(kind: str, title: str, body: str) -> str:
    return (f"<div class='callout {kind}'><strong>{html.escape(title)}</strong>"
            f"<div>{body}</div></div>")


def _warnings_block(warnings) -> str:
    if not warnings:
        return _callout("good", "No model-integrity warnings",
                        "Domain size, grid resolution, boundary influence, "
                        "mass balance and pressure-regime applicability all "
                        "passed their checks.")
    items = "".join(f"<li>{html.escape(str(w))}</li>" for w in dict.fromkeys(warnings))
    return _callout("warning", f"{len(set(map(str, warnings)))} item(s) to review",
                    f"<ul>{items}</ul>")


CSS = """
:root{--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--ink3:#8a8983;
--grid:#e4e3df;--blue:#2a78d6;--orange:#eb6834;--good:#0ca30c;
--warning:#fab219;--critical:#d03b3b;--card:#ffffff;}
*{box-sizing:border-box}
body{margin:0;background:var(--surface);color:var(--ink);
font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:32px 24px 80px}
h1{font-size:28px;margin:0 0 4px;letter-spacing:-.01em}
h2{font-size:20px;margin:44px 0 6px;padding-top:18px;border-top:1px solid var(--grid)}
h3{font-size:15px;margin:26px 0 6px;color:var(--ink2);text-transform:uppercase;
letter-spacing:.06em;font-weight:600}
p{margin:.6em 0}
.sub{color:var(--ink2);margin:0 0 6px}
.cite{color:var(--ink3);font-size:12.5px;margin:0 0 14px}
.muted{color:var(--ink3);font-size:13px}
table{border-collapse:collapse;width:100%;font-size:13.5px}
table.kv th{text-align:left;font-weight:500;color:var(--ink2);padding:5px 14px 5px 0;
vertical-align:top;width:42%}
table.kv td{padding:5px 0;vertical-align:top}
table.kv tr+tr th,table.kv tr+tr td{border-top:1px solid var(--grid)}
table.grid th{text-align:left;color:var(--ink2);font-weight:600;padding:7px 10px;
border-bottom:2px solid var(--grid);white-space:nowrap;position:sticky;top:0;
background:var(--surface)}
table.grid td{padding:6px 10px;border-bottom:1px solid var(--grid);white-space:nowrap}
.scroll{overflow-x:auto;max-height:520px;overflow-y:auto;border:1px solid var(--grid);
border-radius:8px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;
margin:16px 0}
.card{background:var(--card);border:1px solid var(--grid);border-radius:10px;padding:14px 16px}
.card .n{font-size:26px;font-weight:600;letter-spacing:-.02em;display:block}
.card .l{font-size:12.5px;color:var(--ink2)}
figure{margin:18px 0}
figure img{width:100%;height:auto;border:1px solid var(--grid);border-radius:10px;
background:#fff}
figcaption{font-size:12.5px;color:var(--ink2);margin-top:7px}
.callout{border-left:4px solid var(--ink3);background:var(--card);padding:12px 16px;
border-radius:0 8px 8px 0;margin:16px 0;font-size:14px}
.callout.good{border-color:var(--good)}
.callout.warning{border-color:var(--warning)}
.callout.critical{border-color:var(--critical)}
.callout ul{margin:.5em 0 0;padding-left:1.1em}
details{margin:14px 0;border:1px solid var(--grid);border-radius:8px;padding:10px 14px}
summary{cursor:pointer;color:var(--ink2);font-size:14px}
pre{overflow-x:auto;font-size:12px;background:var(--card);padding:12px;
border-radius:8px;border:1px solid var(--grid)}
footer{margin-top:56px;padding-top:18px;border-top:1px solid var(--grid);
color:var(--ink3);font-size:12.5px}
@media (prefers-color-scheme:dark){
:root{--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--ink3:#8a8983;--grid:#383835;
--card:#232321;--blue:#3987e5;--orange:#d95926}
figure img{background:#232321}}
"""


# ==========================================================================
def build_html(result, *, include_figures: bool = True,
               title: str | None = None, theme: str = "light") -> str:
    """Render a :class:`containment.workflow.ProjectResult` as one HTML document."""
    p = result.project
    s = result.summary()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    figs: list[tuple[str, str]] = []

    if include_figures:
        import matplotlib
        matplotlib.use("Agg")

        wells = [w for w in p.wells]
        figs.append((
            "Delineated Area of Review",
            "The AoR is the union of the maximum-over-time CO2 plume and the "
            "maximum-over-time region above the threshold pressure, per EPA "
            "816-R-13-005 Section 3.4. The shaded field is the maximum "
            "pressure buildup reached at each location at any time in the "
            "simulation.",
            _fig_to_b64(viz.aor_map(
                result.aor, x=result.x, y=result.y,
                dp_field=result.dp_fields.max(axis=0),
                wells=wells,
                penetrations=(result.corrective.wells if result.corrective else None),
                theme=theme, title=f"{p.name} - Area of Review"))))

        figs.append((
            "Threshold pressure by method",
            "Every applicable method from EPA Section 3.4.1, side by side. The "
            "spread between them is the single largest discretionary lever in "
            "an AoR delineation, which is why all of them are shown rather "
            "than only the one used.",
            _fig_to_b64(viz.threshold_comparison(
                result.thresholds, result.selected_threshold, theme=theme))))

        figs.append((
            "Plume evolution",
            "Successive plume outlines. Tint deepens with time; each contour "
            "carries its year.",
            _fig_to_b64(viz.evolution_map(
                result.x, result.y, result.plume_fields, result.times,
                level=(p.plume_cutoff if p.engine == "ve" else 0.5),
                wells=wells, theme=theme,
                title=f"{p.name} - CO2 plume outline by year"))))

        if result.pisc is not None:
            figs.append((
                "Post-injection behaviour",
                "Plume and pressure-front area, plume migration rate, and "
                "pressure decline against the AoR threshold. Three panels "
                "sharing one time axis rather than one frame with three "
                "scales.",
                _fig_to_b64(viz.pisc_panels(result.pisc, theme=theme))))
            if result.pisc.directional:
                try:
                    figs.append((
                        "Plume reach by direction",
                        "Final reach along each compass azimuth from the first "
                        "injector, labelled with the final migration rate. A "
                        "plume can be stable in three directions and still "
                        "running in the fourth.",
                        _fig_to_b64(viz.migration_rose(
                            result.pisc.directional, theme=theme))))
                except Exception:
                    pass

        unc = result.uncertainty or {}
        if unc.get("_tornado_obj") is not None:
            figs.append((
                "Sensitivity of AoR area",
                "One-parameter-at-a-time swings around the base case "
                "[40 CFR 146.93(c)(2)(vi)].",
                _fig_to_b64(viz.tornado_chart(unc["_tornado_obj"], theme=theme))))
        mc = unc.get("_monte_carlo_obj")
        if mc is not None and getattr(mc, "exceedance", None) is not None:
            figs.append((
                "Probabilistic Area of Review",
                "Fraction of Monte Carlo realisations placing each location "
                "inside the AoR. P90 is the area nearly every credible model "
                "includes; P10 is the outer envelope of what any of them does.",
                _fig_to_b64(viz.probabilistic_aor_map(mc, wells=wells, theme=theme))))
            figs.append((
                "Ensemble distribution of AoR area",
                "Latin-hypercube ensemble over the uncertain reservoir "
                "parameters.",
                _fig_to_b64(viz.monte_carlo_histogram(mc, theme=theme))))

    # ------------------------------------------------------------------ #
    aor = s["aor"]
    th = s["threshold"]
    cards = [
        (f"{aor['aor_area_acres']:,.0f}", "AoR area (acres)"),
        (f"{aor['aor_area_sq_mi']:,.1f}", "AoR area (sq mi)"),
        (f"{th['delta_p_critical_psi']:,.0f}", "threshold dP (psi)"),
        (f"{U.mass_out(p.total_injected_mass(), 'MMT'):,.1f}", "CO2 injected (MMT)"),
    ]
    if result.corrective:
        ca = s["corrective_action"]
        cards += [(f"{ca['penetrations_inside_aor']:,}", "penetrations in AoR"),
                  (f"{ca['corrective_action_required']:,}", "need corrective action")]
    if result.pisc:
        rec = s["pisc"]["recommended_pisc"].get("recommended_years")
        if rec is not None and np.isfinite(rec):
            cards.append((f"{rec:,.0f}", "PISC years supported by model"))

    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>{html.escape(title or p.name)} - AoR &amp; PISC</title>",
        f"<style>{CSS}</style></head><body><div class='wrap'>",
        f"<h1>{html.escape(title or p.name)}</h1>",
        "<p class='sub'>Area of Review and Post-Injection Site Care analysis"
        + (f" - {html.escape(p.operator)}" if p.operator else "")
        + (f" - permit {html.escape(p.permit)}" if p.permit else "") + "</p>",
        f"<p class='cite'>Generated {now} by containment. Depth datum: "
        f"{html.escape(p.datum)}.</p>",
        "<div class='cards'>" + "".join(
            f"<div class='card'><span class='n'>{n}</span>"
            f"<span class='l'>{label}</span></div>" for n, label in cards) + "</div>",
        _warnings_block(result.warnings),
    ]

    # 1 project + fluids
    parts += [
        "<h2>1. Project and model setup</h2>",
        "<p class='cite'>40 CFR 146.84(b)(1) - the method for delineating the "
        "AoR, the model used, the assumptions made, and the site "
        "characterization data the model is based on.</p>",
        _kv_table(s["project"], drop=("warnings",)),
        "<h3>Fluid properties at in-situ conditions</h3>",
        _kv_table(s["fluids"]),
        "<h3>Closed-form cross-checks</h3>",
        "<p class='muted'>EPA Section 2.3.2 suggests analytical models as "
        "\"a relatively simple comparative check on numerical modeling "
        "results\". These bracket the answer; they do not replace it.</p>",
        _kv_table(s["analytical_checks"]),
    ]

    # 2 threshold
    parts += [
        "<h2>2. Threshold pressure</h2>",
        "<p class='cite'>40 CFR 146.84(c)(1); EPA 816-R-13-005 Section 3.4.1 - "
        "the minimum injection-zone pressure that would drive fluid into a "
        "USDW through a hypothetical conduit perforated in both intervals.</p>",
        _kv_table(th),
        _rows_table([t for t in s["threshold_all_methods"]]),
    ]

    # 3 AoR
    parts += [
        "<h2>3. Area of Review delineation</h2>",
        "<p class='cite'>40 CFR 146.84(a) and (c)(1); EPA Section 3.4 and "
        "Box 3-2 - the AoR encompasses the maximum extent of the separate-phase "
        "plume or the pressure front over the lifetime of the project.</p>",
        _kv_table(aor),
    ]
    if result.aor.aor is not None and not result.aor.aor.is_empty and p.wells:
        inj = [w for w in p.wells if w.kind == "injector"]
        if inj:
            az = result.aor.extent_by_azimuth(inj[0].x, inj[0].y, 16)
            parts += [
                "<h3>AoR extent by azimuth from " + html.escape(inj[0].name) + "</h3>",
                _rows_table([{"azimuth_deg": k,
                              "distance_ft": U.length_out(v, "ft"),
                              "distance_mi": U.length_out(v, "mi")}
                             for k, v in az.items()])]

    # 3b stacked injection zones
    # getattr, not attribute access: a result may have been built by an older
    # version of the package and reloaded here (see ProjectResult.summary).
    zones = getattr(result, "zones", None) or []
    series = getattr(result, "series", None) or []
    if zones:
        parts += [
            "<h3>Injection zones</h3>",
            "<p class='cite'>Each zone was delineated separately, with its own "
            "fluid properties and its own threshold pressure, and the Area of "
            "Review above is the geometric union of the zone delineations. The "
            "union is not the sum: stacked zones overlap, and adding the zone "
            "acreages would overstate the AoR.</p>",
            _rows_table([z.summary() for z in zones]),
            "<h3>Rate allocation between zones</h3>",
            _rows_table(p.zone_allocation()),
        ]
        union = result.aor.metadata.get("union_area_acres", result.aor.area_acres)
        summed = result.aor.metadata.get("sum_of_zone_areas_acres", union)
        parts.append(_callout(
            "note", "Union, not sum",
            f"Project AoR {union:,.0f} acres. The zone AoRs add up to "
            f"{summed:,.0f} acres, which double-counts the "
            f"{summed - union:,.0f} acres where they overlap."))

    # 3c the AoR through time
    if series:
        rows = delineate.series_growth(series)
        parts += [
            "<h3>Area of Review at each re-evaluation</h3>",
            "<p class='cite'>40 CFR 146.84(e) - the AoR is re-evaluated at "
            "least every five years. Ground newly inside the AoR at a "
            "re-evaluation is subject to artificial-penetration "
            "identification, assessment and corrective action under "
            "146.84(e)(2)-(3).</p>",
            _rows_table(rows),
        ]
        first, last = series[0], series[-1]
        parts.append(_callout(
            "note", "AoR growth",
            f"{first.area_acres:,.0f} acres at year {first.year:,.0f}, "
            f"{last.area_acres:,.0f} acres at year {last.year:,.0f}. Each "
            "snapshot is delineated from the maximum-over-time fields up to "
            "that date."))

    # 4 corrective action
    if result.corrective:
        ca_sum = s["corrective_action"]
        parts += [
            "<h2>4. Artificial penetrations and corrective action</h2>",
            "<p class='cite'>40 CFR 146.84(c)(2), (c)(3) and (d); EPA "
            "Section 4 and the well-evaluation decision tree in Figure 4-3.</p>",
            _kv_table(ca_sum),
            "<h3>Well-by-well determination</h3>",
            _rows_table(result.corrective.table()),
            "<h3>Phased corrective action by modelled arrival time</h3>",
            "<p class='muted'>40 CFR 146.84(b)(2)(iv) permits phased corrective "
            "action at the Director's discretion. Phasing here is by the year "
            "the modelled plume or pressure front first reaches each well, "
            "which comes from the same model that produced the AoR. EPA "
            "recommends all identified deficient wells receive corrective "
            "action before the end of the injection phase.</p>",
            _kv_table(result.corrective.phases()),
        ]

    # 5 PISC
    if result.pisc:
        pi = s["pisc"]
        parts += [
            "<h2>5. Post-injection site care</h2>",
            "<p class='cite'>40 CFR 146.93(a)(2) and (c); 16 TAC 5.203(m).</p>",
            _kv_table({k: v for k, v in pi.items()
                       if k not in ("recommended_pisc", "warnings")}),
            "<h3>Recommended timeframe</h3>",
            _callout("good" if np.isfinite(pi["recommended_pisc"].get(
                "recommended_years", float("nan"))) else "warning",
                pi["recommended_pisc"].get("basis", "n/a"),
                html.escape(pi["recommended_pisc"].get("verdict", ""))),
            "<h3>Time series</h3>",
            _rows_table(result.pisc.table()),
        ]
        from . import pisc as pisc_mod

        chk = pisc_mod.alternative_timeframe_checklist(
            result.pisc,
            usdw_separation=(p.injection_zone.top_depth - p.usdw.base_depth
                             if np.isfinite(p.injection_zone.top_depth)
                             and np.isfinite(p.usdw.base_depth) else float("nan")),
            abandoned_wells_assessed=bool(result.corrective),
            conduits_identified=bool(result.corrective),
            sensitivity_analysis_done=bool(result.uncertainty),
        )
        met = sum(1 for r in chk if r["satisfied_by_model"])
        parts += [
            "<h3>40 CFR 146.93(c) demonstration checklist</h3>",
            _callout("warning" if met < len(chk) else "good",
                     f"{met} of {len(chk)} items are answered by the model",
                     "The remainder need project evidence - trapping "
                     "narratives, laboratory and field studies, confining-zone "
                     "characterisation and an approved QASP. A modelling tool "
                     "cannot satisfy 146.93(c) on its own. Regulatory text is "
                     "transcribed from a permit application's own crosswalk; "
                     "verify against the current CFR before submitting."),
            _rows_table(chk),
        ]

    # 5b uncertainty
    if result.uncertainty:
        u = result.uncertainty
        parts += [
            "<h2>5b. Sensitivity and uncertainty</h2>",
            "<p class='cite'>EPA Section 3.3.4 recommends sensitivity analysis "
            "to support the initial delineation; 40 CFR 146.93(c)(2)(vi) "
            "requires one to support an alternative PISC timeframe.</p>",
            _callout("warning", "How to read these numbers",
                     html.escape(u.get("comparability", ""))),
            _kv_table({k: v for k, v in u.items()
                       if k in ("engine_used", "project_engine",
                                "base_case_area_acres")}),
            "<h3>Ensemble percentiles of AoR area</h3>",
            _kv_table(u["monte_carlo"].get("aor_area_acres", {})),
            "<h3>Spread relative to the ensemble base case</h3>",
            _kv_table(u.get("percentile_ratio_to_base", {})),
            "<h3>Rank correlation with AoR area</h3>",
            _rows_table(u["monte_carlo"]["aor_area_acres"]["rank_correlations"]),
        ]

    # 5c the GIS map
    try:
        from . import gis

        ctx = gis.MapContext.from_project(p)
        parts += [
            "<h2>5c. Map</h2>",
            _callout("good", "An interactive map was written alongside this report",
                     "Open <code>*_map.html</code> from the same output directory. "
                     "It carries the AoR, its two components and every artificial "
                     "penetration on switchable satellite, street, topographic and "
                     "relief basemaps, with a measuring tool, and it opens offline "
                     "in any browser. Georeferencing: "
                     + html.escape(ctx.note) + "."),
        ]
    except Exception:
        parts += [
            "<h2>5c. Map</h2>",
            _callout("warning", "No GIS map for this run",
                     "The project has no georeferencing, so the AoR cannot be "
                     "placed on a real map. Give the wells "
                     "<code>latitude</code> and <code>longitude</code>, or set "
                     "<code>project.crs.epsg</code>."),
        ]

    # 6 figures
    if figs:
        parts.append("<h2>6. Figures</h2>")
        for item in figs:
            if len(item) < 3:
                continue
            cap, note, b64 = item
            parts.append(
                f"<figure><img alt='{html.escape(cap)}' "
                f"src='data:image/png;base64,{b64}'>"
                f"<figcaption><strong>{html.escape(cap)}.</strong> "
                f"{html.escape(note)}</figcaption></figure>")

    # 7 input record
    parts += [
        "<h2>7. Input record</h2>",
        "<p class='cite'>40 CFR 146.84(g) - modelling inputs and data used to "
        "support AoR delineation must be retained for ten years. EPA Section "
        "3.5 asks that a submittal contain everything needed to replicate the "
        "modelling exercise.</p>",
        "<details><summary>Project file (as parsed)</summary>"
        f"<pre>{html.escape(json.dumps(p.to_dict(), indent=2, default=str))}</pre></details>",
        "<details><summary>Full result summary (JSON)</summary>"
        f"<pre>{html.escape(json.dumps(_clean(s), indent=2, default=str))}</pre></details>",
        "<footer>Produced with containment - open-source Area of Review and "
        "Post-Injection Site Care toolkit for UIC Class VI projects. "
        "This report is an engineering analysis, not a regulatory "
        "determination.</footer>",
        "</div></body></html>",
    ]
    return "".join(parts)


def _clean(obj):
    """Strip non-serialisable helper objects out of a summary dict."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


def write_html(result, path: str, **kw) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(build_html(result, **kw))
    return path


def write_json(result, path: str) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(_clean(result.summary()), fh, indent=2, default=str)
    return path


__all__ = ["build_html", "write_html", "write_json"]
