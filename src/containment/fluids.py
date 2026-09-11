"""CO2 and brine PVT properties at storage-formation conditions.

Two back-ends are supported:

``coolprop``
    Uses :mod:`CoolProp`, i.e. the Span & Wagner (1996) Helmholtz EOS for CO2
    density and the Fenghour, Wakeham & Vesovic (1998) correlation for
    viscosity.  This is the reference-quality option and is used automatically
    whenever CoolProp is importable.

``builtin``
    A dependency-free fallback: the Spycher, Pruess & Ennis-King (2003)
    modified Redlich-Kwong EOS for CO2 density (the same EOS used by the
    Spycher solubility model and cited in EPA's AoR guidance, Table 2-1) and
    Fenghour et al. (1998) for viscosity, implemented here directly.

Brine density and viscosity use Batzle & Wang (1992) in both back-ends.
CoolProp does not provide NaCl-brine transport properties, and Batzle & Wang
is the correlation most widely reported in CCS pressure-transient work.

The choice of back-end is recorded on every result object so that a permit
reviewer can see exactly which EOS produced a number.

References
----------
Span, R. & Wagner, W. (1996) *J. Phys. Chem. Ref. Data* 25, 1509-1596.
Fenghour, A., Wakeham, W.A. & Vesovic, V. (1998) *J. Phys. Chem. Ref. Data*
    27, 31-44.
Spycher, N., Pruess, K. & Ennis-King, J. (2003) *Geochim. Cosmochim. Acta* 67,
    3015-3031.
Batzle, M. & Wang, Z. (1992) *Geophysics* 57, 1396-1408.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from . import units as U

try:  # pragma: no cover - exercised only when CoolProp is installed
    from CoolProp.CoolProp import PropsSI as _PropsSI

    HAVE_COOLPROP = True
except Exception:  # pragma: no cover
    _PropsSI = None
    HAVE_COOLPROP = False


# ==========================================================================
# CO2 critical constants and Span-Wagner saturation ancillaries
# ==========================================================================
TC_CO2 = 304.1282  # K
PC_CO2 = 7.3773e6  # Pa
RHOC_CO2 = 467.6  # kg/m^3
TTRIP_CO2 = 216.592  # K


def co2_saturation_pressure(T: float) -> float:
    """Saturation pressure of CO2 (Pa) from the Span & Wagner ancillary.

    Valid on the triple point -> critical point interval.  Returns ``PC_CO2``
    at and above the critical temperature.
    """
    if T >= TC_CO2:
        return PC_CO2
    theta = 1.0 - T / TC_CO2
    a = (-7.0602087, 1.9391218, -1.6463597, -3.2995634)
    s = (a[0] * theta + a[1] * theta ** 1.5
         + a[2] * theta ** 2.0 + a[3] * theta ** 4.0)
    return PC_CO2 * math.exp(TC_CO2 / T * s)


def near_critical(P: float, T: float,
                  temperature_margin: float = 20.0,
                  pressure_band: tuple[float, float] = (0.85, 1.6)) -> bool:
    """Is (P, T) close enough to the CO2 critical point to distrust a cubic EOS?

    Cubic equations of state lose accuracy sharply around the critical point,
    and 80-110 bar at 30-50 C is squarely inside that region - which is also
    where a good many shallow storage formations sit.
    """
    return (T < TC_CO2 + temperature_margin
            and pressure_band[0] * PC_CO2 <= P <= pressure_band[1] * PC_CO2)


# ==========================================================================
# CO2 density
# ==========================================================================
# Spycher-Pruess modified Redlich-Kwong, in the paper's units:
#   P [bar], V [cm^3/mol], T [K], R = 83.1447 bar.cm^3/(mol.K)
#   P = RT/(V - b) - a / (T^0.5 * V * (V + b))
#   a(T) = 7.54e7 - 4.13e4 * T   [bar.cm^6.K^0.5/mol^2]
#   b     = 27.8                 [cm^3/mol]
_R_RK = 83.1447
_B_RK = 27.8


def _rk_a(T: float) -> float:
    return 7.54e7 - 4.13e4 * T


def _co2_molar_volume_rk(P: float, T: float) -> float:
    """Molar volume (cm^3/mol) of CO2 from the modified RK EOS.

    ``P`` in Pa, ``T`` in K.  The cubic is solved in closed form and the root
    appropriate to the phase (liquid below the saturation pressure, vapour
    above it, single root when supercritical) is selected.
    """
    p_bar = P / U.BAR
    a = _rk_a(T)
    b = _B_RK
    sqrtT = math.sqrt(T)

    # V^3 + c2 V^2 + c1 V + c0 = 0
    c2 = -_R_RK * T / p_bar
    c1 = -(_R_RK * T * b / p_bar - a / (p_bar * sqrtT) + b * b)
    c0 = -a * b / (p_bar * sqrtT)

    roots = np.roots([1.0, c2, c1, c0])
    real = np.array([r.real for r in roots if abs(r.imag) < 1e-8 * max(1.0, abs(r.real))])
    real = real[real > b]
    if real.size == 0:
        # Numerically degenerate: fall back to ideal gas as a last resort.
        return _R_RK * T / p_bar
    if real.size == 1:
        return float(real[0])

    # Multiple real roots -> two-phase region of the cubic. Below the
    # saturation pressure the fluid is a vapour (largest root); above it a
    # liquid (smallest root).  This is the selection rule of Spycher et al.
    if T < TC_CO2 and P > co2_saturation_pressure(T):
        return float(real.min())
    return float(real.max())


def co2_density(P: float, T: float, backend: str = "auto") -> float:
    """CO2 mass density in kg/m^3.  ``P`` in Pa, ``T`` in K."""
    if backend in ("auto", "coolprop") and HAVE_COOLPROP:
        return float(_PropsSI("D", "P", P, "T", T, "CO2"))
    if backend == "coolprop" and not HAVE_COOLPROP:
        raise RuntimeError("CoolProp back-end requested but CoolProp is not installed")
    v_cm3 = _co2_molar_volume_rk(P, T)  # cm^3/mol
    return U.M_CO2 / (v_cm3 * 1e-6)  # kg/mol / (m^3/mol)


# ==========================================================================
# CO2 viscosity -- Fenghour, Wakeham & Vesovic (1998)
# ==========================================================================
_FWV_A = (0.235156, -0.491266, 5.211155e-2, 5.347906e-2, -1.537102e-2)
_FWV_D11 = 0.4071119e-2
_FWV_D21 = 0.7198037e-4
_FWV_D64 = 0.2411697e-16
_FWV_D81 = 0.2971072e-22
_FWV_D82 = -0.1627888e-22


def co2_viscosity(P: float, T: float, rho: float | None = None,
                  backend: str = "auto") -> float:
    """CO2 dynamic viscosity in Pa.s.

    The critical enhancement term is neglected, as recommended by Fenghour
    et al. outside a narrow region around the critical point; the error is
    below ~1 % for storage-formation conditions.
    """
    if backend in ("auto", "coolprop") and HAVE_COOLPROP:
        return float(_PropsSI("V", "P", P, "T", T, "CO2"))
    if rho is None:
        rho = co2_density(P, T, backend="builtin")
    t_star = T / 251.196
    ln_t = math.log(t_star)
    ln_g = sum(_FWV_A[i] * ln_t ** i for i in range(5))
    eta0 = 1.00697 * math.sqrt(T) / math.exp(ln_g)  # uPa.s
    d_eta = (_FWV_D11 * rho
             + _FWV_D21 * rho ** 2
             + _FWV_D64 * rho ** 6 / t_star ** 3
             + _FWV_D81 * rho ** 8
             + _FWV_D82 * rho ** 8 / t_star)
    return (eta0 + d_eta) * 1e-6


# ==========================================================================
# Brine -- Batzle & Wang (1992)
# ==========================================================================
def salinity_to_mass_fraction(value: float, unit: str = "ppm") -> float:
    """Convert a salinity to NaCl mass fraction (kg NaCl / kg brine).

    Accepted units: ``ppm``, ``mg/L`` (treated as ppm), ``wt%``, ``fraction``,
    ``molal`` / ``mol/kg`` (mol NaCl per kg water), ``g/L``.
    """
    u = str(unit).strip().lower().replace(" ", "")
    if u in ("ppm", "mg/l", "mgl", "mg/kg"):
        return value * 1e-6
    if u in ("wt%", "%", "pct", "percent"):
        return value * 1e-2
    if u in ("fraction", "massfraction", "-", "frac"):
        return value
    if u in ("molal", "mol/kg", "molkg", "m"):
        m_nacl = value * U.M_NACL  # kg NaCl per kg water
        return m_nacl / (1.0 + m_nacl)
    if u in ("g/l", "gl", "kg/m3"):
        return value * 1e-3  # approximate: g/L / 1000 g/L
    raise ValueError(f"unknown salinity unit {unit!r}")


def water_density(P: float, T: float) -> float:
    """Pure-water density (kg/m^3) from Batzle & Wang (1992) eq. 27."""
    t = T - 273.15  # degC
    p = P / U.MPA  # MPa
    rho = 1.0 + 1e-6 * (
        -80.0 * t - 3.3 * t ** 2 + 0.00175 * t ** 3
        + 489.0 * p - 2.0 * t * p + 0.016 * t ** 2 * p
        - 1.3e-5 * t ** 3 * p - 0.333 * p ** 2 - 0.002 * t * p ** 2
    )
    return rho * 1000.0


def brine_density(P: float, T: float, salinity_mass_fraction: float) -> float:
    """NaCl-brine density (kg/m^3) from Batzle & Wang (1992) eq. 27b.

    ``P`` in Pa, ``T`` in K, salinity as NaCl mass fraction.
    """
    s = salinity_mass_fraction
    t = T - 273.15
    p = P / U.MPA
    rho_w = water_density(P, T) / 1000.0
    rho_b = rho_w + s * (
        0.668 + 0.44 * s
        + 1e-6 * (300.0 * p - 2400.0 * p * s
                  + t * (80.0 + 3.0 * t - 3300.0 * s - 13.0 * p + 47.0 * p * s))
    )
    return rho_b * 1000.0


def brine_viscosity(T: float, salinity_mass_fraction: float) -> float:
    """NaCl-brine dynamic viscosity (Pa.s), Batzle & Wang (1992) eq. 32.

    Pressure dependence is weak (< ~2 % over the storage pressure range) and
    is neglected by the correlation.
    """
    s = salinity_mass_fraction
    t = max(T - 273.15, 1e-6)
    mu_cp = 0.1 + 0.333 * s + (1.65 + 91.9 * s ** 3) * math.exp(
        -(0.42 * (s ** 0.8 - 0.17) ** 2 + 0.045) * t ** 0.8
    )
    return mu_cp * U.CP


def brine_compressibility(P: float, T: float, salinity_mass_fraction: float,
                          dp: float = 1e5) -> float:
    """Isothermal brine compressibility (1/Pa) by central difference."""
    r1 = brine_density(P - dp, T, salinity_mass_fraction)
    r2 = brine_density(P + dp, T, salinity_mass_fraction)
    r0 = brine_density(P, T, salinity_mass_fraction)
    return (r2 - r1) / (2.0 * dp * r0)


# ==========================================================================
# convenience container
# ==========================================================================
@dataclass
class FluidState:
    """Fluid properties evaluated once at representative in-situ conditions.

    A single evaluation point is the standard simplification for analytical
    AoR screening; the vertical-equilibrium solver re-evaluates CO2 density
    and viscosity cell-by-cell when ``recompute`` is enabled.
    """

    pressure: float          # Pa
    temperature: float       # K
    salinity: float          # NaCl mass fraction
    rho_co2: float           # kg/m^3
    mu_co2: float            # Pa.s
    rho_brine: float         # kg/m^3
    mu_brine: float          # Pa.s
    c_brine: float           # 1/Pa
    backend: str = "builtin"
    notes: list[str] = field(default_factory=list)

    @property
    def delta_rho(self) -> float:
        """Brine minus CO2 density -- the buoyancy driver (kg/m^3)."""
        return self.rho_brine - self.rho_co2

    @property
    def viscosity_ratio(self) -> float:
        """mu_brine / mu_co2 (the unfavourable-mobility driver)."""
        return self.mu_brine / self.mu_co2

    def summary(self) -> dict:
        return {
            "pressure_psi": U.pressure_out(self.pressure, "psi"),
            "temperature_degF": U.temperature_out(self.temperature, "F"),
            "salinity_ppm": self.salinity * 1e6,
            "rho_co2_kg_m3": self.rho_co2,
            "rho_co2_lb_ft3": U.density_out(self.rho_co2, "lb/ft3"),
            "mu_co2_cP": U.viscosity_out(self.mu_co2, "cP"),
            "rho_brine_kg_m3": self.rho_brine,
            "rho_brine_lb_ft3": U.density_out(self.rho_brine, "lb/ft3"),
            "mu_brine_cP": U.viscosity_out(self.mu_brine, "cP"),
            "brine_compressibility_1_psi": U.compressibility_out(self.c_brine, "1/psi"),
            "delta_rho_kg_m3": self.delta_rho,
            "viscosity_ratio": self.viscosity_ratio,
            "eos_backend": self.backend,
        }


def evaluate(pressure: float, temperature: float, salinity_mass_fraction: float,
             backend: Literal["auto", "coolprop", "builtin"] = "auto",
             ) -> FluidState:
    """Evaluate the full fluid state at (P, T, salinity) in SI units."""
    use = "coolprop" if (backend in ("auto", "coolprop") and HAVE_COOLPROP) else "builtin"
    if backend == "coolprop" and not HAVE_COOLPROP:
        raise RuntimeError("CoolProp back-end requested but CoolProp is not installed")

    rho_c = co2_density(pressure, temperature, backend=use)
    mu_c = co2_viscosity(pressure, temperature, rho=rho_c, backend=use)
    rho_b = brine_density(pressure, temperature, salinity_mass_fraction)
    mu_b = brine_viscosity(temperature, salinity_mass_fraction)
    c_b = brine_compressibility(pressure, temperature, salinity_mass_fraction)

    notes = []
    if use == "builtin":
        notes.append(
            "CO2 density from the Spycher-Pruess modified Redlich-Kwong EOS "
            "(install CoolProp for the Span-Wagner reference EOS)."
        )
        if near_critical(pressure, temperature):
            notes.append(
                "WARNING: the evaluation point is near the CO2 critical point "
                f"({U.pressure_out(PC_CO2, 'bar'):.1f} bar, "
                f"{U.temperature_out(TC_CO2, 'C'):.1f} C), where the built-in "
                "cubic EOS is unreliable - errors of tens of percent in CO2 "
                "density are possible, and density feeds straight into plume "
                "volume. Install CoolProp (`pip install CoolProp`) before "
                "using this result."
            )
    if temperature < TC_CO2 and pressure < co2_saturation_pressure(temperature):
        notes.append(
            "Evaluation point lies in the CO2 gas field (P < P_sat); check that "
            "the storage formation really is above the critical pressure."
        )
    if rho_c < 200.0:
        notes.append(
            f"CO2 density is only {rho_c:.0f} kg/m3 -- gas-like. Plume volumes "
            "will be large and buoyancy strong."
        )
    return FluidState(pressure, temperature, salinity_mass_fraction,
                      rho_c, mu_c, rho_b, mu_b, c_b, backend=use, notes=notes)


def hydrostatic_pressure(depth: float, gradient: float | None = None,
                         surface_pressure: float = U.ATM) -> float:
    """Hydrostatic pressure (Pa) at ``depth`` (m below datum).

    ``gradient`` in Pa/m; defaults to a fresh-water 0.433 psi/ft column.
    """
    if gradient is None:
        gradient = U.pressure_gradient(0.433, "psi/ft")
    return surface_pressure + gradient * depth


__all__ = [
    "HAVE_COOLPROP", "TC_CO2", "PC_CO2", "RHOC_CO2",
    "co2_saturation_pressure", "co2_density", "co2_viscosity", "near_critical",
    "salinity_to_mass_fraction", "water_density", "brine_density",
    "brine_viscosity", "brine_compressibility",
    "FluidState", "evaluate", "hydrostatic_pressure",
]
