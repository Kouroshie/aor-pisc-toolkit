"""Two-phase relative permeability, fractional flow and Buckley-Leverett.

EPA's guidance is blunt about this: "model predictions are very sensitive to
the shape of the relative permeability-saturation functions used"
(816-R-13-005, Section 2.2.2).  The functions here are therefore first-class
objects that get carried through the analytical plume model, the
vertical-equilibrium solver and the sensitivity analysis, rather than being
buried as constants.

Two families are provided:

Brooks-Corey / Corey power law
    The form used by EASiTool and by most Class VI applications:
    ``k_rg = k_rg0 * Sn^n`` and ``k_rw = k_rw0 * (1-Sn)^m`` on the normalised
    gas saturation ``Sn = (Sg - Sgr) / (1 - Sar - Sgr)``.

van Genuchten-Mualem
    The form usually paired with TOUGH2/ECO2N models, so that a TOUGH-based
    operator model can be reproduced with its own curves.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class BrooksCorey:
    """Corey power-law relative permeability.

    Parameters
    ----------
    swr : residual (irreducible) wetting-phase saturation, ``Sar`` in EASiTool
    sgr : residual (critical) gas saturation
    krw0, krg0 : end-point relative permeabilities
    m : brine (wetting) exponent
    n : CO2 (non-wetting) exponent
    """

    swr: float = 0.30
    sgr: float = 0.20
    krw0: float = 1.0
    krg0: float = 0.30
    m: float = 3.0
    n: float = 3.0

    def __post_init__(self):
        if not 0.0 <= self.swr < 1.0:
            raise ValueError("swr must be in [0, 1)")
        if not 0.0 <= self.sgr < 1.0:
            raise ValueError("sgr must be in [0, 1)")
        if self.swr + self.sgr >= 1.0:
            raise ValueError("swr + sgr must be < 1")

    @property
    def span(self) -> float:
        return 1.0 - self.swr - self.sgr

    def normalise(self, sg):
        return np.clip((np.asarray(sg, float) - self.sgr) / self.span, 0.0, 1.0)

    def krg(self, sg):
        return self.krg0 * self.normalise(sg) ** self.n

    def krw(self, sg):
        return self.krw0 * (1.0 - self.normalise(sg)) ** self.m

    def describe(self) -> dict:
        return {"model": "Brooks-Corey", "swr": self.swr, "sgr": self.sgr,
                "krw0": self.krw0, "krg0": self.krg0, "m": self.m, "n": self.n}


@dataclass
class VanGenuchten:
    """van Genuchten-Mualem relative permeability (TOUGH2/ECO2N style)."""

    swr: float = 0.30
    sgr: float = 0.05
    lam: float = 0.457   # van Genuchten m
    krg0: float = 1.0

    @property
    def span(self) -> float:
        return 1.0 - self.swr - self.sgr

    def _se(self, sg):
        sw = 1.0 - np.asarray(sg, float)
        return np.clip((sw - self.swr) / (1.0 - self.swr), 1e-12, 1.0)

    def krw(self, sg):
        se = self._se(sg)
        return np.sqrt(se) * (1.0 - (1.0 - se ** (1.0 / self.lam)) ** self.lam) ** 2

    def krg(self, sg):
        # Corey form for the gas phase, as used in TOUGH2 ECO2N
        shat = np.clip((1.0 - np.asarray(sg, float) - self.swr)
                       / (1.0 - self.swr - self.sgr), 0.0, 1.0)
        return self.krg0 * (1.0 - shat) ** 2 * (1.0 - shat ** 2)

    def describe(self) -> dict:
        return {"model": "van Genuchten-Mualem", "swr": self.swr,
                "sgr": self.sgr, "lambda": self.lam, "krg0": self.krg0}


RelPerm = BrooksCorey | VanGenuchten


# ==========================================================================
# fractional flow and the Buckley-Leverett shock
# ==========================================================================
def fractional_flow(sg, rp: RelPerm, mu_g: float, mu_w: float):
    """CO2 fractional flow ``f_g`` neglecting capillary and gravity terms."""
    krg = np.asarray(rp.krg(sg), float)
    krw = np.asarray(rp.krw(sg), float)
    lg = krg / mu_g
    lw = krw / mu_w
    tot = lg + lw
    return np.where(tot > 0.0, lg / np.maximum(tot, 1e-300), 0.0)


def dfg_dsg(sg, rp: RelPerm, mu_g: float, mu_w: float, h: float = 1e-5):
    """Derivative of the fractional-flow curve (central difference)."""
    sg = np.asarray(sg, float)
    lo = np.clip(sg - h, 0.0, 1.0)
    hi = np.clip(sg + h, 0.0, 1.0)
    return (fractional_flow(hi, rp, mu_g, mu_w)
            - fractional_flow(lo, rp, mu_g, mu_w)) / np.maximum(hi - lo, 1e-30)


@dataclass
class BuckleyLeverett:
    """Radial Buckley-Leverett solution for CO2 displacing brine.

    The Welge tangent construction is done numerically from the initial
    condition ``Sg = sgr`` (or ``Sg = 0`` for a virgin, brine-filled
    formation).  ``shock_saturation`` is the CO2 saturation at the leading
    front and ``shock_slope`` is ``df_g/dS_g`` there, which sets the front
    radius through::

        r_f(t) = sqrt( Q_res * t / (pi * phi * H) * (df_g/dS_g)|_shock )

    where ``Q_res`` is the volumetric CO2 injection rate at reservoir
    conditions.  Behind the front the saturation profile is the rarefaction
    ``r(S_g, t) = sqrt(Q_res t / (pi phi H) * df_g/dS_g(S_g))``.
    """

    rp: RelPerm
    mu_g: float
    mu_w: float
    sg_initial: float = 0.0
    n_samples: int = 2001

    shock_saturation: float = 0.0
    shock_slope: float = 0.0
    sg_max: float = 0.0

    def __post_init__(self):
        sg_max = 1.0 - self.rp.swr
        self.sg_max = sg_max
        s = np.linspace(self.sg_initial + 1e-6, sg_max - 1e-9, self.n_samples)
        f = fractional_flow(s, self.rp, self.mu_g, self.mu_w)
        f0 = float(fractional_flow(np.array([self.sg_initial]),
                                   self.rp, self.mu_g, self.mu_w)[0])
        # Welge: maximise the chord slope from the initial state
        chord = (f - f0) / (s - self.sg_initial)
        k = int(np.argmax(chord))
        self.shock_saturation = float(s[k])
        self.shock_slope = float(chord[k])
        if not np.isfinite(self.shock_slope) or self.shock_slope <= 0:
            raise ValueError("degenerate fractional-flow curve; check relperm inputs")

    # ---------------------------------------------------------------- #
    def front_radius(self, q_res: float, t: float, phi: float, h: float) -> float:
        """Leading-edge (shock) radius in m.

        ``q_res`` m^3/s of CO2 at reservoir conditions, ``t`` seconds,
        ``phi`` porosity, ``h`` net thickness in m.
        """
        if t <= 0 or q_res <= 0:
            return 0.0
        return float(np.sqrt(q_res * t * self.shock_slope / (np.pi * phi * h)))

    def saturation_profile(self, q_res: float, t: float, phi: float, h: float,
                           n: int = 400) -> tuple[np.ndarray, np.ndarray]:
        """Radius (m) and CO2 saturation behind the front."""
        s = np.linspace(self.shock_saturation, self.sg_max - 1e-9, n)
        slope = dfg_dsg(s, self.rp, self.mu_g, self.mu_w)
        slope = np.maximum(slope, 0.0)
        r = np.sqrt(np.maximum(q_res * t * slope / (np.pi * phi * h), 0.0))
        order = np.argsort(r)
        return r[order], s[order]

    def average_saturation(self) -> float:
        """Volume-averaged CO2 saturation inside the front (Welge)."""
        f_shock = float(fractional_flow(np.array([self.shock_saturation]),
                                        self.rp, self.mu_g, self.mu_w)[0])
        return float(self.shock_saturation + (1.0 - f_shock) / self.shock_slope)

    def describe(self) -> dict:
        return {
            "relperm": self.rp.describe(),
            "viscosity_ratio_mu_w_over_mu_g": self.mu_w / self.mu_g,
            "shock_saturation": self.shock_saturation,
            "shock_slope_dfg_dsg": self.shock_slope,
            "average_saturation_behind_front": self.average_saturation(),
        }


def endpoint_mobility_ratio(rp: RelPerm, mu_g: float, mu_w: float) -> float:
    """CO2-to-brine end-point mobility ratio ``Gamma`` used by sharp-interface models.

    ``Gamma = (k_rg(1-Swr)/mu_g) / (k_rw(Sg=0)/mu_w)``.  Values well above 1
    (typically 3-20 for CO2/brine) are what make the plume much wider than a
    volumetric-radius estimate.
    """
    krg_e = float(np.asarray(rp.krg(1.0 - rp.swr), float))
    krw_e = float(np.asarray(rp.krw(0.0), float))
    return (krg_e / mu_g) / (krw_e / mu_w)


__all__ = [
    "BrooksCorey", "VanGenuchten", "RelPerm", "fractional_flow", "dfg_dsg",
    "BuckleyLeverett", "endpoint_mobility_ratio",
]
