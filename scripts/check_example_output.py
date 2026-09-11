"""Assert that a completed `aorpisc run` produced a sane result.

Used by CI as a smoke test on the shipped example. Kept as a checked-in file
rather than an inline heredoc because the CI matrix includes Windows runners,
where the default shell is PowerShell and a bash heredoc does not parse.

    python scripts/check_example_output.py ci-out/<stem>_summary.json
"""

from __future__ import annotations

import json
import sys


def main(path: str) -> int:
    with open(path, encoding="utf-8") as fh:
        s = json.load(fh)

    checks = {
        "AoR area is positive": s["aor"]["aor_area_acres"] > 0,
        "threshold pressure is positive": s["threshold"]["delta_p_critical_psi"] > 0,
        "a plume was produced": s["pisc"]["peak_plume_area_acres"] > 0,
        "the AoR is at least as large as either component": (
            s["aor"]["aor_area_acres"] >= max(s["aor"]["plume_area_acres"],
                                              s["aor"]["pressure_front_area_acres"]) - 1e-6),
        "CO2 mass balance closed": (
            s.get("ve_solver", {}).get("mass_balance_error_fraction", 0.0) < 0.02),
        "the closed-form checks bracket sensibly": (
            s["analytical_checks"]["volumetric_radius_ft"]
            < s["analytical_checks"]["nordbotten_celia_radius_ft"]),
    }

    width = max(len(k) for k in checks)
    failed = 0
    for name, ok in checks.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<{width}}")
        failed += not ok

    print(f"\n  AoR: {s['aor']['aor_area_acres']:,.0f} acres "
          f"({s['aor']['aor_area_sq_mi']:,.2f} sq mi), "
          f"threshold {s['threshold']['delta_p_critical_psi']:,.0f} psi")
    if failed:
        print(f"\n{failed} check(s) failed", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
