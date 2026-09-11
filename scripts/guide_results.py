"""Sections 7 onwards of the user guide: reading the results, and the rest."""

from __future__ import annotations

from docx.shared import Inches
from guide_kit import (
    D,
    bullet,
    callout,
    code,
    figure,
    h,
    num,
    p,
    page_break,
    rich,
    table,
)

PROJ, AOR = D["project"], D["aor"]


def pick(rows, cols, limit=40):
    if not rows:
        return []
    keep = [c for c in cols if any(c in r for r in rows)]
    return [{c: r.get(c, "") for c in keep} for r in rows[:limit]]


def first(d, *keys, default="n/a"):
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] not in (None, ""):
            return d[k]
    return default


def indent(par, inches=0.25):
    par.paragraph_format.left_indent = Inches(inches)
    return par


# ==========================================================================
h(1, "7. Reading the results, panel by panel")
p("The app shows eight or nine panels depending on the project. This section "
  "takes each in turn, with the figures and numbers the worked example "
  "actually produced, and says what to look at and what to do about it.")

# ------------------------------------------------------------------- 7.1
h(2, "7.1 The headline numbers")
sel = D["selected_threshold"]
pisc = D.get("pisc", {})
rec = pisc.get("recommended_pisc", {}) if isinstance(pisc, dict) else {}
table([
    {"Metric": "AoR area", "Value":
        f"{num(AOR['area_acres'])} acres ({num(AOR['area_sq_mi'], '{:,.1f}')} sq mi)",
     "What it is": "The union of plume and pressure front, maximum over the "
                   "project life. This is the number that goes in the permit."},
    {"Metric": "Threshold dP", "Value":
        f"{num(first(sel, 'delta_p_critical_psi'))} psi",
     "What it is": f"Computed by {first(sel, 'method')}, not assumed."},
    {"Metric": "CO2 injected", "Value":
        f"{num(PROJ['total_mass_MMT'], '{:,.1f}')} MMT",
     "What it is": "Total mass over the injection period, summed from the "
                   "well schedules."},
    {"Metric": "PISC supported by model", "Value":
        f"{num(first(rec, 'recommended_years'), '{:,.0f}')} yr",
     "What it is": str(first(rec, "basis", default="see section 7.9"))[:90]},
])
rich(("What controls this AoR: ", True), str(AOR.get("controlling", "")))

# ------------------------------------------------------------------- 7.2
h(2, "7.2 Model-integrity warnings: read these first")
p("Before any number is believed, the run checks itself and says what it "
  "found. These are not cosmetic. A warning here usually means the answer "
  "below it is wrong, not merely uncertain.")
warn = D.get("warnings", [])
if warn:
    p(f"This run raised {len(warn)} item(s):")
    for w in warn:
        indent(bullet(str(w)))
else:
    p("This run raised none.")

h(3, "What each kind of warning means, and what to do")
table([
    {"Warning": "The AoR boundary reaches the edge of the model domain",
     "What it means": "The delineation is truncated by the grid, so the AoR "
                      "is only a lower bound.",
     "What to do": "Enlarge half_width and re-run until the AoR is a small "
                   "fraction of the domain."},
    {"Warning": "Only N cells across the plume",
     "What it means": "A coarse grid misrepresents buoyancy-driven migration; "
                      "EPA cautions against it directly.",
     "What to do": "Reduce cell_size over the well field, or widen "
                   "fine_half_width."},
    {"Warning": "No cell exceeds the threshold",
     "What it means": "The pressure front contributes nothing and the plume "
                      "alone sets the AoR. This is a legitimate outcome.",
     "What to do": "Nothing, but state it explicitly in the AoR plan."},
    {"Warning": "The plume footprint is still growing at the end of the run",
     "What it means": "Stabilisation cannot be claimed from a run that ends "
                      "while the plume is still moving.",
     "What to do": "Raise end_year until growth flattens, then re-run."},
    {"Warning": "A well exceeds its declared bottomhole-pressure limit",
     "What it means": "The schedule is not injectable as written, so this is "
                      "not the project's AoR.",
     "What to do": "Lower the rate, add a well, or raise the limit if the "
                   "completion supports it."},
    {"Warning": "Zones were delineated separately and unioned",
     "What it means": "Informational: the project AoR is a union, not a sum.",
     "What to do": "Quote the union in the permit and show the per-zone areas "
                   "behind it."},
])
page_break()

# ------------------------------------------------------------------- 7.3
h(2, "7.3 Threshold pressure")
p("This is where an AoR is won or lost, so every method is computed and shown, "
  "not only the one chosen. Methods that do not apply to the site's pressure "
  "regime are drawn hatched and excluded from the automatic choice.")
