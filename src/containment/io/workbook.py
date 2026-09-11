"""The whole project as one Excel workbook, and back again.

A YAML project file is the better record: it diffs, it reviews, and it goes in
version control. It is also the thing that stops a team adopting a tool,
because the people who hold the reservoir data work in spreadsheets.

This module writes every input a run needs into one workbook, one sheet per
part of the project, and reads that workbook back into the same dictionary
:class:`containment.config.Project` takes. Nothing is lost in the round trip,
so a team can hand the workbook around, fill it in, and run it without ever
opening a text editor.

Numbers stay in the units the project declares. They are never converted on
the way out or the way in, because a spreadsheet that silently changes units
is worse than no spreadsheet.
"""

from __future__ import annotations

import csv
import os
from typing import Any

# Sheets that hold a flat key/value list rather than a table.
_KV_SHEETS = {
    "Project": "project",
    "Units": "units",
    "USDW": ("formation", "usdw"),
    "Relative permeability": "relative_permeability",
    "Threshold": "threshold",
    "Model": "model",
    "Plume": "plume",
    "Uncertainty": "uncertainty",
}

_ZONE_COLUMNS = ["name", "top_depth", "base_depth", "thickness", "porosity",
                 "permeability", "temperature", "salinity_ppm",
                 "initial_pressure", "rock_compressibility", "dip_degrees",
                 "dip_azimuth", "anisotropy_kv_kh",
                 "confining_top_depth", "confining_base_depth"]

_WELL_COLUMNS = ["name", "kind", "zone", "latitude", "longitude", "x", "y",
                 "rate", "rate_unit", "start_year", "stop_year",
                 "start_date", "stop_date", "max_bhp", "radius", "schedule"]

_HEADER_FILL = "DDE6F2"


def _require_openpyxl():
    try:
        import openpyxl  # noqa: F401
    except ImportError as exc:      # pragma: no cover - environment dependent
        raise ImportError(
            "reading and writing project workbooks needs openpyxl: "
            "pip install openpyxl, or install containment[full]") from exc


def _flatten(d: dict, prefix: str = "") -> list[tuple[str, Any]]:
    """A nested dict as dotted key/value rows, so one sheet can hold it."""
    rows: list[tuple[str, Any]] = []
    for k, v in (d or {}).items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            rows.extend(_flatten(v, f"{key}."))
        elif isinstance(v, (list, tuple)):
            rows.append((key, ", ".join(str(x) for x in v)))
        else:
            rows.append((key, v))
    return rows


def _unflatten(rows) -> dict:
    """The inverse of :func:`_flatten`."""
    out: dict = {}
    for key, value in rows:
        if key is None or str(key).strip() == "":
            continue
        cur = out
        parts = str(key).split(".")
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = value
    return out


def _style_header(ws, ncols: int) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill

    fill = PatternFill("solid", fgColor=_HEADER_FILL)
    for col in range(1, ncols + 1):
        cell = ws.cell(row=1, column=col)
        cell.font = Font(bold=True)
        cell.fill = fill
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"


def _autosize(ws, limit: int = 46) -> None:
    for col in ws.columns:
        width = max((len(str(c.value)) for c in col if c.value is not None),
                    default=8)
        ws.column_dimensions[col[0].column_letter].width = min(width + 2, limit)


def _kv_sheet(wb, title: str, data: dict, note: str = "") -> None:
    ws = wb.create_sheet(title)
    ws.append(["key", "value"])
    for key, value in _flatten(data):
        ws.append([key, value])
    if note:
        ws.append([])
        ws.append(["note", note])
    _style_header(ws, 2)
    _autosize(ws)


def _table_sheet(wb, title: str, rows: list[dict], columns: list[str]) -> None:
    ws = wb.create_sheet(title)
    ws.append(columns)
    for row in rows:
        ws.append([row.get(c) for c in columns])
    _style_header(ws, len(columns))
    _autosize(ws)


