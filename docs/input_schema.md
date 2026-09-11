# The project file

One YAML file describes a complete run. It is also the record 40 CFR 146.84(g)
asks you to keep for ten years, and the thing EPA Section 3.5 means by "all
necessary information for the UIC Program Director to evaluate the AoR
delineation results and replicate the computational modeling exercise".

Values are written in whatever units the permit uses. They are converted to SI
once, on the way in.

```python
from containment.config import Project
project = Project.from_yaml("my_site.yaml")
print(project.warnings)      # read these before you trust anything
```

---

## `project`

| key | type | notes |
|---|---|---|
| `name` | string | appears on every figure and in the report title |
| `operator` | string | optional |
| `permit` | string | optional |
| `datum` | string | **state it.** "ground surface, depths positive downward", "MSL", "KB". Threshold pressure is sensitive to the datum and the number is meaningless without it |
| `notes` | string | free text, carried into the report |
| `crs` | mapping | `{epsg: 32614}` for an exact transform (needs `pyproj`), or `{origin_lon: -97.5, origin_lat: 27.5}` for a local tangent-plane approximation. Usually unnecessary: give the wells `latitude`/`longitude` and the frame is built for you. Add `x_offset`/`y_offset` to **pin** the frame, which is required when one site is modelled as several projects (one per storage formation) whose polygons are combined later. **Foot-based CRSs are handled**: a Texas State Plane or BLM zone quoted in US survey feet (EPSG:32040, 32064, 2278 and friends) has its axis unit read from the CRS and converted, and `x_offset`/`y_offset` stay in that CRS's own units so a pinned frame reads like an easting off a plat |

---

## `units`

Defaults in **bold**.

| key | default | accepted |
|---|---|---|
| `length` | **ft** | m, km, ft, mi, in, cm, mm |
| `depth` | **ft** | same as length |
| `pressure` | **psi** | Pa, kPa, MPa, bar, psi, atm |
| `temperature` | **F** | C, F, K, R |
| `permeability` | **mD** | mD, D, uD, nD, m2 |
| `rate` | **MMT/yr** | any `mass/time`: MMT/yr, tonne/day, ton/day, kg/s |
| `brine_rate` | **bbl/day** | any `volume/time`: bbl/day, m3/day, ft3/day |
| `time` | **yr** | s, day, yr |
| `compressibility` | **1/psi** | 1/Pa, 1/psi, 1/bar, 1/MPa |

---

## `formation`

Three intervals. Depths are **positive downward** from the stated datum.

For a well completed in more than one formation, give `injection_zones` (a
list) instead of `injection_zone`. Each entry takes every key the singular
form does, plus a `name`, and may carry its own `confining_zone`; zones left
without one fall back to `formation.confining_zone`. List them shallowest
first.

```yaml
formation:
  injection_zones:
    - name: Frio A
      top_depth: 5200
      thickness: 180
      porosity: 0.20
      permeability: 220
      temperature: 140
      salinity_ppm: 70000
      initial_pressure: 2250
      confining_zone: {top_depth: 5000, base_depth: 5200}
    - name: Frio B
      top_depth: 6000
      thickness: 250
      porosity: 0.18
      permeability: 150
      temperature: 150
      salinity_ppm: 90000
      initial_pressure: 2600
      confining_zone: {top_depth: 5700, base_depth: 6000}
  usdw: {...}
```

Each zone is then modelled on its own grid, with CO2 properties evaluated at
its own pressure and temperature and a threshold pressure computed from its
own depth against the same USDW. The project AoR is the geometric **union** of
the zone AoRs, and the per-zone delineations are reported behind it. Nothing
is averaged across zones.

A single `injection_zones` entry is identical to the singular spelling.

### `injection_zone`

| key | required | notes |
|---|---|---|
| `top_depth` | yes | |
| `thickness` | yes | **net**, not gross. This is the thickness available to CO2 |
| `base_depth` | no | supplies `thickness` if that is absent |
| `porosity` | yes | fraction |
| `permeability` | yes | horizontal |
| `temperature` | yes | |
| `salinity_ppm` | yes | or `salinity` with `salinity_unit` (ppm, wt%, molal, fraction) |
| `initial_pressure` | yes | measured, at the stated datum. The threshold pressure depends on it directly |
| `rock_compressibility` | no | default 4e-6 /psi. Added to the computed brine compressibility |
| `dip_degrees` | no | default 0 |
| `dip_azimuth` | no | compass direction the formation dips **towards**: 0 = north, 90 = east. CO2 migrates the opposite way |
| `anisotropy_kv_kh` | no | not used by the VE solver, which is vertically integrated |

### `confining_zone`

`top_depth` and `base_depth`. Used by the corrective-action screen to decide
which penetrations reach the confining zone, and to decide whether a recorded
plug sits across it. If omitted, the screen assumes a 100 ft interval directly
above the injection zone and says so.

### `usdw`

The **lowermost** USDW, which is the one the threshold pressure is measured
against.

| key | required | notes |
|---|---|---|
| `base_depth` | yes | |
| `initial_pressure` | strongly recommended | if absent, hydrostatic at 0.433 psi/ft is assumed and the fact is recorded as a warning |
| `temperature` | no | default 70 degF |
| `salinity_ppm` | no | default 500 ppm |

