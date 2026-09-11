# Importing someone else's model

A Class VI applicant usually already has a numerical model in CMG-GEM,
ECLIPSE, TOUGH2/ECO2N or STOMP. A reviewer does not need to rebuild it. They
need to take its output and re-delineate the AoR under different, explicitly
stated assumptions: a different threshold pressure, a different saturation
cutoff, a different time horizon, a different 3-D-to-map projection.

That is what `containment.io.importers` is for.

---

## The projection decision

A Class VI model is 3-D; an AoR is a map. How the layers collapse is a real
decision that applications state explicitly, and different choices move the
boundary. `aggregate` offers:

| value | meaning | when |
|---|---|---|
| `max` | maximum over all layers at each (x, y) | the conservative default. One application words it: "the maximum differential pressure of any model cell in 3D is projected onto a 2D map ... no pressure averaging is performed" |
| `pv_weighted` | pore-volume weighted mean over layers | saturation maps, where a thin high-saturation streak should not define the outline |
| `top` / `bottom` | a single layer | when only the top of the injection zone matters |
| `sum` | thickness-weighted total | converting a per-layer CO2 column into a total column |

Whatever you pick is recorded on the result and printed in the report.

---

## Long-format CSV

The common denominator. One row per cell per output time.

```csv
x,y,layer,time,PRESSURE,SGAS
0,0,1,0,2481,0.0
500,0,1,0,2483,0.0
...
0,0,1,22,2794,0.42
```

```bash
containment import sim_export.csv \
    --x-col x --y-col y --time-col time \
    --dp-col PRESSURE --absolute-pressure --initial-pressure 2481 \
    --plume-col SGAS --plume-cutoff 0.01 \
    --threshold 313 \
    --length-unit ft --pressure-unit psi --time-unit yr \
    --aggregate max \
    -o aor.geojson
```

```python
from containment.io import importers
from containment import delineate, units as U

sim = importers.load_grid_csv(
    "sim_export.csv",
    dp_col="PRESSURE", dp_is_absolute=True, initial_pressure=2481.0,
    plume_col="SGAS",
    length_unit="ft", pressure_unit="psi", time_unit="yr",
    aggregate="max")

print(sim.summary())        # grid, extent, time range, and any warnings

aor = delineate.delineate(
    sim.x, sim.y,
    dp_field=sim.dp_max(),                       # maximum over time
    threshold_pressure=U.pressure(313, "psi"),
    plume_field=sim.plume_max(),
    plume_level=0.01,
    plume_criterion="CO2 saturation >= 0.01 in any layer",
    method="re-delineated from the operator's CMG-GEM export")

print(aor.summary())
```

### Absolute pressure or buildup?

This is the single most common way an imported AoR comes out wrong, so
neither has a silent default:

* `dp_is_absolute=False` (the default): the column already holds **buildup**
  above the pre-injection pressure.
* `dp_is_absolute=True`: the column holds **absolute** pressure, and
  `initial_pressure` is subtracted.

The reader checks itself. If it was told the column is buildup but the minimum
value anywhere in the model is above 100 psi, it says so:

> the pressure column was read as *buildup* but its minimum value anywhere in
> the model is 2,481 psi. That is almost certainly absolute pressure: re-read
> with dp_is_absolute=True and an initial_pressure, or the pressure front will
> swallow the whole domain.

If the initial pressure varies across the model - a dipping formation, or
several stacked injection intervals - subtracting one number is not right.
Export a buildup column from the simulator instead.

---

## TOUGH2 / ECO2N element tables

```python
sim = importers.load_tough_elem("out.elem", sg_key="SG", p_key="P",
                                time_unit="s", aggregate="max")
```

Handles the whitespace-delimited `ELEM ... X Y Z P SG ...` block layout that
TOUGH post-processors produce, with repeated blocks per output time introduced
by a line containing `TIME`. TOUGH convention is metres and pascals.

If `initial_pressure` is not given, the minimum pressure in the first block is
used as the reference and the choice is recorded in `sim.notes`.

---

## ECLIPSE free-format keyword arrays

```python
poro = importers.load_eclipse_ascii("MODEL.GRDECL", "PORO",
                                    nx=120, ny=90, nz=12, aggregate="max")
```

Handles GRDECL repeat syntax (`12*0.25`), `--` comments and the terminating
`/`. Returns the array already collapsed to `(ny, nx)`.

This is for static property arrays. For dynamic results, export a CSV.

---

## Fast interchange

```python
from containment.io import exporters, importers

exporters.save_npz("fields.npz", x, y, times, dp=dp, plume=plume)
sim = importers.load_field_npz("fields.npz")
```

`containment run -o out/` writes one of these for every run. It is the right way
to hand a large model to somebody else, and it is what the field archive in
the report's input record refers to.

---

## Building the whole workflow on imported fields

The importer gives you fields; everything downstream works the same way.

```python
import numpy as np
from containment import corrective, delineate, pisc, units as U
from containment.io import importers

sim = importers.load_grid_csv("sim.csv", dp_col="DP", plume_col="SGAS",
                              length_unit="ft", pressure_unit="psi")
thr = U.pressure(313, "psi")

aor = delineate.delineate(sim.x, sim.y,
                          dp_field=sim.dp_max(), threshold_pressure=thr,
                          plume_field=sim.plume_max(), plume_level=0.01)

pi = pisc.analyse(sim.times,
                  plume_fields=sim.plume, plume_level=0.01,
                  dp_fields=sim.dp, threshold_pressure=thr,
                  cell_area=sim.cell_area,
                  injection_end=U.time(22, "yr"),
                  x=sim.x, y=sim.y, origins=[(0.0, 0.0)])
print(pi.recommended_timeframe()["verdict"])

wells = corrective.load_wells_csv("legacy_wells.csv", unit="ft")
plan = corrective.screen(wells, aor,
                         U.length(5700, "ft"), U.length(6000, "ft"))
plan = corrective.arrival_times(plan, sim.x, sim.y, sim.times,
                                plume_fields=sim.plume, plume_level=0.01,
                                dp_fields=sim.dp, threshold_pressure=thr)
print(plan.phases())
```

---

## Sanity checks worth running on an import

1. **Does the reported grid extent match the model?** `sim.summary()` prints
   cell size, extent and time range. A silent unit error shows up here first.
2. **Does the maximum buildup look right?** Compare against the operator's
   own stated maximum differential pressure. If it is out by a factor of
   14.5 or 145, the pressure unit is wrong.
3. **Re-delineate at the operator's own threshold and cutoff first.** If you
   cannot reproduce their AoR area within a few per cent, something in the
   import is wrong and no amount of re-analysis will fix it. Only once you
   match should you start changing assumptions.
4. **Then vary one thing at a time**: the threshold method, the saturation
   cutoff, the layer aggregation. The spread across those choices is usually
   larger than the spread across reasonable reservoir parameters, and it is
   the part an operator has discretion over.