# ==========================================================================
def to_excel(project, path: str, *, penetrations_csv: str | None = None) -> str:
    """Write every input of a project into one workbook.

    ``project`` is a :class:`~containment.config.Project` or the dictionary one
    was built from. Values keep the units the project declared.
    """
    _require_openpyxl()
    from openpyxl import Workbook

    d = project.to_dict() if hasattr(project, "to_dict") else dict(project)
    wb = Workbook()
    wb.remove(wb.active)

    # ---- read me
    ws = wb.create_sheet("Read me")
    for line in [
        ["Containment project workbook"],
        [],
        ["This workbook holds every input one run needs. Fill it in, save it,"],
        ["and load it with:"],
        [],
        ["    containment run project.xlsx"],
        [],
        ["or in the browser app, choose 'Upload project' and pick this file."],
        [],
        ["Numbers are in the units declared on the Units sheet. Nothing is"],
        ["converted when this file is written or read, so changing a unit on"],
        ["that sheet changes how every number on the others is interpreted."],
        [],
        ["Sheets:"],
        ["  Project               name, operator, permit, start date, CRS"],
        ["  Units                 the units every other sheet is written in"],
        ["  Injection zones       one row per zone; several rows is a stacked"],
        ["                        completion, each with its own confining zone"],
        ["  USDW                  the interval being protected"],
        ["  Relative permeability the two-phase flow functions"],
        ["  Threshold             how the critical pressure is computed"],
        ["  Model                 engine, boundary, grid, horizon"],
        ["  Plume                 the saturation cutoff that counts as plume"],
        ["  Wells                 injectors, extractors and their schedules"],
        ["  Faults                sealing or partly sealing traces"],
        ["  Penetrations          the artificial penetrations to screen"],
        ["  Uncertainty           tornado and Monte Carlo settings"],
    ]:
        ws.append(line)
    ws["A1"].font = __import__("openpyxl").styles.Font(bold=True, size=14)
    ws.column_dimensions["A"].width = 74

    # ---- key/value sheets
    for title, key in _KV_SHEETS.items():
        if isinstance(key, tuple):
            data = d.get(key[0], {}).get(key[1], {})
        else:
            data = d.get(key, {})
        _kv_sheet(wb, title, data or {})

    # ---- injection zones, one row each
    formation = d.get("formation", {}) or {}
    zones = list(formation.get("injection_zones") or [])
    if not zones and formation.get("injection_zone"):
        z = dict(formation["injection_zone"])
        z.setdefault("name", "injection zone")
        cz = formation.get("confining_zone") or {}
        z["confining_top_depth"] = cz.get("top_depth")
        z["confining_base_depth"] = cz.get("base_depth")
        zones = [z]
    else:
        flat = []
        for z in zones:
            z = dict(z)
            cz = z.pop("confining_zone", None) or formation.get("confining_zone") or {}
            z["confining_top_depth"] = cz.get("top_depth")
            z["confining_base_depth"] = cz.get("base_depth")
            flat.append(z)
        zones = flat
    _table_sheet(wb, "Injection zones", zones, _ZONE_COLUMNS)

    # ---- wells
    wells = []
    for w in d.get("wells", []) or []:
        row = dict(w)
        if isinstance(row.get("schedule"), list):
            row["schedule"] = "; ".join(
                f"{s.get('year', s.get('date', ''))}:{s.get('rate', '')}"
                for s in row["schedule"])
        wells.append(row)
    _table_sheet(wb, "Wells", wells, _WELL_COLUMNS)

    # ---- faults
    faults = []
    for f in d.get("faults", []) or []:
        row = {"name": f.get("name"), "multiplier": f.get("multiplier")}
        pts = f.get("latlon") or f.get("points") or []
        row["points"] = "; ".join(f"{a}, {b}" for a, b in pts)
        row["coordinates"] = "latlon" if f.get("latlon") else "xy"
        faults.append(row)
    _table_sheet(wb, "Faults", faults, ["name", "multiplier", "coordinates",
                                        "points"])

    # ---- penetrations, read out of the CSV the project points at
    pen_cfg = d.get("penetrations", {}) or {}
    csv_path = penetrations_csv or pen_cfg.get("csv")
    pen_rows, pen_cols = [], []
    if csv_path and os.path.exists(csv_path):
        with open(csv_path, newline="", encoding="utf-8-sig") as fh:
            rdr = csv.DictReader(fh)
            pen_cols = list(rdr.fieldnames or [])
            pen_rows = [dict(r) for r in rdr]
    if pen_rows:
        _table_sheet(wb, "Penetrations", pen_rows, pen_cols)
        ws = wb["Penetrations"]
        ws.insert_rows(1)
        ws["A1"] = (f"coordinate_unit: {pen_cfg.get('coordinate_unit', 'm')} "
                    f"(source: {csv_path})")
        ws["A1"].font = __import__("openpyxl").styles.Font(italic=True)
    else:
        _table_sheet(wb, "Penetrations", [], ["name", "api", "type", "status",
                                              "latitude", "longitude",
                                              "total_depth", "year_drilled",
                                              "year_abandoned", "plug_depths",
                                              "plug_material", "cased",
                                              "records_complete", "mit_passed",
                                              "notes"])

    wb.save(path)
    return path


