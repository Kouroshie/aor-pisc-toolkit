"""Sensitivity and uncertainty analysis for AoR delineation.

EPA is explicit that a pre-injection AoR is a prediction made before any
site-specific migration data exist, and that this "highlights the need for
uncertainty and sensitivity analyses" (816-R-13-005, Section 3.3.4); the
alternative-PISC criteria at 40 CFR 146.93(c)(2)(vi) require a sensitivity
analysis outright.  In practice most applications supply a handful of
one-parameter-at-a-time runs.

Two analyses are offered here:

:func:`tornado`
    One-parameter-at-a-time, the familiar tornado chart.  Cheap, easy to
    explain to a reviewer, and the right first step -- it tells you which
    three parameters are worth measuring better.

:func:`monte_carlo`
    Latin-hypercube sampling over joint parameter distributions, producing an
    **ensemble of AoR outcomes**.  With gridded runs this yields a
    probabilistic AoR: the fraction of realisations in which each cell falls
    inside the AoR, from which a P10/P50/P90 boundary can be contoured.

The probabilistic AoR is the piece that is genuinely missing from current
practice.  A deterministic AoR drawn from a single base-case realisation says
nothing about how much of the boundary is a modelling choice; a P90 contour
says exactly that, and gives the Director a defensible basis for asking that
corrective action extend to it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np


# ==========================================================================
# parameter distributions
# ==========================================================================
@dataclass
class Parameter:
    """An uncertain input.

    ``low``/``base``/``high`` are in whatever unit the model function expects;
    they are used directly for the tornado and to parameterise the sampling
    distribution.

    ``distribution`` is one of ``"triangular"`` (a reasonable default when
    only a range and a best estimate are known), ``"uniform"``, ``"normal"``
    (``low``/``high`` taken as +/- 2 sigma) or ``"lognormal"`` (for
    permeability, where the spread is multiplicative).  Every distribution is
    truncated to ``[low, high]``: reservoir properties do not have tails that
    reach negative values, and an untruncated normal will produce them.
    """

    name: str
    base: float
    low: float
    high: float
    distribution: str = "triangular"
    unit: str = ""

    def sample(self, u: np.ndarray) -> np.ndarray:
        """Inverse-CDF transform of uniform deviates ``u`` in [0, 1)."""
        lo, hi, mode = self.low, self.high, self.base
        d = self.distribution.lower()
        if d == "uniform":
            return lo + u * (hi - lo)
        if d == "normal":
            from scipy.special import erfinv
            mu = mode
            sigma = max((hi - lo) / 4.0, 1e-300)
            # truncated at the stated range: an untruncated normal will happily
            # hand back a negative permeability or porosity in the tails
            return np.clip(mu + sigma * np.sqrt(2.0) * erfinv(2.0 * u - 1.0),
                           lo, hi)
        if d == "lognormal":
            from scipy.special import erfinv
            lo_ = max(lo, 1e-300)
            hi_ = max(hi, lo_ * (1 + 1e-9))
            mu = np.log(max(mode, 1e-300))
            sigma = max((np.log(hi_) - np.log(lo_)) / 4.0, 1e-300)
            return np.clip(
                np.exp(mu + sigma * np.sqrt(2.0) * erfinv(2.0 * u - 1.0)), lo_, hi_)
        # triangular
        span = max(hi - lo, 1e-300)
        c = np.clip((mode - lo) / span, 0.0, 1.0)
        out = np.where(u < c,
                       lo + np.sqrt(np.maximum(u * span * (mode - lo), 0.0)),
                       hi - np.sqrt(np.maximum((1.0 - u) * span * (hi - mode), 0.0)))
        return out

    def describe(self) -> dict:
        return {"name": self.name, "base": self.base, "low": self.low,
                "high": self.high, "distribution": self.distribution,
                "unit": self.unit}


def latin_hypercube(n: int, d: int, seed: int | None = None) -> np.ndarray:
    """Latin-hypercube sample of ``n`` points in ``d`` dimensions, in [0, 1)."""
    rng = np.random.default_rng(seed)
    cut = (np.arange(n)[:, None] + rng.random((n, d))) / n
    for j in range(d):
        rng.shuffle(cut[:, j])
    return cut


# ==========================================================================
# tornado (one parameter at a time)
# ==========================================================================
@dataclass
class TornadoResult:
    metric: str
    base_value: float
    rows: list[dict] = field(default_factory=list)

    def sorted_rows(self) -> list[dict]:
        return sorted(self.rows, key=lambda r: -abs(r["swing"]))

    def summary(self) -> dict:
        return {"metric": self.metric, "base_value": self.base_value,
                "parameters": self.sorted_rows()}

    def __str__(self) -> str:
        out = [f"Tornado on {self.metric} (base = {self.base_value:,.4g})"]
        for r in self.sorted_rows():
            out.append(f"  {r['parameter']:28s} low {r['low_value']:12,.4g}  "
                       f"high {r['high_value']:12,.4g}  swing {r['swing']:12,.4g} "
                       f"({r['swing_pct']:+.1f} %)")
        return "\n".join(out)


def tornado(evaluate: Callable[[dict], float], parameters: Sequence[Parameter],
            metric: str = "AoR area (acres)") -> TornadoResult:
    """One-parameter-at-a-time sensitivity.

    ``evaluate`` takes a dict of ``{parameter name: value}`` and returns the
    scalar of interest.  Every parameter is held at ``base`` except the one
    being varied, which is set to ``low`` then ``high``.
    """
    base = {p.name: p.base for p in parameters}
    base_value = float(evaluate(base))
    res = TornadoResult(metric=metric, base_value=base_value)
    for p in parameters:
        lo_case = dict(base, **{p.name: p.low})
        hi_case = dict(base, **{p.name: p.high})
        lo = float(evaluate(lo_case))
        hi = float(evaluate(hi_case))
        res.rows.append({
            "parameter": f"{p.name}" + (f" [{p.unit}]" if p.unit else ""),
            "low_input": p.low, "high_input": p.high,
            "low_value": lo, "high_value": hi,
            "swing": hi - lo,
            "swing_pct": 100.0 * (hi - lo) / base_value if base_value else float("nan"),
            "direction": "direct" if hi >= lo else "inverse",
        })
    return res


# ==========================================================================
# Monte Carlo / probabilistic AoR
# ==========================================================================
@dataclass
class MonteCarloResult:
    parameters: list[Parameter]
    samples: np.ndarray                  # (n, d) sampled inputs
    metrics: dict[str, np.ndarray] = field(default_factory=dict)
    exceedance: np.ndarray | None = None  # (ny, nx) fraction of realisations inside
    x: np.ndarray | None = None
    y: np.ndarray | None = None
    failures: int = 0

    def percentiles(self, metric: str, qs=(10, 50, 90)) -> dict:
        v = self.metrics[metric]
        v = v[np.isfinite(v)]
        return {f"P{q}": float(np.percentile(v, q)) for q in qs}

    def correlations(self, metric: str) -> list[dict]:
        """Rank (Spearman) correlation of each input with the metric.

        Rank correlation rather than Pearson because AoR area is a strongly
        non-linear function of permeability and thickness; ranks keep the
        ordering honest.
        """
        from scipy.stats import spearmanr

        v = self.metrics[metric]
        ok = np.isfinite(v)
        out = []
        for j, p in enumerate(self.parameters):
            rho = float(spearmanr(self.samples[ok, j], v[ok]).statistic)
            out.append({"parameter": p.name, "unit": p.unit,
                        "spearman_rho": rho, "abs": abs(rho)})
        return sorted(out, key=lambda r: -r["abs"])

    def probabilistic_aor(self, probability: float = 0.9):
        """Contour the region included in at least ``probability`` of realisations.

        ``probability = 0.9`` gives the "P90 AoR": the area that 90 % of the
        sampled models put inside the AoR.  A conservative reviewer will ask
        instead for the region included in *at least 10 %* of realisations
        (``probability = 0.1``), which is the outer envelope of credible AoRs.
        """
        from .delineate import field_to_polygons

        if self.exceedance is None:
            raise ValueError("no gridded ensemble was recorded; pass a grid to monte_carlo")
        return field_to_polygons(self.x, self.y, self.exceedance, probability)

    def summary(self) -> dict:
        out = {
            "realisations": int(self.samples.shape[0]),
            "failures": self.failures,
            "parameters": [p.describe() for p in self.parameters],
        }
        for m in self.metrics:
            out[m] = {**self.percentiles(m),
                      "mean": float(np.nanmean(self.metrics[m])),
                      "min": float(np.nanmin(self.metrics[m])),
                      "max": float(np.nanmax(self.metrics[m])),
                      "rank_correlations": self.correlations(m)[:5]}
        return out


def monte_carlo(evaluate: Callable[[dict], dict], parameters: Sequence[Parameter],
                n: int = 200, seed: int | None = 0,
                grid_x: np.ndarray | None = None,
                grid_y: np.ndarray | None = None,
                progress: Callable[[int, int], None] | None = None
                ) -> MonteCarloResult:
    """Latin-hypercube Monte Carlo over the AoR model.

    ``evaluate`` receives ``{parameter name: value}`` and must return a dict.
    Scalar entries are collected as metrics.  If it also returns an
    ``"inside"`` key holding a boolean ``(ny, nx)`` mask of cells inside the
    AoR for that realisation, the cell-wise inclusion probability is
    accumulated and a probabilistic AoR becomes available.
    """
    parameters = list(parameters)
    u = latin_hypercube(n, len(parameters), seed=seed)
    samples = np.column_stack([p.sample(u[:, j]) for j, p in enumerate(parameters)])

    metrics: dict[str, list[float]] = {}
    inside_sum = None
    failures = 0

    for i in range(n):
        case = {p.name: float(samples[i, j]) for j, p in enumerate(parameters)}
        try:
            out = evaluate(case)
        except Exception:
            failures += 1
            out = {}
        for k, v in out.items():
            if k == "inside":
                mask = np.asarray(v, dtype=float)
                inside_sum = mask if inside_sum is None else inside_sum + mask
                continue
            if np.isscalar(v):
                metrics.setdefault(k, []).append(float(v))
        for k in metrics:
            if len(metrics[k]) < i + 1 - failures:
                metrics[k].append(float("nan"))
        if progress:
            progress(i + 1, n)

    exceed = (inside_sum / max(n - failures, 1)) if inside_sum is not None else None
    return MonteCarloResult(
        parameters=parameters,
        samples=samples,
        metrics={k: np.asarray(v, float) for k, v in metrics.items()},
        exceedance=exceed, x=grid_x, y=grid_y, failures=failures,
    )


# ==========================================================================
# ready-made parameter sets
# ==========================================================================
def default_parameters(permeability_md: float, porosity: float,
                       thickness_ft: float, compressibility_1_psi: float,
                       spread: float = 0.5) -> list[Parameter]:
    """A conventional starting set of uncertain reservoir parameters.

    ``spread`` is the fractional half-range for the additive parameters and
    the multiplicative factor for permeability (0.5 -> permeability varies by
    a factor of 2 either way, which is a realistic pre-drill range).
    """
    return [
        Parameter("permeability_md", permeability_md,
                  permeability_md * (1 - spread), permeability_md / (1 - spread),
                  "lognormal", "mD"),
        Parameter("porosity", porosity,
                  porosity * (1 - spread * 0.6), min(porosity * (1 + spread * 0.6), 0.45),
                  "triangular", "-"),
        Parameter("thickness_ft", thickness_ft,
                  thickness_ft * (1 - spread * 0.5), thickness_ft * (1 + spread * 0.5),
                  "triangular", "ft"),
        Parameter("compressibility_1_psi", compressibility_1_psi,
                  compressibility_1_psi * 0.5, compressibility_1_psi * 2.0,
                  "lognormal", "1/psi"),
    ]


__all__ = [
    "Parameter", "latin_hypercube", "TornadoResult", "tornado",
    "MonteCarloResult", "monte_carlo", "default_parameters",
]
