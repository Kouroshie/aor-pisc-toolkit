"""Read plume and pressure fields out of somebody else's simulator.

Most Class VI applicants already have a numerical model -- CMG-GEM, ECLIPSE,
TOUGH2/ECO2N, STOMP.  A regulator reviewing that application does not need to
rebuild it; they need to take its output and re-delineate the AoR under
different, explicitly stated assumptions: a different threshold pressure, a
different saturation cutoff, a different time horizon.  That is what these
readers are for.

Three-to-two dimensions
-----------------------
A Class VI model is 3-D; an AoR is a map.  The projection rule is a real
decision and applications state it explicitly.  ``aggregate`` offers:

``"max"``
    maximum over all layers at each (x, y).  The most conservative and the
    most common: "the maximum differential pressure of any model cell in 3D is
    projected onto a 2D map ... no pressure averaging is performed".
``"pv_weighted"``
    pore-volume weighted average over layers.  Appropriate for saturation
    maps where a thin high-saturation streak should not define the outline.
``"top"`` / ``"bottom"``
    single layer, for a model where only the top of the injection zone
    matters.
``"sum"``
    thickness-weighted total, e.g. converting per-layer CO2 column to a total
    CO2 column.

Whichever is chosen is recorded on the result so it lands in the report.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field

import numpy as np

from .. import units as U


@dataclass
class SimulationImport:
    """Gridded fields read from an external model."""

    x: np.ndarray                       # 1-D cell-centre x (m)
    y: np.ndarray                       # 1-D cell-centre y (m)
    times: np.ndarray                   # 1-D times (s)
    dp: np.ndarray | None = None        # (nt, ny, nx) pressure increase, Pa
    plume: np.ndarray | None = None     # (nt, ny, nx) plume indicator
    source: str = ""
    aggregate: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def cell_area(self) -> float:
        dx = float(np.median(np.diff(self.x))) if len(self.x) > 1 else 1.0
        dy = float(np.median(np.diff(self.y))) if len(self.y) > 1 else 1.0
        return abs(dx * dy)

    def dp_max(self) -> np.ndarray:
        return self.dp.max(axis=0)

    def plume_max(self) -> np.ndarray:
        return self.plume.max(axis=0)

    def summary(self) -> dict:
        return {
            "source": self.source,
            "aggregate": self.aggregate,
            "grid": [len(self.y), len(self.x)],
            "cell_size_ft": [
                U.length_out(float(np.median(np.diff(self.x))), "ft") if len(self.x) > 1 else None,
                U.length_out(float(np.median(np.diff(self.y))), "ft") if len(self.y) > 1 else None,
            ],
            "extent_mi": [U.length_out(float(self.x[-1] - self.x[0]), "mi"),
                          U.length_out(float(self.y[-1] - self.y[0]), "mi")],
            "n_times": len(self.times),
            "time_range_years": [U.time_out(float(self.times[0]), "yr"),
                                 U.time_out(float(self.times[-1]), "yr")],
            "max_dp_psi": (U.pressure_out(float(np.nanmax(self.dp)), "psi")
                           if self.dp is not None else None),
            "max_plume_value": float(np.nanmax(self.plume)) if self.plume is not None else None,
            "notes": list(self.notes),
        }


# ==========================================================================
def _regularise(xs, ys, vals, weights=None, aggregate="max"):
    """Collapse scattered (x, y, value) records onto a regular grid."""
    ux = np.unique(np.round(xs, 3))
    uy = np.unique(np.round(ys, 3))
    ix = np.searchsorted(ux, np.round(xs, 3))
    iy = np.searchsorted(uy, np.round(ys, 3))
    shape = (len(uy), len(ux))

    if aggregate == "max":
        out = np.full(shape, -np.inf)
        np.maximum.at(out, (iy, ix), vals)
        out[~np.isfinite(out)] = np.nan
    elif aggregate == "sum":
        out = np.zeros(shape)
        np.add.at(out, (iy, ix), vals)
    elif aggregate == "pv_weighted":
        w = np.ones_like(vals) if weights is None else weights
        num = np.zeros(shape)
        den = np.zeros(shape)
        np.add.at(num, (iy, ix), vals * w)
        np.add.at(den, (iy, ix), w)
        out = np.where(den > 0, num / np.maximum(den, 1e-300), np.nan)
    else:  # "top" / "bottom" / "first"
        out = np.full(shape, np.nan)
        out[iy, ix] = vals
    return ux, uy, out


def load_grid_csv(path: str, *,
                  x_col: str = "x", y_col: str = "y",
                  time_col: str | None = "time",
                  dp_col: str | None = None,
                  plume_col: str | None = None,
                  weight_col: str | None = None,
                  length_unit: str = "m",
                  pressure_unit: str = "psi",
                  time_unit: str = "yr",
                  aggregate: str = "max",
                  dp_is_absolute: bool = False,
                  initial_pressure: float = float("nan")) -> SimulationImport:
    """Read a long-format CSV export from a reservoir simulator.

    One row per cell per output time, with coordinate columns and one or both
    of a pressure column and a plume column.  Extra layers at the same (x, y)
    are collapsed with ``aggregate``.

    ``dp_is_absolute`` tells the reader the pressure column holds absolute
    pressure rather than buildup; ``initial_pressure`` (in ``pressure_unit``)
    is then subtracted.  Getting this backwards is the single most common way
    an imported AoR comes out wrong, so both are explicit and neither has a
    silent default.
    """
    ls = U.length(1.0, length_unit)
    rows_x, rows_y, rows_t, rows_dp, rows_pl, rows_w = [], [], [], [], [], []

    with open(path, newline="", encoding="utf-8-sig") as fh:
        rdr = csv.DictReader(fh)
        missing = [c for c in (x_col, y_col) if c not in (rdr.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: missing column(s) {missing}; "
                             f"found {rdr.fieldnames}")
        for r in rdr:
            try:
                rows_x.append(float(r[x_col]) * ls)
                rows_y.append(float(r[y_col]) * ls)
            except (TypeError, ValueError):
                continue
            rows_t.append(float(r[time_col]) if (time_col and r.get(time_col)) else 0.0)
            rows_dp.append(float(r[dp_col]) if (dp_col and r.get(dp_col)) else np.nan)
            rows_pl.append(float(r[plume_col]) if (plume_col and r.get(plume_col)) else np.nan)
            rows_w.append(float(r[weight_col]) if (weight_col and r.get(weight_col)) else 1.0)

    if not rows_x:
        raise ValueError(f"{path}: no readable rows")

    xs = np.array(rows_x)
    ys = np.array(rows_y)
    ts = U.time(np.array(rows_t), time_unit)
    ws = np.array(rows_w)
    utimes = np.unique(ts)

    notes = []
    dp_stack = plume_stack = None
    ux = uy = None

    if dp_col:
        p0 = U.pressure(initial_pressure, pressure_unit) if dp_is_absolute else 0.0
        if dp_is_absolute and not np.isfinite(p0):
            raise ValueError("dp_is_absolute=True requires initial_pressure")
        vals = U.pressure(np.array(rows_dp), pressure_unit) - p0
        frames = []
        for t in utimes:
            m = ts == t
            ux, uy, f = _regularise(xs[m], ys[m], vals[m], ws[m], aggregate)
            frames.append(f)
        dp_stack = np.array(frames)
        if not dp_is_absolute:
            floor = float(np.nanmin(dp_stack))
            if floor > U.pressure(100.0, "psi"):
                notes.append(
                    f"the pressure column was read as *buildup* but its minimum "
                    f"value anywhere in the model is "
                    f"{U.pressure_out(floor, 'psi'):,.0f} psi. That is almost "
                    "certainly absolute pressure: re-read with "
                    "dp_is_absolute=True and an initial_pressure, or the "
                    "pressure front will swallow the whole domain.")
            elif floor < -U.pressure(50.0, "psi"):
                notes.append(
                    "the pressure column contains large negative values; check "
                    "the sign convention and whether this is drawdown rather "
                    "than buildup")

    if plume_col:
        vals = np.array(rows_pl)
        frames = []
        for t in utimes:
            m = ts == t
            ux2, uy2, f = _regularise(xs[m], ys[m], vals[m], ws[m], aggregate)
            frames.append(f)
            ux, uy = ux2, uy2
        plume_stack = np.array(frames)

    return SimulationImport(
        x=ux, y=uy, times=utimes,
        dp=dp_stack, plume=plume_stack,
        source=os.path.basename(path),
        aggregate=aggregate, notes=notes,
    )


def load_field_npz(path: str) -> SimulationImport:
    """Read a NumPy ``.npz`` archive with ``x``, ``y``, ``times`` and fields.

    Expected keys: ``x`` (m), ``y`` (m), ``times`` (s), and any of ``dp`` (Pa)
    and ``plume``, each ``(nt, ny, nx)``.  This is the fastest interchange
    format for a large model and is what :func:`containment.io.exporters.save_npz`
    writes.
    """
    z = np.load(path)
    return SimulationImport(
        x=z["x"], y=z["y"], times=z["times"],
        dp=z["dp"] if "dp" in z else None,
        plume=z["plume"] if "plume" in z else None,
        source=os.path.basename(path), aggregate=str(z.get("aggregate", "")),
    )


def load_tough_elem(path: str, *, sg_key: str = "SG", p_key: str = "P",
                    time_unit: str = "s", aggregate: str = "max",
                    initial_pressure: float | None = None) -> SimulationImport:
    """Read a TOUGH2/ECO2N element output table.

    Handles the common whitespace-delimited "ELEM ... X Y Z P SG ..." block
    layout produced by TOUGH2 post-processors, with repeated blocks per
    output time introduced by a line containing ``TIME``.  Pressures are Pa
    and lengths metres, per TOUGH convention.
    """
    times: list[float] = []
    blocks: list[list[tuple[float, float, float, float]]] = []
    header: list[str] | None = None
    cur: list[tuple[float, float, float, float]] = []

    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            up = line.upper()
            if "TIME" in up and any(ch.isdigit() for ch in line):
                nums = [float(t) for t in _floats(line)]
                if nums:
                    if cur:
                        blocks.append(cur)
                        cur = []
                    times.append(nums[-1])
                    header = None
                continue
            if ("X" in up.split() and "Y" in up.split()) or sg_key in up.split():
                header = line.split()
                continue
            if header is None:
                continue
            parts = line.split()
            if len(parts) < len(header):
                continue
            try:
                rec = dict(zip(header, parts, strict=False))
                cur.append((float(rec["X"]), float(rec["Y"]),
                            float(rec.get(p_key, "nan")),
                            float(rec.get(sg_key, "nan"))))
            except (KeyError, ValueError):
                continue
    if cur:
        blocks.append(cur)
    if not blocks:
        raise ValueError(f"{path}: no element records recognised")

    ts = U.time(np.array(times[:len(blocks)], float), time_unit)
    dp_frames, sg_frames = [], []
    ux = uy = None
    for b in blocks:
        arr = np.array(b, float)
        ux, uy, pf = _regularise(arr[:, 0], arr[:, 1], arr[:, 2], None, aggregate)
        _, _, sf = _regularise(arr[:, 0], arr[:, 1], arr[:, 3], None, aggregate)
        dp_frames.append(pf)
        sg_frames.append(sf)

    dp = np.array(dp_frames)
    p0 = initial_pressure if initial_pressure is not None else np.nanmin(dp[0])
    return SimulationImport(
        x=ux, y=uy, times=ts, dp=dp - p0, plume=np.array(sg_frames),
        source=os.path.basename(path), aggregate=aggregate,
        notes=[f"pressure buildup referenced to {U.pressure_out(p0, 'psi'):,.0f} psi"],
    )


def load_eclipse_ascii(path: str, keyword: str, nx: int, ny: int, nz: int,
                       *, aggregate: str = "max", dx: float = 1.0,
                       dy: float = 1.0, x0: float = 0.0, y0: float = 0.0
                       ) -> np.ndarray:
    """Read one keyword array from an ECLIPSE-style free-format ASCII file.

    Handles GRDECL repeat syntax (``12*0.25``) and terminating ``/``.
    Returns the array collapsed to ``(ny, nx)`` with ``aggregate`` applied
    across the ``nz`` layers -- the same 3-D-to-map projection used elsewhere.
    """
    vals: list[float] = []
    grabbing = False
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.split("--")[0].strip()
            if not s:
                continue
            if not grabbing:
                if s.split()[0].upper() == keyword.upper():
                    grabbing = True
                    s = " ".join(s.split()[1:])
                    if not s:
                        continue
                else:
                    continue
            done = s.endswith("/")
            s = s.rstrip("/").strip()
            for tok in s.split():
                if "*" in tok:
                    cnt, _, v = tok.partition("*")
                    vals.extend([float(v)] * int(cnt))
                else:
                    vals.append(float(tok))
            if done:
                break
    if not grabbing:
        raise ValueError(f"{path}: keyword {keyword!r} not found")
    a = np.asarray(vals, float)
    if a.size != nx * ny * nz:
        raise ValueError(f"{keyword}: got {a.size} values, expected {nx * ny * nz}")
    cube = a.reshape(nz, ny, nx)
    if aggregate == "max":
        return np.nanmax(cube, axis=0)
    if aggregate == "sum":
        return np.nansum(cube, axis=0)
    if aggregate == "top":
        return cube[0]
    if aggregate == "bottom":
        return cube[-1]
    return np.nanmean(cube, axis=0)


def _floats(line: str):
    out = []
    for tok in line.replace(",", " ").split():
        try:
            out.append(float(tok))
        except ValueError:
            continue
    return out


__all__ = ["SimulationImport", "load_grid_csv", "load_field_npz",
           "load_tough_elem", "load_eclipse_ascii"]
