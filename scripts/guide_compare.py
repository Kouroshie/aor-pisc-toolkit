"""Section 13 of the guide: the EASiTool comparison, and the appendices."""

from __future__ import annotations

import os

from guide_kit import (
    MUTED,
    D,
    bullet,
    callout,
    code,
    doc,
    h,
    num,
    p,
    page_break,
    rich,
    table,
)

PROJ, AOR = D["project"], D["aor"]

# ==========================================================================
h(1, "13. How this compares with EASiTool")
p("EASiTool, from the Gulf Coast Carbon Center at UT Austin, is the tool this "
  "one is most often compared with. It is well made, widely used, and shares "
  "the analytical lineage this toolkit rests on. The comparison below was made "
  "by running EASiTool 5.1 on its own input template in September 2026, not by "
  "reading its documentation.")

callout("The short version",
        "EASiTool sizes a project: how much CO2 fits, how many wells it takes, "
        "and what it is worth. Containment builds the permit demonstrations: "
        "where the Area of Review is, which wells must be fixed, and how long "
        "the site must be watched afterwards. If you are screening a "
        "prospect, use EASiTool. If you are writing or reviewing a Class VI "
        "permit, the three demonstrations are what you need, and EASiTool does "
        "not produce two of them.")

h(2, "13.1 The three differences that matter most")

h(3, "1. The threshold pressure is computed here, and typed in there")
p("In EASiTool, 'Critical Pressure Increase' is a number the user enters. The "
  "template ships with 2 MPa, about 290 psi, and the results page offers a "
  "slider. Nothing in its input file describes a USDW or a confining zone, so "
  "there is nothing from which a threshold could be derived.")
p("In Containment the threshold is computed from the site: four EPA and TCEQ "
  "methods, each checked against the site's pressure regime, with the most "
  "protective applicable one chosen and all of them shown. On this guide's "
  f"worked example the computed threshold is "
  f"{num(D['selected_threshold'].get('delta_p_critical_psi'))} psi. Typing in "
  "the EASiTool default instead would have produced a different AoR, and no "
  "record of why.")
rich(("Why this matters in a hearing: ", True),
     "the threshold is the single largest discretionary lever in a "
     "delineation. A reviewer who asks where the number came from needs an "
     "answer better than a default in a spreadsheet.")

h(3, "2. The AoR is a maximum over time here, and a snapshot there")
p("EASiTool's maps are titled with a date and driven by a timestep slider: "
  "the AoR is evaluated at the selected time. EPA Section 3.4 asks for the "
  "maximum extent over the lifetime of the project and the entire timeframe of "
  "the simulation. Those are different numbers, and they diverge in a specific "
  "way: the pressure front peaks at shut-in and then relaxes, while the plume "
  "keeps creeping updip for decades afterwards. A snapshot taken at either "
  "moment misses the other.")

h(3, "3. Corrective action and PISC exist here and not there")
p("EASiTool has no artificial-penetration screening and no post-injection "
  "site care analysis. Those are two of the three demonstrations a Class VI "
  "permit turns on. They are not add-ons to an AoR: the corrective-action list "
  "is derived from the AoR polygon and the modelled arrival times, and the "
  "PISC case is derived from what the plume and the pressure do after shut-in.")