---

## `relative_permeability`

```yaml
relative_permeability:
  model: brooks_corey     # or van_genuchten
  swr: 0.35               # residual brine
  sgr: 0.20               # residual (trapped) CO2
  krw0: 1.0
  krg0: 0.30
  m: 3.0                  # brine exponent
  n: 3.0                  # CO2 exponent
```

For van Genuchten: `swr`, `sgr`, `lambda`, `krg0`.

`sgr` is the single most consequential number for post-injection behaviour: it
sets how much CO2 is left behind as the plume migrates, and therefore whether
migration ever stops. `krg0` and the exponents set the mobility ratio, which
sets how far ahead of a volume balance the plume nose runs.

Literature ranges (EASiTool user manual, Table): `swr` 0.2-0.6, `sgr`
0.1-0.35, exponents 1.5-4.0, `krg0` 0.1-0.6.

---

## `threshold`

```yaml
threshold:
  method: auto           # auto | method1 | method2 | method2b | mud_column
  mud_weight_ppg: 9.0
  gel_strength: 10       # in the project pressure unit
  mud_datum_depth: 6000  # optional; defaults to the injection-zone mid-depth
  datum: top             # where dP_c is evaluated: `top` or a depth below
  datum_depth: 5862      # optional explicit depth, overrides `datum`
  override: 313          # optional; skips all methods and uses this dP_c
```

**`datum` is not cosmetic.** The threshold pressure is evaluated at a depth,
and the default here is the mid-point of the injection zone. Many published
applications quote it at the **top** of the injection zone instead, which is
where the topmost perforation and the shallowest conduit connection are.
Moving the datum across a 313 ft interval changes `dP_c` by the weight of
157 ft of brine; on one published Texas site that is 714 psi at the top
versus 790 psi at mid-perforation, a 10 % difference in the number that sets
the whole pressure front. Set it explicitly and say which you used.

`auto` runs every method and selects the smallest `dP_c` that is applicable to
the site's pressure regime, which gives the largest pressure front and the
most protective AoR. All methods appear in the report regardless.

`override` records itself as "supplied directly and not derived" so it cannot
pass unnoticed.

---

## `wells`

Wells take **either** local `x`/`y` **or** `latitude`/`longitude`. Latitude and
longitude is the better path: the local frame is built around the well field
automatically, the UTM zone is chosen for you, and the GIS map becomes
available without you computing anything.

Add `zone:` to send a completion's whole rate to one named injection zone of
a stacked project. A well with no `zone` is treated as commingled and its rate
is split between zones in proportion to flow capacity `k*h`, which is
recorded in the result and flagged as an assumption. To use a measured zonal
allocation, give one well row per zone with the same name and coordinates,
each naming its zone and carrying its own rate:

```yaml
wells:
  - {name: INJ-1, latitude: 31.9686, longitude: -99.9018, zone: Frio A,
     rate: 0.6, start_year: 0, stop_year: 20}
  - {name: INJ-1, latitude: 31.9686, longitude: -99.9018, zone: Frio B,
     rate: 0.4, start_year: 0, stop_year: 20}
```

```yaml
wells:
  # the recommended form
  - name: INJ-0
    latitude: 31.9686
    longitude: -99.9018
    rate: 1.0
    start_year: 0
    stop_year: 20

  # local coordinates still work
  - name: INJ-1
    x: 0                  # in units.length, from an arbitrary project origin
    y: 0
    kind: injector        # injector | extractor
    rate: 1.0             # in units.rate
    start_year: 0
    stop_year: 20
    radius: 0.33          # ft
    max_bhp: 4200         # optional, psi

  # a stepped schedule instead of start/stop:
  - name: INJ-2
    x: 4000
    y: 0
    schedule:
      - {year: 0,  rate: 0.4}
      - {year: 5,  rate: 1.2}
      - {year: 18, rate: 0.6}
      - {year: 25, rate: 0.0}

  # brine extraction for pressure management
  - name: EXT-1
    x: 2000
    y: 3000
    kind: extractor
    rate: 12000           # in units.brine_rate, positive
    start_year: 2
    stop_year: 20
```

Rates are held constant until the next entry. A rate of 0 shuts the well in.
The VE solver lands a timestep exactly on every rate change.

---

## `model`

```yaml
model:
  engine: ve                 # ve | analytical
  boundary: infinite         # infinite | constant_pressure | noflow
  end_year: 130
  output_years: [0, 1, 2, 5, 10, 20, 30, 50, 80, 130]   # optional
  aor_reevaluation_years: 5  # 40 CFR 146.84(e) cadence; the AoR is also
                             # delineated at each of these dates
  grid:
    cell_size: 400           # the fine cell
    fine_half_width: 6000    # extent of the fine cells around the well field
    half_width: 40000        # total domain half-width -> telescoping grid
    growth: 1.14             # geometric growth factor outside the fine region
    # or, for a uniform grid:
    nx: 161
    ny: 161
```

**engine**

