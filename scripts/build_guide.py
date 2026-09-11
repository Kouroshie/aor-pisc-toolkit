"""Assemble the Containment user guide as a Word document.

Reads ``data.json`` and ``figures/`` produced by ``build_showcase.py`` and
writes ``Containment_User_Guide.docx`` beside them. Every number and figure in
the guide comes from that run, so the document cannot drift from the tool.

    python scripts/build_showcase.py      # first: run the example
    python scripts/build_guide.py         # then: write the guide
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: E402
from docx.shared import Pt  # noqa: E402
from guide_kit import (  # noqa: E402
    BRAND,
    INK,
    MUTED,
    OUT,
    D,
    bullet,
    callout,
    code,
    doc,
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
    """Rows reduced to the columns that exist, in the order asked for."""
    if not rows:
        return []
    keep = [c for c in cols if any(c in r for r in rows)]
    return [{c: r.get(c, "") for c in keep} for r in rows[:limit]]


def first(d: dict, *keys, default="n/a"):
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] not in (None, ""):
            return d[k]
    return default


# ==========================================================================
# COVER
# ==========================================================================
p("UIC CLASS VI", bold=True, size=10, colour=BRAND,
  align=WD_ALIGN_PARAGRAPH.CENTER, space_after=2)
t = p("Containment", size=40, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER,
      space_after=4)
t.runs[0].font.name = "Georgia"
t.runs[0].font.color.rgb = INK
p("Area of Review, corrective action and post-injection site care",
  size=13, colour=MUTED, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=20)
p("A complete user guide, from nothing to a finished permit demonstration",
  size=12, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=24)

p(f"Every number, table and figure in this guide came from one run of the "
  f"worked example on {D['generated']}. Nothing here is illustrative. That run "
  f"exercised {len(D['functions_used'])} toolkit entry points, produced "
  f"{len(D['figures'])} figures and {len(D['exports'])} export files, and took "
  f"{num(D['runtime_s'])} seconds.",
  italic=True, size=9.5, colour=MUTED, align=WD_ALIGN_PARAGRAPH.CENTER,
  space_after=14)

figure("aor_map",
       "The finished product: the Area of Review for the worked example used "
       "throughout this guide, with its two components, the injection wells, "
       "and every artificial penetration colour-coded by the action it needs.",
       width=5.3)
page_break()

# ==========================================================================
h(1, "The site")
p("Before anything else, here is where this project is and what its Area of "
  "Review covers, on four basemaps. Every later figure in this guide is a "
  "version of this picture with the basemap stripped away, so it is worth "
  "spending a moment on: the dashed line is the AoR that goes in the permit, "
  "the triangles are the injection wells, and the crosses and circles are "
  "artificial penetrations coloured by the action each one needs.")

_MAPS = [
    ("gis_satellite", "Satellite imagery. The basemap to send to a landman or "
                      "a surface owner: it shows what is actually on the "
                      "ground inside the boundary, which is the first "
                      "question anyone asks."),
    ("gis_streets", "Streets. Roads, place names and parcel context, which is "
                    "what a public meeting or a notification letter needs."),
    ("gis_topo", "Topographic. Drainage, contours and cultural features, for "
                 "siting monitoring wells and planning access."),
    ("gis_terrain", "Shaded relief. Strips the clutter and shows the "
                    "landform, which is useful when the AoR crosses a "
                    "meaningful break in terrain."),
]
for _name, _cap in _MAPS:
    figure(_name, _cap, width=6.0)

callout("These are static figures of a live map",
        "The same content is produced as an interactive HTML map that opens "
        "offline in any browser, with switchable basemaps, a layer switcher, "
        "a measuring tool and a popup on every well carrying its "
        "determination and modelled arrival year. Section 9 covers it. Send "
        "the HTML when you can; use these when the destination is a document.")
page_break()

# ==========================================================================
h(1, "0. How to read this guide")
p("This document takes a new user from nothing to a defensible Area of "
  "Review, corrective-action list and post-injection site care case. It is "
  "organised the way the work is done, not the way the software is written.")
rich(("Thirty minutes: ", True), "read sections 1, 2 and 5, then open the app "
     "and press Run on a shipped example.")
rich(("Preparing a permit: ", True), "read all of it, and give particular "
     "attention to 7.2 on the integrity warnings and 11 on where the tool "
     "should not be trusted.")
rich(("Reviewing someone else's submission: ", True), "sections 7.3, 7.4 and "
     "11 are where the arguments happen.")

callout("What this is not",
        "Containment is an engineering analysis, not a regulatory "
        "determination. The permitting authority decides the Area of Review. "
        "What this produces is a defensible, reproducible and fully disclosed "
        "basis for proposing one.")

h(2, "Contents")
for line in [
    "1.  What the tool does",
    "2.  Installing it, and the three ways to run it",
    "3.  The concepts, and the rule behind them",
    "4.  The project file, field by field",
    "5.  The worked example used throughout",
    "6.  Running it: browser, command line, library",
    "7.  Reading the results, panel by panel",
    "8.  Exports: what to hand to whom",
    "9.  The GIS map",
    "10. Importing someone else's simulation",
    "11. Where the tool should not be trusted",
    "12. Troubleshooting",
    "13. How this compares with EASiTool",
    "Appendix A. The complete project file",
    "Appendix B. Command-line reference",
    "Appendix C. Everything this run exercised",
    "Appendix D. Glossary",
]:
    par = p(line, size=10)
    par.paragraph_format.space_after = Pt(2)
    par.paragraph_format.left_indent = __import__("docx").shared.Inches(0.2)
page_break()

# ==========================================================================
h(1, "1. What the tool does")
p("A Class VI permit rests on three technical demonstrations. Containment "
  "produces all three from one project file, and keeps them consistent with "
  "each other because they come from the same model run.")

table([
    {"Demonstration": "Area of Review", "Rule": "40 CFR 146.84",
     "The question it answers":
         "How far could injected CO2 or displaced brine reach, and over what "
         "ground must artificial penetrations be found and assessed?"},
    {"Demonstration": "Corrective action", "Rule": "40 CFR 146.84(d)",
     "The question it answers":
         "Which old wells inside that ground could leak, what must be done to "
         "each, and in what order?"},
    {"Demonstration": "Post-injection site care", "Rule": "40 CFR 146.93",
     "The question it answers":
         "How long must the site be monitored after injection stops before "
         "non-endangerment can be demonstrated?"},
])

h(2, "1.1 What comes out")
for item in [
    "An AoR polygon as GeoJSON, KML, ESRI shapefile and CSV, with the plume "
    "and pressure-front components reported separately and a statement of "
    "which one controls the boundary.",
    "A corrective-action list: every artificial penetration with a "
    "determination, the reason for it, and a modelled arrival time that "
    "phases the work.",
    "A PISC case: plume stabilisation, migration rates, pressure decay, a "
    "defensible timeframe, and the 40 CFR 146.93(c) checklist.",
    "The AoR at every re-evaluation date 146.84(e) requires, with the acreage "
    "newly included at each one.",
    "A sensitivity study: which inputs move the answer, and how wide the "
    "answer is when they all move together.",
    "A self-contained HTML report, an interactive satellite map, and the "
    "project file plus gridded-field archive that reproduce the run.",
]:
    bullet(item)

h(2, "1.2 What it will not do")
for item in [
    "It will not size a storage project. There is no capacity estimate, no "
    "well-count optimisation and no economics. Section 13 says what to use "
    "for that.",
    "It will not replace a full-physics compositional simulator. It is a "
    "vertical-equilibrium model with an analytical cross-check, which is the "
    "right tool for delineation and the wrong one for, say, near-wellbore "
    "geochemistry.",
    "It will not make the regulatory decision, and it will not hide the "
    "choices you made. Every discretionary input appears in the report.",
]:
    bullet(item)
page_break()

# ==========================================================================
h(1, "2. Installing it, and the three ways to run it")

h(2, "2.1 The hosted app, with nothing to install")
code("https://containment.streamlit.app")
p("Use it to learn the tool, to try a variation quickly, or to show a result "
  "to someone who does not run Python. It is a public app, so do not put "
  "confidential operator data into it. For that, install locally and run the "
  "same app on your own machine, where nothing leaves your network.")

h(2, "2.2 Installing locally")
code('pip install containment\n\n'
     '# with everything: browser app, GIS map, shapefiles, interactive plots\n'
     'pip install "containment[full]"',
     "Python 3.10 or newer.")
table([
    {"Extra": "app", "Brings in": "streamlit, plotly, pandas",
     "Needed for": "the browser app and its interactive figures"},
    {"Extra": "gis", "Brings in": "pyproj, folium, pyshp",
     "Needed for": "the satellite map, exact coordinate transforms, shapefiles"},
    {"Extra": "full", "Brings in": "both of the above",
     "Needed for": "everything described in this guide"},
])
callout("CoolProp is a base dependency, deliberately",
        "CO2 density near the critical point is where a storage calculation "
        "lives, and the built-in cubic equation of state is about 40 percent "
        "wrong there. CoolProp is installed by default so nobody runs a "
        "shallow, cool site on the fallback without knowing it.")

h(2, "2.3 The command line")
code("containment run project.yaml --report out.html\n"
     "containment threshold project.yaml\n"
     "containment reevaluate previous.yaml current.yaml\n"
     "containment import simulation.csv --project project.yaml\n"
     "containment app",
     "The five subcommands. Appendix B has the full help text.")

h(2, "2.4 As a library")
code('from containment import workflow\n'
     'from containment.config import Project\n\n'
     'project = Project.from_yaml("project.yaml")\n'
     'res = workflow.run(project)\n\n'
     'print(res.aor.area_acres)                  # the AoR\n'
     'print(res.selected_threshold.summary())    # how the threshold was set\n'
     'for row in res.corrective.table():         # the corrective-action list\n'
     '    print(row["name"], row["action"])',
     "The library is what both the app and the CLI call, so all three give "
     "identical numbers.")
page_break()

# ==========================================================================
h(1, "3. The concepts, and the rule behind them")

h(2, "3.1 How an Area of Review is built")
p("EPA's rule is four steps, and the fourth is the one most often got wrong "
  "(816-R-13-005, Section 3.4, Box 3-2):")
for i, step in enumerate([
    "Compute the threshold pressure: the smallest injection-zone pressure "
    "buildup that could push formation fluid into the lowermost USDW through "
    "a hypothetical conduit open to both intervals.",
    "Map the maximum extent, over the whole simulation, of the pressure front "
    "defined by that threshold.",
    "Map the maximum extent, over the whole simulation, of the separate-phase "
    "CO2 plume.",
    "Take the geometric union of the two, direction by direction. Not the "
    "larger of the two areas, and not the pressure front alone, because "
    "separate-phase fluids may migrate beyond the extent of the pressure "
    "front.",
], 1):
    par = p(f"{i}. {step}")
    par.paragraph_format.left_indent = __import__("docx").shared.Inches(0.25)

callout("The two mistakes this tool is built to prevent",
        "First, taking the larger of the two areas instead of the union: the "
        "plume can reach ground the pressure front does not, and the reverse. "
        "Second, using a snapshot in time instead of the maximum over the "
        "project life: the pressure front peaks at shut-in while the plume "
        "keeps creeping updip for decades afterwards.")

h(2, "3.2 Why the threshold pressure matters more than anything else")
p("The threshold pressure is the largest discretionary lever in the whole "
  "delineation. Move it and the AoR moves with it. That is why this tool "
  "computes it from the site rather than asking you to type a number: it "
  "needs the lowermost USDW, the confining zone, and a fluid column between "
  "them. Four methods are computed, those that do not apply to the site's "
  "pressure regime are set aside, and the most protective survivor is chosen. "
  "All of them appear in the report so the choice can be argued on the record.")

h(2, "3.3 The vocabulary")
table([
    {"Term": "Threshold (critical) pressure",
     "What it means": "The pressure buildup in the injection zone that would "
                      "just lift formation fluid into the lowermost USDW "
                      "through an open conduit."},
    {"Term": "Pressure-front AoR",
     "What it means": "The contour where buildup equals that threshold. "
                      "Usually the larger component early in a project, and "
                      "it shrinks once injection stops."},
    {"Term": "Plume AoR",
     "What it means": "The footprint of free-phase CO2 at the disclosed "
                      "saturation cutoff. It never shrinks: it creeps updip "
                      "until residual trapping stops it."},
    {"Term": "USDW",
     "What it means": "Underground source of drinking water, under 10,000 "
                      "mg/L TDS and not exempted. The thing the whole "
                      "programme protects."},
    {"Term": "Corrective action",
     "What it means": "Repair or re-plugging of artificial penetrations "
                      "inside the AoR that could act as leakage conduits."},
    {"Term": "PISC",
     "What it means": "Post-injection site care. Fifty years by default, or "
                      "a shorter period if non-endangerment is demonstrated."},
    {"Term": "Vertical equilibrium",
     "What it means": "The assumption that CO2 and brine segregate quickly "
                      "compared with lateral flow, so only the map view has "
                      "to be stepped in time."},
], caption="Appendix D has the full glossary.")
page_break()

# ==========================================================================
h(1, "4. The project file, field by field")
p("One YAML file describes the site, the wells, the model and the analysis. "
  "It is the record of what was run, it is what 146.84(g) asks you to retain, "
  "and it is what a reviewer needs to reproduce your numbers. The browser "
  "app can build one for you and hand it back from the Export panel.")

h(2, "4.1 project")
code('project:\n'
     '  name: Coastal Bend Storage Hub\n'
     '  operator: Worked Example Storage LLC\n'
     '  permit: pending\n'
     '  datum: ground surface, depths positive downward\n'
     '  start_date: 2027-01-01      # model time is measured from here\n'
     '  crs:\n'
     '    epsg: 32615               # UTM zone 15N\n'
     '    x_offset: 408000.0\n'
     '    y_offset: 3320000.0')
p("`start_date` is optional but worth setting: with it, results carry real "
  "calendar dates as well as model years, which is how permits are written. "
  "`crs` pins the frame for exports and the GIS map. If you give wells in "
  "latitude and longitude, the frame is built for you and the UTM zone chosen "
  "automatically.")

h(2, "4.2 units")
p("Every number in the file is read in the units declared here, and every "
  "number in the output is written back in them. Mixing field and SI units "
  "across files is safe because nothing is assumed.")
code('units:\n'
     '  length: ft\n  depth: ft\n  pressure: psi\n  temperature: F\n'
     '  permeability: mD\n  rate: MMT/yr\n  brine_rate: bbl/day\n'
     '  time: yr\n  compressibility: 1/psi')

h(2, "4.3 formation")
p("Three intervals are required: the injection zone, the confining zone above "
  "it, and the lowermost USDW. The USDW is not decoration. Without it there "
  "is no threshold pressure, and without a threshold pressure there is no "
  "pressure-front AoR.")
code('formation:\n'
     '  injection_zone:\n'
     '    top_depth: 6000\n'
     '    thickness: 300            # NET sand, not gross interval\n'
     '    porosity: 0.24\n'
     '    permeability: 350\n'
     '    temperature: 155\n'
     '    salinity_ppm: 75000\n'
     '    initial_pressure: 2481    # measured, pre-injection\n'
     '    rock_compressibility: 6.0e-6\n'
     '    dip_degrees: 0.8\n'
     '    dip_azimuth: 135          # dips southeast, so CO2 goes northwest\n'
     '  confining_zone:\n'
     '    top_depth: 5600\n'
     '    base_depth: 6000\n'
     '  usdw:\n'
     '    base_depth: 1050\n'
     '    initial_pressure: 455\n'
     '    temperature: 82\n'
     '    salinity_ppm: 1200')

h(3, "Stacked zones: one wellbore, several formations")
p("An operator may complete one wellbore in two or more sands. That is not "
  "one thicker zone and cannot be modelled as one: each interval sits at its "
  "own depth and pressure, so CO2 has a different density in each, each earns "
  "its own threshold pressure against the same USDW, and each spreads "
  "differently. Give a list and each is delineated on its own, then unioned.")
code('formation:\n'
     '  injection_zones:\n'
     '    - name: Frio Upper\n'
     '      top_depth: 5200\n'
     '      thickness: 180\n'
     '      permeability: 280\n'
     '      initial_pressure: 2180\n'
     '      confining_zone: {top_depth: 4900, base_depth: 5200}\n'
     '    - name: Frio Lower\n'
     '      top_depth: 6000\n'
     '      thickness: 300\n'
     '      permeability: 350\n'
     '      initial_pressure: 2481\n'
     '      confining_zone: {top_depth: 5600, base_depth: 6000}')

h(2, "4.4 wells")
p("Wells take either local x/y in feet or latitude and longitude. Prefer "
  "latitude and longitude: the local frame is built around the well field "
  "automatically and the GIS map becomes available without you computing "
  "anything.")
code('wells:\n'
     '  - name: INJ-A1\n'
     '    latitude: 29.98\n'
     '    longitude: -94.13\n'
     '    rate: 0.9                 # MMT/yr\n'
     '    start_date: 2027-01-01\n'
     '    stop_date: 2052-01-01\n'
     '    max_bhp: 3100             # psi; checked, and reported\n\n'
     '  - name: INJ-B1              # a stepped schedule\n'
     '    latitude: 29.996773\n'
     '    longitude: -94.12242\n'
     '    schedule:\n'
     '      - {year: 4,  rate: 0.5}\n'
     '      - {year: 8,  rate: 1.1}\n'
     '      - {year: 20, rate: 0.6}\n'
     '      - {year: 25, rate: 0.0}\n\n'
     '  - name: EXT-1               # brine extraction, pressure management\n'
     '    latitude: 29.988524\n'
     '    longitude: -94.117682\n'
     '    kind: extractor\n'
     '    rate: 9000                # bbl/day\n'
     '    start_date: 2031-01-01\n'
     '    stop_date: 2052-01-01')
for item in [
    "`max_bhp` gives the well a pressure limit. Every run then reports the "
    "highest bottomhole pressure the model demanded of it and whether that "
    "fits, because an AoR computed from a rate that cannot be injected is not "
    "that project's AoR.",
    "`kind: extractor` makes a brine well. Extraction lowers pressure and can "
    "shrink the pressure-front AoR materially, which is the point of it.",
    "In a stacked project, add `zone: Frio Lower` to send a completion's whole "
    "rate to one interval. A well that names no zone is treated as commingled "
    "and its rate is split between zones in proportion to flow capacity k*h.",
]:
    bullet(item)

h(2, "4.5 threshold, faults, model, plume, penetrations, uncertainty")
code('threshold:\n'
     '  method: auto                # compute all, choose the most protective\n'
     '  mud_weight_ppg: 9.0\n'
     '  gel_strength: 10\n\n'
     'faults:\n'
     '  - name: Bend Fault\n'
     '    multiplier: 0.0           # 0 sealing, 1 open\n'
     '    latlon: [[30.012, -94.098], [29.975, -94.086]]\n\n'
     'model:\n'
     '  engine: ve                  # ve | analytical\n'
     '  boundary: constant_pressure # infinite | constant_pressure | noflow\n'
     '  end_year: 100\n'
     '  aor_reevaluation_years: 5   # 40 CFR 146.84(e)\n'
     '  grid:\n'
     '    cell_size: 500            # fine cells over the well field\n'
     '    fine_half_width: 18000\n'
     '    half_width: 85000         # telescoping outward to here\n\n'
     'plume:\n'
     '  cutoff: 0.02                # a disclosed choice, not a constant\n\n'
     'penetrations:\n'
     '  csv: examples/gulf_coast_wells.csv\n'
     '  coordinate_unit: ft\n\n'
     'uncertainty:\n'
     '  enabled: true\n  realisations: 120\n  spread: 0.5\n  seed: 42')

table([
    {"Choice": "engine: ve",
     "When to use it": "Always, for a permit. Handles dip, heterogeneity and "
                       "post-injection migration, which PISC needs."},
    {"Choice": "engine: analytical",
     "When to use it": "Screening and cross-checks. Fast, but no gravity "
                       "override and no migration after shut-in."},
    {"Choice": "boundary: infinite",
     "When to use it": "Default. Usually the conservative choice for pressure."},
    {"Choice": "boundary: constant_pressure",
     "When to use it": "A laterally extensive, well-connected aquifer."},
    {"Choice": "boundary: noflow",
     "When to use it": "A compartment bounded by sealing faults. Gives the "
                       "largest buildup, and pressure never dissipates, so be "
                       "careful using it for PISC."},
], caption="The two choices that change the answer most after the threshold.")
page_break()

# ==========================================================================
h(1, "5. The worked example used throughout")
p(f"Every figure and number in section 7 comes from one project: "
  f"{PROJ['name']}. It is synthetic, shaped like a Texas Gulf Coast project, "
  f"and built deliberately to put every part of the toolkit to work.")

table([
    {"Feature": "Injection zones", "This project":
        f"{len(PROJ['zones'])} stacked sands ({', '.join(PROJ['zones'])}), "
        "each with its own confining interval"},
    {"Feature": "Wells", "This project":
        f"{PROJ['injectors']} CO2 injectors on calendar-date schedules, one "
        f"of them stepped, plus {PROJ['extractors']} brine extractor for "
        "pressure management"},
    {"Feature": "Total CO2", "This project":
        f"{num(PROJ['total_mass_MMT'], '{:,.1f}')} million tonnes"},
    {"Feature": "Structure", "This project":
        "0.8 degrees of dip to the southeast, and one fully sealing fault to "
        "the northeast"},
    {"Feature": "Horizon", "This project":
        f"{num(PROJ['end_year'])} years, re-evaluated every "
        f"{num(PROJ['reevaluation_years'])}"},
    {"Feature": "Georeferencing", "This project":
        str(first(PROJ.get("crs", {}), "kind", default="local frame"))
        + (f", {PROJ.get('gis_note', '')}" if PROJ.get("gis_note") else "")},
    {"Feature": "Penetrations", "This project":
        f"{num(first(D['corrective'], 'wells_screened', 'n_wells', default=0))} "
        "artificial penetrations screened from a CSV of latitude/longitude"},
    {"Feature": "Uncertainty", "This project":
        "tornado plus a 120-realisation Latin-hypercube Monte Carlo"},
])
callout("Run it yourself",
        "The file is examples/showcase_full.yaml in the repository, and the "
        "penetration list is examples/gulf_coast_wells.csv. In the app, choose "
        "'Shipped example'. On the command line: containment run "
        "examples/showcase_full.yaml. Appendix A reproduces the whole file.")
page_break()

# ==========================================================================
h(1, "6. Running it: browser, command line, library")

h(2, "6.1 The browser app, step by step")
for i, step in enumerate([
    "Open containment.streamlit.app. Choose how to start: Form builds a "
    "project from the sidebar, Upload project YAML reloads one you exported, "
    "and Shipped example is the fastest way to see a finished run.",
    "Describe the site in the sidebar: injection zone, confining zone, USDW, "
    "relative permeability, threshold method, model and grid. Every field "
    "carries a tooltip explaining what it does to the answer. The defaults "
    "are a plausible Gulf Coast sand, not your site.",
    "Tick 'inject into more than one formation' if the wellbore is completed "
    "in several sands, and fill the zone table that appears.",
    "Enter the wells in the table. Latitude and longitude unlock the GIS map.",
    "Tick 'run uncertainty analysis' if you need the tornado and the "
    "probabilistic AoR, then press Run.",
    "Read the panels, then take what you need from the Export panel.",
], 1):
    par = p(f"{i}. {step}")
    par.paragraph_format.left_indent = __import__("docx").shared.Inches(0.25)
    par.paragraph_format.space_after = Pt(5)

h(2, "6.2 The command line")
code("containment run examples/showcase_full.yaml \\\n"
     "    --report report.html --output aor.geojson",
     "The same run that produced this guide.")
p("A run prints the headline numbers, every model-integrity warning, and the "
  "path to whatever it wrote. It exits non-zero if the project cannot be read, "
  "which makes it usable in a pipeline.")

h(2, "6.3 As a library")
p("Everything the app shows is on the result object. The pieces worth knowing:")
table([
    {"Attribute": "res.aor", "Holds":
        "the AoR, with .area_acres, .plume, .pressure_front and "
        ".controlling_component()"},
    {"Attribute": "res.zones", "Holds":
        "one entry per stacked injection zone, each with its own threshold "
        "and AoR"},
    {"Attribute": "res.series", "Holds":
        "the AoR at each re-evaluation date"},
    {"Attribute": "res.corrective", "Holds":
        "the screened penetrations, .table() and .phases()"},
    {"Attribute": "res.pisc", "Holds":
        "plume stabilisation, migration and the recommended timeframe"},
    {"Attribute": "res.uncertainty", "Holds":
        "the tornado and Monte Carlo objects"},
    {"Attribute": "res.well_pressure", "Holds":
        "the per-well bottomhole-pressure verdict"},
    {"Attribute": "res.warnings", "Holds":
        "every model-integrity item the run raised"},
])
page_break()

# ==========================================================================
# The rest of the guide lives in two more modules, purely so that no single
# file has to hold a hundred-page document. They are loaded by name rather
# than with `import`, because the order matters and an import sorter will
# happily alphabetise two imports and silently reorder the document.
# ==========================================================================
import importlib  # noqa: E402

for section in ("guide_results",     # 7 to 12: reading the results
                "guide_compare"):    # 13, and the appendices
    importlib.import_module(section)

path = os.path.join(OUT, "Containment_User_Guide.docx")
doc.save(path)
print(f"wrote {path}")
print(f"   {len(doc.paragraphs)} paragraphs, {len(doc.tables)} tables, "
      f"{len(doc.inline_shapes)} figures embedded")