figure("threshold_comparison",
       "Every threshold method side by side. The chosen one is highlighted; "
       "hatched bars do not apply to this pressure regime.")
table(pick(D["thresholds"],
           ["method", "delta_p_critical_psi", "p_threshold_abs_psi", "regime",
            "applicable"]),
      caption="The methods computed for this project.")
rich(("Chosen: ", True), f"{first(sel, 'method')} at "
     f"{num(first(sel, 'delta_p_critical_psi'))} psi. ",
     (str(first(sel, "citation", default="")), False, True))
callout("What a reviewer will ask",
        "Why this method rather than another, and what the AoR would have been "
        "under the alternatives. The table above answers the first. Re-running "
        "with threshold.method set to each in turn answers the second, and "
        "takes seconds.")

# ------------------------------------------------------------------- 7.4
h(2, "7.4 The AoR map")
figure("aor_map",
       "The Area of Review. Background shading is the maximum pressure buildup "
       "each location ever sees. The dashed outline is the union that goes in "
       "the permit.")
p("Three things to check on this map. First, which component controls, and "
  "where: the union usually has a shape neither component has on its own. "
  "Second, whether the boundary runs into the edge of the domain, which would "
  "mean the grid is too small. Third, whether the shape makes geological "
  "sense: dip should pull it updip, and a sealing fault should flatten it on "
  "that side.")
az = D.get("azimuth_mi", {})
if az:
    table([{"azimuth (deg)": k, "distance (mi)": num(v, "{:,.2f}")}
           for k, v in az.items()],
          caption="AoR extent by azimuth from the first injector. This is the "
                  "table a landman uses to find whose ground is affected.")

# ------------------------------------------------------------------- 7.5
h(2, "7.5 Stacked injection zones")
p("This project injects into two sands through one wellbore. Each was "
  "modelled on its own grid, with CO2 properties at its own pressure and "
  "temperature and a threshold pressure from its own depth. Nothing is "
  "averaged across zones.")
figure("zone_map",
       "Each zone's own AoR, with the project AoR drawn over them as the "
       "dashed union.")
table(pick(D["zones"],
           ["zone", "top_depth_ft", "net_thickness_ft", "permeability_mD",
            "threshold_dp_psi", "co2_allocated_MMT", "aor_area_acres",
            "controlling_component"]),
      caption="Each zone on its own terms.")
meta = AOR.get("metadata", {})
union = first(meta, "union_area_acres", default=AOR["area_acres"])
summed = first(meta, "sum_of_zone_areas_acres", default=union)
try:
    overlap = float(summed) - float(union)
    pct = 100.0 * overlap / float(summed) if float(summed) else 0.0
except (TypeError, ValueError):
    overlap, pct = 0.0, 0.0
callout("The union is not the sum",
        f"The project AoR is {num(union)} acres. The zone AoRs add up to "
        f"{num(summed)} acres, which double-counts the {num(overlap)} acres "
        f"where they overlap, about {num(pct)} percent of the sum. Quote the "
        "union.")
table(pick(D["zone_allocation"],
           ["zone", "top_depth_ft", "net_thickness_ft", "permeability_mD",
            "kh_share_percent", "named_completions"]),
      caption="How each zone's share of a commingled rate was set. This split "
              "is an assumption: if you have a spinner or distributed-"
              "temperature survey, name the zone on each well row and enter "
              "the measured rates instead.")
page_break()

# ------------------------------------------------------------------- 7.6
h(2, "7.6 The AoR through time")
p("40 CFR 146.84(e) requires the AoR to be re-evaluated at least every five "
  "years, and each re-evaluation asks whether it has grown into ground nobody "
  "has screened. That schedule is computed in advance here.")
figure("aor_series_map",
       "The AoR at each re-evaluation date, nested. Time runs light to dark.")
figure("aor_growth",
       "Area against time, with the area added at each re-evaluation below. "
       "Growth slows sharply once injection ends.")
series = D.get("series", [])
dates = D.get("series_dates", [])
rows = []
for i, r in enumerate(series):
    row = {"year": num(r.get("year")),
           "date": dates[i] if i < len(dates) else "",
           "area_acres": num(r.get("area_acres")),
           "added_acres": num(r.get("added_acres")),
           "newly_included_acres": num(r.get("newly_included_acres"))}
    rows.append(row)
table(rows, caption="The re-evaluation ledger. `newly_included_acres` is "
                    "ground inside the AoR at that date that was outside it at "
                    "the one before, which is precisely what 146.84(e)(2) "
                    "makes subject to corrective action.")