page_break()
h(2, "13.2 Side by side")
table([
    {"Capability": "Purpose",
     "EASiTool 5.1": "Storage capacity, well-count optimisation, NPV",
     "Containment": "AoR delineation, corrective action, PISC"},
    {"Capability": "Threshold pressure",
     "EASiTool 5.1": "An input you type (default 2 MPa)",
     "Containment": "Computed, four methods compared, regime-checked"},
    {"Capability": "USDW and confining zone",
     "EASiTool 5.1": "Not in the input file",
     "Containment": "Required; the threshold is derived from them"},
    {"Capability": "AoR definition",
     "EASiTool 5.1": "Pressure field at a selected timestep",
     "Containment": "Maximum over project life, plume and pressure unioned"},
    {"Capability": "Plume representation",
     "EASiTool 5.1": "A radius per well",
     "Containment": "A contoured field: merged plumes, dip, residual trapping"},
    {"Capability": "Heterogeneity, dip, structure",
     "EASiTool 5.1": "One homogeneous reservoir area",
     "Containment": "Full fields of k, porosity, thickness and top structure"},
    {"Capability": "Faults",
     "EASiTool 5.1": "A trace, no properties",
     "Containment": "Traces with transmissibility multipliers"},
    {"Capability": "Stacked injection zones",
     "EASiTool 5.1": "Not supported; net sand capped at 500 m",
     "Containment": "Per-zone delineation, unioned, per-zone thresholds"},
    {"Capability": "Post-injection migration",
     "EASiTool 5.1": "Pressure relaxes; no migration physics",
     "Containment": "Buoyant updip migration with residual trapping"},
    {"Capability": "AoR re-evaluation [146.84(e)]",
     "EASiTool 5.1": "A timestep slider",
     "Containment": "Delineation at every re-evaluation date, with newly "
                    "included acreage"},
    {"Capability": "Corrective action",
     "EASiTool 5.1": "None",
     "Containment": "EPA Figure 4-3 tree, phased by arrival time"},
    {"Capability": "PISC",
     "EASiTool 5.1": "None",
     "Containment": "146.93 metrics, stabilisation, timeframe, (c) checklist"},
    {"Capability": "Sensitivity target",
     "EASiTool 5.1": "Mean reservoir pressure and capacity",
     "Containment": "AoR area, plus a probabilistic AoR map"},
    {"Capability": "Model-integrity checks",
     "EASiTool 5.1": "None reported",
     "Containment": "Domain, resolution, boundary, mass balance, regime"},
    {"Capability": "Economics",
     "EASiTool 5.1": "NPV, capex and opex, 45Q credit, discount rate",
     "Containment": "None"},
    {"Capability": "Storage capacity",
     "EASiTool 5.1": "Yes, under fixed bottomhole pressure",
     "Containment": "Not computed"},
    {"Capability": "Well-count optimisation",
     "EASiTool 5.1": "Capacity and NPV against number of injectors",
     "Containment": "None"},
    {"Capability": "Exports",
     "EASiTool 5.1": "Shapefile, output workbook",
     "Containment": "GeoJSON, KML, shapefile, CSV, HTML report, field archive"},
    {"Capability": "Input format",
     "EASiTool 5.1": "One Excel template, SI or field units",
     "Containment": "YAML project file, any units, or a simulator import"},
    {"Capability": "Licence and access",
     "EASiTool 5.1": "Web app, sign-in, alpha",
     "Containment": "Apache-2.0 source, pip-installable, library plus CLI "
                    "plus app, tested in CI"},
])

h(2, "13.3 What Containment has that EASiTool does not")
p("Stated plainly, for anyone deciding which to use for permit work:")
for item in [
    "A computed threshold pressure, by four methods, with applicability "
    "checks, instead of a number typed into a box.",
    "A real AoR polygon: the geometric union of plume and pressure front, "
    "taken as the maximum over the project lifetime as the rule requires.",
    "Corrective action: EPA's decision tree applied to every artificial "
    "penetration, with phasing by modelled arrival time.",
    "Post-injection site care: stabilisation, migration rate, pressure decay, "
    "a defensible timeframe and the 146.93(c) checklist.",
    "A USDW and a confining zone as first-class inputs.",
    "Stacked injection zones, each delineated on its own terms and unioned.",
    "The AoR at every 146.84(e) re-evaluation date, with the ground newly "
    "included at each one, which is what triggers further corrective action.",
    "Heterogeneity, dip, structural surfaces and faults with transmissibility "
    "multipliers.",
    "Post-injection buoyant migration with residual trapping, run for "
    "centuries where that is what the demonstration needs.",
    "Model-integrity warnings: domain size, grid resolution, boundary "
    "influence, mass balance and threshold applicability, reported rather "
    "than assumed.",
    "A probabilistic AoR as a map, with P10, P50 and P90 boundaries, and a "
    "tornado ranked on AoR area rather than on pressure.",
    "AoR re-evaluation differencing, which is the 146.84(e)(2) calculation "
    "itself.",
    "Reproducibility as a deliverable: a project file and a gridded-field "
    "archive that together are the record 146.84(g) asks you to keep.",
    "Open source under Apache-2.0, installable as a library, scriptable, and "
    "covered by a test suite that runs in CI. EPA notes that proprietary "
    "codes may prevent full evaluation of model results; every equation here "
    "carries its citation in the source.",
]:
    bullet(item)

h(2, "13.4 What EASiTool has that Containment does not")
p("In fairness, and because these are real gaps if they matter to your work:")
for item in [
    "Storage capacity under a fixed bottomhole pressure.",
    "Well-count optimisation: capacity and NPV against the number of "
    "injectors.",
    "Economics: capital and operating cost, the 45Q tax credit, discount "
    "rate, net present value.",
    "An Excel input template with built-in unit conversion and validation "
    "ranges, which is friendlier than YAML for many teams.",
    "The ability to draw a project area directly on the map.",
    "A desktop build for classroom and multi-user settings.",
]:
    bullet(item)
p("Four capabilities were added to Containment after that comparison, with "
  "credit to EASiTool for showing they were missing: shapefile export, "
  "per-well bottomhole-pressure verdicts, calendar dates on schedules and "
  "results, and a sensitivity study that varies fluid properties, relative "
  "permeability and the threshold pressure rather than only the four storage "
  "properties.")