# ==========================================================================
def from_excel(path: str) -> dict:
    """Read a workbook written by :func:`to_excel` back into a project dict."""
    _require_openpyxl()
    from openpyxl import load_workbook

    wb = load_workbook(path, data_only=True)
    d: dict = {}

    def kv(title: str) -> dict:
        if title not in wb.sheetnames:
            return {}
        ws = wb[title]
        rows = []
        for key, value in ws.iter_rows(min_row=2, max_col=2, values_only=True):
            if key is None or str(key).strip().lower() == "note":
                continue
            rows.append((key, value))
        return _unflatten(rows)

    def rows_of(title: str, header_row: int = 1) -> list[dict]:
        if title not in wb.sheetnames:
            return []
        ws = wb[title]
        data = list(ws.iter_rows(min_row=header_row, values_only=True))
        if not data:
            return []
        header = [str(c) if c is not None else "" for c in data[0]]
        out = []
        for raw in data[1:]:
            row = {h: v for h, v in zip(header, raw, strict=False)
                   if h and v is not None and str(v).strip() != ""}
            if row:
                out.append(row)
        return out

    for title, key in _KV_SHEETS.items():
        data = kv(title)
        if not data:
            continue
        if isinstance(key, tuple):
            d.setdefault(key[0], {})[key[1]] = data
        else:
            d[key] = data

    # ---- injection zones
    zones = []
    for z in rows_of("Injection zones"):
        z = dict(z)
        top = z.pop("confining_top_depth", None)
        base = z.pop("confining_base_depth", None)
        if top is not None or base is not None:
            z["confining_zone"] = {k: v for k, v in
                                   (("top_depth", top), ("base_depth", base))
                                   if v is not None}
        zones.append(z)
    if zones:
        d.setdefault("formation", {})
        if len(zones) == 1:
            one = dict(zones[0])
            cz = one.pop("confining_zone", None)
            one.pop("name", None)
            d["formation"]["injection_zone"] = one
            if cz:
                d["formation"]["confining_zone"] = cz
        else:
            d["formation"]["injection_zones"] = zones

    # ---- wells
    wells = []
    for w in rows_of("Wells"):
        w = dict(w)
        sched = w.pop("schedule", None)
        if sched:
            steps = []
            for part in str(sched).split(";"):
                if ":" not in part:
                    continue
                when, rate = part.split(":", 1)
                when, rate = when.strip(), rate.strip()
                key = "date" if "-" in when else "year"
                steps.append({key: (when if key == "date" else float(when)),
                              "rate": float(rate)})
            if steps:
                w["schedule"] = steps
        for date_key in ("start_date", "stop_date"):
            if w.get(date_key) is not None:
                w[date_key] = str(w[date_key])[:10]
        wells.append(w)
    if wells:
        d["wells"] = wells

    # ---- faults
    faults = []
    for f in rows_of("Faults"):
        pts = []
        for pair in str(f.get("points", "")).split(";"):
            bits = [b.strip() for b in pair.split(",") if b.strip()]
            if len(bits) == 2:
                pts.append([float(bits[0]), float(bits[1])])
        if not pts:
            continue
        entry = {"name": f.get("name"), "multiplier": f.get("multiplier", 0.0)}
        entry["latlon" if f.get("coordinates", "latlon") == "latlon"
              else "points"] = pts
        faults.append(entry)
    if faults:
        d["faults"] = faults

    # ---- penetrations: written back out as a CSV beside the workbook
    pens = rows_of("Penetrations", header_row=2)
    if pens:
        out_csv = os.path.splitext(path)[0] + "_penetrations.csv"
        cols: list[str] = []
        for row in pens:
            for k in row:
                if k not in cols:
                    cols.append(k)
        with open(out_csv, "w", newline="", encoding="utf-8") as fh:
            wr = csv.DictWriter(fh, fieldnames=cols)
            wr.writeheader()
            for row in pens:
                wr.writerow(row)
        unit = "m"
        header = wb["Penetrations"]["A1"].value or ""
        if "coordinate_unit:" in str(header):
            unit = str(header).split("coordinate_unit:")[1].split("(")[0].strip()
        d["penetrations"] = {"csv": out_csv, "coordinate_unit": unit}

    return d


__all__ = ["to_excel", "from_excel"]
