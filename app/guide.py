"""Help text for the browser app.

Three kinds of help live here, kept out of ``streamlit_app`` so that file
stays readable as a layout:

``FIELD``   one-line tooltips, hung off every input the user can turn.
``LEAD``    a short "what am I looking at" note at the top of each result tab.
``render`` draws the Help panel: quick start, glossary, limits, troubleshooting.

The wording assumes a permit engineer who knows the rule but not this tool.
Anything that is a modelling choice rather than a fact says so, because the
number a reviewer argues about is almost always a choice made here.
"""

from __future__ import annotations

import streamlit as st

# --------------------------------------------------------------------------
# tooltips
# --------------------------------------------------------------------------
FIELD = {
    # ---- injection zone
    "iz_top": "Depth to the top of the injection zone, below ground surface. "
              "Sets the pressure and temperature the CO2 sees, and so its "
              "density.",
    "iz_h": "Net thickness that actually accepts CO2, not gross interval. "
            "The AoR scales roughly with the inverse of this: a thin zone "
            "spreads the same tonnage further.",
    "iz_phi": "Effective porosity of the net interval, as a fraction. Pore "
              "volume sets how far the plume has to travel to store the "
              "injected mass.",
    "iz_k": "Horizontal permeability of the injection zone. Drives the "
            "pressure buildup: lower permeability means a larger "
            "pressure-front AoR for the same rate.",
    "iz_t": "Formation temperature at injection depth. With pressure, it "
            "fixes CO2 density and viscosity through the equation of state.",
    "iz_s": "Formation brine salinity as total dissolved solids. Sets brine "
            "density and viscosity, and so the buoyancy contrast with CO2.",
    "iz_p": "Pre-injection (virgin) reservoir pressure at the datum. The "
            "buildup that matters for the AoR is measured from this.",
    "iz_cr": "Pore-volume compressibility of the rock. With brine "
             "compressibility it sets total storativity, which controls how "
             "fast pressure spreads.",
    "iz_dip": "Structural dip of the injection zone. Dip drives updip "
              "migration after injection stops, which is what usually decides "
              "the PISC timeframe.",
    "iz_az": "Compass direction the formation dips toward, in degrees from "
             "north. CO2 migrates in the opposite direction (updip).",
    # ---- confining zone and USDW
    "cz_top": "Top of the primary confining zone (the caprock). Used for the "
              "threshold-pressure calculation and for screening which "
              "artificial penetrations breach the seal.",
    "cz_base": "Base of the primary confining zone, normally the top of the "
               "injection zone.",
    "usdw_base": "Depth to the base of the lowermost underground source of "
                 "drinking water. This is the interval 40 CFR 146.84 asks you "
                 "to protect, and the separation from it drives the "
                 "non-endangerment case.",
    "usdw_p": "Pressure in the lowermost USDW. With its depth, this sets the "
              "hydraulic head that formation fluid would have to overcome to "
              "reach the USDW.",
    "usdw_t": "Temperature in the lowermost USDW, for the fluid-density "
              "column used in the threshold calculation.",
    "usdw_s": "Salinity of the lowermost USDW. Under 10,000 ppm TDS is the "
              "regulatory definition of a USDW.",
    # ---- relative permeability
    "swr": "Irreducible brine saturation. Raising it shrinks the pore space "
           "available to CO2 and pushes the plume further out.",
    "sgr": "Residual CO2 saturation: the fraction left behind and trapped as "
           "the plume passes. The single most important control on whether "
           "the plume stops moving during PISC.",
    "krg0": "CO2 relative permeability at its end point. Higher values let "
            "CO2 move more freely against brine.",
    "corey": "Brooks-Corey exponent used for both phases. Higher exponents "
             "mean sharper, more piston-like displacement.",
    # ---- threshold pressure
    "method": "How the critical pressure buildup is computed. 'auto' runs "
              "every method, discards those that do not apply to this "
              "pressure regime, and takes the most protective survivor. "
              "Methods 1 and 2 follow EPA 816-R-13-005.",
    "ppg": "Drilling-mud weight assumed to be standing in an offset "
           "penetration, for the mud-column variant of the threshold "
           "calculation.",
    "gel": "Gel strength of that mud column, the extra pressure needed to "
           "break it into motion.",
    # ---- model
    "engine": "ve = vertical-equilibrium numerical solver: handles dip, "
              "heterogeneity and post-injection migration, and is what PISC "
              "needs. analytical = superposition of closed-form solutions: "
              "fast, but no gravity override and no migration after shut-in.",
    "boundary": "infinite acts as if the aquifer never ends (usually the "
                "conservative choice for pressure). constant_pressure "
                "represents an open, strongly connected aquifer. noflow "
                "represents sealing faults and gives the largest buildup.",
    "cell": "Fine-grid cell size near the wells. Smaller resolves the plume "
            "edge better and costs runtime; the run warns you if the AoR is "
            "resolved by too few cells.",
    "half": "Half-width of the modelled domain. It must comfortably exceed "
            "the pressure front, or the boundary condition contaminates the "
            "answer. The run warns you when it is too tight.",
    "end_year": "How far past the start of injection to simulate. It has to "
                "run well beyond the end of injection for the plume to "
                "stabilise, which is what the PISC demonstration rests on.",
    "cutoff": "Column-averaged CO2 saturation that counts as 'plume'. A "
              "defensible, disclosed choice, not a physical constant: "
              "lowering it grows the plume AoR.",
    # ---- run controls
    "uncertainty": "Adds a one-at-a-time tornado plus a Latin-hypercube Monte "
                   "Carlo, giving a probabilistic AoR. 40 CFR 146.93(c)(2)(vi) "
                   "requires a sensitivity analysis to support an alternative "
                   "PISC timeframe.",
    "realisations": "Monte Carlo sample count. 150 is enough for a stable "
                    "P10/P50/P90; more tightens the tails and costs runtime.",
    # ---- wells and other panels
    "wells": "Rates are million tonnes of CO2 per year. start_year and "
             "stop_year are measured from the start of the simulation, so a "
             "well can come on late or stop early.",
    "basemap": "Satellite imagery is the one to send to a landman. "
               "Topographic and shaded relief help when the argument is about "
               "surface access or drainage.",
    "pens_unit": "Unit for the x, y and depth columns in the uploaded CSV. "
                 "Everything is converted internally.",
    "georef": "Attach a coordinate reference system so the GeoJSON and KML "
              "land in the right place in GIS. An EPSG code is exact; an "
              "origin longitude and latitude is a local approximation that "
              "degrades with distance from that origin.",
    "epsg": "Projected CRS of the model's local frame. Texas State Plane and "
            "UTM zone 14N (EPSG:32614) cover most of the state. Check the "
            "units: several Texas codes are in US survey feet, not metres.",
}