p("Each snapshot is delineated from the maximum-over-time fields up to that "
  "date, which is the AoR a reviewer would approve if the project were "
  "evaluated then. That is why the series never shrinks.")

h(3, "Differencing two re-evaluations")
figure("comparison_map",
       "Two delineations overlaid, with the newly included ground highlighted.")
delta = D.get("reevaluation_delta", {})
if delta:
    table([{"Quantity": k.replace("_", " "), "Value": num(v, "{:,.2f}")
            if isinstance(v, (int, float)) else str(v)[:120]}
           for k, v in delta.items()],
          caption="The 146.84(e) comparison, produced by "
                  "`containment reevaluate`.")
newly = D.get("newly_included", [])
if newly:
    p(f"Wells newly inside the AoR between those two dates: {', '.join(newly)}. "
      "These are the penetrations that must now be identified, assessed and, "
      "where necessary, corrected.")

# ------------------------------------------------------------------- 7.7
h(2, "7.7 Corrective action")
p("Artificial penetrations through the confining zone are the realistic "
  "leakage pathway. Every well in the list is screened against the AoR, "
  "against the seal, and against the modelled arrival time of pressure and of "
  "CO2, which is what phases the work.")
ca = D.get("corrective", {})
if ca:
    table([{"Quantity": k.replace("_", " "),
            "Value": (num(v, "{:,.2f}") if isinstance(v, (int, float))
                      else str(v)[:110])}
           for k, v in list(ca.items())[:14]],
          caption="The corrective-action summary.")
table(pick(D.get("corrective_table", []),
           ["name", "type", "status", "in_aor", "penetrates_confining_zone",
            "action", "priority", "pressure_arrival_yr", "plume_arrival_yr",
            "reason"],
           limit=25),
      caption="Well-by-well determination, following EPA's Figure 4-3 decision "
              "tree.")
phases = D.get("corrective_phases", {})
if isinstance(phases, dict) and phases:
    rows = []
    for k, v in phases.items():
        rows.append({"phase": str(k),
                     "wells": (", ".join(v) if isinstance(v, list)
                               else str(v))[:110]})
    table(rows, caption="Phased by modelled arrival time: which wells have to "
                        "be dealt with first, and which can wait.")
callout("How to read a determination",
        "A well only needs corrective action if it is inside the AoR AND "
        "penetrates the confining zone AND its construction or records leave "
        "doubt that it will hold. A well inside the AoR that stops well above "
        "the seal is not a conduit into the injection zone, and the reason "
        "column says so.")
page_break()

# ------------------------------------------------------------------- 7.8
h(2, "7.8 Post-injection site care")
p("The default under 40 CFR 146.93 is fifty years. A shorter timeframe has to "
  "be earned with a demonstration that the plume has stopped moving and "
  "pressure has fallen below the threshold.")
figure("pisc_panels",
       "Plume area, migration rate and pressure decline after injection ends.")
if "migration_rose" in D.get("figures", []):
    figure("migration_rose",
           "Direction of plume migration. Dip drives it updip, which is where "
           "monitoring should be concentrated.", width=4.6)
table(pick([r for i, r in enumerate(D.get("pisc_table", []))
            if i % 4 == 0 or i == len(D.get("pisc_table", [])) - 1],
           ["year", "years_post_injection", "plume_area_acres",
            "effective_radius_ft", "migration_rate_ft_per_yr",
            "area_expansion_rate_acres_per_yr", "pressure_front_area_acres"],
           limit=16),
      caption="The PISC table: what the plume and the pressure are doing after "
              "shut-in.")
table([{"Quantity": k.replace("_", " "),
        "Value": (num(v, "{:,.2f}") if isinstance(v, (int, float))
                  else str(v)[:110])}
       for k, v in D.get("pisc", {}).items()
       if not isinstance(v, (dict, list))],
      caption="The PISC headline numbers.")
if rec:
    rich(("Recommended timeframe: ", True),
         f"{num(first(rec, 'recommended_years'))} years. ",
         (str(first(rec, "verdict", "basis", default=""))[:400], False, True))
table(pick(D.get("pisc_checklist", []),
           ["citation", "requirement", "satisfied_by_model", "evidence"],
           limit=20),
      caption="The 40 CFR 146.93(c) checklist for an alternative timeframe. "
              "Anything not satisfied is work still to do, not an error.")

# ------------------------------------------------------------------- 7.9
h(2, "7.9 Uncertainty")
p("Two questions, two tools. Which inputs move the answer, and how wide is "
  "the answer when they all move together.")
