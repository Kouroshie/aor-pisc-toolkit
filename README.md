# Containment

Open-source Python toolkit for the three technical demonstrations behind a UIC
**Class VI** permit: delineating the **Area of Review (AoR)**, sizing the
**corrective-action** list for artificial penetrations, and testing a
**post-injection site care (PISC)** timeframe. For geologic carbon storage
projects, following
[40 CFR 146.84 / 146.93](https://www.ecfr.gov/current/title-40/chapter-I/subchapter-D/part-146/subpart-H)
and EPA's *Class VI Well Area of Review Evaluation and Corrective Action
Guidance* ([816-R-13-005](https://www.epa.gov/uic/class-vi-guidance-documents), May 2013).

It runs as a Python library, a command-line tool, and a browser app.

```bash
pip install "containment[full]"
containment run examples/epa_hypothetical_site.yaml -o out/
```

---

## What it does

| Stage | What you get |
|---|---|
| **Fluid properties** | CO2 density/viscosity (Span-Wagner via CoolProp, or a built-in Spycher-Pruess RK EOS + Fenghour correlation), brine density/viscosity/compressibility (Batzle-Wang) |
| **Threshold pressure** | Four methods side by side - Thornhill/EPA Method 1, Nicot uniform-density (Method 2), a variable-density column integration, and the TCEQ/Class I static mud column + gel strength - plus explicit handling of the over-pressurised case |
| **Flow modelling** | (a) analytical superposition - Theis + image wells + radial Buckley-Leverett + two-phase apparent skin; (b) a vertical-equilibrium two-phase numerical solver on a heterogeneous, dipping, faulted grid; (c) import of your existing CMG / ECLIPSE / TOUGH2 output |
| **AoR delineation** | Union of the maximum-over-time plume and the maximum-over-time pressure front, exported as GeoJSON / KML / CSV, with extent-by-azimuth tables |
| **Stacked injection zones** | One wellbore completed in several formations: each zone delineated on its own terms, with its own fluids, its own threshold pressure and its own AoR, and the project AoR taken as the **geometric union** |
| **AoR through time** | The AoR at every re-evaluation date under 40 CFR 146.84(e), with the acreage newly included at each one - the ground that becomes subject to corrective action |
| **Corrective action** | EPA's Figure 4-3 decision tree applied to every penetration, **plus phased corrective action scheduled by modelled arrival time** |
| **PISC** | Plume area, expansion rate, effective-radius migration rate, directional migration, pressure decline, plume-stabilisation year, a defensible PISC duration, and the 40 CFR 146.93(c) checklist |
| **Uncertainty** | Tornado sensitivity and a Latin-hypercube Monte Carlo producing a **probabilistic AoR** (P10 / P50 / P90 boundaries) |
| **GIS map** | A self-contained HTML map on switchable satellite / street / topographic / relief basemaps, with the AoR, both components and every artificial penetration colour-coded by required action, a measuring tool, and popups carrying each well's determination and its modelled arrival year. No API key, no account, opens offline |
| **Exports** | GeoJSON, KML, **ESRI shapefile (.zip)**, CSV, gridded-field archive, and the project YAML that reproduces the run |
| **Well pressure check** | Highest bottomhole pressure per well against its declared limit, with a verdict, so an uninjectable schedule is caught before its AoR is believed |
| **Reporting** | One self-contained HTML report, organised the way an AoR & Corrective Action Plan and a PISC & Site Closure Plan are organised, with the regulatory citation on every section |

---

## How this compares with EASiTool

[EASiTool 5.1](https://gccc.beg.utexas.edu/easitool) (Gulf Coast Carbon Center,
UT Austin) is the tool this one gets compared with, it is good at what it does,
and this toolkit shares its analytical lineage (Mathias et al. 2011;
Buckley-Leverett fronts; superposition of pressure buildup). The comparison
below was made by running EASiTool 5.1 on its own input template in September
2026, not from its documentation.

The two tools answer different questions. **EASiTool sizes a project**: how
much CO2 fits, how many wells it takes, what it is worth. **This one builds
the permit demonstrations**: where the Area of Review is, which wells have to
be fixed, and how long the site must be watched afterwards.

| | EASiTool 5.1 | containment |
|---|---|---|
| Purpose | storage capacity, well-count optimisation, NPV | AoR delineation, corrective action, PISC demonstration |
| **Threshold pressure** | **an input you type** (template default 2 MPa, adjustable by slider) | **computed** by four EPA/TCEQ methods, compared, with pressure-regime checks |
| USDW and confining zone | not represented in the input file | required inputs; the threshold is derived from them |
| AoR | evaluated **at a selected timestep**, from the pressure field | **maximum extent over the project lifetime** [EPA Section 3.4], plume and pressure front unioned, each reported separately |
| Plume | a radius per well | a contoured field: merged plumes, dip-driven migration, residual trapping |
| Geometry | one homogeneous reservoir area, net sand capped at 500 m | full fields of permeability, porosity, thickness and top structure, arbitrary domain |
| Stacked zones | not supported (the template says to split thick intervals and run them separately) | modelled per zone, each with its own threshold, and unioned |
| Faults | a trace, no properties | traces with transmissibility multipliers |
| Boundaries | open, closed | infinite, constant-pressure, no-flow |
| Post-injection | pressure relaxes; no migration physics | vertical-equilibrium buoyant migration with residual trapping, centuries if needed |
| AoR through time | a timestep slider | delineation at every 146.84(e) re-evaluation date, with the acreage newly included at each |
| Corrective action | none | EPA Figure 4-3 decision tree, phased by modelled arrival time |
| PISC | none | 146.93 metrics, stabilisation year, defensible timeframe, (c) checklist |
| Sensitivity | tornado over ~14 inputs on mean reservoir pressure; Monte Carlo on capacity | tornado over 12 inputs **on AoR area**, Latin-hypercube Monte Carlo, probabilistic AoR as a map |
| Model-integrity checks | none reported | domain size, grid resolution, boundary influence, mass balance, threshold applicability |
| Economics | NPV, capex/opex, 45Q credit, discount rate | none |
| Storage capacity | yes, under fixed BHP | not computed |
| Well optimisation | capacity and NPV against number of injectors | none |
| Well pressure check | per-well pass/fail against a limit | per-well pass/fail against a limit |
| GIS output | interactive map, shapefile | interactive map on switchable basemaps, GeoJSON, KML, **shapefile**, CSV |
| Input | one Excel template, SI or field units | YAML project file, any unit system, or a CSV/simulator import |
| Access | web app, sign-in, alpha | `pip install containment`, library + CLI + web app, Apache-2.0, 155 tests in CI |

**Where EASiTool is the better choice.** If the question is *how much can we
store, with how many wells, and does it pay*, EASiTool answers it directly and
this toolkit does not answer it at all. Its Excel front end is also friendlier
to anyone who does not want to edit YAML.

**Where this one is.** A Class VI Area of Review is not a pressure contour at a
chosen date and a threshold someone typed in. It is the maximum extent over the
project lifetime of whichever is larger, plume or pressure front, against a
threshold derived from the USDW you are protecting. That derivation needs a
USDW, a confining zone and a fluid column, none of which EASiTool asks for.
Everything downstream of the AoR -- the corrective-action list, the PISC
timeframe, the re-evaluation schedule -- follows from it.

Four things were added to this toolkit after that side-by-side: shapefile
export, per-well bottomhole-pressure verdicts, calendar dates on schedules and
results, and a sensitivity study that varies fluid properties, relative
permeability and the threshold pressure rather than only the four storage
properties. Credit where due.

A last point that is not a feature comparison. EPA notes that proprietary codes
"may prevent full evaluation of model results" and encourages operators to
disclose code assumptions and governing equations. Everything here is readable,
every equation carries its citation in the docstring, and a reviewer can re-run
the operator's own numbers under different assumptions in seconds.

---

## Quick start

### Command line

```bash
# full workflow: threshold, model, AoR, corrective action, PISC, HTML report
containment run examples/epa_hypothetical_site.yaml -o out/

# just the threshold pressure, every method, with its inputs and citations
containment threshold examples/epa_hypothetical_site.yaml

# re-delineate an AoR from somebody else's simulator output
containment import sim_export.csv --dp-col PRESSURE --absolute-pressure \
    --initial-pressure 2481 --plume-col SGAS --plume-cutoff 0.01 \
    --threshold 313 --length-unit ft -o aor.geojson

# AoR reevaluation: difference two delineations [40 CFR 146.84(e)]
containment reevaluate year0.yaml year5.yaml -o out/

# browser app
containment app
```

### Python

```python
from containment.config import Project
from containment import workflow, report

project = Project.from_yaml("my_site.yaml")
result  = workflow.run(project)

print(result.aor.summary()["aor_area_acres"])
print(result.pisc.recommended_timeframe()["verdict"])
report.write_html(result, "aor_report.html")
```

### Threshold pressure on its own

```python
from containment import threshold, fluids, units as U

results = threshold.compare_methods(
    p_usdw=U.pressure(289, "psi"),
    p_inj=U.pressure(1817, "psi"),
    depth_usdw=U.length(1217, "ft"),
    depth_inj=U.length(5862, "ft"),
    temperature_inj=U.temperature(140, "F"),
    temperature_usdw=U.temperature(80, "F"),
    salinity_inj=fluids.salinity_to_mass_fraction(150_000, "ppm"),
)
for r in results:
    print(r)
```

---

## The project file

One YAML file fully describes a run - which is also how 40 CFR 146.84(g)
(retain modelling inputs for ten years) and EPA Section 3.5 ("all necessary
information ... to replicate the computational modeling exercise") get
satisfied. Values are written in permit units (`psi`, `ft`, `mD`, `MMT/yr`)
and converted once on the way in.

```yaml
project:
  name: My Storage Hub
  datum: ground surface, depths positive downward

units: { length: ft, depth: ft, pressure: psi, temperature: F, rate: MMT/yr }

formation:
  injection_zone:
    top_depth: 6000
    thickness: 300
    porosity: 0.18
    permeability: 120           # mD
    temperature: 150            # degF
    salinity_ppm: 90000
    initial_pressure: 2481      # psi
    rock_compressibility: 5.0e-6
    dip_degrees: 0.6
    dip_azimuth: 200
  confining_zone: { top_depth: 5700, base_depth: 6000 }
  usdw:          { base_depth: 1200, initial_pressure: 520, temperature: 80,
                   salinity_ppm: 800 }

relative_permeability:
  model: brooks_corey
  swr: 0.35
  sgr: 0.20
  krg0: 0.30
  m: 3.0
  n: 3.0

threshold:
  method: auto                  # auto | method1 | method2 | method2b | mud_column
  mud_weight_ppg: 9.0
  gel_strength: 10              # psi

wells:
  - { name: INJ-1, x: 0,    y: 0, rate: 1.0, start_year: 0, stop_year: 20 }
  - { name: INJ-2, x: 3000, y: 0, rate: 1.0, start_year: 2, stop_year: 22 }

model:
  engine: ve                    # analytical | ve
  grid: { nx: 141, ny: 141, cell_size: 500 }
  boundary: constant_pressure
  end_year: 100

plume: { cutoff: 0.01, criterion: "column-averaged CO2 saturation >= 0.01" }

penetrations: { csv: legacy_wells.csv, coordinate_unit: ft }

uncertainty: { enabled: true, realisations: 200, spread: 0.5 }
```

See [`docs/input_schema.md`](docs/input_schema.md) for every field.

### Shipped examples

| file | what it exercises | runtime |
|---|---|---|
| [`examples/epa_hypothetical_site.yaml`](examples/epa_hypothetical_site.yaml) | EPA's own hypothetical site from Box 3-1 of 816-R-13-005: three injectors, 2 MMT/yr for 30 years, a telescoping grid, 200 years of post-injection migration, and a legacy-well list through the corrective-action screen | ~15 s |
| [`examples/gulf_coast_hub.yaml`](examples/gulf_coast_hub.yaml) | a synthetic Texas-style hub: staggered four-well start-up, brine extraction for pressure management, the TCEQ mud-column threshold, a georeferenced UTM export, and the Monte Carlo uncertainty run | ~4 min |

The second one lands on a case worth seeing: with a mud-column threshold of
334 psi the pressure front never forms, so the AoR is the plume alone. That is
a legitimate and fairly common outcome in Texas applications, and the toolkit
says so explicitly rather than quietly returning an empty polygon.

---

## How the AoR is built

EPA's rule is four steps, and the fourth is the one most often got wrong:

1. compute the threshold pressure - the minimum injection-zone pressure that
   would push fluid into a USDW through a hypothetical conduit perforated in
   both intervals;
2. map the **maximum-over-time** extent of the pressure front;
3. map the **maximum-over-time** extent of the separate-phase plume;
4. take the **geometric union** of the two - direction by direction, not the
   larger of the two areas. "Separate-phase fluids may migrate beyond the
   extent of the pressure front" (EPA Section 3.4, Box 3-2).

The toolkit reports both components separately, says which one controls the
boundary and by how much, and refuses to be quiet about the checks that make
the answer meaningful: domain size against boundary influence, grid resolution
against plume radius, CO2 mass balance, and whether the threshold method you
picked is even applicable to your pressure regime.

### Injecting into more than one formation

An operator may complete one wellbore in two or more zones. That is a
different project from one well in a thicker single zone and cannot be
modelled as one: each zone sits at its own depth and pressure, so CO2 has a
different density in each, each gets its own threshold pressure measured
against the same USDW, and each spreads differently because k, h and porosity
differ.

List the zones and the toolkit runs the whole delineation once per zone, then
unions the results:

```yaml
formation:
  injection_zones:
    - name: Frio A
      top_depth: 5200
      thickness: 180
      permeability: 220
      initial_pressure: 2250
      confining_zone: {top_depth: 5000, base_depth: 5200}
    - name: Frio B
      top_depth: 6000
      thickness: 250
      permeability: 150
      initial_pressure: 2600
      confining_zone: {top_depth: 5700, base_depth: 6000}
```

Two consequences worth stating in a permit:

- **The project AoR is not the sum of the zone AoRs.** Stacked zones overlap
  heavily, so adding acreages overstates the AoR by something approaching the
  number of zones. The result reports the union, the sum and the overlap.
- **A different zone can control in different directions**, so the union has a
  shape that neither zone has on its own. That shape is what gets mapped and
  screened for penetrations.

Where a well row names a `zone`, its whole rate goes there. Where it names
none, the completion is treated as commingled and the rate is split between
zones in proportion to flow capacity `k*h` - an assumption, flagged as one,
and replaceable with a measured zonal allocation by giving one well row per
zone.

Worked example: `examples/stacked_zones.yaml`.

### The AoR at each re-evaluation

40 CFR 146.84(e) requires the AoR to be re-evaluated at least every five
years, and each re-evaluation asks whether it has expanded into ground that
has not been screened. Every run therefore carries a series of delineations on
that cadence:

```python
res = workflow.run(project)
for row in delineate.series_growth(res.series):
    print(row["year"], row["area_acres"], row["newly_included_acres"])
```

Each snapshot is delineated from the maximum-over-time fields **up to that
date**, which is the AoR a reviewer would approve if the project were
evaluated then, and `newly_included_acres` is exactly the area
146.84(e)(2)-(3) makes subject to artificial-penetration identification and
corrective action. `delineate.aor_series(..., mode="instantaneous")` contours
each date on its own instead, which shows the pressure front relaxing after
shut-in but is not an AoR in the regulatory sense.

Set the cadence with `model.aor_reevaluation_years` (default 5).

---

## Model integrity checks

Results carry warnings rather than assuming the user will notice. Among them:

- the AoR boundary reaching the edge of the model domain, or filling more than
  40 % of it (EPA Section 3.3.3.2);
- pressure buildup on the model boundary as a fraction of the threshold  - 
  a no-flow edge that is too close inflates the pressure front, a
  constant-pressure edge truncates it;
- fewer than ~20 grid cells across the plume (EPA Section 2.2.7 on coarse
  grids misrepresenting buoyancy-driven flow);
- CO2 mass-balance error in the VE solver;
- a threshold method being applied outside the pressure regime EPA restricts
  it to;
- post-injection output times spaced so far apart that migration rates are
  long-interval averages;
- a fully closed domain, which never lets pressure dissipate, being used for
  PISC work;
- penetrations inside the AoR with no recorded total depth
  [40 CFR 146.84(c)(2)].

---

## Validation

Run `pytest`. The suite checks, among other things:

- the Nordbotten-Celia interface profile integrates to **exactly** the
  injected volume;
- the VE solver conserves CO2 mass to machine precision, and its radial
  interface profile converges toward the Nordbotten-Celia analytical solution
  as the grid refines;
- closed-system pressurisation in the VE solver matches the compressibility
  volume balance `dP = dV / (V_pore . c_t)`;
- Theis superposition reproduces the exponential-integral solution;
- EPA Method 1 reproduces a published Class VI application's threshold
  pressure (714 psi at a published Class VI applicant's the first injector) to the psi;
- EPA Method 2's numerical variable-density variant collapses to Eq-3 for a
  constant-density column;
- Buckley-Leverett Welge construction, unit round-trips, image-well
  symmetry, polygon union arithmetic, and the corrective-action decision tree.

See [`docs/validation.md`](docs/validation.md).

---

## Documentation

- [`docs/methods.md`](docs/methods.md) - every equation, its assumptions, and its citation
- [`docs/input_schema.md`](docs/input_schema.md) - the project file, field by field
- [`docs/validation.md`](docs/validation.md) - what is tested and against what
- [`docs/importing.md`](docs/importing.md) - reading CMG / ECLIPSE / TOUGH2 output

---

## Running it in a browser, hosted

The repository is ready to deploy to [Streamlit Community
Cloud](https://share.streamlit.io) (free), which gives anyone a URL and
requires no Python install on their side:

1. sign in at <https://share.streamlit.io> with the GitHub account that owns
   this repository;
2. **Create app** -> **Deploy a public app from GitHub**;
3. repository `Kouroshie/containment`, branch `main`, main file path
   `app/streamlit_app.py`;
4. **Deploy**.

`requirements.txt` and `.streamlit/config.toml` at the repository root are
there for exactly this. The app adds `src/` to `sys.path` itself, so the
package does not need to be pip-installed in the hosted environment. Pushing
to `main` redeploys automatically.

Hugging Face Spaces (Streamlit SDK) works from the same two files if you would
rather host there.

## Performance

The analytical engine is seconds. The vertical-equilibrium solver is seconds
to minutes, driven by cell count and by how short the CFL-limited transport
step gets (brine extraction and high permeability both shorten it). A
161 x 161 grid over 230 years runs in about 10 seconds; a 190 x 190 telescoping
grid over 125 years with an extractor takes about 3 minutes. Monte Carlo runs
on the analytical engine deliberately, so a few hundred realisations is
seconds rather than hours - and the result carries an explicit note that its
absolute areas are not directly comparable to a vertical-equilibrium AoR.

## Limitations - read these

- The vertical-equilibrium solver assumes buoyant segregation is fast relative
  to lateral spreading. That is a good assumption for a thin, permeable
  storage formation and a poor one for a thick, low-permeability or strongly
  layered interval. Check the reported gravity number.
- Dissolution and mineral trapping are **off by default**. Neglecting them
  over-predicts the plume, which is conservative for an AoR, but it means the
  toolkit cannot answer 146.93(c)(1)(v) (trapping rates by phase) on its own.
- Geochemistry, geomechanics and induced-seismicity screening are out of
  scope. The Class VI Rule does not require them in the AoR model, but the
  Director may.
- Analytical models are single-layer, homogeneous, horizontal and isothermal.
  They are cross-checks, not substitutes.
- Nothing here is a regulatory determination. It is an engineering analysis
  whose assumptions are written down so they can be argued with.

---

## Contributing

Issues and pull requests welcome - particularly additional threshold-pressure
methods from state programmes, importers for other simulators, and validation
cases against published Class VI applications. See
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## Licence

Apache License 2.0. See [`LICENSE`](LICENSE).

## Citing

If this contributes to published or submitted work, please cite the repository
(see [`CITATION.cff`](CITATION.cff)) and the underlying sources it implements  - 
EPA 816-R-13-005, Nordbotten, Celia & Bachu (2005), Mathias et al. (2011),
Nicot et al. (2008), Batzle & Wang (1992), Span & Wagner (1996), Fenghour et
al. (1998).
