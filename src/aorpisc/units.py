"""Unit handling for AoR/PISC calculations.

Everything inside the solver runs in **SI**:

======================  =====================
quantity                internal SI unit
======================  =====================
length                  m
pressure                Pa
temperature             K
mass                    kg
time                    s
permeability            m^2
density                 kg/m^3
viscosity               Pa.s
volumetric rate         m^3/s
mass rate               kg/s
compressibility         1/Pa
======================  =====================

Class VI permit applications are written almost entirely in oilfield/US
customary units (psi, ft, mD, ppg, MMT/yr, acres).  Every public entry point
therefore accepts a unit string and converts on the way in, and the reporting
layer converts back on the way out.  Keeping one and only one internal unit
system is what stops the "psi vs. psia vs. MPa" class of error that shows up
repeatedly when re-deriving operator numbers by hand.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# physical constants
# --------------------------------------------------------------------------
G = 9.80665  # standard gravity, m/s^2
R_GAS = 8.31446261815324  # J/(mol.K)
M_CO2 = 44.0095e-3  # kg/mol
M_H2O = 18.01528e-3  # kg/mol
M_NACL = 58.442769e-3  # kg/mol

# --------------------------------------------------------------------------
# elementary conversion factors (multiply value-in-unit by factor -> SI)
# --------------------------------------------------------------------------
FT = 0.3048
IN = 0.0254
MILE = 1609.344
KM = 1000.0
ACRE = 4046.8564224  # m^2
SQMI = 2589988.110336  # m^2
PSI = 6894.757293168361  # Pa
BAR = 1.0e5
MPA = 1.0e6
KPA = 1.0e3
ATM = 101325.0
DARCY = 9.869232667160128e-13  # m^2
MD = DARCY * 1e-3
CP = 1.0e-3  # Pa.s
DAY = 86400.0
YEAR = 365.25 * DAY
TONNE = 1000.0  # kg (metric tonne)
SHORT_TON = 907.18474  # kg
LBM = 0.45359237
BBL = 0.158987294928  # m^3
MMT = 1.0e9  # kg  (million metric tonnes)

_LENGTH = {
    "m": 1.0, "meter": 1.0, "meters": 1.0,
    "km": KM, "kilometer": KM,
    "ft": FT, "feet": FT, "foot": FT,
    "in": IN, "inch": IN,
    "mi": MILE, "mile": MILE, "miles": MILE,
    "cm": 0.01, "mm": 0.001,
}

_PRESSURE = {
    "pa": 1.0, "kpa": KPA, "mpa": MPA, "gpa": 1e9,
    "bar": BAR, "bars": BAR, "barg": BAR,
    "psi": PSI, "psia": PSI, "psig": PSI,  # gauge/absolute handled by caller
    "atm": ATM,
}

_AREA = {
    "m2": 1.0, "m^2": 1.0, "sqm": 1.0,
    "km2": KM ** 2, "km^2": KM ** 2,
    "ft2": FT ** 2, "ft^2": FT ** 2,
    "acre": ACRE, "acres": ACRE,
    "mi2": SQMI, "mi^2": SQMI, "sqmi": SQMI, "sq_mi": SQMI,
}

_PERM = {
    "m2": 1.0, "m^2": 1.0,
    "d": DARCY, "darcy": DARCY,
    "md": MD, "millidarcy": MD, "millidarcies": MD,
    "ud": DARCY * 1e-6, "microdarcy": DARCY * 1e-6,
    "nd": DARCY * 1e-9, "nanodarcy": DARCY * 1e-9,
}

_VISC = {"pa.s": 1.0, "pas": 1.0, "pa_s": 1.0, "cp": CP, "mpa.s": CP, "p": 0.1}

_TIME = {
    "s": 1.0, "sec": 1.0, "second": 1.0, "seconds": 1.0,
    "min": 60.0, "hr": 3600.0, "hour": 3600.0, "h": 3600.0,
    "d": DAY, "day": DAY, "days": DAY,
    "yr": YEAR, "y": YEAR, "year": YEAR, "years": YEAR,
}

_MASS = {
    "kg": 1.0, "g": 1e-3, "t": TONNE, "tonne": TONNE, "tonnes": TONNE,
    "metric_ton": TONNE, "mt": 1e9,  # Mt = megatonne = 1e9 kg
    "mmt": MMT, "million_tonnes": MMT,
    "ton": SHORT_TON, "short_ton": SHORT_TON,
    "lb": LBM, "lbm": LBM,
}

_VOLUME = {
    "m3": 1.0, "m^3": 1.0,
    "ft3": FT ** 3, "ft^3": FT ** 3, "scf": FT ** 3,
    "bbl": BBL, "stb": BBL, "rb": BBL,
    "l": 1e-3, "liter": 1e-3,
}

_DENSITY = {
    "kg/m3": 1.0, "kg/m^3": 1.0,
    "g/cm3": 1000.0, "g/cc": 1000.0, "sg": 1000.0,
    "lb/ft3": LBM / FT ** 3, "lbm/ft3": LBM / FT ** 3, "pcf": LBM / FT ** 3,
    "ppg": LBM / (BBL / 42.0),  # lb per US gallon
    "lb/gal": LBM / (BBL / 42.0),
}


def _lookup(table: dict, unit: str, kind: str) -> float:
    key = str(unit).strip().lower().replace(" ", "")
    if key not in table:
        raise ValueError(
            f"unknown {kind} unit {unit!r}; supported: {sorted(table)}"
        )
    return table[key]


# --------------------------------------------------------------------------
# scalar converters:  to_si(value, unit)  /  from_si(value_si, unit)
# --------------------------------------------------------------------------
def length(v, unit="m"):
    return v * _lookup(_LENGTH, unit, "length")


def length_out(v_si, unit="m"):
    return v_si / _lookup(_LENGTH, unit, "length")


def pressure(v, unit="Pa"):
    return v * _lookup(_PRESSURE, unit, "pressure")


def pressure_out(v_si, unit="Pa"):
    return v_si / _lookup(_PRESSURE, unit, "pressure")


def area(v, unit="m2"):
    return v * _lookup(_AREA, unit, "area")


def area_out(v_si, unit="m2"):
    return v_si / _lookup(_AREA, unit, "area")


def permeability(v, unit="mD"):
    return v * _lookup(_PERM, unit, "permeability")


def permeability_out(v_si, unit="mD"):
    return v_si / _lookup(_PERM, unit, "permeability")


def viscosity(v, unit="cP"):
    return v * _lookup(_VISC, unit, "viscosity")


def viscosity_out(v_si, unit="cP"):
    return v_si / _lookup(_VISC, unit, "viscosity")


def time(v, unit="s"):
    return v * _lookup(_TIME, unit, "time")


def time_out(v_si, unit="s"):
    return v_si / _lookup(_TIME, unit, "time")


def mass(v, unit="kg"):
    return v * _lookup(_MASS, unit, "mass")


def mass_out(v_si, unit="kg"):
    return v_si / _lookup(_MASS, unit, "mass")


def volume(v, unit="m3"):
    return v * _lookup(_VOLUME, unit, "volume")


def volume_out(v_si, unit="m3"):
    return v_si / _lookup(_VOLUME, unit, "volume")


def density(v, unit="kg/m3"):
    return v * _lookup(_DENSITY, unit, "density")


def density_out(v_si, unit="kg/m3"):
    return v_si / _lookup(_DENSITY, unit, "density")


def temperature(v, unit="K"):
    """Convert temperature to kelvin."""
    u = str(unit).strip().lower().lstrip("deg").lstrip(" deg")
    if u in ("k", "kelvin"):
        return v
    if u in ("c", "celsius"):
        return v + 273.15
    if u in ("f", "fahrenheit"):
        return (v - 32.0) * 5.0 / 9.0 + 273.15
    if u in ("r", "rankine"):
        return v * 5.0 / 9.0
    raise ValueError(f"unknown temperature unit {unit!r}")


def temperature_out(v_si, unit="K"):
    u = str(unit).strip().lower().lstrip("deg").lstrip(" deg")
    if u in ("k", "kelvin"):
        return v_si
    if u in ("c", "celsius"):
        return v_si - 273.15
    if u in ("f", "fahrenheit"):
        return (v_si - 273.15) * 9.0 / 5.0 + 32.0
    if u in ("r", "rankine"):
        return v_si * 9.0 / 5.0
    raise ValueError(f"unknown temperature unit {unit!r}")


def compressibility(v, unit="1/Pa"):
    u = str(unit).strip().lower().replace(" ", "")
    if u in ("1/pa", "pa-1", "pa^-1"):
        return v
    if u in ("1/psi", "psi-1", "psi^-1"):
        return v / PSI
    if u in ("1/bar", "bar-1"):
        return v / BAR
    if u in ("1/mpa", "mpa-1"):
        return v / MPA
    raise ValueError(f"unknown compressibility unit {unit!r}")


def compressibility_out(v_si, unit="1/Pa"):
    u = str(unit).strip().lower().replace(" ", "")
    if u in ("1/pa", "pa-1", "pa^-1"):
        return v_si
    if u in ("1/psi", "psi-1", "psi^-1"):
        return v_si * PSI
    if u in ("1/bar", "bar-1"):
        return v_si * BAR
    if u in ("1/mpa", "mpa-1"):
        return v_si * MPA
    raise ValueError(f"unknown compressibility unit {unit!r}")


# --------------------------------------------------------------------------
# composite rate converters
# --------------------------------------------------------------------------
def mass_rate(v, unit="kg/s"):
    """e.g. 'MMT/yr', 'tonne/day', 'ton/day', 'kg/s', 'Mt/yr'."""
    m_u, _, t_u = str(unit).partition("/")
    if not t_u:
        raise ValueError(f"mass-rate unit must look like 'MMT/yr', got {unit!r}")
    return mass(v, m_u) / _lookup(_TIME, t_u, "time")


def mass_rate_out(v_si, unit="kg/s"):
    m_u, _, t_u = str(unit).partition("/")
    return mass_out(v_si, m_u) * _lookup(_TIME, t_u, "time")


def volume_rate(v, unit="m3/s"):
    """e.g. 'bbl/day', 'm3/day', 'ft3/day'."""
    v_u, _, t_u = str(unit).partition("/")
    if not t_u:
        raise ValueError(f"volume-rate unit must look like 'bbl/day', got {unit!r}")
    return volume(v, v_u) / _lookup(_TIME, t_u, "time")


def volume_rate_out(v_si, unit="m3/s"):
    v_u, _, t_u = str(unit).partition("/")
    return volume_out(v_si, v_u) * _lookup(_TIME, t_u, "time")


def pressure_gradient(v, unit="psi/ft"):
    """Pressure gradient, e.g. mud weight expressed as 0.468 psi/ft -> Pa/m."""
    p_u, _, l_u = str(unit).partition("/")
    if not l_u:
        raise ValueError(f"gradient unit must look like 'psi/ft', got {unit!r}")
    return pressure(v, p_u) / _lookup(_LENGTH, l_u, "length")


def pressure_gradient_out(v_si, unit="psi/ft"):
    p_u, _, l_u = str(unit).partition("/")
    return pressure_out(v_si, p_u) * _lookup(_LENGTH, l_u, "length")


def ppg_to_gradient_si(ppg: float) -> float:
    """Mud weight in lb/gal -> hydrostatic gradient in Pa/m.

    The familiar field shortcut is ``0.052 psi/ft per ppg`` (9.0 ppg ->
    0.468 psi/ft); this returns the exact value, 0.0519480... psi/ft per ppg.
    """
    return density(ppg, "ppg") * G


__all__ = [
    "G", "R_GAS", "M_CO2", "M_H2O", "M_NACL",
    "FT", "MILE", "PSI", "MPA", "BAR", "MD", "DARCY", "CP", "DAY", "YEAR",
    "TONNE", "ACRE", "SQMI", "MMT", "BBL", "LBM",
    "length", "length_out", "pressure", "pressure_out", "area", "area_out",
    "permeability", "permeability_out", "viscosity", "viscosity_out",
    "time", "time_out", "mass", "mass_out", "volume", "volume_out",
    "density", "density_out", "temperature", "temperature_out",
    "compressibility", "compressibility_out",
    "mass_rate", "mass_rate_out", "volume_rate", "volume_rate_out",
    "pressure_gradient", "pressure_gradient_out", "ppg_to_gradient_si",
]