if D.get("uncertainty_note"):
    callout("Read this before the numbers below",
            str(D["uncertainty_note"])[:600], fill="FFF4E5")
p("That is why the acreages in this section do not match the headline AoR. "
  f"The base case is {num(AOR['area_acres'])} acres on the "
  "vertical-equilibrium engine; the ensemble below runs on the analytical "
  "engine and lands elsewhere. What transfers is the ranking of the "
  "parameters and the width of the distribution, not the absolute area.")
figure("tornado", "One parameter at a time, ranked by how far it moves the "
                  "AoR area.")
tor = D.get("tornado", [])
if tor:
    table([{"parameter": r.get("parameter", ""),
            "low (acres)": num(r.get("low_value")),
            "high (acres)": num(r.get("high_value")),
            "swing (acres)": num(r.get("swing"))} for r in tor],
          caption="The tornado, on AoR area. A parameter with zero swing is "
                  "not broken: it means the other component controls the "
                  "union everywhere, which is itself worth knowing.")
figure("monte_carlo", "The distribution of AoR area over the ensemble.")
figure("probabilistic_aor",
       "The probabilistic AoR: how often each location falls inside the "
       "boundary across the ensemble.")
pct = D.get("monte_carlo_percentiles", {})
if pct:
    table([{"Percentile": k, "AoR area (acres)": num(v)}
           for k, v in pct.items()],
          caption="P10, P50 and P90 of AoR area.")
corr = D.get("monte_carlo_correlations", [])
if corr:
    table(pick(corr, ["parameter", "unit", "spearman_rho"], limit=15),
          caption="Rank correlation with AoR area across the ensemble.")

# ------------------------------------------------------------------ 7.10
h(2, "7.10 The well pressure check")
p("A rate schedule that cannot be injected is not a plan. Where a well "
  "declares a limit, the run reports the highest bottomhole pressure it was "
  "asked for and whether that fits.")
table(pick(D.get("well_pressure", []),
           ["well", "kind", "max_bhp_psi", "year_of_max", "date_of_max",
            "limit_psi", "margin_psi", "verdict"]),
      caption="Per-well bottomhole pressure against the declared limit.")

# ------------------------------------------------------------------ 7.11
h(2, "7.11 Plume evolution and the vertical picture")
figure("plume_evolution",
       "The plume outline at successive times on one map, so growth and "
       "direction are visible together.")
if "cross_section" in D.get("figures", []):
    figure("cross_section",
           "A vertical slice through the vertical-equilibrium solution: CO2 "
           "thickness riding on the top surface of the injection zone.")
page_break()

# ==========================================================================
h(1, "8. Exports: what to hand to whom")
p("Different audiences need different files. Everything below is produced by "
  "one run and lives in the Export panel of the app, or beside your project "
  "file on the command line.")
table([
    {"File": "aor.geojson", "Give it to": "GIS staff, anyone technical",
     "Why": "The AoR, plume and pressure front with full attributes. The best "
            "format, and the one to use internally."},
    {"File": "aor_shapefile.zip", "Give it to": "State agencies, landmen",
     "Why": "The format most agencies ask for. Holds .shp, .shx, .dbf and a "
            ".prj so the frame is unambiguous."},
    {"File": "aor.kml", "Give it to": "Anyone with Google Earth",
     "Why": "Opens on any machine with no GIS software and no training."},
    {"File": "aor_map.html", "Give it to": "Field inspectors, surface owners",
     "Why": "A self-contained satellite map that opens offline, with layer "
            "switching and a measuring tool."},
    {"File": "containment_report.html", "Give it to": "The permit file, reviewers",
     "Why": "Organised the way an AoR and Corrective Action Plan is organised, "
            "with the citation on every section."},
    {"File": "corrective_action.csv", "Give it to": "The well-work planner",
     "Why": "Every penetration, its determination and its arrival time."},
    {"File": "project.yaml", "Give it to": "Anyone who must reproduce the run",
     "Why": "The complete record of what was modelled. Part of what 146.84(g) "
            "asks you to retain for ten years."},
    {"File": "fields.npz", "Give it to": "The modelling team, the archive",
     "Why": "Gridded pressure and saturation through time. The other half of "
            "the 146.84(g) record."},
    {"File": "summary.json", "Give it to": "Downstream tools, dashboards",
     "Why": "Every number in the run, machine-readable."},
])
p("Files this run actually produced: " + ", ".join(D.get("exports", [])) + ".")