page_break()

# ==========================================================================
h(1, "Appendix A. The complete project file")
p("This is the file that produced every number and figure in this guide. It "
  "is examples/showcase_full.yaml in the repository.")
try:
    yaml_path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "examples", "showcase_full.yaml")
    with open(yaml_path, encoding="utf-8") as fh:
        text = fh.read()
    for chunk_start in range(0, len(text.splitlines()), 60):
        chunk = "\n".join(text.splitlines()[chunk_start:chunk_start + 60])
        code(chunk)
except OSError as exc:
    p(f"(not embedded: {exc})", italic=True, colour=MUTED)
page_break()

h(1, "Appendix B. Command-line reference")
for key, title in (("help", "containment --help"),
                   ("threshold", "containment threshold examples/showcase_full.yaml"),
                   ("reevaluate_help", "containment reevaluate --help"),
                   ("import_help", "containment import --help")):
    txt = D.get("cli", {}).get(key, "")
    if not txt:
        continue
    h(3, title)
    code(txt[:2600])
page_break()

h(1, "Appendix C. Everything this run exercised")
p("The worked example was built to put the whole toolkit to work. These are "
  "the entry points it called, which is how this guide can claim to cover the "
  "tool rather than a corner of it.")
funcs = D.get("functions_used", [])
half = (len(funcs) + 1) // 2
rows = []
for i in range(half):
    rows.append({"": funcs[i],
                 " ": funcs[i + half] if i + half < len(funcs) else ""})
table(rows, caption=f"{len(funcs)} entry points.", max_rows=60)

h(1, "Appendix D. Glossary")
table([
    {"Term": "Area of Review (AoR)", "Definition":
        "The region around an injection well where formation fluids could be "
        "driven into a USDW. Delineated by modelling under 40 CFR 146.84 and "
        "re-evaluated at least every five years."},
    {"Term": "Pressure-front AoR", "Definition":
        "The contour where pressure buildup equals the threshold pressure."},
    {"Term": "Plume AoR", "Definition":
        "The footprint of free-phase CO2 at the disclosed saturation cutoff."},
    {"Term": "Threshold (critical) pressure", "Definition":
        "The buildup that would just lift formation fluid into the lowermost "
        "USDW through a hypothetical open conduit."},
    {"Term": "USDW", "Definition":
        "Underground source of drinking water: under 10,000 mg/L TDS and not "
        "exempted."},
    {"Term": "Confining zone", "Definition":
        "The sealing interval above the injection zone."},
    {"Term": "Corrective action", "Definition":
        "Repair or re-plugging of artificial penetrations inside the AoR that "
        "could act as leakage conduits [146.84(d)]."},
    {"Term": "PISC", "Definition":
        "Post-injection site care: monitoring after injection stops, fifty "
        "years by default [146.93]."},
    {"Term": "Non-endangerment demonstration", "Definition":
        "The showing that plume and pressure have stabilised such that no "
        "further USDW endangerment is expected."},
    {"Term": "Vertical equilibrium (VE)", "Definition":
        "The assumption that CO2 and brine segregate quickly compared with "
        "lateral flow, so only the map view is stepped in time."},
    {"Term": "Superposition (analytical engine)", "Definition":
        "Closed-form pressure solutions summed over wells and time. No gravity "
        "override and no post-injection migration."},
    {"Term": "Residual trapping (Sgr)", "Definition":
        "CO2 left immobile behind the trailing edge of the plume. What "
        "eventually halts migration."},
    {"Term": "Stacked injection zones", "Definition":
        "Two or more formations taking CO2 through one wellbore. Delineated "
        "separately and unioned."},
    {"Term": "Commingled completion", "Definition":
        "One tubing string open to several perforated intervals. Without a "
        "zonal allocation survey the split is estimated from k*h."},
    {"Term": "Plume cutoff", "Definition":
        "The saturation that counts as plume edge. A disclosed modelling "
        "choice, not a physical constant."},
    {"Term": "Boundary condition", "Definition":
        "How the model treats the edge of the domain: infinite, constant "
        "pressure, or no-flow."},
    {"Term": "Stabilisation", "Definition":
        "The plume no longer expanding and pressure decaying below the "
        "threshold: the precondition for shortening PISC."},
])

# ==========================================================================
doc.add_paragraph()
p("Containment is open source under Apache-2.0 at "
  "github.com/Kouroshie/containment. The hosted app is at "
  "containment.streamlit.app.", size=9.5, colour=MUTED)
p(f"Guide generated {D['generated']} from a live run of "
  f"examples/showcase_full.yaml.", size=9.5, colour=MUTED, italic=True)

# The document is saved by build_guide.py, once every section has run.
