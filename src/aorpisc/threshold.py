"""Threshold ("critical") pressure for the pressure-front component of the AoR.

The pressure front is *not* the edge of measurable pressure increase.  EPA
defines it as "the minimum pressure within the injection zone necessary to
cause fluid flow from the injection zone into the formation matrix of the
USDW through a hypothetical conduit (i.e., artificial penetration) that is
perforated in both intervals" (EPA 816-R-13-005, Section 3.4.1).  Everything
in this module computes that number, expressed both as an absolute injection
zone pressure ``P_i,f`` and, more usefully for delineation, as the allowable
pressure *increase* ``dP_c`` above the pre-injection pressure.

Four methods are implemented, plus explicit handling of the over-pressurised
case.  Which one applies is not a matter of taste: it depends on whether the
injection zone starts out under-pressurised, hydrostatic, or over-pressurised
relative to the lowermost USDW, and on what the permitting authority accepts
for the state of the hypothetical conduit.  :func:`compare_methods` runs all
of them side by side, which is the fastest way to see how much of an
operator's AoR rests on that single choice.

Sign and datum convention
-------------------------
Depths are **positive downward** from a single, stated datum (usually mean
sea level or ground level -- state which, and use the same one throughout).
Elevations in EPA's equations are recovered as ``z = -depth``, so
``z_u - z_i == depth_i - depth_u`` and the equations below match the guidance
term for term.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np

from . import fluids
from . import units as U

EPA_AOR_GUIDANCE = "EPA 816-R-13-005 (May 2013), UIC Class VI AoR Evaluation and Corrective Action Guidance"


@dataclass
class ThresholdResult:
    """Outcome of one threshold-pressure calculation."""

    method: str
    delta_p_critical: float      # Pa, allowable increase over initial injection-zone pressure
    p_threshold_abs: float       # Pa, absolute injection-zone pressure at the front
    initial_pressure: float      # Pa
    regime: str                  # underpressured | hydrostatic | overpressured | n/a
    citation: str
    inputs: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    applicable: bool = True

    @property
    def delta_p_psi(self) -> float:
        return U.pressure_out(self.delta_p_critical, "psi")

    @property
    def p_threshold_psi(self) -> float:
        return U.pressure_out(self.p_threshold_abs, "psi")

    def summary(self) -> dict:
        return {
            "method": self.method,
            "applicable": self.applicable,
            "regime": self.regime,
            "delta_p_critical_psi": self.delta_p_psi,
            "delta_p_critical_MPa": U.pressure_out(self.delta_p_critical, "MPa"),
            "p_threshold_abs_psi": self.p_threshold_psi,
            "p_threshold_abs_MPa": U.pressure_out(self.p_threshold_abs, "MPa"),
            "initial_pressure_psi": U.pressure_out(self.initial_pressure, "psi"),
            "citation": self.citation,
            "warnings": list(self.warnings),
        }

    def __str__(self) -> str:
        flag = "" if self.applicable else "  [NOT APPLICABLE to this pressure regime]"
        return (f"{self.method}: dP_c = {self.delta_p_psi:,.0f} psi "
                f"(P_i,f = {self.p_threshold_psi:,.0f} psi){flag}")


# ==========================================================================
# pressure-regime classification
# ==========================================================================
def classify_regime(p_usdw: float, p_inj: float, rho_inj: float,
                    depth_usdw: float, depth_inj: float,
                    tolerance_pa: float = U.pressure(10.0, "psi")) -> tuple[str, float]:
    """Classify the injection zone against the lowermost USDW.

    Returns ``(regime, dP_if)`` where ``dP_if`` is EPA Eq-2.  A positive
    ``dP_if`` means the injection zone is under-pressurised and can take that
    much additional pressure before the hydraulic head in the injection zone
    matches the head in the USDW.
    """
    dz = depth_inj - depth_usdw  # == z_u - z_i
    dp_if = p_usdw + rho_inj * U.G * dz - p_inj
    if dp_if > tolerance_pa:
        return "underpressured", dp_if
    if dp_if < -tolerance_pa:
        return "overpressured", dp_if
    return "hydrostatic", dp_if


# ==========================================================================
# Method 1 -- Thornhill / EPA Eq-1 and Eq-2 (under-pressurised case)
# ==========================================================================
def method1_thornhill(p_usdw: float, p_inj: float, rho_inj: float,
                      depth_usdw: float, depth_inj: float) -> ThresholdResult:
    """EPA Method 1: equalise hydraulic heads between injection zone and USDW.

    ``P_i,f = P_u + rho_i * g * (z_u - z_i)``  (EPA Eq-1)
    ``dP_i,f = P_i,f - P_i``                    (EPA Eq-2)

    This is the long-standing UIC pressure-front definition (Thornhill et al.,
    1982) and is the method EPA says is applicable "to any Class VI injection
    well for which, prior to injection, the injection zone is under-pressurized
    compared to the lowermost USDW".

    It is the most conservative of the closed-form methods because it treats
    the conduit as a fully open borehole carrying injection-zone brine at its
    in-situ density all the way to the USDW.
    """
    dz = depth_inj - depth_usdw
    p_if = p_usdw + rho_inj * U.G * dz
    dp = p_if - p_inj
    regime, _ = classify_regime(p_usdw, p_inj, rho_inj, depth_usdw, depth_inj)

    warn = []
    if regime != "underpressured":
        warn.append(
            f"Injection zone is {regime}; EPA restricts Method 1 to the "
            "under-pressurised case (dP_i,f > 0). See EPA Section 3.4.1."
        )
    if dz <= 0:
        warn.append("Injection zone is not below the USDW -- check depths and datum.")
    return ThresholdResult(
        method="Method 1 - Thornhill / equal hydraulic head (EPA Eq-1, Eq-2)",
        delta_p_critical=dp,
        p_threshold_abs=p_if,
        initial_pressure=p_inj,
        regime=regime,
        citation=f"{EPA_AOR_GUIDANCE}, Section 3.4.1 Method 1; Thornhill et al. (1982)",
        inputs={
            "p_usdw_psi": U.pressure_out(p_usdw, "psi"),
            "p_inj_psi": U.pressure_out(p_inj, "psi"),
            "rho_inj_kg_m3": rho_inj,
            "rho_inj_lb_ft3": U.density_out(rho_inj, "lb/ft3"),
            "depth_usdw_ft": U.length_out(depth_usdw, "ft"),
            "depth_inj_ft": U.length_out(depth_inj, "ft"),
            "separation_ft": U.length_out(dz, "ft"),
        },
        warnings=warn,
        applicable=(regime == "underpressured"),
    )


# ==========================================================================
# Method 2 -- Nicot / Bandilla uniform-density column (hydrostatic case)
# ==========================================================================
def method2_nicot_uniform(rho_inj: float, rho_usdw: float,
                          depth_usdw: float, depth_inj: float,
                          p_inj: float = float("nan"),
                          p_usdw: float = float("nan")) -> ThresholdResult:
    """EPA Method 2: displace the fluid initially standing in the borehole.

    ``xi   = (rho_i - rho_u) / (z_u - z_i)``           (EPA Eq-4)
    ``dP_c = 0.5 * g * xi * (z_u - z_i)^2``            (EPA Eq-3)
           ``= 0.5 * g * (rho_i - rho_u) * (z_u - z_i)``

    Derivation, for the record: with an initially linear density profile in
    the conduit the mean column density is ``(rho_i + rho_u)/2``.  Once
    injection-zone fluid has been lifted to the top the mean is ``rho_i``.
    The extra head that has to be overcome is therefore
    ``g * (z_u - z_i) * (rho_i - (rho_i + rho_u)/2)``, which is Eq-3.

    Applicable to the hydrostatic case (Nicot et al., 2008; Bandilla et al.,
    2012).  Birkholzer et al. (2011) note the uniform-density form is the
    conservative one for USDW protection.
    """
    dz = depth_inj - depth_usdw
    xi = (rho_inj - rho_usdw) / dz if dz else 0.0
    dp = 0.5 * U.G * xi * dz ** 2

    regime = "n/a"
    applicable = True
    warn = []
    if np.isfinite(p_inj) and np.isfinite(p_usdw):
        regime, _ = classify_regime(p_usdw, p_inj, rho_inj, depth_usdw, depth_inj)
        applicable = regime == "hydrostatic"
        if not applicable:
            warn.append(
                f"Injection zone is {regime}; EPA restricts Method 2 to the "
                "hydrostatic case. For the over-pressurised case see "
                "`overpressured_allowance`."
            )
    else:
        warn.append(
            "Initial pressures not supplied, so the hydrostatic assumption "
            "behind Method 2 has not been verified. EPA recommends "
            "re-evaluating this assumption once site-specific pressure data "
            "are available."
        )
    if rho_inj <= rho_usdw:
        warn.append(
            "Injection-zone fluid is not denser than USDW fluid; Method 2 "
            "returns a non-positive threshold and should not be used."
        )

    return ThresholdResult(
        method="Method 2 - Nicot uniform-density borehole column (EPA Eq-3, Eq-4)",
        delta_p_critical=dp,
        p_threshold_abs=(p_inj + dp) if np.isfinite(p_inj) else float("nan"),
        initial_pressure=p_inj,
        regime=regime,
        citation=f"{EPA_AOR_GUIDANCE}, Section 3.4.1 Method 2; Nicot et al. (2008); "
                 "Bandilla et al. (2012); Birkholzer et al. (2011)",
        inputs={
            "rho_inj_kg_m3": rho_inj,
            "rho_usdw_kg_m3": rho_usdw,
            "delta_rho_kg_m3": rho_inj - rho_usdw,
            "depth_usdw_ft": U.length_out(depth_usdw, "ft"),
            "depth_inj_ft": U.length_out(depth_inj, "ft"),
            "separation_ft": U.length_out(dz, "ft"),
            "xi_kg_m4": xi,
        },
        warnings=warn,
        applicable=applicable,
    )


# ==========================================================================
# Method 2b -- variable-density column (generalisation of Method 2)
# ==========================================================================
def method_variable_density_column(
    p_inj: float, p_usdw: float,
    depth_usdw: float, depth_inj: float,
    density_profile: Callable[[np.ndarray, np.ndarray], np.ndarray],
    n: int = 401,
) -> ThresholdResult:
    """Threshold pressure with a depth-varying lifted-column density.

    EPA Method 2 assumes the lifted injection-zone fluid keeps its bottom-hole
    density all the way to the USDW.  Real brine expands as it rises (lower
    pressure) and cools (lower temperature), so the true column weight differs.
    This routine drops the constant-density assumption and integrates the
    column directly::

        P_top(dP) = P_i + dP - integral_{z_i}^{z_u} rho(z) g dz
        dP_c      = P_u - P_i + integral rho(z) g dz

    ``density_profile(depth, pressure)`` is called with arrays of depth (m,
    positive down) and the current pressure estimate (Pa) and must return
    density (kg/m^3).  The integral and the pressure profile are solved by
    two Picard sweeps, which is ample -- the coupling is weak.

    This reduces exactly to EPA Eq-3 for a constant ``rho_i`` profile, and
    gives a physically transparent alternative to the "equilibrium" variant
    discussed by Nicot et al. (2008) without adopting its closed form.
    """
    dz_total = depth_inj - depth_usdw
    depths = np.linspace(depth_usdw, depth_inj, n)

    # first pass: linear pressure guess between the two formation pressures
    press = np.linspace(p_usdw, p_inj, n)
    for _ in range(2):
        rho = np.asarray(density_profile(depths, press), dtype=float)
        # integrate downward from the USDW to rebuild the pressure profile
        dP = np.concatenate([[0.0], np.cumsum(
            0.5 * (rho[1:] + rho[:-1]) * U.G * np.diff(depths))])
        press = p_usdw + dP
    column_head = float(np.trapezoid(rho * U.G, depths)) if hasattr(np, "trapezoid") \
        else float(np.trapz(rho * U.G, depths))

    dp = p_usdw + column_head - p_inj
    regime, _ = classify_regime(p_usdw, p_inj, float(rho.mean()), depth_usdw, depth_inj)
    return ThresholdResult(
        method="Method 2b - variable-density lifted column (numerical integration)",
        delta_p_critical=dp,
        p_threshold_abs=p_inj + dp,
        initial_pressure=p_inj,
        regime=regime,
        citation="Generalisation of EPA Method 2 (EPA 816-R-13-005 Section 3.4.1); "
                 "column integrated numerically, see docs/methods.md",
        inputs={
            "mean_column_density_kg_m3": float(rho.mean()),
            "column_head_psi": U.pressure_out(column_head, "psi"),
            "separation_ft": U.length_out(dz_total, "ft"),
            "nodes": n,
        },
        warnings=[],
    )


# ==========================================================================
# Method 3 -- mud column + gel strength (TCEQ / UIC Class I practice)
# ==========================================================================
def method_mud_column(p_inj: float, depth_inj: float,
                      mud_weight_ppg: float = 9.0,
                      gel_strength: float = U.pressure(10.0, "psi"),
                      mud_gradient: float | None = None,
                      surface_pressure: float = 0.0) -> ThresholdResult:
    """Threshold pressure assuming the conduit stands full of drilling mud.

    Texas Class I practice (and several Texas Class VI applications) does not
    treat the hypothetical conduit as an open, brine-filled borehole.  It
    assumes the plugged well is full of ~9 lb/gal mud that has developed a gel
    strength, so the pressure that has to be overcome before injection-zone
    fluid can move up the hole is the mud hydrostatic plus the gel strength::

        dP_c = (mud gradient * depth_inj + gel strength + P_surface) - P_i

    ``mud_gradient`` overrides the mud weight if given (Pa/m).  9.0 ppg
    corresponds to 0.4675 psi/ft.

    The result is *strongly* sensitive to the depth datum: the mud column must
    be measured from the wellhead, not from sea level or from a subsea marker,
    and a few tens of feet of datum error moves the answer by ~10-20 psi.
    Always state the datum alongside the number.

    References
    ----------
    Johnston, O.C. & Knape, B.K. (1986) *Pressure effects of the static mud
        column in abandoned wells*, Texas Water Commission.
    Bump, A. (2023) and TCEQ Class I permitting practice, as applied in
        several Texas Class VI AoR and Corrective Action Plans.
    """
    grad = mud_gradient if mud_gradient is not None else U.ppg_to_gradient_si(mud_weight_ppg)
    p_column = surface_pressure + grad * depth_inj + gel_strength
    dp = p_column - p_inj

    warn = []
    if dp <= 0:
        warn.append(
            "Mud column plus gel strength does not exceed the initial "
            "injection-zone pressure: the well is over-pressurised relative "
            "to a static mud column and this method does not apply."
        )
    return ThresholdResult(
        method="Method 3 - static mud column + gel strength (TCEQ / UIC Class I)",
        delta_p_critical=dp,
        p_threshold_abs=p_column,
        initial_pressure=p_inj,
        regime="n/a",
        citation="Johnston & Knape (1986); TCEQ UIC Class I practice; "
                 "applied in Texas Class VI AoR plans",
        inputs={
            "mud_weight_ppg": mud_weight_ppg if mud_gradient is None else float("nan"),
            "mud_gradient_psi_ft": U.pressure_gradient_out(grad, "psi/ft"),
            "depth_inj_ft": U.length_out(depth_inj, "ft"),
            "gel_strength_psi": U.pressure_out(gel_strength, "psi"),
            "mud_column_pressure_psi": U.pressure_out(p_column, "psi"),
            "p_inj_psi": U.pressure_out(p_inj, "psi"),
        },
        warnings=warn,
    )


# ==========================================================================
# over-pressurised injection zones
# ==========================================================================
def overpressured_allowance(p_usdw: float, p_inj: float, rho_inj: float,
                            rho_usdw: float, depth_usdw: float,
                            depth_inj: float) -> ThresholdResult:
    """Allowable pressure increase when the injection zone starts over-pressurised.

    EPA (Section 3.4.1, "Methods for over-pressurized cases") offers three
    routes.  This implements the first, closed-form one: some
    over-pressurisation is tolerable because of the density contrast, so if
    ``dP_c`` from Method 2 exceeds ``|dP_i,f|`` from Method 2, the difference
    is an estimate of the allowable increase::

        allowable = dP_c(Method 2) - |dP_i,f(Method 2 of Eq-2)|

    If the difference is negative the site is leaking through a hypothetical
    open conduit before injection even starts, and EPA's routes 2 and 3
    (numerical wellbore-leakage modelling, and USDW dilution modelling) are
    required instead.  The result is flagged ``applicable=False`` in that case
    so it cannot be used silently.
    """
    regime, dp_if = classify_regime(p_usdw, p_inj, rho_inj, depth_usdw, depth_inj)
    dz = depth_inj - depth_usdw
    dp_c = 0.5 * U.G * (rho_inj - rho_usdw) * dz

    allowable = dp_c - abs(dp_if)
    warn = []
    applicable = True
    if regime != "overpressured":
        warn.append(f"Injection zone is {regime}, not over-pressurised; use Method 1 or 2.")
        applicable = False
    if allowable <= 0:
        warn.append(
            "Density contrast does not offset the initial over-pressure. A "
            "closed-form threshold is not defensible here -- EPA Section 3.4.1 "
            "requires numerical wellbore-leakage modelling (option 2) and/or a "
            "USDW dilution/attenuation demonstration (option 3)."
        )
        applicable = False
    return ThresholdResult(
        method="Over-pressurised case - density-contrast offset (EPA Sec. 3.4.1 option 1)",
        delta_p_critical=max(allowable, 0.0),
        p_threshold_abs=p_inj + max(allowable, 0.0),
        initial_pressure=p_inj,
        regime=regime,
        citation=f"{EPA_AOR_GUIDANCE}, Section 3.4.1, over-pressurised cases",
        inputs={
            "dP_if_psi": U.pressure_out(dp_if, "psi"),
            "dP_c_method2_psi": U.pressure_out(dp_c, "psi"),
            "allowable_psi": U.pressure_out(allowable, "psi"),
        },
        warnings=warn,
        applicable=applicable,
    )


# ==========================================================================
# side-by-side comparison
# ==========================================================================
def compare_methods(p_usdw: float, p_inj: float,
                    depth_usdw: float, depth_inj: float,
                    temperature_inj: float, temperature_usdw: float,
                    salinity_inj: float, salinity_usdw: float = 0.0005,
                    mud_weight_ppg: float = 9.0,
                    gel_strength: float = U.pressure(10.0, "psi"),
                    mud_datum_depth: float | None = None,
                    ) -> list[ThresholdResult]:
    """Run every threshold method on one site and return them in a list.

    Fluid densities are computed from :mod:`aorpisc.fluids` at the stated
    in-situ conditions.  ``salinity_*`` are NaCl mass fractions.
    ``mud_datum_depth`` defaults to ``depth_inj``.
    """
    rho_i = fluids.brine_density(p_inj, temperature_inj, salinity_inj)
    rho_u = fluids.brine_density(p_usdw, temperature_usdw, salinity_usdw)

    def profile(depth: np.ndarray, press: np.ndarray) -> np.ndarray:
        # injection-zone brine lifted up the hole: salinity fixed, P from the
        # column itself, T on a linear geotherm between the two formations
        frac = (depth - depth_usdw) / max(depth_inj - depth_usdw, 1e-9)
        temp = temperature_usdw + frac * (temperature_inj - temperature_usdw)
        return np.array([fluids.brine_density(float(pp), float(tt), salinity_inj)
                         for pp, tt in zip(press, temp, strict=True)])

    results = [
        method1_thornhill(p_usdw, p_inj, rho_i, depth_usdw, depth_inj),
        method2_nicot_uniform(rho_i, rho_u, depth_usdw, depth_inj, p_inj, p_usdw),
        method_variable_density_column(p_inj, p_usdw, depth_usdw, depth_inj, profile),
        method_mud_column(p_inj, mud_datum_depth if mud_datum_depth is not None else depth_inj,
                          mud_weight_ppg=mud_weight_ppg, gel_strength=gel_strength),
    ]
    regime, _ = classify_regime(p_usdw, p_inj, rho_i, depth_usdw, depth_inj)
    if regime == "overpressured":
        results.append(overpressured_allowance(p_usdw, p_inj, rho_i, rho_u,
                                               depth_usdw, depth_inj))
    return results


def recommended(results: Sequence[ThresholdResult]) -> ThresholdResult:
    """Pick the defensible threshold from a comparison run.

    Among the methods flagged applicable for the site's pressure regime, the
    smallest ``dP_c`` is returned, because the smallest allowable pressure
    increase produces the largest pressure front and therefore the most
    protective AoR.  If nothing is applicable the smallest positive value is
    returned with a warning attached.
    """
    ok = [r for r in results if r.applicable and r.delta_p_critical > 0]
    pool = ok or [r for r in results if r.delta_p_critical > 0]
    if not pool:
        raise ValueError("no method produced a positive threshold pressure")
    best = min(pool, key=lambda r: r.delta_p_critical)
    if not ok:
        best = ThresholdResult(**{**best.__dict__})
        best.warnings = list(best.warnings) + [
            "No method was formally applicable to this pressure regime; this "
            "value is the smallest positive candidate and must be reviewed."
        ]
    return best


__all__ = [
    "ThresholdResult", "classify_regime", "method1_thornhill",
    "method2_nicot_uniform", "method_variable_density_column",
    "method_mud_column", "overpressured_allowance", "compare_methods",
    "recommended", "EPA_AOR_GUIDANCE",
]