# --------------------------------------------------------------------------
# panel leads
# --------------------------------------------------------------------------
LEAD = {
    "aor": "The <b>Area of Review</b> is the union of two footprints: where "
           "free-phase CO2 goes, and where pressure builds enough that "
           "formation fluid could reach a USDW through an open conduit. "
           "Whichever is larger controls, and the dashed outline is the "
           "union. Background shading is the maximum pressure buildup each "
           "location ever sees.",
    "gis": "The same delineation on real imagery, georeferenced from the well "
           "latitudes and longitudes. Toggle layers at the top right, and "
           "download a standalone copy to send to someone without this app.",
    "threshold": "The <b>threshold pressure</b> is the buildup above which "
                 "formation fluid could be driven into the lowermost USDW. It "
                 "is the largest discretionary lever in the whole "
                 "delineation, so every method is shown, not just the chosen "
                 "one. Hatched bars do not apply to this pressure regime and "
                 "are excluded from the automatic choice.",
    "pisc": "<b>Post-injection site care.</b> The default under 40 CFR 146.93 "
            "is 50 years. A shorter timeframe has to be earned with a "
            "demonstration that the plume has stopped moving and pressure has "
            "fallen below the threshold. The checklist at the bottom tracks "
            "what that demonstration still needs.",
    "corrective": "Artificial penetrations through the confining zone are the "
                  "realistic leakage pathway. Upload a well list and each one "
                  "is screened against the AoR, the seal, and the modelled "
                  "arrival time of pressure and of CO2, which is what phases "
                  "the corrective-action schedule.",
    "uncertainty": "Which inputs actually move the AoR, and how wide the "
                   "answer is when they move together. The tornado ranks them "
                   "one at a time; the Monte Carlo samples them jointly.",
    "export": "Everything on this page, in formats a reviewer or a GIS can "
              "open. 40 CFR 146.84(g) requires the modelling inputs behind an "
              "AoR delineation to be retained for ten years: the project YAML "
              "plus the field archive is that record.",
    "help": "How to drive this tool, what the words mean, and where it should "
            "not be trusted.",
}

