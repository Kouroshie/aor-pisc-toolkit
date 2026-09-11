# aorpisc - Area of Review & Post-Injection Site Care toolkit

Open-source Python toolkit for delineating the **Area of Review (AoR)** and
building the **Post-Injection Site Care (PISC)** demonstration for UIC
**Class VI** geologic carbon storage projects, following
[40 CFR 146.84 / 146.93](https://www.ecfr.gov/current/title-40/chapter-I/subchapter-D/part-146/subpart-H)
and EPA's *Class VI Well Area of Review Evaluation and Corrective Action
Guidance* ([816-R-13-005](https://www.epa.gov/uic/class-vi-guidance-documents), May 2013).

It runs as a Python library, a command-line tool, and a browser app.

```bash
pip install "aorpisc[full]"
aorpisc run examples/epa_hypothetical_site.yaml -o out/
```

---

## What it does

| Stage | What you get |
|---|---|
| **Fluid properties** | CO2 density/viscosity (Span-Wagner via CoolProp, or a built-in Spycher-Pruess RK EOS + Fenghour correlation), brine density/viscosity/compressibility (Batzle-Wang) |
| **Threshold pressure** | Four methods side by side - Thornhill/EPA Method 1, Nicot uniform-density (Method 2), a variable-density column integration, and the TCEQ/Class I static mud column + gel strength - plus explicit handling of the over-pressurised case |
| **Flow modelling** | (a) analytical superposition - Theis + image wells + radial Buckley-Leverett + two-phase apparent skin; (b) a vertical-equilibrium two-phase numerical solver on a heterogeneous, dipping, faulted grid; (c) import of your existing CMG / ECLIPSE / TOUGH2 output |
| **AoR delineation** | Union of the maximum-over-time plume and the maximum-over-time pressure front, exported as GeoJSON / KML / CSV, with extent-by-azimuth tables |
| **Corrective action** | EPA's Figure 4-3 decision tree applied to every penetration, **plus phased corrective action scheduled by modelled arrival time** |
| **PISC** | Plume area, expansion rate, effective-radius migration rate, directional migration, pressure decline, plume-stabilisation year, a defensible PISC duration, and the 40 CFR 146.93(c) checklist |
| **Uncertainty** | Tornado sensitivity and a Latin-hypercube Monte Carlo producing a **probabilistic AoR** (P10 / P50 / P90 boundaries) |
| **Reporting** | One self-contained HTML report, organised the way an AoR & Corrective Action Plan and a PISC & Site Closure Plan are organised, with the regulatory citation on every section |

---

## Why not just use EASiTool?

[EASiTool](https://gccc.beg.utexas.edu/research/easitool) (UT Austin BEG) is a
good, widely used tool, and this toolkit implements the same analytical
lineage it rests on (Mathias et al. 2011; Buckley-Leverett fronts;
superposition of pressure buildup). But EASiTool is a **storage-capacity and
well-optimisation** tool, not an AoR tool. The differences that matter for a
Class VI permit:

| | EASiTool v4 | aorpisc |
|---|---|---|
| Purpose | storage capacity, optimal well count and rates, NPV | AoR delineation, corrective action, PISC demonstration |
| Threshold pressure | not computed | four EPA/TCEQ methods, compared, with regime checks |
| AoR polygon | not produced | plume + pressure-front geometric union, exported to GIS |
| Geometry | square reservoir centred in a square basin (arbitrary well locations in the v4 general-geometry module) | arbitrary well coordinates, arbitrary domain, per-well step-rate schedules |
| Heterogeneity, dip, faults | not represented | full field of permeability, porosity, thickness, top-surface structure, fault transmissibility multipliers |
| Post-injection | not modelled | vertical-equilibrium buoyant migration with residual trapping, centuries if needed |
| Uncertainty | one-at-a-time tornado | tornado **and** Latin-hypercube Monte Carlo with a probabilistic AoR |
| Corrective action | none | EPA decision tree + arrival-time phasing |
| PISC | none | full 146.93 metrics and checklist |
| Licence / platform | free binary, Windows, MATLAB Runtime | Apache-2.0 source, any OS, pip-installable, scriptable, CI-tested |

The last row is not a small point. EPA notes that proprietary codes "may
prevent full evaluation of model results" and encourages operators to disclose
code assumptions and governing equations. Everything here is readable, every
equation carries its citation in the docstring, and a reviewer can re-run the
operator's own numbers under different assumptions in seconds.

---

## Quick start

### Command line

```bash
# full workflow: threshold, model, AoR, corrective action, PISC, HTML report
aorpisc run examples/epa_hypothetical_site.yaml -o out/

# just the threshold pressure, every method, with its inputs and citations
aorpisc threshold examples/epa_hypothetical_site.yaml

# re-delineate an AoR from somebody else's simulator output
aorpisc import sim_export.csv --dp-col PRESSURE --absolute-pressure \
    --initial-pressure 2481 --plume-col SGAS --plume-cutoff 0.01 \
    --threshold 313 --length-unit ft -o aor.geojson

# AoR reevaluation: difference two delineations [40 CFR 146.84(e)]
aorpisc reevaluate year0.yaml year5.yaml -o out/

# browser app
aorpisc app
```

### Python

```python
from aorpisc.config import Project
from aorpisc import workflow, report

project = Project.from_yaml("my_site.yaml")
result  = workflow.run(project)

print(result.aor.summary()["aor_area_acres"])
print(result.pisc.recommended_timeframe()["verdict"])
report.write_html(result, "aor_report.html")
```

### Threshold pressure on its own

```python
from aorpisc import threshold, fluids, units as U

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
3. repository `Kouroshie/aor-pisc-toolkit`, branch `main`, main file path
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