* `ve` - the vertical-equilibrium numerical solver. Handles dip, structure,
  heterogeneity, faults, residual trapping and post-injection migration. Use
  this unless you have a reason not to.
* `analytical` - superposition of line sources plus radial Buckley-Leverett
  plumes. Seconds instead of tens of seconds, homogeneous and horizontal, and
  it stops at the end of injection. Use it for screening, for Monte Carlo, and
  as a cross-check.

**boundary**

* `infinite` - infinite-acting. For the VE engine, which needs a finite grid,
  this maps to a far-field constant-pressure edge.
* `constant_pressure` - pressure pinned at the edge. Appropriate for a
  laterally extensive formation.
* `noflow` - a genuinely closed compartment. **Pressure never dissipates in a
  closed box**, so the post-injection pressure front never shrinks and the
  PISC analysis will say so. Use it only if the reservoir really is
  compartmentalised.

**grid** - giving `half_width` switches on a telescoping grid: `cell_size`
cells over `+/- fine_half_width`, growing by `growth` out to `half_width`.
Without it you get a uniform `nx` by `ny` grid. If neither is given, the
domain is sized automatically from the estimated pressure radius.

**output_years** - if omitted, the toolkit builds a schedule that is dense
during injection, lands on every rate change, and spaces logarithmically
afterwards. Post-injection points spaced more than about five years apart make
migration rates long-interval averages, and you will be told so.

---

## `plume`

```yaml
plume:
  cutoff: 0.01
  criterion: "column-averaged CO2 saturation >= 0.01"
```

`cutoff` is applied to the column-averaged CO2 saturation from the VE solver.
`criterion` is free text that travels with the AoR polygon into the GeoJSON,
the KML and the report, because a plume outline without its cutoff is not a
statement about anything.

Common operator choices are 0.01 to 0.05. A tighter cutoff pulls the outline
in; the sensitivity is usually modest in the body of the plume and large at
the tapering nose, which is exactly where an AoR boundary sits.

---

## `penetrations`

```yaml
penetrations:
  csv: legacy_wells.csv
  coordinate_unit: ft
```

CSV columns, all optional except `name`, `x`, `y`:

| column | notes |
|---|---|
| `name`, `api` | identifiers |
| `x`, `y` | in `coordinate_unit`, same origin as the project wells |
| `latitude`, `longitude` | decimal degrees, used in preference to `x`/`y` when the project is georeferenced. This is how well lists arrive from RRC, TWDB and commercial databases |
| `type` / `kind` | oil, gas, injection, water, dry hole, mine |
| `status` | active, shut-in, plugged, abandoned, unknown |
| `total_depth` | in `coordinate_unit`. **Missing depth is flagged**: 40 CFR 146.84(c)(2) requires it |
| `year_drilled`, `year_abandoned` | pre-1952 abandonment routes to field testing |
| `plug_depths` | semicolon separated, e.g. `500;5800;6400` |
| `plug_material` | cement, mechanical, bridge plug, mud, unknown |
| `cased` | true/false |
| `records_complete` | true/false. **Blank means unknown, which routes to field testing** |
| `mit_passed` | true/false |
| `notes` | free text |

---

## `faults`

```yaml
faults:
  - name: Fault A
    multiplier: 0.0          # 0 = sealing, 1 = open, anything between = partly sealing
    latlon:                  # decimal degrees, when the project is georeferenced
      - [29.982, -94.196]
      - [30.041, -94.086]
  - name: growth fault B
    multiplier: 0.05
    points:                  # or in units.length from the project origin
      - [-33000, -39000]
      - [ 33000,  21000]
```

Every grid face the trace crosses gets `multiplier` as a transmissibility
multiplier. A fault that holds is often the thing that **sets** the AoR
boundary on one side rather than merely perturbing it -- several Gulf Coast
applications say exactly that -- so a model with no way to express one will
over-predict in that direction and there will be nothing in the output to
suggest why. Give the trace enough length to cross the whole domain; a trace
that stops inside it lets the plume and the pressure front walk around the end,
which is a real behaviour but rarely the one intended.

Faults apply to the VE engine only. The analytical engine is homogeneous by
construction and ignores them; when both are run, the cross-check will
disagree, and that disagreement is the point.

---

## `uncertainty`

```yaml
uncertainty:
  enabled: true
  realisations: 200
  spread: 0.5      # fractional half-range; 0.5 means permeability varies by ~2x either way
  seed: 0
```

Runs a tornado and a Latin-hypercube Monte Carlo on the fast analytical
engine, producing percentiles of AoR area, rank correlations, and a
probabilistic AoR (P10/P50/P90 boundaries). Re-run the two or three most
influential cases through the VE engine to confirm.

---

## Validation on load

`Project.from_dict` checks and reports, without stopping:

* no wells, or no injector;
* the injection zone not below the lowermost USDW (a datum or sign error);
* confining zone overlapping the injection zone;
* missing injection-zone or USDW initial pressure;
* missing or non-positive net thickness;
* porosity outside (0, 1);
* a VE domain smaller than 5 miles across;
* a closed no-flow domain used for a run longer than 30 years.

Read `project.warnings` before trusting a result. The CLI and the app print
them; the report puts them at the top.