# --------------------------------------------------------------------------
# glossary
# --------------------------------------------------------------------------
GLOSSARY = [
    ("Area of Review (AoR)",
     "The region around an injection well where formation fluids could be "
     "driven into a USDW. Under 40 CFR 146.84 it is delineated by computational "
     "modelling and re-evaluated at least every five years."),
    ("Pressure-front AoR",
     "The contour where pressure buildup equals the threshold pressure. It is "
     "usually larger than the plume early in a project, and it shrinks once "
     "injection stops."),
    ("Plume AoR",
     "The footprint of free-phase (supercritical) CO2, taken here at the "
     "column-averaged saturation cutoff you set. Unlike pressure, it never "
     "shrinks: it keeps creeping updip until it is residually trapped."),
    ("Threshold (critical) pressure",
     "The pressure buildup in the injection zone that would just lift "
     "formation fluid into the lowermost USDW through a hypothetical open "
     "conduit. Computed here by the EPA 816-R-13-005 methods."),
    ("USDW",
     "Underground source of drinking water: an aquifer with less than "
     "10,000 mg/L total dissolved solids that is not exempted. The thing the "
     "whole programme exists to protect."),
    ("Confining zone",
     "The sealing interval above the injection zone. Its integrity is what "
     "makes the pressure-front criterion, rather than direct leakage, the "
     "governing concern."),
    ("Post-injection site care (PISC)",
     "Monitoring after injection stops, 50 years by default under "
     "40 CFR 146.93, until a non-endangerment demonstration is approved."),
    ("Non-endangerment demonstration",
     "The showing that the plume and pressure front have stabilised such that "
     "no further USDW endangerment is expected. Required to shorten PISC or "
     "close the site."),
    ("Corrective action",
     "Repair or re-plugging of artificial penetrations inside the AoR that "
     "could act as leakage conduits, under 40 CFR 146.84(d)."),
    ("Vertical equilibrium (VE)",
     "A modelling assumption that CO2 and brine segregate quickly compared "
     "with lateral flow, so the vertical saturation profile can be solved "
     "analytically and only the map view is stepped in time. Fast enough to "
     "run in a browser, and accurate for thin, well-connected zones."),
    ("Superposition (analytical engine)",
     "Closed-form pressure solutions summed over wells and time. No gravity "
     "override, no post-injection migration, so it is a cross-check and a "
     "Monte Carlo workhorse rather than a PISC tool."),
    ("Residual trapping (Sgr)",
     "CO2 left immobile behind the trailing edge of the plume. It is what "
     "eventually halts migration, and the PISC timeframe is highly sensitive "
     "to it."),
    ("Boundary condition",
     "How the model treats the edge of the domain: infinite, constant "
     "pressure (open aquifer), or no-flow (sealing faults). No-flow gives the "
     "largest buildup and the largest pressure-front AoR."),
    ("Plume cutoff",
     "The saturation that counts as plume edge. A disclosed modelling choice: "
     "state it in the permit, because a reviewer can and will ask."),
    ("Tornado / Monte Carlo",
     "One-at-a-time sensitivity ranking, and joint random sampling. Together "
     "they answer 'what moves the answer' and 'how wide is the answer'."),
    ("Stabilisation",
     "The plume no longer expanding and pressure decaying below the "
     "threshold. Demonstrating it is the precondition for shortening PISC."),
]


