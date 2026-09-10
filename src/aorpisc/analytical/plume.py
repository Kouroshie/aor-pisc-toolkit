"""Analytical separate-phase CO2 plume models.

Three complementary closed-form models, all for a homogeneous, horizontal,
constant-thickness formation with a fully penetrating vertical injector:

:class:`VolumetricPlume`
    The mass-balance cylinder.  Not a flow model -- included because it is the
    lower bound every other model should exceed, and because it makes the
    effect of CO2 density and residual saturation obvious.

:class:`NordbottenCeliaPlume`
    Sharp-interface similarity solution of Nordbotten, Celia & Bachu (2005).
    Gives the full interface shape, so it captures the gravity tongue that
    makes the leading edge run far ahead of the volumetric radius when the
    end-point mobility ratio is unfavourable.

:class:`BuckleyLeverettPlume`
    Radial two-phase Buckley-Leverett front, i.e. the plume model used by
    EASiTool.  Resolves the saturation profile rather than a sharp interface,
    which matters when the operator's plume outline is defined by a saturation
    cutoff (0.01, 0.03, ...) as most Class VI applications do.

All three are **injection-period** models.  EPA requires the AoR to cover the
maximum extent over the whole simulation, including post-injection buoyant
migration, and none of these closed forms carries buoyant spreading after
shut-in.  Use :mod:`aorpisc.numerical.ve_solver` for the post-injection
period, or bound it with :func:`residual_trapping_limit_radius`.

References
----------
Nordbotten, J.M., Celia, M.A. & Bachu, S. (2005) *Transp. Porous Media* 58,
    339-360.
Mathias, S.A. et al. (2011) *Water Resour. Res.* 47, W12525.
EPA 816-R-13-005 (2013), Sections 2.3.2 and 3.4.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .. import units as U
from .relperm import BrooksCorey, BuckleyLeverett, RelPerm, endpoint_mobility_ratio


@dataclass
class PlumeInputs:
    """Formation and operating inputs shared by the analytical plume models."""

    thickness: float            # net thickness, m
    porosity: float             # fraction
    permeability: float         # m^2 (only used by mobility-ratio models)
    rho_co2: float              # kg/m^3 at storage conditions
    mu_co2: float               # Pa.s
    rho_brine: float            # kg/m^3
    mu_brine: float             # Pa.s
    relperm: RelPerm = field(default_factory=BrooksCorey)

    @property
    def effective_porosity(self) -> float:
        """Pore space actually available to CO2: ``phi * (1 - Swr)``."""
        return self.porosity * (1.0 - self.relperm.swr)

    def reservoir_rate(self, mass_rate: float) -> float:
        """kg/s of CO2 -> m^3/s at reservoir conditions."""
        return mass_rate / self.rho_co2


# ==========================================================================
class VolumetricPlume:
    """Cylinder of CO2 with uniform saturation -- the mass-balance bound."""

    name = "Volumetric (mass balance)"

    def __init__(self, inp: PlumeInputs, average_saturation: float | None = None):
        self.inp = inp
        if average_saturation is None:
            average_saturation = 1.0 - inp.relperm.swr
        self.sg_avg = average_saturation

    def radius(self, mass_injected: float) -> float:
        """Plume radius (m) for a cumulative injected mass (kg)."""
        if mass_injected <= 0:
            return 0.0
        vol = mass_injected / self.inp.rho_co2
        return float(np.sqrt(vol / (np.pi * self.inp.porosity
                                    * self.sg_avg * self.inp.thickness)))

    def describe(self) -> dict:
        return {"model": self.name, "average_saturation": self.sg_avg}


# ==========================================================================
class NordbottenCeliaPlume:
    """Sharp-interface similarity solution (Nordbotten, Celia & Bachu 2005).

    With ``Gamma`` the end-point CO2/brine mobility ratio and the similarity
    variable ``chi = 2 pi phi_eff H r^2 / (Q t)``, the dimensionless CO2
    column height is

    ============================  ===========================================
    ``chi <= 2/Gamma``            ``h_c/H = 1``   (fully swept)
    ``2/Gamma < chi < 2 Gamma``   ``h_c/H = (sqrt(2 Gamma / chi) - 1)/(Gamma - 1)``
    ``chi >= 2 Gamma``            ``h_c/H = 0``   (ahead of the nose)
    ============================  ===========================================

    so the leading edge sits at ``chi = 2 Gamma``, i.e.

        ``r_max = sqrt( Gamma * Q * t / (pi * phi_eff * H) )``

    which is ``sqrt(Gamma)`` times the volumetric radius.  For CO2 in brine
    ``Gamma`` is typically 3-20, so the sharp-interface nose runs roughly
    2-4.5x further than a naive volume balance -- the single biggest reason a
    volumetric AoR estimate is not defensible.

    The profile integrates to exactly the injected volume; this is asserted in
    the test suite.
    """

    name = "Nordbotten-Celia-Bachu sharp interface"

    def __init__(self, inp: PlumeInputs, gamma: float | None = None):
        self.inp = inp
        self.gamma = (endpoint_mobility_ratio(inp.relperm, inp.mu_co2, inp.mu_brine)
                      if gamma is None else float(gamma))
        if self.gamma <= 0:
            raise ValueError("mobility ratio Gamma must be positive")

    # ------------------------------------------------------------------ #
    def _chi(self, r, volume_injected):
        phi_e = self.inp.effective_porosity
        return (2.0 * np.pi * phi_e * self.inp.thickness
                * np.asarray(r, float) ** 2 / max(volume_injected, 1e-30))

    def interface_height(self, r, volume_injected: float):
        """CO2 column height ``h_c`` (m) at radius ``r`` (m)."""
        g = self.gamma
        chi = self._chi(r, volume_injected)
        with np.errstate(divide="ignore", invalid="ignore"):
            mid = (np.sqrt(2.0 * g / np.maximum(chi, 1e-300)) - 1.0) / (g - 1.0) \
                if abs(g - 1.0) > 1e-9 else np.where(chi <= 2.0, 1.0, 0.0)
        h = np.where(chi <= 2.0 / g, 1.0, np.where(chi >= 2.0 * g, 0.0, mid))
        return np.clip(h, 0.0, 1.0) * self.inp.thickness

    def radius(self, mass_injected: float) -> float:
        """Leading-edge (nose) radius in m."""
        if mass_injected <= 0:
            return 0.0
        vol = mass_injected / self.inp.rho_co2
        phi_e = self.inp.effective_porosity
        return float(np.sqrt(self.gamma * vol / (np.pi * phi_e * self.inp.thickness)))

    def fully_swept_radius(self, mass_injected: float) -> float:
        """Radius inside which CO2 occupies the full formation thickness."""
        if mass_injected <= 0:
            return 0.0
        vol = mass_injected / self.inp.rho_co2
        phi_e = self.inp.effective_porosity
        return float(np.sqrt(vol / (np.pi * self.gamma * phi_e * self.inp.thickness)))

    def describe(self) -> dict:
        return {"model": self.name, "mobility_ratio_gamma": self.gamma}


# ==========================================================================
class BuckleyLeverettPlume:
    """Radial Buckley-Leverett plume, resolving the saturation profile.

    ``saturation_cutoff`` reproduces the operator convention of outlining the
    plume at a chosen CO2 saturation (commonly 0.01-0.05).  The leading shock
    is the physical edge; a cutoff above the shock saturation pulls the
    outline in, a cutoff below it has no effect (there is no CO2 ahead of the
    shock).
    """

    name = "Radial Buckley-Leverett (two-phase)"

    def __init__(self, inp: PlumeInputs, saturation_cutoff: float = 0.0):
        self.inp = inp
        self.bl = BuckleyLeverett(inp.relperm, inp.mu_co2, inp.mu_brine)
        self.saturation_cutoff = saturation_cutoff

    def radius(self, mass_injected: float) -> float:
        if mass_injected <= 0:
            return 0.0
        vol = mass_injected / self.inp.rho_co2
        h, phi = self.inp.thickness, self.inp.porosity
        r_shock = float(np.sqrt(vol * self.bl.shock_slope / (np.pi * phi * h)))
        if self.saturation_cutoff <= self.bl.shock_saturation:
            return r_shock
        # cutoff inside the rarefaction: invert r(Sg)
        from .relperm import dfg_dsg
        slope = float(dfg_dsg(np.array([self.saturation_cutoff]),
                              self.inp.relperm, self.inp.mu_co2, self.inp.mu_brine)[0])
        slope = max(slope, 0.0)
        return float(np.sqrt(vol * slope / (np.pi * phi * h)))

    def profile(self, mass_injected: float, n: int = 400):
        vol = mass_injected / self.inp.rho_co2
        return self.bl.saturation_profile(vol, 1.0, self.inp.porosity,
                                          self.inp.thickness, n=n)

    def describe(self) -> dict:
        d = {"model": self.name, "saturation_cutoff": self.saturation_cutoff}
        d.update(self.bl.describe())
        return d


# ==========================================================================
def residual_trapping_limit_radius(mass_injected: float, rho_co2: float,
                                   porosity: float, thickness: float,
                                   sgr: float) -> float:
    """Radius at which the whole injected mass sits at residual saturation.

    ``A = V_co2 / (phi * H * Sgr)``, ``r = sqrt(A / pi)``.

    Read this as the footprint of a plume that has migrated until every last
    tonne is residually trapped through the *full* interval thickness.  It is
    a mass-balance ceiling on the fully-swept area, and a useful sanity check
    on a long-horizon PISC prediction: a model whose fully-swept region grows
    past this radius is not conserving mass.

    It is **not** a ceiling on the outline drawn at a low saturation cutoff.
    A cutoff of 0.01 on a column-averaged saturation picks up cells holding
    only a few per cent of the interval thickness, and that outline legitimately
    extends beyond this radius.  Compare like with like.
    """
    if sgr <= 0:
        return float("inf")
    vol = mass_injected / rho_co2
    area = vol / (porosity * thickness * sgr)
    return float(np.sqrt(area / np.pi))


def gravity_number(permeability: float, thickness: float, delta_rho: float,
                   mu_co2: float, q_res: float) -> float:
    """Dimensionless gravity number ``Gamma_g`` for buoyancy vs. viscous forces.

    ``Gamma_g = 2 pi k * delta_rho * g * H^2 / (mu_co2 * Q_res)``.  Values
    much greater than 1 mean buoyancy dominates and the plume will be strongly
    tongued along the caprock; values below ~1 mean a viscous-dominated,
    near-cylindrical plume.  Useful for deciding whether a sharp-interface
    model is adequate or a full VE/3D simulation is needed.
    """
    if q_res <= 0:
        return float("inf")
    return float(2.0 * np.pi * permeability * delta_rho * U.G * thickness ** 2
                 / (mu_co2 * q_res))


__all__ = [
    "PlumeInputs", "VolumetricPlume", "NordbottenCeliaPlume",
    "BuckleyLeverettPlume", "residual_trapping_limit_radius", "gravity_number",
]
