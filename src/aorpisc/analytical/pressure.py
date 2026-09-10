"""Multi-well pressure buildup by superposition, with boundaries and two-phase skin.

This is the analytical engine behind the pressure-front half of the AoR.  It
is deliberately more general than the pattern-based analytical tools in common
use: wells sit at arbitrary coordinates, each carries its own step-rate
schedule (so shut-ins, ramp-ups and staggered start-ups are honoured), brine
extractors are just wells with negative rate, and no-flow or constant-pressure
boundaries are imposed by an image-well lattice rather than by assuming a
square reservoir centred in a square basin.

Physics
-------
Far from any injector the displaced fluid is brine, so the pressure response
is the single-phase line-source (Theis) solution

    dP(r, t) = q_res * mu_w / (4 pi k H) * E1( r^2 / (4 eta t) ),
    eta = k / (phi mu_w c_t)

with ``q_res`` the CO2 injection rate converted to reservoir volume.  The
two-phase and dry-out region around the wellbore adds an extra pressure drop
that behaves as a skin; it is evaluated by integrating the Buckley-Leverett
saturation profile,

    S_a(t) = integral_{rw}^{rf(t)} ( lambda_w0 / lambda_t(r) - 1 ) d ln r

which is the composite-radial form of the apparent skin used by Mathias et al.
(2011) and by EASiTool.  Because ``S_a`` acts only inside ``r_f``, it changes
bottomhole pressure and injectivity but leaves the far-field pressure front
essentially untouched -- which is why a pressure-front AoR is far less
sensitive to relative permeability than a plume AoR.

Time superposition uses rate differences; space superposition adds wells and
their images.  Both are exact for the linear diffusion equation.

Limitations, stated plainly
---------------------------
Homogeneous, isotropic, constant-thickness, isothermal, single-layer, and
slightly compressible.  Heterogeneity, dip, faults and layering need
:mod:`aorpisc.numerical.ve_solver` or an imported operator simulation.  EPA
816-R-13-005 Section 2.3.2 says analytical models "may be used to complement
numerical modeling efforts" and as "a relatively simple comparative check on
numerical modeling results" -- that is exactly the role intended here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.special import exp1

from .. import units as U
from .relperm import BrooksCorey, BuckleyLeverett, RelPerm


# ==========================================================================
# wells
# ==========================================================================
@dataclass
class Well:
    """An injector, extractor or monitoring point.

    ``schedule`` is a list of ``(start_time_s, rate)`` pairs held constant
    until the next entry.  Rates are **mass** rates in kg/s for CO2 injectors
    (positive) and **volumetric** rates in m^3/s for brine extractors
    (negative).  A rate of 0 shuts the well in.
    """

    name: str
    x: float
    y: float
    schedule: list[tuple[float, float]] = field(default_factory=list)
    kind: str = "injector"        # injector | extractor | monitor
    radius: float = 0.1           # wellbore radius, m
    top_perf: float = float("nan")
    bottom_perf: float = float("nan")

    def rate_at(self, t: float) -> float:
        r = 0.0
        for t0, q in sorted(self.schedule):
            if t >= t0:
                r = q
            else:
                break
        return r

    def steps(self) -> list[tuple[float, float]]:
        """Rate *changes*: ``(t, delta_q)`` pairs for time superposition."""
        out, prev = [], 0.0
        for t0, q in sorted(self.schedule):
            if q != prev:
                out.append((t0, q - prev))
                prev = q
        return out

    def cumulative_mass(self, t: float) -> float:
        """Cumulative injected mass (kg) at time ``t`` for a CO2 injector."""
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

    def end_of_injection(self) -> float:
        """Time at which the well last stops injecting (s)."""
        last = 0.0
        for t0, q in sorted(self.schedule):
            if q > 0:
                last = t0
            elif q == 0 and last:
                return t0
        return last


def constant_rate_well(name: str, x: float, y: float, mass_rate: float,
                       start: float, stop: float, **kw) -> Well:
    """Convenience constructor for a well injecting at a constant rate."""
    return Well(name=name, x=x, y=y,
                schedule=[(start, mass_rate), (stop, 0.0)], **kw)


# ==========================================================================
# boundaries
# ==========================================================================
@dataclass
class Boundary:
    """Model-domain boundary condition.

    ``kind`` is ``"infinite"`` (no boundaries), or ``"rectangle"`` with
    ``xmin, xmax, ymin, ymax`` and a per-side condition in ``sides``, each of
    ``"noflow"`` or ``"constant_pressure"``.  Boundaries are imposed with an
    image-well lattice built by repeated reflection to ``order`` levels.

    EPA (Section 3.3.3.2) asks that boundary conditions and domain extent be
    tested so they "do not result in numerical artifacts that impact the model
    results".  :meth:`influence_check` reports how close the pressure front
    gets to each boundary so that test is documented rather than assumed.
    """

    kind: str = "infinite"
    xmin: float = 0.0
    xmax: float = 0.0
    ymin: float = 0.0
    ymax: float = 0.0
    sides: tuple[str, str, str, str] = ("noflow",) * 4  # xmin, xmax, ymin, ymax
    order: int = 4
    max_images: int = 4000

    @staticmethod
    def _images_1d(p: float, lo: float, hi: float, s_lo: float, s_hi: float,
                   order: int) -> tuple[np.ndarray, np.ndarray]:
        """Image positions and weights for a source in the slab ``[lo, hi]``.

        Reflecting about ``lo`` then about ``hi`` is a translation by ``2L``
        that multiplies the weight by ``s_lo * s_hi``, so the whole lattice is

            p + 2mL   with weight (s_lo s_hi)^|m|
            2lo - p + 2mL  with weight s_lo (s_lo s_hi)^|m|

        for integer ``m``.  Building it in closed form rather than by
        breadth-first reflection matters for constant-pressure boundaries: the
        lattice has to stay symmetric in ``m`` or the positive and negative
        images no longer cancel on the boundary and the "constant pressure"
        edge is not constant at all.
        """
        L = hi - lo
        u = p - lo
        prod = s_lo * s_hi
        m = np.arange(-(order + 2), order + 3, dtype=float)
        w = prod ** np.abs(m)
        pos = np.concatenate([lo + u + 2.0 * m * L, lo - u + 2.0 * m * L])
        wts = np.concatenate([w, s_lo * w])
        # Truncate by distance from the slab centre, not by reflection index.
        # Index truncation clips the two families at different places and
        # leaves the lattice lopsided, which shows up as a spurious asymmetry
        # in the pressure field even for a well on the axis of symmetry.
        centre = 0.5 * (lo + hi)
        keep = np.abs(pos - centre) <= (order + 0.5) * L + 1e-9
        return pos[keep], wts[keep]

    def images(self, x: float, y: float, prune_beyond: float | None = None
               ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Image-well positions and signs for a source at ``(x, y)``.

        ``prune_beyond`` drops images further than that distance from the
        domain centre.  An image contributes nothing once it is many diffusion
        lengths away, so pruning on ``sqrt(4 eta t)`` keeps a large closed
        domain from turning into a thousand-term sum for no gain.
        """
        if self.kind == "infinite":
            return np.array([x]), np.array([y]), np.array([1.0])

        sign = {"noflow": 1.0, "constant_pressure": -1.0}
        sx0, sx1, sy0, sy1 = (sign[s] for s in self.sides)
        px, wx = self._images_1d(x, self.xmin, self.xmax, sx0, sx1, self.order)
        py, wy = self._images_1d(y, self.ymin, self.ymax, sy0, sy1, self.order)
        XS, YS = np.meshgrid(px, py)
        WS = np.outer(wy, wx)
        xs, ys, ws = XS.ravel(), YS.ravel(), WS.ravel()

        if prune_beyond is not None and np.isfinite(prune_beyond):
            cx = 0.5 * (self.xmin + self.xmax)
            cy = 0.5 * (self.ymin + self.ymax)
            keep = np.hypot(xs - cx, ys - cy) <= prune_beyond
            if keep.any():
                xs, ys, ws = xs[keep], ys[keep], ws[keep]
        if xs.size > self.max_images:
            cx = 0.5 * (self.xmin + self.xmax)
            cy = 0.5 * (self.ymin + self.ymax)
            order_by = np.argsort(np.hypot(xs - cx, ys - cy))[:self.max_images]
            xs, ys, ws = xs[order_by], ys[order_by], ws[order_by]
        return xs, ys, ws

    def describe(self) -> dict:
        if self.kind == "infinite":
            return {"kind": "infinite acting"}
        return {
            "kind": "rectangle", "sides": list(self.sides),
            "extent_ft": [U.length_out(self.xmax - self.xmin, "ft"),
                          U.length_out(self.ymax - self.ymin, "ft")],
            "image_order": self.order,
        }


