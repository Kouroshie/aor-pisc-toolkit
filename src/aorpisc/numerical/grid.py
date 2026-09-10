"""Areal Cartesian grid and cell properties for the vertical-equilibrium solver.

The grid is 2-D in plan view.  The third dimension is carried as per-cell
*thickness* and *top-surface elevation*, which is what lets a
vertical-equilibrium model represent dip, structural closure, thickness
pinch-outs and a heterogeneous permeability field without the cost of a
3-D simulation.  EPA 816-R-13-005 Section 2.2.7 warns that "overly coarse
grids were not able to simulate buoyancy-driven flow"; :meth:`Grid.resolution_check`
turns that warning into a number you can put in a permit application.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .. import units as U


@dataclass
class Grid:
    """Cartesian areal grid, uniform or graded.

    Cell ``(j, i)`` is row ``j``, column ``i``.  Arrays are stored ``(ny, nx)``
    so they plot directly with ``imshow``/``pcolormesh``.

    ``dx`` and ``dy`` may each be a scalar (uniform spacing) or a 1-D array of
    per-column / per-row widths.  Graded spacing is what resolves the tension
    every Class VI model runs into: the plume needs cells small enough to see
    a buoyant tongue, and the pressure front needs a domain tens of miles
    across.  A uniform grid cannot do both without a prohibitive cell count.
    :meth:`telescoping` builds the usual answer -- fine cells over the well
    field, geometrically growing outward -- which is the "adaptive grid block
    size ... refinement" EPA describes in Section 2.3.1.
    """

    nx: int
    ny: int
    dx: float | np.ndarray      # m, scalar or per-column
    dy: float | np.ndarray      # m, scalar or per-row
    x0: float = 0.0             # m, left edge
    y0: float = 0.0             # m, bottom edge

    # ------------------------------------------------------------------ #
    @classmethod
    def telescoping(cls, *, center: tuple[float, float], fine_cell: float,
                    fine_half_width: float, total_half_width: float,
                    growth: float = 1.12, max_cell: float | None = None
                    ) -> Grid:
        """Fine cells over the well field, growing geometrically outward.

        ``fine_cell`` cells cover +/- ``fine_half_width`` of ``center``; beyond
        that each successive cell is ``growth`` times wider until the domain
        reaches +/- ``total_half_width``.
        """
        if total_half_width <= fine_half_width:
            n = max(int(round(2 * total_half_width / fine_cell)), 1)
            return cls(nx=n, ny=n, dx=fine_cell, dy=fine_cell,
                       x0=center[0] - n * fine_cell / 2,
                       y0=center[1] - n * fine_cell / 2)

        n_fine = max(int(round(2 * fine_half_width / fine_cell)), 2)
        widths = [fine_cell] * n_fine
        reach = n_fine * fine_cell / 2
        w = fine_cell
        outer: list[float] = []
        cap = max_cell if max_cell is not None else 12.0 * fine_cell
        while reach < total_half_width and len(outer) < 400:
            w = min(w * growth, cap)
            outer.append(w)
            reach += w
        widths = list(reversed(outer)) + widths + outer
        arr = np.asarray(widths, float)
        span = arr.sum()
        return cls(nx=len(arr), ny=len(arr), dx=arr.copy(), dy=arr.copy(),
                   x0=center[0] - span / 2, y0=center[1] - span / 2)

    # ------------------------------------------------------------------ #
    @property
    def shape(self) -> tuple[int, int]:
        return (self.ny, self.nx)

    @property
    def ncells(self) -> int:
        return self.nx * self.ny

    @property
    def dxs(self) -> np.ndarray:
        return (np.full(self.nx, float(self.dx)) if np.ndim(self.dx) == 0
                else np.asarray(self.dx, float))

    @property
    def dys(self) -> np.ndarray:
        return (np.full(self.ny, float(self.dy)) if np.ndim(self.dy) == 0
                else np.asarray(self.dy, float))

    @property
    def uniform(self) -> bool:
        return np.ndim(self.dx) == 0 and np.ndim(self.dy) == 0

    @property
    def areas(self) -> np.ndarray:
        """Per-cell plan area, shape ``(ny, nx)``."""
        return np.outer(self.dys, self.dxs)

    @property
    def cell_area(self) -> float:
        """Mean cell area.  Use :attr:`areas` for anything quantitative."""
        return float(self.areas.mean())

    @property
    def xf(self) -> np.ndarray:
        """Column face coordinates, length ``nx + 1``."""
        return self.x0 + np.concatenate([[0.0], np.cumsum(self.dxs)])

    @property
    def yf(self) -> np.ndarray:
        return self.y0 + np.concatenate([[0.0], np.cumsum(self.dys)])

    @property
    def xc(self) -> np.ndarray:
        f = self.xf
        return 0.5 * (f[:-1] + f[1:])

    @property
    def yc(self) -> np.ndarray:
        f = self.yf
        return 0.5 * (f[:-1] + f[1:])

    def meshgrid(self) -> tuple[np.ndarray, np.ndarray]:
        return np.meshgrid(self.xc, self.yc)

    @property
    def extent(self) -> tuple[float, float, float, float]:
        """``(xmin, xmax, ymin, ymax)`` of the outer edges, for plotting."""
        return (self.xf[0], self.xf[-1], self.yf[0], self.yf[-1])

    def index(self, x: float, y: float) -> tuple[int, int] | None:
        """Row/column containing ``(x, y)``, or ``None`` if outside."""
        i = int(np.searchsorted(self.xf, x, side="right") - 1)
        j = int(np.searchsorted(self.yf, y, side="right") - 1)
        if 0 <= i < self.nx and 0 <= j < self.ny:
            return j, i
        return None

    def resolution_check(self, plume_radius: float,
                         min_cells_across: int = 20,
                         center: tuple[float, float] | None = None) -> dict:
        """Is the grid fine enough to resolve a plume of this radius?

        On a graded grid the test is applied to the cells the plume actually
        occupies, not to the coarse outer padding.
        """
        dxs, dys = self.dxs, self.dys
        if center is not None and not self.uniform:
            xc, yc = self.xc, self.yc
            selx = np.abs(xc - center[0]) <= plume_radius
            sely = np.abs(yc - center[1]) <= plume_radius
            dxs = dxs[selx] if selx.any() else dxs
            dys = dys[sely] if sely.any() else dys
        rep = float(max(np.median(dxs), np.median(dys)))
        across = 2.0 * plume_radius / rep
        return {
            "representative_cell_ft": U.length_out(rep, "ft"),
            "finest_cell_ft": U.length_out(float(min(self.dxs.min(), self.dys.min())), "ft"),
            "coarsest_cell_ft": U.length_out(float(max(self.dxs.max(), self.dys.max())), "ft"),
            "cells_across_plume": across,
            "target": min_cells_across,
            "verdict": ("adequate" if across >= min_cells_across
                        else f"REFINE: only {across:.0f} cells across the plume; "
                             f"EPA cautions that coarse grids misrepresent "
                             f"buoyancy-driven migration"),
        }

    def describe(self) -> dict:
        return {
            "nx": self.nx, "ny": self.ny,
            "uniform": self.uniform,
            "finest_cell_ft": U.length_out(float(min(self.dxs.min(), self.dys.min())), "ft"),
            "coarsest_cell_ft": U.length_out(float(max(self.dxs.max(), self.dys.max())), "ft"),
            "domain_mi": [U.length_out(float(self.dxs.sum()), "mi"),
                          U.length_out(float(self.dys.sum()), "mi")],
            "cells": self.ncells,
        }


def _broadcast(value, shape, name) -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    if arr.ndim == 0:
        return np.full(shape, float(arr))
    if arr.shape != shape:
        raise ValueError(f"{name} has shape {arr.shape}, expected {shape}")
    return arr.astype(float).copy()


@dataclass
class GridProperties:
    """Per-cell static properties.

    Every field accepts either a scalar (uniform) or a full ``(ny, nx)``
    array, so a homogeneous screening case and a geostatistical realisation
    use the same code path.

    ``top_elevation`` is the elevation of the top of the injection zone
    (metres, positive **up**, any consistent datum).  Its gradient is what
    drives up-dip buoyant migration, so a structure map dropped in here is the
    single most valuable piece of site data the model can use.

    ``fault_mult_x`` / ``fault_mult_y`` multiply the transmissibility of the
    faces between column ``i`` and ``i+1`` (shape ``(ny, nx-1)``) and between
    row ``j`` and ``j+1`` (shape ``(ny-1, nx)``).  Set to 0 for a sealing
    fault, to a small number for a partially sealing one.
    """

    grid: Grid
    permeability: np.ndarray = field(default=None)      # m^2
    porosity: np.ndarray = field(default=None)
    thickness: np.ndarray = field(default=None)         # m, net
    top_elevation: np.ndarray = field(default=None)     # m, positive up
    active: np.ndarray = field(default=None)            # bool
    fault_mult_x: np.ndarray = field(default=None)
    fault_mult_y: np.ndarray = field(default=None)
    anisotropy_y_over_x: np.ndarray = field(default=None)

    def __post_init__(self):
        s = self.grid.shape
        self.permeability = _broadcast(
            self.permeability if self.permeability is not None else U.permeability(50, "mD"),
            s, "permeability")
        self.porosity = _broadcast(
            self.porosity if self.porosity is not None else 0.15, s, "porosity")
        self.thickness = _broadcast(
            self.thickness if self.thickness is not None else U.length(100, "ft"),
            s, "thickness")
        self.top_elevation = _broadcast(
            self.top_elevation if self.top_elevation is not None else 0.0,
            s, "top_elevation")
        self.anisotropy_y_over_x = _broadcast(
            self.anisotropy_y_over_x if self.anisotropy_y_over_x is not None else 1.0,
            s, "anisotropy_y_over_x")
        if self.active is None:
            self.active = np.ones(s, dtype=bool)
        else:
            self.active = np.asarray(self.active, dtype=bool)
            if self.active.shape != s:
                raise ValueError(f"active mask shape {self.active.shape} != {s}")
        if self.fault_mult_x is None:
            self.fault_mult_x = np.ones((s[0], s[1] - 1))
        if self.fault_mult_y is None:
            self.fault_mult_y = np.ones((s[0] - 1, s[1]))

    # ------------------------------------------------------------------ #
    @property
    def pore_volume(self) -> np.ndarray:
        return self.porosity * self.thickness * self.grid.areas * self.active

    def dip_angle(self) -> np.ndarray:
        """Local dip of the top surface in degrees."""
        gy, gx = np.gradient(self.top_elevation, self.grid.yc, self.grid.xc)
        return np.degrees(np.arctan(np.hypot(gx, gy)))

    def add_dip(self, dip_degrees: float, azimuth_degrees: float = 0.0,
                reference: tuple[float, float] | None = None) -> GridProperties:
        """Impose a uniform structural dip on the top surface.

        ``azimuth_degrees`` is the compass direction the formation dips
        *towards* (0 = north / +y, 90 = east / +x), matching the convention on
        a structure map.
        """
        X, Y = self.grid.meshgrid()
        if reference is None:
            reference = (X.mean(), Y.mean())
        az = np.radians(azimuth_degrees)
        # unit vector pointing down-dip
        ux, uy = np.sin(az), np.cos(az)
        s = (X - reference[0]) * ux + (Y - reference[1]) * uy
        self.top_elevation = self.top_elevation - s * np.tan(np.radians(dip_degrees))
        return self

    def add_sealing_fault(self, points: list[tuple[float, float]],
                          multiplier: float = 0.0) -> GridProperties:
        """Set transmissibility multipliers along a polyline fault trace.

        ``points`` are ``(x, y)`` vertices in model coordinates.  Every grid
        face the trace crosses gets ``multiplier`` (0 = fully sealing).
        """
        g = self.grid
        pts = np.asarray(points, float)
        for a, b in zip(pts[:-1], pts[1:], strict=True):
            fine = float(min(g.dxs.min(), g.dys.min()))
            n = max(int(np.hypot(*(b - a)) / fine * 4), 2)
            for t in np.linspace(0.0, 1.0, n):
                p = a + t * (b - a)
                idx = g.index(p[0], p[1])
                if idx is None:
                    continue
                j, i = idx
                # block the face on the side the trace is heading toward
                if i < g.nx - 1:
                    self.fault_mult_x[j, i] = multiplier
                if i > 0:
                    self.fault_mult_x[j, i - 1] = multiplier
                if abs(b[1] - a[1]) > abs(b[0] - a[0]):
                    continue
                if j < g.ny - 1:
                    self.fault_mult_y[j, i] = multiplier
                if j > 0:
                    self.fault_mult_y[j - 1, i] = multiplier
        return self

    def describe(self) -> dict:
        act = self.active
        return {
            "grid": self.grid.describe(),
            "active_cells": int(act.sum()),
            "permeability_mD": {
                "min": U.permeability_out(float(self.permeability[act].min()), "mD"),
                "mean": U.permeability_out(float(self.permeability[act].mean()), "mD"),
                "max": U.permeability_out(float(self.permeability[act].max()), "mD"),
            },
            "porosity": {"min": float(self.porosity[act].min()),
                         "mean": float(self.porosity[act].mean()),
                         "max": float(self.porosity[act].max())},
            "thickness_ft": {"min": U.length_out(float(self.thickness[act].min()), "ft"),
                             "mean": U.length_out(float(self.thickness[act].mean()), "ft"),
                             "max": U.length_out(float(self.thickness[act].max()), "ft")},
            "max_dip_deg": float(self.dip_angle()[act].max()),
            "sealing_faces": int((self.fault_mult_x < 1).sum() + (self.fault_mult_y < 1).sum()),
            "total_pore_volume_m3": float(self.pore_volume.sum()),
        }


def lognormal_permeability(grid: Grid, mean_md: float, sigma_ln: float = 1.0,
                           correlation_length: float = 1000.0,
                           anisotropy: float = 1.0, seed: int | None = None
                           ) -> np.ndarray:
    """Correlated log-normal permeability field (m^2).

    A Gaussian random field is generated by filtering white noise with a
    Gaussian kernel of the requested correlation length, then exponentiated.
    This gives the kind of heterogeneity EPA describes in Section 2.2.1 --
    "geostatistical and stochastic methods ... to create a statistical ensemble
    of possible permeability distributions" -- without pulling in a full
    geostatistics stack.  For real work, import the operator's own realisation
    instead.
    """
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(grid.shape)
    lx = max(correlation_length / float(np.median(grid.dxs)), 0.5)
    ly = max(correlation_length * anisotropy / float(np.median(grid.dys)), 0.5)

    def _kernel(n, length):
        half = min(int(np.ceil(3 * length)), n)
        t = np.arange(-half, half + 1)
        k = np.exp(-0.5 * (t / length) ** 2)
        return k / np.sqrt((k ** 2).sum())

    kx, ky = _kernel(grid.nx, lx), _kernel(grid.ny, ly)
    from scipy.ndimage import convolve1d
    sm = convolve1d(noise, kx, axis=1, mode="reflect")
    sm = convolve1d(sm, ky, axis=0, mode="reflect")
    sm = (sm - sm.mean()) / (sm.std() + 1e-30)
    field_md = mean_md * np.exp(sigma_ln * sm - 0.5 * sigma_ln ** 2)
    return U.permeability(field_md, "mD")


__all__ = ["Grid", "GridProperties", "lognormal_permeability"]
