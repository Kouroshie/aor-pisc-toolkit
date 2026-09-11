"""Vertical-equilibrium (VE) two-phase CO2/brine solver.

Why VE rather than a full 3-D simulation
----------------------------------------
CO2 storage formations are thin relative to the plume: hundreds of feet of
sand under a plume miles across.  Buoyant segregation is fast compared with
lateral spreading, so the vertical saturation distribution collapses to a
sharp CO2-over-brine interface almost everywhere.  Integrating that
assumption vertically leaves a 2-D areal problem that runs in seconds instead
of hours, while still capturing the things that actually move an AoR
boundary: dip and structure, permeability heterogeneity, sealing faults,
multi-well interference, residual trapping, and post-injection buoyant
migration.

That last item is the reason this solver exists.  The closed-form models in
:mod:`containment.analytical` stop at the end of injection.  EPA requires the
model to run "until the plume movement ceases, until pressure differentials
sufficient to cause the movement of injected fluids or formation fluids into
a USDW are no longer present, or until the end of a fixed time period"
[40 CFR 146.84(c)(1)] -- for a dipping formation that means centuries of
up-dip migration after the wells are shut in, which no analytical solution
covers.

Formulation
-----------
State variables per cell: ``psi`` (brine pressure extrapolated to the top of
the injection zone) and ``vco2`` (CO2 pore volume).  Mobile CO2 column
``h`` and its historical maximum ``hmax`` follow from ``vco2``:

    V = phi A [ (1 - Swr) h + Sgr (hmax - h) ]

Phase potentials, with ``E`` the top-surface elevation and
``drho = rho_w - rho_c``:

    Phi_w = psi + rho_w g E
    Phi_c = psi + drho g h + rho_c g E

so the ``drho g h`` term is the buoyancy that drives up-dip migration and the
``rho g E`` term is the structural drive.  Upscaled face mobilities are

    Lambda_c = k krg0 h / mu_c
    Lambda_w = k [ krw0 (H - hmax) + krw(Sgr) (hmax - h) ] / mu_w

Time stepping is IMPES: an implicit sparse solve for ``psi`` (total volume
balance with rock+fluid compressibility), then an explicit, CFL-limited,
upwind update of ``vco2``.  Mass balance is tracked every step and reported.

Reference
---------
Nordbotten, J.M. & Celia, M.A. (2012) *Geological Storage of CO2: Modeling
Approaches for Large-Scale Simulation*, Wiley.
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass, field

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import spsolve

from .. import units as U
from ..analytical.relperm import BrooksCorey, RelPerm
from .grid import Grid, GridProperties


# ==========================================================================
@dataclass
class VEWell:
    """A well in the VE model.

    ``schedule`` holds ``(start_time_s, rate)`` steps.  For ``kind
    ="injector"`` the rate is CO2 mass in kg/s; for ``"extractor"`` it is
    brine volume in m^3/s and should be given as a positive number (the sign
    is applied internally).
    """

    name: str
    x: float
    y: float
    schedule: list[tuple[float, float]] = field(default_factory=list)
    kind: str = "injector"
    radius: float = 0.1
    max_bhp: float = float("inf")   # Pa; rate is throttled if exceeded
    min_bhp: float = 0.0            # Pa; for extractors

    def rate_at(self, t: float) -> float:
        r = 0.0
        for t0, q in sorted(self.schedule):
            if t >= t0:
                r = q
            else:
                break
        return r

    def cumulative_mass(self, t: float) -> float:
        if self.kind != "injector":
            return 0.0
        total, prev_t, prev_q = 0.0, None, 0.0
        for t0, q in sorted(self.schedule):
            if prev_t is not None:
                total += prev_q * (min(t, t0) - prev_t)
            if t <= t0:
                return max(total, 0.0)
            prev_t, prev_q = t0, q
        if prev_t is not None:
            total += prev_q * (t - prev_t)
        return max(total, 0.0)


# ==========================================================================
@dataclass
class VEResult:
    """Time series of VE solver output on the model grid."""

    grid: Grid
    times: np.ndarray                  # s
    dp: np.ndarray                     # (nt, ny, nx) pressure buildup, Pa
    h: np.ndarray                      # (nt, ny, nx) mobile CO2 column, m
    hmax: np.ndarray                   # (nt, ny, nx) historical max column, m
    bhp: dict[str, np.ndarray] = field(default_factory=dict)
    mass_balance_error: float = 0.0
    steps: int = 0
    runtime_s: float = 0.0
    warnings: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    # ---------------------------------------------------------------- #
    @property
    def dp_max(self) -> np.ndarray:
        """Cell-wise maximum pressure buildup over all output times."""
        return self.dp.max(axis=0)

    @property
    def plume_mask_max(self) -> np.ndarray:
        """Cells that ever contained separate-phase CO2 (mobile or residual)."""
        return self.hmax[-1] > 1e-6

    def co2_column(self, index: int = -1) -> np.ndarray:
        """Total (mobile + residual) CO2-bearing column thickness at a time."""
        return self.hmax[index]

    def saturation_proxy(self, index: int, props: GridProperties,
                         relperm: RelPerm) -> np.ndarray:
        """Column-averaged CO2 saturation, comparable to a 3-D model's map.

        Class VI applications usually outline the plume at a CO2 saturation
        cutoff (0.01-0.05) taken from a 3-D model.  This converts the VE state
        into the same currency so cutoffs are comparable.
        """
        h, hm = self.h[index], self.hmax[index]
        sg_mob = 1.0 - relperm.swr
        return ((sg_mob * h + relperm.sgr * (hm - h))
                / np.maximum(props.thickness, 1e-9))

    def summary(self) -> dict:
        return {
            "n_output_times": len(self.times),
            "final_time_years": U.time_out(float(self.times[-1]), "yr"),
            "timesteps": self.steps,
            "runtime_s": self.runtime_s,
            "mass_balance_error_fraction": self.mass_balance_error,
            "max_pressure_buildup_psi": U.pressure_out(float(self.dp_max.max()), "psi"),
            "max_co2_column_ft": U.length_out(float(self.hmax[-1].max()), "ft"),
            "plume_cells_final": int(self.plume_mask_max.sum()),
            "warnings": list(self.warnings),
            **self.meta,
        }


# ==========================================================================
class VESolver:
    """IMPES vertical-equilibrium solver for CO2 storage."""

    def __init__(self, props: GridProperties, *,
                 rho_co2: float, mu_co2: float,
                 rho_brine: float, mu_brine: float,
                 total_compressibility: float,
                 reference_pressure: float,
                 reference_elevation: float | None = None,
                 relperm: RelPerm | None = None,
                 boundary: str = "noflow",
                 boundary_pressure: float | None = None,
                 dissolution_fraction_per_year: float = 0.0):
        self.props = props
        self.grid = props.grid
        self.rho_c = rho_co2
        self.mu_c = mu_co2
        self.rho_w = rho_brine
        self.mu_w = mu_brine
        self.ct = total_compressibility
        self.relperm = relperm or BrooksCorey()
        self.boundary = boundary
        self.dissolution = dissolution_fraction_per_year

        self.drho = rho_brine - rho_co2
        if self.drho <= 0:
            raise ValueError(
                "brine must be denser than CO2 for a VE model; check P/T inputs")

        self.krg0 = float(np.asarray(self.relperm.krg(1.0 - self.relperm.swr)))
        self.krw0 = float(np.asarray(self.relperm.krw(0.0)))
        self.krw_res = float(np.asarray(self.relperm.krw(self.relperm.sgr)))
        self.sg_mob = 1.0 - self.relperm.swr
        self.sg_res = self.relperm.sgr
        if self.sg_mob <= self.sg_res:
            raise ValueError("1 - Swr must exceed Sgr")

        E = props.top_elevation
        if reference_elevation is None:
            reference_elevation = float(np.mean(E[props.active]))
        self.reference_elevation = reference_elevation
        self.reference_pressure = reference_pressure
        # initial brine potential is uniform -> psi_init varies with structure
        self.psi_init = reference_pressure - self.rho_w * U.G * (E - reference_elevation)
        self.boundary_pressure = boundary_pressure

        self._build_geometry()

    # ------------------------------------------------------------------ #
    def _build_geometry(self):
        g, p = self.grid, self.props
        k = p.permeability
        ky = k * p.anisotropy_y_over_x

        def harm(a, b):
            return 2.0 * a * b / np.maximum(a + b, 1e-300)

        # geometric transmissibility of internal faces (k folded in, thickness
        # and relperm applied later as the upscaled mobile thickness).
        # Face width and centre-to-centre distance are taken per face so a
        # graded grid is handled exactly.
        dxs, dys = g.dxs, g.dys
        gx = dys[:, None] / (0.5 * (dxs[:-1] + dxs[1:]))[None, :]
        gy = dxs[None, :] / (0.5 * (dys[:-1] + dys[1:]))[:, None]
        self.Tx = harm(k[:, :-1], k[:, 1:]) * gx * p.fault_mult_x
        self.Ty = harm(ky[:-1, :], ky[1:, :]) * gy * p.fault_mult_y

        act = p.active
        self.Tx *= act[:, :-1] & act[:, 1:]
        self.Ty *= act[:-1, :] & act[1:, :]

        idx = np.arange(g.ncells).reshape(g.shape)
        self.ix_L, self.ix_R = idx[:, :-1].ravel(), idx[:, 1:].ravel()
        self.iy_B, self.iy_T = idx[:-1, :].ravel(), idx[1:, :].ravel()
        self.Txf, self.Tyf = self.Tx.ravel(), self.Ty.ravel()
        self.idx = idx
        self.act_flat = act.ravel()

        areas = g.areas
        self.areas = areas.ravel()
        self.accum_base = (p.porosity * p.thickness * areas * self.ct).ravel()
        self.pv = (p.porosity * areas).ravel()   # pore volume per metre of column
        self.thick = p.thickness.ravel()
        self.elev = p.top_elevation.ravel()

    # ------------------------------------------------------------------ #
    def _state_from_volume(self, vco2: np.ndarray, hmax: np.ndarray):
        """Recover mobile column ``h`` from CO2 pore volume and history."""
        cap_at_hmax = self.pv * self.sg_mob * hmax
        filling = vco2 >= cap_at_hmax
        h = np.where(
            filling,
            vco2 / np.maximum(self.pv * self.sg_mob, 1e-300),
            (vco2 / np.maximum(self.pv, 1e-300) - self.sg_res * hmax)
            / (self.sg_mob - self.sg_res),
        )
        h = np.clip(h, 0.0, self.thick)
        hmax = np.maximum(hmax, h)
        return h, hmax

    def _mobilities(self, h, hmax):
        lam_c = self.krg0 * h / self.mu_c
        lam_w = (self.krw0 * np.maximum(self.thick - hmax, 0.0)
                 + self.krw_res * np.maximum(hmax - h, 0.0)) / self.mu_w
        return lam_c, lam_w

    @staticmethod
    def _upwind(T, lam, iL, iR, dphi):
        """Face mobility taken from the upstream cell."""
        up = np.where(dphi >= 0.0, lam[iL], lam[iR])
        return T * up

    # ------------------------------------------------------------------ #
    def _well_cells(self, wells: list[VEWell]):
        out = []
        for w in wells:
            loc = self.grid.index(w.x, w.y)
            if loc is None:
                raise ValueError(f"well {w.name!r} at ({w.x}, {w.y}) is outside the grid")
            j, i = loc
            c = int(self.idx[j, i])
            if not self.act_flat[c]:
                raise ValueError(f"well {w.name!r} sits in an inactive cell")
            out.append((w, c))
        return out

    def _well_index(self, cell: int, w: VEWell) -> float:
        """Peaceman productivity index divided by mobility (m^3 units)."""
        g = self.grid
        j, i = divmod(cell, g.nx)
        re = 0.28 * np.hypot(g.dxs[i], g.dys[j])
        k = self.props.permeability.ravel()[cell]
        H = self.thick[cell]
        return 2.0 * np.pi * k * H / max(np.log(re / max(w.radius, 1e-3)), 0.1)

    # ------------------------------------------------------------------ #
    def run(self, wells: list[VEWell], end_time: float,
            output_times: np.ndarray | None = None,
            dt_init: float = U.time(1.0, "day"),
            dt_max: float = U.time(2.0, "yr"),
            cfl: float = 0.15,
            max_steps: int = 200_000,
            verbose: bool = False) -> VEResult:
        """Advance the model to ``end_time`` (s) and record ``output_times``."""
        t0_wall = _time.perf_counter()
        g = self.grid
        n = g.ncells

        if output_times is None:
            output_times = np.linspace(0.0, end_time, 41)
        output_times = np.asarray(sorted(set(np.append(output_times, end_time))), float)
        output_times = output_times[output_times <= end_time + 1e-9]

        psi = self.psi_init.ravel().copy()
        vco2 = np.zeros(n)
        hmax = np.zeros(n)
        wells_cells = self._well_cells(wells)

        rec_dp, rec_h, rec_hmax = [], [], []
        rec_bhp = {w.name: [] for w in wells}
        warnings: list[str] = []
        injected_total = 0.0
        capped_volume = 0.0

        t = 0.0
        dt_next = dt_init          # step the solver *wants* to take
        step = 0
        next_out = 0

        def record(tnow, psi_, h_, hmax_):
            rec_dp.append((psi_ - self.psi_init.ravel()).reshape(g.shape).copy())
            rec_h.append(h_.reshape(g.shape).copy())
            rec_hmax.append(hmax_.reshape(g.shape).copy())
            for w, c in wells_cells:
                rec_bhp[w.name].append(float(psi_[c]))

        h, hmax = self._state_from_volume(vco2, hmax)
        if output_times[0] <= 0.0:
            record(0.0, psi, h, hmax)
            next_out = 1

        while t < end_time - 1e-6 and step < max_steps:
            # do not step past the next requested output time, and do not let
            # that clipping shrink the step the solver wants next time round
            target = output_times[next_out] if next_out < len(output_times) else end_time
            # a well starting or stopping is a discontinuity: land exactly on it
            for w in wells:
                for t0, _ in sorted(w.schedule):
                    if t + 1e-9 < t0 < target:
                        target = t0
                        break
            dt = min(dt_next, dt_max, target - t)
            if dt <= 0:
                next_out += 1
                continue

            h, hmax = self._state_from_volume(vco2, hmax)
            lam_c, lam_w = self._mobilities(h, hmax)

            # ---- gravity/structure heads on faces (explicit) -----------
            def face_terms(iL, iR, T, _psi=psi, _h=h, _lc=lam_c, _lw=lam_w):
                dpsi = _psi[iL] - _psi[iR]
                gw = self.rho_w * U.G * (self.elev[iL] - self.elev[iR])
                gc = (self.drho * U.G * (_h[iL] - _h[iR])
                      + self.rho_c * U.G * (self.elev[iL] - self.elev[iR]))
                Lc = self._upwind(T, _lc, iL, iR, dpsi + gc)
                Lw = self._upwind(T, _lw, iL, iR, dpsi + gw)
                return gw, gc, Lc, Lw

            gwx, gcx, Lcx, Lwx = face_terms(self.ix_L, self.ix_R, self.Txf)
            gwy, gcy, Lcy, Lwy = face_terms(self.iy_B, self.iy_T, self.Tyf)

            # ---- assemble the implicit pressure system -----------------
            acc = self.accum_base / dt
            rows, cols, vals = [], [], []
            rhs = acc * psi

            for iA, iB, Lc, Lw, gc, gw in (
                (self.ix_L, self.ix_R, Lcx, Lwx, gcx, gwx),
                (self.iy_B, self.iy_T, Lcy, Lwy, gcy, gwy),
            ):
                Lt = Lc + Lw
                rows.extend([iA, iB, iA, iB])
                cols.extend([iA, iB, iB, iA])
                vals.extend([Lt, Lt, -Lt, -Lt])
                grav = Lc * gc + Lw * gw
                np.add.at(rhs, iA, -grav)
                np.add.at(rhs, iB, +grav)

            rows = np.concatenate(rows)
            cols = np.concatenate(cols)
            vals = np.concatenate(vals)

            diag_extra = np.zeros(n)
            if self.boundary == "constant_pressure":
                pb = (self.boundary_pressure if self.boundary_pressure is not None
                      else None)
                edge = np.zeros(g.shape, dtype=bool)
                edge[0, :] = edge[-1, :] = True
                edge[:, 0] = edge[:, -1] = True
                ei = self.idx[edge]
                Tb = (self.props.permeability.ravel()[ei] * self.thick[ei]
                      * self.krw0 / self.mu_w * 2.0)
                diag_extra[ei] += Tb
                target_psi = (self.psi_init.ravel()[ei] if pb is None
                              else pb - self.rho_w * U.G
                              * (self.elev[ei] - self.reference_elevation))
                np.add.at(rhs, ei, Tb * target_psi)

            # ---- wells -------------------------------------------------
            q_co2 = np.zeros(n)
            q_tot = np.zeros(n)
            for w, c in wells_cells:
                q = w.rate_at(t)
                if q == 0.0:
                    continue
                if w.kind == "injector":
                    qv = q / self.rho_c
                    q_co2[c] += qv
                    q_tot[c] += qv
                else:
                    q_tot[c] -= abs(q)
            rhs += q_tot

            # inactive cells: pin to their initial value
            inactive = ~self.act_flat
            if inactive.any():
                ii = np.where(inactive)[0]
                diag_extra[ii] += 1.0
                rhs[ii] = self.psi_init.ravel()[ii]

            A = csr_matrix((vals, (rows, cols)), shape=(n, n))
            A = A + csr_matrix((acc + diag_extra, (np.arange(n), np.arange(n))),
                               shape=(n, n))
            psi_new = spsolve(A.tocsc(), rhs)
            if not np.all(np.isfinite(psi_new)):
                warnings.append(f"non-finite pressure at t = {U.time_out(t, 'yr'):.2f} yr; "
                                "step rejected and dt halved")
                dt_next = dt * 0.5
                if dt_next < U.time(1.0, "hour"):
                    warnings.append("pressure solve failed irrecoverably")
                    break
                continue

            # ---- explicit CO2 transport --------------------------------
            def co2_flux(iL, iR, Lc, gc, _psi=psi_new):
                return Lc * ((_psi[iL] - _psi[iR]) + gc)

            Fx = co2_flux(self.ix_L, self.ix_R, Lcx, gcx)
            Fy = co2_flux(self.iy_B, self.iy_T, Lcy, gcy)

            div = np.zeros(n)
            np.add.at(div, self.ix_L, Fx)
            np.add.at(div, self.ix_R, -Fx)
            np.add.at(div, self.iy_B, Fy)
            np.add.at(div, self.iy_T, -Fy)

            net = q_co2 - div            # m^3/s into each cell
            # CFL: no cell may gain/lose more than `cfl` of its CO2 capacity
            capacity = np.maximum(self.pv * self.sg_mob * self.thick, 1e-9)
            with np.errstate(divide="ignore", invalid="ignore"):
                dt_cfl = cfl * np.min(capacity / np.maximum(np.abs(net), 1e-12))
            dt_cfl = float(max(dt_cfl, U.time(1.0, "hour")))
            if dt_cfl < dt:
                # the transport step is the binding constraint: shorten this
                # step (the implicit pressure solve stays valid, it is simply
                # evaluated over a shorter interval) and remember the limit
                dt = dt_cfl
            dt_next = min(dt_cfl * 1.25, dt_max)

            vco2 = vco2 + dt * net
            if self.dissolution > 0:
                vco2 *= max(0.0, 1.0 - self.dissolution * dt / U.YEAR)
            vco2 = np.maximum(vco2, 0.0)

            # ---- overfill (plume reaches the base of the interval) -----
            vmax = self.pv * self.sg_mob * self.thick
            over = vco2 - vmax
            for _ in range(5):
                if not np.any(over > 1e-9):
                    break
                spill = np.where(over > 0, over, 0.0)
                vco2 -= spill
                # push the excess to the lowest-potential open neighbour
                moved = np.zeros(n)
                h_tmp, _ = self._state_from_volume(vco2, hmax)
                phic = psi_new + self.drho * U.G * h_tmp + self.rho_c * U.G * self.elev
                for iA, iB in ((self.ix_L, self.ix_R), (self.iy_B, self.iy_T)):
                    down = np.where(phic[iA] > phic[iB], iB, iA)
                    src = np.where(phic[iA] > phic[iB], iA, iB)
                    np.add.at(moved, down, spill[src] * 0.25)
                vco2 = vco2 + moved
                leftover = spill.sum() - moved.sum()
                capped_volume += max(leftover, 0.0)
                over = vco2 - vmax

            psi = psi_new
            t += dt
            step += 1
            injected_total += sum(
                max(w.rate_at(t - dt), 0.0) * dt for w, _ in wells_cells
                if w.kind == "injector")

            if next_out < len(output_times) and t >= output_times[next_out] - 1e-6:
                h, hmax = self._state_from_volume(vco2, hmax)
                record(t, psi, h, hmax)
                next_out += 1
            if verbose and step % 100 == 0:
                print(f"  step {step:6d}  t = {U.time_out(t, 'yr'):8.2f} yr  "
                      f"dt = {U.time_out(dt, 'day'):8.2f} d  "
                      f"max dP = {U.pressure_out((psi - self.psi_init.ravel()).max(), 'psi'):8.1f} psi",
                      flush=True)

        # make sure the final state is recorded
        h, hmax = self._state_from_volume(vco2, hmax)
        while next_out < len(output_times):
            record(t, psi, h, hmax)
            next_out += 1

        if step >= max_steps:
            warnings.append(
                f"stopped at max_steps = {max_steps} (t = {U.time_out(t, 'yr'):.1f} yr "
                f"of {U.time_out(end_time, 'yr'):.1f} yr requested)")

        expected_vol = injected_total / self.rho_c
        actual_vol = vco2.sum() + capped_volume
        mb_err = (abs(actual_vol - expected_vol) / expected_vol) if expected_vol > 0 else 0.0
        if mb_err > 0.02:
            warnings.append(
                f"CO2 mass-balance error {mb_err:.1%}; reduce cfl or dt_max, or "
                "refine the grid")
        if capped_volume > 0.01 * max(expected_vol, 1e-30):
            warnings.append(
                f"{capped_volume / max(expected_vol, 1e-30):.1%} of the injected CO2 "
                "filled the full interval thickness -- the vertical-equilibrium "
                "assumption is stressed; check net thickness and injection rate")

        res = VEResult(
            grid=g,
            times=output_times[:len(rec_dp)],
            dp=np.array(rec_dp),
            h=np.array(rec_h),
            hmax=np.array(rec_hmax),
            bhp={k: np.array(v) for k, v in rec_bhp.items()},
            mass_balance_error=float(mb_err),
            steps=step,
            runtime_s=_time.perf_counter() - t0_wall,
            warnings=warnings,
            meta={"boundary": self.boundary,
                  "dissolution_fraction_per_year": self.dissolution,
                  "properties": self.props.describe()},
        )
        return res


__all__ = ["VESolver", "VEResult", "VEWell"]