# ==========================================================================
h(1, "9. The GIS map")
p("The map is built from the well latitudes and longitudes, on switchable "
  "satellite, street, topographic and shaded-relief basemaps, with the AoR, "
  "both components and every penetration colour-coded by required action, a "
  "measuring tool, and popups carrying each well's determination and its "
  "modelled arrival year. No API key and no account.")
if PROJ.get("gis_note"):
    rich(("Georeferencing for this run: ", True), str(PROJ["gis_note"]))
callout("Send the HTML, not a screenshot",
        "The downloaded map opens offline in any browser with the basemaps, "
        "the layer switcher and the measuring tool intact. It is the artefact "
        "to send to a landman, a field inspector or a surface owner, and it "
        "answers most of their questions without a meeting.")

# ==========================================================================
h(1, "10. Importing someone else's simulation")
p("If the flow modelling was done in CMG, ECLIPSE or TOUGH2, the delineation "
  "can still be done here. Export the gridded pressure and saturation, then "
  "re-delineate with the same rules and the same threshold methods.")
code("containment import simulation.csv --project project.yaml \\\n"
     "    --pressure dp --saturation sg --output aor.geojson",
     "Re-delineating an AoR from a third-party simulation.")
imp = D.get("import_check", {})
if imp:
    p(f"As a check on that path, this run exported its own fields to CSV and "
      f"re-imported them. The native delineation gave "
      f"{num(imp.get('native_area_acres'))} acres and the round trip through "
      f"the importer gave {num(imp.get('area_acres'))} acres.")

# ==========================================================================
h(1, "11. Where the tool should not be trusted")
callout("Thick injection zones",
        "The vertical-equilibrium engine assumes CO2 and brine segregate "
        "faster than they flow sideways. Validated against operator AoR "
        "figures it lands within about 2 percent on a 250 ft zone, but runs "
        "1.5 to 1.8 times wide on a 1,200 to 2,000 ft shale-punctuated "
        "interval. Treat a thick-zone AoR as a conservative upper bound and "
        "cross-check it against a full-physics simulator.", fill="FFF4E5")
callout("Stacked zones are modelled as hydraulically independent",
        "Each zone is solved on its own grid, so pressure built up in one does "
        "not push back on another through a leaky seal or a shared aquifer "
        "leg. Where zones are known to be in communication, that understates "
        "buildup and the pressure-front AoR with it.", fill="FFF4E5")
callout("Monte Carlo areas are not the base-case area",
        "The uncertainty run uses the fast analytical engine, so its absolute "
        "areas are not comparable with a vertical-equilibrium base case. Read "
        "the ranking and the ratios, not the raw acreage.", fill="FFF4E5")
callout("Foot-based projected coordinate systems",
        "Operators pin models to Texas State Plane or BLM zones in US survey "
        "feet (EPSG 32040, 32064, 2278). The toolkit handles these, but check "
        "the units on any CRS you supply: a silent factor of 3.28 is the "
        "easiest large error to make in this work.", fill="FFF4E5")
callout("It is an engineering analysis",
        "Not a regulatory determination. The permitting authority decides.",
        fill="EAF2FB")

# ==========================================================================
h(1, "12. Troubleshooting")
table([
    {"Symptom": "The GIS map panel says it needs coordinates",
     "Cause and fix": "The wells were entered as x/y rather than latitude and "
                      "longitude, so there is nothing to georeference against. "
                      "Re-enter them as lat/lon, or supply a CRS."},
    {"Symptom": "The AoR fills most of the model domain",
     "Cause and fix": "The boundary condition is shaping the result. Enlarge "
                      "half_width until the AoR is a small fraction of the "
                      "domain, then confirm the answer stops changing."},
    {"Symptom": "The plume has not stopped moving at the end of the run",
     "Cause and fix": "Raise end_year. A PISC timeframe cannot be claimed "
                      "from a run that ends mid-migration."},
    {"Symptom": "A threshold method is missing from the comparison",
     "Cause and fix": "It does not apply to this pressure regime and was "
                      "excluded deliberately. The report says which and why."},
    {"Symptom": "The hosted app says it has gone over its resource limits",
     "Cause and fix": "The public host allows about 2.7 GB. Shrink the domain, "
                      "coarsen cell_size, or run it locally where there is no "
                      "such limit."},
    {"Symptom": "The hosted app was asleep when you arrived",
     "Cause and fix": "Free apps hibernate after 12 hours without traffic and "
                      "take under a minute to wake."},
    {"Symptom": "A run takes minutes rather than seconds",
     "Cause and fix": "Normal for a vertical-equilibrium run over a century "
                      "with uncertainty. Use engine: analytical while you are "
                      "still changing inputs, then switch back."},
])
page_break()