# ==========================================================================
# the aquifer model
# ==========================================================================
@dataclass
class AquiferModel:
    """Homogeneous single-layer aquifer for superposed pressure calculations."""

    permeability: float          # m^2
    thickness: float             # m (net)
    porosity: float
    total_compressibility: float  # 1/Pa (rock + fluid)
    mu_brine: float              # Pa.s
    mu_co2: float                # Pa.s
    rho_co2: float               # kg/m^3
    initial_pressure: float      # Pa
    relperm: RelPerm = field(default_factory=BrooksCorey)
    boundary: Boundary = field(default_factory=Boundary)
    include_two_phase_skin: bool = True
    dryout_radius_factor: float = 0.0   # r_dry / r_front, 0 disables dry-out

    def __post_init__(self):
        self._bl = BuckleyLeverett(self.relperm, self.mu_co2, self.mu_brine)
        self._lambda_w0 = self.relperm.krw(0.0) / self.mu_brine

    # ------------------------------------------------------------------ #
    @property
    def diffusivity(self) -> float:
        """Hydraulic diffusivity ``eta = k / (phi mu c_t)`` in m^2/s."""
        return self.permeability / (self.porosity * self.mu_brine
                                    * self.total_compressibility)

    @property
    def transmissibility(self) -> float:
        """``k H / mu_w`` in m^3/(Pa.s) per unit length."""
        return self.permeability * self.thickness / self.mu_brine

    def reservoir_rate(self, well: Well, t: float) -> float:
        """Volumetric rate (m^3/s) entering the aquifer from ``well`` at ``t``."""
        q = well.rate_at(t)
        return q / self.rho_co2 if well.kind == "injector" else q

    # ------------------------------------------------------------------ #
    def front_radius(self, well: Well, t: float) -> float:
        """CO2 Buckley-Leverett front radius (m) for one injector."""
        if well.kind != "injector":
            return 0.0
        m = well.cumulative_mass(t)
        if m <= 0:
            return 0.0
        vol = m / self.rho_co2
        return float(np.sqrt(vol * self._bl.shock_slope
                             / (np.pi * self.porosity * self.thickness)))

    def apparent_skin(self, well: Well, t: float, n: int = 300) -> float:
        """Composite-radial two-phase apparent skin ``S_a`` (dimensionless).

        Integrates ``(lambda_w0 / lambda_t - 1)`` over ``d ln r`` across the
        two-phase bank, plus a fully dry (Sg = 1) inner annulus if
        ``dryout_radius_factor`` is set.
        """
        if not self.include_two_phase_skin or well.kind != "injector":
            return 0.0
        rf = self.front_radius(well, t)
        rw = max(well.radius, 1e-3)
        if rf <= rw:
            return 0.0

        r_prof, s_prof = self._bl.saturation_profile(
            1.0, 1.0, self.porosity, self.thickness, n=n)
        # profile is self-similar: rescale so the shock sits at rf
        r_prof = r_prof / max(r_prof.max(), 1e-30) * rf
        # inside the rarefaction the formation is at maximum CO2 saturation all
        # the way to the wellbore; carry that plateau down to r_w
        if r_prof[0] > rw:
            r_prof = np.concatenate([[rw], r_prof])
            s_prof = np.concatenate([[s_prof[0]], s_prof])

        r_dry = self.dryout_radius_factor * rf
        lr = np.log(np.clip(r_prof, rw, rf))
        krg = np.asarray(self.relperm.krg(s_prof), float)
        krw = np.asarray(self.relperm.krw(s_prof), float)
        lam_t = krg / self.mu_co2 + krw / self.mu_brine
        integrand = self._lambda_w0 / np.maximum(lam_t, 1e-300) - 1.0

        s_a = float(np.trapezoid(integrand, lr)) if hasattr(np, "trapezoid") \
            else float(np.trapz(integrand, lr))

        if r_dry > rw:
            lam_dry = self.relperm.krg(1.0 - self.relperm.swr) / self.mu_co2
            s_a += (self._lambda_w0 / lam_dry - 1.0) * np.log(r_dry / rw)
        return s_a

    # ------------------------------------------------------------------ #
    def _line_source(self, r2: np.ndarray, dt: float, q: float) -> np.ndarray:
        """Theis response to a rate step ``q`` acting for ``dt`` seconds."""
        if dt <= 0 or q == 0.0:
            return np.zeros_like(r2)
        u = r2 / (4.0 * self.diffusivity * dt)
        return (q * self.mu_brine / (4.0 * np.pi * self.permeability
                                     * self.thickness)) * exp1(np.maximum(u, 1e-300))

    def delta_p(self, x, y, t: float, wells: list[Well],
                include_skin_at_well: bool = False) -> np.ndarray:
        """Pressure increase (Pa) at ``(x, y)`` and time ``t``.

        ``x`` and ``y`` may be scalars or arrays of any matching shape.
        Superposition is exact in both time (rate steps) and space (wells and
        their images).
        """
        x = np.atleast_1d(np.asarray(x, float))
        y = np.atleast_1d(np.asarray(y, float))
        dp = np.zeros(np.broadcast(x, y).shape, dtype=float)

        # images beyond a handful of diffusion lengths cannot be felt yet
        reach = 6.0 * np.sqrt(4.0 * self.diffusivity * max(t, 1.0))
        span = np.hypot(self.boundary.xmax - self.boundary.xmin,
                        self.boundary.ymax - self.boundary.ymin)
        prune = reach + span

        for w in wells:
            if w.kind == "monitor":
                continue
            xs, ys, ws = self.boundary.images(w.x, w.y, prune_beyond=prune)
            r2 = ((x[..., None] - xs) ** 2 + (y[..., None] - ys) ** 2)
            r2 = np.maximum(r2, w.radius ** 2)
            for t0, dq in w.steps():
                if t <= t0:
                    continue
                q_res = dq / self.rho_co2 if w.kind == "injector" else dq
                dp += np.sum(self._line_source(r2, t - t0, q_res) * ws, axis=-1)

            if include_skin_at_well:
                s_a = self.apparent_skin(w, t)
                if s_a:
                    q_res = self.reservoir_rate(w, t)
                    dp_skin = (q_res * self.mu_brine * s_a
                               / (2.0 * np.pi * self.permeability * self.thickness))
                    near = ((x - w.x) ** 2 + (y - w.y) ** 2) <= (2.0 * w.radius) ** 2
                    dp = dp + np.where(near, dp_skin, 0.0)
        return dp

    def bottomhole_pressure(self, well: Well, t: float, wells: list[Well]) -> float:
        """Bottomhole pressure (Pa) of ``well``, including interference and skin."""
        dp = float(self.delta_p(well.x + well.radius, well.y, t, wells)[0])
        s_a = self.apparent_skin(well, t)
        q_res = self.reservoir_rate(well, t)
        dp += (q_res * self.mu_brine * s_a
               / (2.0 * np.pi * self.permeability * self.thickness))
        return self.initial_pressure + dp

    # ------------------------------------------------------------------ #
    def pressure_grid(self, xgrid: np.ndarray, ygrid: np.ndarray,
                      times: np.ndarray, wells: list[Well]
                      ) -> tuple[np.ndarray, np.ndarray]:
        """Pressure increase over a grid and a list of times.

        Returns ``(dp_t, dp_max)`` where ``dp_t`` has shape
        ``(n_times, ny, nx)`` and ``dp_max`` is the cell-wise maximum over all
        times.  The maximum-over-time field is what EPA asks the AoR to be
        built from: "the AoR encompass the maximum extent of the separate-phase
        plume or pressure front over the lifetime of the project and entire
        timeframe of the model simulations" (Section 3.4).
        """
        X, Y = np.meshgrid(xgrid, ygrid)
        out = np.empty((len(times), *X.shape), dtype=float)
        for i, t in enumerate(times):
            out[i] = self.delta_p(X, Y, float(t), wells)
        return out, out.max(axis=0)

    def influence_check(self, wells: list[Well], t: float,
                        threshold: float) -> dict:
        """How close the pressure front gets to each model boundary.

        Reports the pressure increase on the four boundary faces at time
        ``t``; if it approaches ``threshold`` the domain is too small and the
        AoR will be distorted by the boundary.
        """
        if self.boundary.kind == "infinite":
            return {"kind": "infinite", "boundary_effect": "none"}
        n = 101
        xs = np.linspace(self.boundary.xmin, self.boundary.xmax, n)
        ys = np.linspace(self.boundary.ymin, self.boundary.ymax, n)
        faces = {
            "xmin": self.delta_p(np.full(n, self.boundary.xmin), ys, t, wells),
            "xmax": self.delta_p(np.full(n, self.boundary.xmax), ys, t, wells),
            "ymin": self.delta_p(xs, np.full(n, self.boundary.ymin), t, wells),
            "ymax": self.delta_p(xs, np.full(n, self.boundary.ymax), t, wells),
        }
        peak = {k: float(np.max(v)) for k, v in faces.items()}
        worst = max(peak.values())
        return {
            "kind": self.boundary.kind,
            "max_dp_on_faces_psi": {k: U.pressure_out(v, "psi") for k, v in peak.items()},
            "threshold_psi": U.pressure_out(threshold, "psi"),
            "fraction_of_threshold": worst / threshold if threshold else float("nan"),
            "verdict": ("boundary influence negligible" if worst < 0.05 * threshold
                        else "ENLARGE DOMAIN: boundary pressure is a significant "
                             "fraction of the threshold and will distort the AoR"),
        }

    def describe(self) -> dict:
        return {
            "permeability_mD": U.permeability_out(self.permeability, "mD"),
            "thickness_ft": U.length_out(self.thickness, "ft"),
            "porosity": self.porosity,
            "total_compressibility_1_psi": U.compressibility_out(
                self.total_compressibility, "1/psi"),
            "diffusivity_ft2_day": self.diffusivity / U.FT ** 2 * U.DAY,
            "mu_brine_cP": U.viscosity_out(self.mu_brine, "cP"),
            "mu_co2_cP": U.viscosity_out(self.mu_co2, "cP"),
            "initial_pressure_psi": U.pressure_out(self.initial_pressure, "psi"),
            "relperm": self.relperm.describe(),
            "boundary": self.boundary.describe(),
            "two_phase_skin": self.include_two_phase_skin,
        }


def radius_of_investigation(model: AquiferModel, t: float,
                            dp_threshold: float, q_res: float) -> float:
    """Radius at which a single well's buildup equals ``dp_threshold``.

    Solves ``(q mu / 4 pi k H) E1(r^2 / 4 eta t) = dp_threshold`` by bisection.
    A fast, single-well estimate of the pressure-front radius that is useful
    for sizing the model domain before running the full superposition.
    """
    if q_res <= 0 or dp_threshold <= 0:
        return 0.0
    coef = q_res * model.mu_brine / (4.0 * np.pi * model.permeability * model.thickness)
    if coef <= 0:
        return 0.0
    target = dp_threshold / coef  # = E1(u)
    lo, hi = 1e-12, 1e3
    if exp1(lo) < target:
        return 0.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if exp1(mid) > target:
            lo = mid
        else:
            hi = mid
    u = 0.5 * (lo + hi)
    return float(np.sqrt(4.0 * model.diffusivity * t * u))


__all__ = ["Well", "constant_rate_well", "Boundary", "AquiferModel",
           "radius_of_investigation"]