# --------------------------------------------------------------------------
def render() -> None:
    """Draw the Help panel."""
    st.markdown("### Getting a result in five steps")
    st.markdown(
        "1. **Pick a starting point** at the top of the page. *Shipped "
        "example* is the fastest way to see a finished run; *Form* builds a "
        "project from the sidebar; *Upload project YAML* reloads a project "
        "you exported earlier.\n"
        "2. **Describe the site** in the sidebar: injection zone, confining "
        "zone, USDW, relative permeability. Every field carries a tooltip "
        "explaining what it does to the answer. Defaults are a plausible "
        "Gulf Coast sandstone, not your site.\n"
        "3. **Enter the wells** in the table. Latitude and longitude unlock "
        "the GIS map; plain x/y in feet also works if you would rather not "
        "georeference.\n"
        "4. **Press Run.** Tick *run uncertainty analysis* first if you need "
        "the tornado and the probabilistic AoR.\n"
        "5. **Read the panels, then export.** The Export tab produces the "
        "GeoJSON, KML, HTML report and project YAML that constitute the "
        "record of what was run.")

    st.markdown("### What each panel is for")
    for label, key in (("AoR map", "aor"), ("GIS map", "gis"),
                       ("Threshold", "threshold"), ("PISC", "pisc"),
                       ("Corrective action", "corrective"),
                       ("Uncertainty", "uncertainty"), ("Export", "export")):
        st.markdown(
            f"<div class='aor-term'><dt>{label}</dt>"
            f"<dd>{LEAD[key]}</dd></div>", unsafe_allow_html=True)

    st.markdown("### Glossary")
    st.caption("Terms as 40 CFR 146 and EPA 816-R-13-005 use them.")
    left, right = st.columns(2)
    half = (len(GLOSSARY) + 1) // 2
    for col, chunk in ((left, GLOSSARY[:half]), (right, GLOSSARY[half:])):
        with col:
            for term, definition in chunk:
                st.markdown(
                    f"<div class='aor-term'><dt>{term}</dt>"
                    f"<dd>{definition}</dd></div>", unsafe_allow_html=True)

    st.markdown("### Where this tool should not be trusted")
    st.warning(
        "**Thick injection zones.** The vertical-equilibrium engine assumes "
        "CO2 and brine segregate faster than they flow sideways. Validated "
        "against operator AoR figures it lands within about 2 percent on a "
        "250 ft zone, but runs 1.5 to 1.8 times wide on a 1,200 to 2,000 ft "
        "shale-punctuated interval. Treat a thick-zone AoR as a conservative "
        "upper bound and cross-check it against a full-physics simulator.")
    st.warning(
        "**Monte Carlo areas are not the base-case area.** The uncertainty "
        "run uses the fast analytical engine, so its absolute AoR areas are "
        "not comparable with a VE-engine result. Read the ratios and the "
        "ranking, not the raw acreage.")
    st.info(
        "**This is an engineering analysis, not a regulatory determination.** "
        "The permitting authority decides the AoR. What this tool produces is "
        "a defensible, reproducible, fully disclosed basis for proposing one.")

    st.markdown("### If something looks wrong")
    st.markdown(
        "- **The GIS map tab says it needs coordinates.** The wells were "
        "entered as x/y rather than latitude and longitude, so there is "
        "nothing to georeference against.\n"
        "- **A model-integrity item appears above the panels.** That is the "
        "run checking itself: domain too small for the pressure front, AoR "
        "resolved by too few cells, boundary influencing the answer, mass "
        "balance drifting, or a threshold method being applied outside its "
        "pressure regime. Fix the flagged input and run again rather than "
        "reporting the number.\n"
        "- **The plume has not stopped moving.** Raise *simulation end "
        "(years)* until it does. A PISC timeframe cannot be claimed from a "
        "run that ends while the plume is still migrating.\n"
        "- **The app says it has gone over its resource limits.** The public "
        "host allows about 2.7 GB. Shrink the domain half-width, coarsen the "
        "cell size, or run it locally.\n"
        "- **The page was asleep when you arrived.** Apps on the free host "
        "hibernate after 12 hours without traffic and take under a minute to "
        "wake.")

    st.markdown("### Running it yourself")
    st.markdown(
        "The whole toolkit is open source under Apache-2.0 at "
        "[github.com/Kouroshie/aor-pisc-toolkit]"
        "(https://github.com/Kouroshie/aor-pisc-toolkit). "
        "`pip install aorpisc` gives you the same engines behind a CLI "
        "(`aorpisc run project.yaml`), which is the route to take for large "
        "domains, batch runs, or anything that should not leave your network.")
