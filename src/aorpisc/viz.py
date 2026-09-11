"""Figures for AoR and PISC results.

Static figures use matplotlib (they go into reports and PDFs); the browser app
uses the Plotly builders at the bottom of this module so the same numbers are
hoverable.

Design rules applied throughout
-------------------------------
* One y-axis per panel.  Where two quantities matter -- plume area and
  migration rate, say -- they are separate stacked panels sharing an x-axis,
  never two scales on one frame.
* Categorical colour is assigned by identity in a fixed order and never
  cycled: pressure front is always blue, plume always orange, and the AoR
  union is drawn as a heavy ink outline because it is the result, not a peer
  series.
* Magnitude fields (pressure buildup, inclusion probability) use a single-hue
  light-to-dark sequential ramp.  Change maps use a blue/red diverging ramp
  with a neutral midpoint.
* Every panel with two or more series carries a legend, and series are direct-
  labelled where the geometry allows, so identity never rests on colour alone.
* Status colours are reserved for pass/fail verdicts and are never reused as
  a series colour.

The palette is the validated default from the accompanying design system:
categorical slots blue ``#2a78d6`` / orange ``#eb6834`` / aqua ``#1baf7a``
clear the colour-vision-deficiency and normal-vision separation floors on all
pairs in both light and dark modes.
"""

from __future__ import annotations

import numpy as np

from . import units as U

# --------------------------------------------------------------------------
# palette
# --------------------------------------------------------------------------
LIGHT = {
    "surface": "#fcfcfb",
    "ink": "#0b0b0b",
    "ink_2": "#52514e",
    "ink_3": "#8a8983",
    "grid": "#e4e3df",
    "series": ("#2a78d6", "#eb6834", "#1baf7a", "#eda100"),
    "seq": ("#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"),
    "div_low": "#2a78d6", "div_mid": "#f0efec", "div_high": "#e34948",
    "good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b",
}

DARK = {
    "surface": "#1a1a19",
    "ink": "#ffffff",
    "ink_2": "#c3c2b7",
    "ink_3": "#8a8983",
    "grid": "#383835",
    "series": ("#3987e5", "#d95926", "#199e70", "#c98500"),
    "seq": ("#0d366b", "#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb"),
    "div_low": "#3987e5", "div_mid": "#383835", "div_high": "#e66767",
    "good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b",
}

PRESSURE_COLOR = 0   # categorical slot for the pressure front
PLUME_COLOR = 1      # categorical slot for the plume


def palette(theme: str = "light") -> dict:
    return DARK if str(theme).lower() == "dark" else LIGHT


def _sequential_cmap(theme: str = "light", name: str = "aorpisc_seq"):
    from matplotlib.colors import LinearSegmentedColormap

    p = palette(theme)
    steps = list(p["seq"])
    if theme == "light":
        steps = [p["surface"]] + steps
    else:
        steps = [p["surface"]] + steps
    return LinearSegmentedColormap.from_list(name, steps)


def _diverging_cmap(theme: str = "light"):
    from matplotlib.colors import LinearSegmentedColormap

    p = palette(theme)
    return LinearSegmentedColormap.from_list(
        "aorpisc_div", [p["div_low"], p["div_mid"], p["div_high"]])


def _style(ax, theme: str, xlabel="", ylabel="", title=""):
    p = palette(theme)
    ax.set_facecolor(p["surface"])
    ax.figure.patch.set_facecolor(p["surface"])
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(p["grid"])
        ax.spines[side].set_linewidth(1.0)
    ax.tick_params(colors=p["ink_2"], labelsize=9, length=3, width=1.0)
    ax.grid(True, color=p["grid"], linewidth=0.8, alpha=0.9)
    ax.set_axisbelow(True)
    if xlabel:
        ax.set_xlabel(xlabel, color=p["ink_2"], fontsize=10)
    if ylabel:
        ax.set_ylabel(ylabel, color=p["ink_2"], fontsize=10)
    if title:
        ax.set_title(title, color=p["ink"], fontsize=12, loc="left", pad=10)
    return ax


def _legend(ax, theme: str, **kw):
    p = palette(theme)
    leg = ax.legend(frameon=False, fontsize=9, labelcolor=p["ink_2"], **kw)
    return leg


def _polys(geom):
    if geom is None or getattr(geom, "is_empty", True):
        return []
    return list(geom.geoms) if hasattr(geom, "geoms") else [geom]


def _draw_geom(ax, geom, *, facecolor=None, edgecolor=None, lw=1.5,
               alpha=1.0, hatch=None, zorder=2, label=None, ls="-"):
    from matplotlib.patches import Polygon as MplPolygon

    first = True
    for g in _polys(geom):
        xy = np.asarray(g.exterior.coords)
        ax.add_patch(MplPolygon(
            xy, closed=True, facecolor=facecolor or "none",
            edgecolor=edgecolor or "none", linewidth=lw, alpha=alpha,
            hatch=hatch, zorder=zorder, linestyle=ls,
            label=label if first else None))
        for interior in g.interiors:
            ax.add_patch(MplPolygon(
                np.asarray(interior.coords), closed=True,
                facecolor=palette("light")["surface"], edgecolor=edgecolor or "none",
                linewidth=lw, zorder=zorder + 0.1, linestyle=ls))
        first = False


# ==========================================================================
# 1. the AoR map
# ==========================================================================
def aor_map(result, *, x=None, y=None, dp_field=None, threshold=None,
            wells=None, penetrations=None, theme="light",
            length_unit="mi", figsize=(9.5, 8.5), ax=None,
            zoom_pad=0.35, title="Area of Review"):
    """Map of the AoR with its plume and pressure-front components.

    The pressure-buildup field, if supplied, underlies the polygons as a
    single-hue sequential ramp so the reader can see how steeply the pressure
    falls off toward the threshold contour rather than only where the contour
    landed.

    The view is framed on the AoR with ``zoom_pad`` of margin rather than on
    the whole model domain: a domain sized to keep the boundary out of the way
    is, by design, much larger than the answer, and plotting all of it shrinks
    the AoR to a dot.
    """
    import matplotlib.pyplot as plt

    p = palette(theme)
    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    else:
        fig = ax.figure
    scale = 1.0 / U.length(1.0, length_unit)

    if dp_field is not None and x is not None and y is not None:
        dp_psi = U.pressure_out(np.asarray(dp_field), "psi")
        thr_psi = U.pressure_out(result.threshold_pressure, "psi")
        # Clip the ramp a little above the threshold. The buildup at the
        # wellbore is an order of magnitude larger than the threshold, and
        # scaling to it flattens the whole map into one dark tone exactly
        # where the contour that matters lives.
        vmax = max(2.5 * thr_psi, float(np.nanpercentile(dp_psi, 97)), 1.0)
        im = ax.pcolormesh(np.asarray(x) * scale, np.asarray(y) * scale,
                           np.clip(dp_psi, 0.0, vmax),
                           cmap=_sequential_cmap(theme), shading="auto",
                           vmin=0.0, vmax=vmax, alpha=0.85,
                           zorder=0, rasterized=True)
        cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.03, shrink=0.85,
                          extend="max")
        cb.set_label(f"maximum pressure buildup (psi, clipped at {vmax:,.0f})",
                     color=p["ink_2"], fontsize=9)
        cb.ax.tick_params(colors=p["ink_2"], labelsize=8)
        cb.outline.set_visible(False)
        if thr_psi > 0:
            cb.ax.axhline(thr_psi, color=p["ink"], linewidth=1.6)
            cb.ax.annotate("threshold", (0.5, thr_psi), xycoords=("axes fraction", "data"),
                           ha="center", va="bottom", fontsize=7.5, color=p["ink"])

    def scaled(geom):
        from shapely.affinity import scale as sscale
        return sscale(geom, xfact=scale, yfact=scale, origin=(0, 0))

    if result.pressure_front is not None and not result.pressure_front.is_empty:
        _draw_geom(ax, scaled(result.pressure_front),
                   facecolor="none", alpha=1.0,
                   edgecolor=p["series"][PRESSURE_COLOR], lw=2.2, zorder=2,
                   label=f"pressure front (dP >= "
                         f"{U.pressure_out(result.threshold_pressure, 'psi'):,.0f} psi)")
    if result.plume is not None and not result.plume.is_empty:
        _draw_geom(ax, scaled(result.plume),
                   facecolor=p["series"][PLUME_COLOR], alpha=0.45,
                   edgecolor=p["series"][PLUME_COLOR], lw=2.2, zorder=3,
                   label=f"CO2 plume ({result.plume_criterion})")
    if result.aor is not None and not result.aor.is_empty:
        # When one component contains the other, the union is that component
        # and the two boundaries are the same line. A solid AoR drawn on top
        # would erase it, so dash the AoR and say so in the legend.
        coincident = result.coincident_with()
        _draw_geom(ax, scaled(result.aor), facecolor=None, edgecolor=p["ink"],
                   lw=2.4, zorder=5,
                   ls=(0, (7, 4)) if coincident else "-",
                   label=f"AoR - {result.area_acres:,.0f} acres "
                         f"({result.area_sq_mi:,.1f} sq mi)"
                         + (f", on the {coincident}" if coincident else ""))

    if wells:
        wx = [w.x * scale for w in wells if getattr(w, "kind", "injector") == "injector"]
        wy = [w.y * scale for w in wells if getattr(w, "kind", "injector") == "injector"]
        ax.scatter(wx, wy, s=110, marker="v", color=p["ink"],
                   edgecolor=p["surface"], linewidth=2.0, zorder=7,
                   label="CO2 injector")
        # Push each label radially outward from the centre of the well field.
        # A row of closely spaced injectors is the common case, and radial
        # placement fans the labels apart instead of stacking them.
        inj = [w for w in wells if getattr(w, "kind", "injector") == "injector"]
        if inj:
            cx0 = np.mean([w.x for w in inj])
            cy0 = np.mean([w.y for w in inj])
            fallback = [(1.0, 0.6), (1.0, -0.9), (-1.0, 0.6), (-1.0, -0.9)]
            for k, w in enumerate(inj):
                ux, uy = w.x - cx0, w.y - cy0
                norm = np.hypot(ux, uy)
                if norm < 1e-9:
                    ux, uy = fallback[k % len(fallback)]
                    norm = np.hypot(ux, uy)
                ux, uy = ux / norm, uy / norm
                ax.annotate(w.name, (w.x * scale, w.y * scale),
                            textcoords="offset points",
                            xytext=(14 * ux, 14 * uy - 4),
                            ha="left" if ux >= 0 else "right",
                            va="bottom" if uy >= 0 else "top",
                            fontsize=8.5, color=p["ink"], zorder=8,
                            bbox=dict(boxstyle="round,pad=0.15",
                                      fc=p["surface"], ec="none", alpha=0.8))
        ex = [w.x * scale for w in wells if getattr(w, "kind", "") == "extractor"]
        ey = [w.y * scale for w in wells if getattr(w, "kind", "") == "extractor"]
        if ex:
            ax.scatter(ex, ey, s=110, marker="^", color=p["series"][2],
                       edgecolor=p["surface"], linewidth=2.0, zorder=7,
                       label="brine extractor")

    if penetrations:
        groups = {
            "corrective action": (p["critical"], "X", 70),
            "field testing": (p["warning"], "s", 46),
            "monitor": (p["ink_2"], "o", 34),
            "no action": (p["ink_3"], ".", 24),
        }
        for action, (c, m, s) in groups.items():
            sel = [w for w in penetrations if w.in_aor and w.action == action]
            if not sel:
                continue
            ax.scatter([w.x * scale for w in sel], [w.y * scale for w in sel],
                       s=s, marker=m, color=c, zorder=6, linewidth=1.4,
                       label=f"{action} ({len(sel)})")

    _style(ax, theme, xlabel=f"easting ({length_unit})",
           ylabel=f"northing ({length_unit})", title=title)

    # frame on the answer, not on the domain
    focus = result.aor if (result.aor is not None and not result.aor.is_empty)         else result.plume
    if focus is not None and not focus.is_empty:
        x0, y0, x1, y1 = (v * scale for v in focus.bounds)
        half = 0.5 * max(x1 - x0, y1 - y0) * (1.0 + zoom_pad)
        cx, cy = 0.5 * (x0 + x1), 0.5 * (y0 + y1)
        ax.set_xlim(cx - half, cx + half)
        ax.set_ylim(cy - half, cy + half)
    ax.set_aspect("equal", adjustable="box")

    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ncol = 2 if len(handles) > 4 else 1
        ax.legend(handles, labels, frameon=False, fontsize=9,
                  labelcolor=p["ink_2"], loc="upper center", ncol=ncol,
                  bbox_to_anchor=(0.5, -0.11), borderaxespad=0.0)
    fig.tight_layout()
    return fig


# ==========================================================================
# 2. plume / pressure evolution
# ==========================================================================
def evolution_map(x, y, fields, times, level, *, theme="light",
                  length_unit="mi", figsize=(8.5, 7.5), ax=None,
                  title="Plume evolution", label_fmt="{:,.0f} yr",
                  wells=None, colour_slot=PLUME_COLOR):
    """Contours of one field at successive times, on a single map.

    Time is encoded as lightness along a single hue -- an ordinal ramp, since
    the years are ordered -- and every contour is direct-labelled with its
    year, so the sequence never depends on the reader distinguishing similar
    tints.
    """
    import matplotlib.pyplot as plt
    from matplotlib.colors import to_rgb

    p = palette(theme)
    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    else:
        fig = ax.figure
    scale = 1.0 / U.length(1.0, length_unit)
    X, Y = np.meshgrid(np.asarray(x) * scale, np.asarray(y) * scale)

    base = np.array(to_rgb(p["series"][colour_slot]))
    surf = np.array(to_rgb(p["surface"]))
    n = len(times)
    for i, t in enumerate(times):
        if np.nanmax(fields[i]) < level:
            continue
        # ordinal ramp: never lighter than 25 % of the way from surface to hue
        f = 0.25 + 0.75 * (i / max(n - 1, 1))
        col = tuple(surf + f * (base - surf))
        cs = ax.contour(X, Y, fields[i], levels=[level], colors=[col],
                        linewidths=1.6 + 1.2 * (i / max(n - 1, 1)), zorder=2 + i * 0.01)
        try:
            ax.clabel(cs, fmt=lambda _v, _t=t: label_fmt.format(U.time_out(_t, "yr")),
                      fontsize=8, colors=p["ink_2"], inline=True)
        except Exception:
            pass

    if wells:
        ax.scatter([w.x * scale for w in wells], [w.y * scale for w in wells],
                   s=90, marker="v", color=p["ink"], edgecolor=p["surface"],
                   linewidth=2.0, zorder=7)

    _style(ax, theme, xlabel=f"easting ({length_unit})",
           ylabel=f"northing ({length_unit})", title=title)
    ax.set_aspect("equal", adjustable="datalim")
    fig.tight_layout()
    return fig


# ==========================================================================
# 3. PISC time series (stacked panels, one axis each)
# ==========================================================================
def pisc_panels(result, *, theme="light", figsize=(9.0, 9.0),
                title="Post-injection behaviour"):
    """Three stacked panels: plume area, migration rate, pressure decline.

    Deliberately three panels rather than one frame with three scales.  They
    share the time axis, so the eye still reads them together, but each keeps
    an honest y-axis.
    """
    import matplotlib.pyplot as plt

    p = palette(theme)
    fig, axes = plt.subplots(3, 1, figsize=figsize, sharex=True,
                             layout="constrained")
    t = result.times_years
    end = result.injection_end_year

    from matplotlib.ticker import FuncFormatter

    comma = FuncFormatter(lambda v, _pos: f"{v:,.0f}")

    ax = axes[0]
    plume_ac = U.area_out(result.plume_area_m2, "acres")
    press_ac = U.area_out(result.pressure_area_m2, "acres")
    ax.plot(t, np.where(plume_ac > 0, plume_ac, np.nan),
            color=p["series"][PLUME_COLOR], linewidth=2.0, label="CO2 plume")
    ax.plot(t, np.where(press_ac > 0, press_ac, np.nan),
            color=p["series"][PRESSURE_COLOR], linewidth=2.0,
            label="pressure front")
    # The pressure front can be an order of magnitude larger than the plume;
    # on a linear axis the plume flattens onto zero and stops being readable.
    # Both series are the same quantity in the same unit, so a log axis is
    # still one honest axis.
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(comma)
    _style(ax, theme, ylabel="area (acres)", title=f"{title} - area")
    _legend(ax, theme, loc="lower right")

    ax = axes[1]
    rate = U.length_out(result.migration_rate, "ft")
    ax.plot(t, np.where(rate > 0, rate, np.nan),
            color=p["series"][PLUME_COLOR], linewidth=2.0)
    peak = U.length_out(result.peak_migration_rate(), "ft")
    if np.isfinite(peak) and peak > 0:
        ax.axhline(0.05 * peak, color=p["ink_3"], linewidth=1.2, linestyle="--")
        ax.annotate("5 % of peak rate", (t[-1], 0.05 * peak),
                    textcoords="offset points", xytext=(-6, 6), ha="right",
                    fontsize=8.5, color=p["ink_2"])
        ax.set_yscale("log")
        ax.yaxis.set_major_formatter(comma)
    _style(ax, theme, ylabel="migration rate (ft/yr)",
           title="plume migration rate")

    ax = axes[2]
    ax.plot(t, U.pressure_out(result.max_dp, "psi"),
            color=p["series"][PRESSURE_COLOR], linewidth=2.0,
            label="maximum buildup anywhere")
    thr = U.pressure_out(result.threshold_pressure, "psi")
    ax.axhline(thr, color=p["critical"], linewidth=1.6, linestyle="--")
    ax.annotate(f"AoR threshold {thr:,.0f} psi", (t[-1], thr),
                textcoords="offset points", xytext=(-6, 6), ha="right",
                fontsize=8.5, color=p["critical"])
    _style(ax, theme, xlabel="years from start of injection",
           ylabel="pressure buildup (psi)", title="pressure decline")
    _legend(ax, theme, loc="upper right")

    for ax in axes:
        ax.axvline(end, color=p["ink_3"], linewidth=1.2, linestyle=":")
    axes[0].annotate("injection ceases", (end, 0.02), xycoords=("data", "axes fraction"),
                     textcoords="offset points", xytext=(6, 2), rotation=90,
                     va="bottom", fontsize=8.5, color=p["ink_2"])
    axes[2].yaxis.set_major_formatter(comma)
    return fig


# ==========================================================================
# 4. threshold-method comparison
# ==========================================================================
def threshold_comparison(results, selected=None, *, theme="light",
                         figsize=(9.0, 4.2),
                         title="Threshold pressure by method"):
    """Horizontal bars of dP_c per method.

    Methods that do not apply to the site's pressure regime are drawn with a
    hatched fill and said so in the label -- texture as the secondary
    encoding, so the distinction survives greyscale and colour-vision
    deficiency.
    """
    import matplotlib.pyplot as plt

    p = palette(theme)
    fig, ax = plt.subplots(figsize=figsize)
    names = [r.method.split(" - ")[0] for r in results]
    vals = [r.delta_p_psi for r in results]
    ypos = np.arange(len(results))[::-1]

    for i, r in enumerate(results):
        chosen = (selected is not None and r.method == selected.method)
        ax.barh(ypos[i], r.delta_p_psi, height=0.62,
                color=p["series"][PRESSURE_COLOR] if r.applicable else p["surface"],
                edgecolor=p["ink"] if chosen else p["series"][PRESSURE_COLOR],
                linewidth=2.2 if chosen else 1.2,
                hatch=None if r.applicable else "///", zorder=3)
        suffix = "" if r.applicable else "  (not applicable to this regime)"
        ax.annotate(f"{r.delta_p_psi:,.0f} psi{suffix}",
                    (r.delta_p_psi, ypos[i]), textcoords="offset points",
                    xytext=(8, -3), fontsize=9,
                    color=p["ink"] if chosen else p["ink_2"])

    ax.set_yticks(ypos)
    ax.set_yticklabels(names, fontsize=9, color=p["ink_2"])
    _style(ax, theme, xlabel="allowable pressure increase, dP_c (psi)", title=title)
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, max(vals + [1.0]) * 1.45)
    if selected is not None:
        ax.annotate("heavy outline = method used for this AoR",
                    (0.99, -0.22), xycoords="axes fraction", ha="right",
                    fontsize=8.5, color=p["ink_2"])
    fig.tight_layout()
    return fig


# ==========================================================================
# 5. tornado
# ==========================================================================
def tornado_chart(tor, *, theme="light", figsize=(9.0, 4.6),
                  title=None):
    """Tornado of one-parameter-at-a-time swings around the base case."""
    import matplotlib.pyplot as plt

    p = palette(theme)
    rows = tor.sorted_rows()
    fig, ax = plt.subplots(figsize=figsize)
    ypos = np.arange(len(rows))[::-1]
    base = tor.base_value

    for i, r in enumerate(rows):
        lo, hi = r["low_value"], r["high_value"]
        ax.barh(ypos[i], lo - base, left=base, height=0.6,
                color=p["series"][0], zorder=3,
                label="low end of range" if i == 0 else None)
        ax.barh(ypos[i], hi - base, left=base, height=0.6,
                color=p["series"][1], zorder=3,
                label="high end of range" if i == 0 else None)
        ax.annotate(f"{r['swing_pct']:+.0f} %", (max(lo, hi), ypos[i]),
                    textcoords="offset points", xytext=(8, -3),
                    fontsize=9, color=p["ink_2"])

    ax.axvline(base, color=p["ink"], linewidth=1.8, zorder=4)
    ax.annotate(f"base {base:,.0f}", (base, ypos[0] + 0.6),
                ha="center", fontsize=9, color=p["ink"])
    ax.set_yticks(ypos)
    ax.set_yticklabels([r["parameter"] for r in rows], fontsize=9, color=p["ink_2"])
    _style(ax, theme, xlabel=tor.metric,
           title=title or f"Sensitivity of {tor.metric}")
    ax.grid(axis="y", visible=False)
    _legend(ax, theme, loc="lower right")
    fig.tight_layout()
    return fig


# ==========================================================================
# 6. probabilistic AoR
# ==========================================================================
def probabilistic_aor_map(mc, *, wells=None, theme="light", length_unit="mi",
                          figsize=(8.5, 7.5),
                          title="Probabilistic Area of Review"):
    """Cell-wise probability of falling inside the AoR, with P10/P50/P90 rings.

    The ramp is a single hue by magnitude: pale where few realisations include
    the cell, dark where nearly all do.  The three labelled contours are the
    lines a reviewer can actually argue about -- P90 is the area almost every
    credible model includes, P10 the outer envelope of what any of them does.
    """
    import matplotlib.pyplot as plt

    p = palette(theme)
    if mc.exceedance is None:
        raise ValueError("this Monte Carlo run recorded no gridded ensemble")
    fig, ax = plt.subplots(figsize=figsize)
    scale = 1.0 / U.length(1.0, length_unit)
    X, Y = np.meshgrid(mc.x * scale, mc.y * scale)

    im = ax.pcolormesh(X, Y, mc.exceedance, cmap=_sequential_cmap(theme),
                       vmin=0, vmax=1, shading="auto", zorder=0, rasterized=True)
    cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    cb.set_label("fraction of realisations including this cell",
                 color=p["ink_2"], fontsize=9)
    cb.ax.tick_params(colors=p["ink_2"], labelsize=8)
    cb.outline.set_visible(False)

    cs = ax.contour(X, Y, mc.exceedance, levels=[0.1, 0.5, 0.9],
                    colors=[p["ink"]], linewidths=[1.2, 1.8, 2.4],
                    linestyles=[":", "--", "-"], zorder=3)
    ax.clabel(cs, fmt={0.1: "P10 envelope", 0.5: "P50", 0.9: "P90"},
              fontsize=8.5, colors=p["ink"], inline=True)

    if wells:
        ax.scatter([w.x * scale for w in wells], [w.y * scale for w in wells],
                   s=100, marker="v", color=p["ink"], edgecolor=p["surface"],
                   linewidth=2.0, zorder=7)

    _style(ax, theme, xlabel=f"easting ({length_unit})",
           ylabel=f"northing ({length_unit})", title=title)
    ax.set_aspect("equal", adjustable="datalim")
    fig.tight_layout()
    return fig


def monte_carlo_histogram(mc, metric="aor_area_acres", *, theme="light",
                          figsize=(8.0, 4.0), title=None):
    """Distribution of an ensemble metric with P10/P50/P90 markers."""
    import matplotlib.pyplot as plt

    p = palette(theme)
    v = mc.metrics[metric]
    v = v[np.isfinite(v)]
    fig, ax = plt.subplots(figsize=figsize)
    ax.hist(v, bins=max(12, int(np.sqrt(v.size))), color=p["series"][0],
            edgecolor=p["surface"], linewidth=1.2, zorder=3)
    for q, style in ((10, ":"), (50, "-"), (90, "--")):
        val = float(np.percentile(v, q))
        ax.axvline(val, color=p["ink"], linewidth=1.8, linestyle=style, zorder=4)
        ax.annotate(f"P{q}  {val:,.0f}", (val, ax.get_ylim()[1]),
                    rotation=90, va="top", ha="right", fontsize=8.5,
                    color=p["ink"], textcoords="offset points", xytext=(-4, -6))
    _style(ax, theme, xlabel=metric.replace("_", " "), ylabel="realisations",
           title=title or f"Ensemble distribution of {metric.replace('_', ' ')}")
    fig.tight_layout()
    return fig


# ==========================================================================
# 7. directional migration rose
# ==========================================================================
def migration_rose(directional, origin_key=None, *, theme="light",
                   figsize=(6.5, 6.5), title="Plume reach by direction"):
    """Polar plot of final plume reach per compass azimuth.

    Direction is the point of this figure, so it uses a polar frame with north
    at the top and clockwise azimuths -- the same orientation as the structure
    map the reader already has on the desk.
    """
    import matplotlib.pyplot as plt

    p = palette(theme)
    if not directional:
        raise ValueError("no directional analysis was recorded")
    key = origin_key or next(iter(directional))
    data = directional[key]
    az = np.array(sorted(data), float)
    reach = np.array([data[a]["final_reach_ft"] for a in az], float)
    rate = np.array([data[a]["final_rate_ft_per_yr"] for a in az], float)

    theta = np.radians(np.append(az, az[0]))
    r = np.append(reach, reach[0])

    fig, ax = plt.subplots(figsize=figsize, subplot_kw={"projection": "polar"})
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.plot(theta, r, color=p["series"][PLUME_COLOR], linewidth=2.2, zorder=3)
    ax.fill(theta, r, color=p["series"][PLUME_COLOR], alpha=0.22, zorder=2)
    for a, rr, ra in zip(az, reach, rate, strict=True):
        if np.isfinite(ra) and ra > 0:
            ax.annotate(f"{ra:,.0f} ft/yr", (np.radians(a), rr),
                        textcoords="offset points", xytext=(4, 4),
                        fontsize=8, color=p["ink_2"])
    ax.set_facecolor(p["surface"])
    fig.patch.set_facecolor(p["surface"])
    ax.tick_params(colors=p["ink_2"], labelsize=9)
    ax.grid(color=p["grid"], linewidth=0.8)
    ax.set_title(f"{title}\n(labels: final migration rate)",
                 color=p["ink"], fontsize=12, pad=18)
    return fig


# ==========================================================================
# 8. AoR comparison (reevaluation)
# ==========================================================================
def comparison_map(previous, current, *, wells=None, theme="light",
                   length_unit="mi", figsize=(8.5, 7.5),
                   title="AoR reevaluation"):
    """Previous versus reevaluated AoR, with the newly included area filled."""
    import matplotlib.pyplot as plt
    from shapely.affinity import scale as sscale

    p = palette(theme)
    fig, ax = plt.subplots(figsize=figsize)
    scale = 1.0 / U.length(1.0, length_unit)

    added = current.aor.difference(previous.aor)
    removed = previous.aor.difference(current.aor)

    if not added.is_empty:
        _draw_geom(ax, sscale(added, scale, scale, origin=(0, 0)),
                   facecolor=p["div_high"], alpha=0.30, edgecolor="none",
                   zorder=2,
                   label=f"newly included ({U.area_out(added.area, 'acres'):,.0f} acres) "
                         " - requires assessment [146.84(e)(2)]")
    if not removed.is_empty:
        _draw_geom(ax, sscale(removed, scale, scale, origin=(0, 0)),
                   facecolor=p["div_low"], alpha=0.30, edgecolor="none",
                   zorder=2,
                   label=f"no longer included ({U.area_out(removed.area, 'acres'):,.0f} acres)")
    _draw_geom(ax, sscale(previous.aor, scale, scale, origin=(0, 0)),
               edgecolor=p["ink_2"], lw=1.8, ls="--", zorder=4,
               label=f"previous AoR ({previous.area_acres:,.0f} acres)")
    _draw_geom(ax, sscale(current.aor, scale, scale, origin=(0, 0)),
               edgecolor=p["ink"], lw=2.4, zorder=5,
               label=f"reevaluated AoR ({current.area_acres:,.0f} acres)")

    if wells:
        ax.scatter([w.x * scale for w in wells], [w.y * scale for w in wells],
                   s=100, marker="v", color=p["ink"], edgecolor=p["surface"],
                   linewidth=2.0, zorder=7)
    _style(ax, theme, xlabel=f"easting ({length_unit})",
           ylabel=f"northing ({length_unit})", title=title)
    ax.set_aspect("equal", adjustable="datalim")
    _legend(ax, theme, loc="upper left", bbox_to_anchor=(1.02, 1.0))
    fig.tight_layout()
    return fig


# ==========================================================================
# cross-section
# ==========================================================================
def cross_section(ve_result, props, index=-1, *, along="x", position=None,
                  theme="light", length_unit="mi", figsize=(9.0, 4.0),
                  title="CO2 column along section"):
    """CO2 column thickness under the caprock along a section line."""
    import matplotlib.pyplot as plt

    p = palette(theme)
    g = ve_result.grid
    scale = 1.0 / U.length(1.0, length_unit)
    if along == "x":
        j = g.ny // 2 if position is None else int(np.argmin(np.abs(g.yc - position)))
        s = g.xc
        h = ve_result.h[index][j]
        hm = ve_result.hmax[index][j]
        top = props.top_elevation[j]
        thick = props.thickness[j]
    else:
        i = g.nx // 2 if position is None else int(np.argmin(np.abs(g.xc - position)))
        s = g.yc
        h = ve_result.h[index][:, i]
        hm = ve_result.hmax[index][:, i]
        top = props.top_elevation[:, i]
        thick = props.thickness[:, i]

    fig, ax = plt.subplots(figsize=figsize)
    e_top = U.length_out(top, "ft")
    e_base = U.length_out(top - thick, "ft")
    ax.fill_between(s * scale, e_base, e_top, color=p["grid"], zorder=1,
                    label="injection zone")
    ax.fill_between(s * scale, U.length_out(top - hm, "ft"), e_top,
                    color=p["series"][PLUME_COLOR], alpha=0.28, zorder=2,
                    label="CO2 swept (mobile + residual)")
    ax.fill_between(s * scale, U.length_out(top - h, "ft"), e_top,
                    color=p["series"][PLUME_COLOR], alpha=0.75, zorder=3,
                    label="mobile CO2 column")
    ax.plot(s * scale, e_top, color=p["ink"], linewidth=1.8, zorder=4)
    _style(ax, theme, xlabel=f"distance ({length_unit})",
           ylabel="elevation (ft)",
           title=f"{title} - year {U.time_out(float(ve_result.times[index]), 'yr'):,.0f}")
    _legend(ax, theme, loc="lower right")
    fig.tight_layout()
    return fig


# ==========================================================================
# Plotly builders for the browser app
# ==========================================================================
def plotly_aor_map(result, x=None, y=None, dp_field=None, wells=None,
                   penetrations=None, theme="light", length_unit="mi"):
    """Interactive AoR map. Requires plotly."""
    import plotly.graph_objects as go

    p = palette(theme)
    scale = 1.0 / U.length(1.0, length_unit)
    fig = go.Figure()

    if dp_field is not None and x is not None:
        fig.add_trace(go.Heatmap(
            x=np.asarray(x) * scale, y=np.asarray(y) * scale,
            z=U.pressure_out(np.asarray(dp_field), "psi"),
            colorscale=[[i / (len(p["seq"])), c]
                        for i, c in enumerate([p["surface"], *p["seq"]])],
            colorbar=dict(title="max dP (psi)", thickness=14),
            hovertemplate="dP %{z:,.0f} psi<extra></extra>", zsmooth="best"))

    def add(geom, name, colour, fill, width, dash=None):
        first = True
        for gpoly in _polys(geom):
            xy = np.asarray(gpoly.exterior.coords) * scale
            fig.add_trace(go.Scatter(
                x=xy[:, 0], y=xy[:, 1], mode="lines", name=name,
                line=dict(color=colour, width=width, dash=dash),
                fill="toself" if fill else None,
                fillcolor=fill, legendgroup=name, showlegend=first,
                hovertemplate=f"{name}<extra></extra>"))
            first = False

    add(result.pressure_front,
        f"pressure front (>= {U.pressure_out(result.threshold_pressure, 'psi'):,.0f} psi)",
        p["series"][PRESSURE_COLOR], "rgba(42,120,214,0.16)", 2)
    add(result.plume, f"CO2 plume ({result.plume_criterion})",
        p["series"][PLUME_COLOR], "rgba(235,104,52,0.26)", 2)
    # a union that equals one of its components shares that component's
    # boundary, so dash the AoR rather than painting the component out
    coincident = result.coincident_with()
    add(result.aor,
        f"AoR - {result.area_acres:,.0f} acres"
        + (f", on the {coincident}" if coincident else ""),
        p["ink"], None, 3, dash="dash" if coincident else None)

    if wells:
        inj = [w for w in wells if getattr(w, "kind", "injector") == "injector"]
        # fan the labels radially so a tight well row does not overprint itself
        cx0 = np.mean([w.x for w in inj]) if inj else 0.0
        cy0 = np.mean([w.y for w in inj]) if inj else 0.0
        pos = []
        for k, w in enumerate(inj):
            dx, dy = w.x - cx0, w.y - cy0
            if abs(dx) < 1e-9 and abs(dy) < 1e-9:
                dx, dy = (1.0, 1.0) if k % 2 == 0 else (-1.0, -1.0)
            pos.append(("top " if dy >= 0 else "bottom ")
                       + ("right" if dx >= 0 else "left"))
        fig.add_trace(go.Scatter(
            x=[w.x * scale for w in inj], y=[w.y * scale for w in inj],
            mode="markers+text", name="injector",
            marker=dict(symbol="triangle-down", size=13, color=p["ink"],
                        line=dict(color=p["surface"], width=2)),
            text=[w.name for w in inj], textposition=pos,
            textfont=dict(size=10, color=p["ink"])))
    if penetrations:
        colours = {"corrective action": p["critical"], "field testing": p["warning"],
                   "monitor": p["ink_2"], "no action": p["ink_3"]}
        for action, c in colours.items():
            sel = [w for w in penetrations if w.in_aor and w.action == action]
            if not sel:
                continue
            fig.add_trace(go.Scatter(
                x=[w.x * scale for w in sel], y=[w.y * scale for w in sel],
                mode="markers", name=f"{action} ({len(sel)})",
                marker=dict(size=9, color=c,
                            symbol="x" if action == "corrective action" else "circle"),
                customdata=[[w.name, w.action_reason] for w in sel],
                hovertemplate="%{customdata[0]}<br>%{customdata[1]}<extra></extra>"))

    # frame on the AoR, not on the whole model domain
    focus = result.aor if (result.aor is not None and not result.aor.is_empty)         else result.plume
    xr = yr = None
    if focus is not None and not focus.is_empty:
        x0, y0, x1, y1 = (v * scale for v in focus.bounds)
        half = 0.5 * max(x1 - x0, y1 - y0) * 1.35
        cx, cy = 0.5 * (x0 + x1), 0.5 * (y0 + y1)
        xr, yr = [cx - half, cx + half], [cy - half, cy + half]

    fig.update_layout(
        template="plotly_white" if theme == "light" else "plotly_dark",
        paper_bgcolor=p["surface"], plot_bgcolor=p["surface"],
        xaxis=dict(title=f"easting ({length_unit})", range=xr),
        yaxis=dict(title=f"northing ({length_unit})", range=yr,
                   scaleanchor="x", scaleratio=1),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=60, r=20, t=60, b=50), height=650)
    return fig


def plotly_pisc(result, theme="light"):
    """Interactive three-panel PISC figure (shared x, one y-scale each)."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    p = palette(theme)
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True,
                        vertical_spacing=0.08,
                        subplot_titles=("area", "plume migration rate",
                                        "pressure decline"))
    t = result.times_years
    fig.add_trace(go.Scatter(x=t, y=U.area_out(result.plume_area_m2, "acres"),
                             name="CO2 plume", line=dict(color=p["series"][1], width=2)),
                  row=1, col=1)
    fig.add_trace(go.Scatter(x=t, y=U.area_out(result.pressure_area_m2, "acres"),
                             name="pressure front",
                             line=dict(color=p["series"][0], width=2)), row=1, col=1)
    fig.add_trace(go.Scatter(x=t, y=U.length_out(result.migration_rate, "ft"),
                             name="migration rate", showlegend=False,
                             line=dict(color=p["series"][1], width=2)), row=2, col=1)
    fig.add_trace(go.Scatter(x=t, y=U.pressure_out(result.max_dp, "psi"),
                             name="max buildup", showlegend=False,
                             line=dict(color=p["series"][0], width=2)), row=3, col=1)
    thr = U.pressure_out(result.threshold_pressure, "psi")
    fig.add_hline(y=thr, line=dict(color=p["critical"], width=2, dash="dash"),
                  annotation_text=f"AoR threshold {thr:,.0f} psi", row=3, col=1)
    for r in (1, 2, 3):
        fig.add_vline(x=result.injection_end_year,
                      line=dict(color=p["ink_3"], width=1.5, dash="dot"), row=r, col=1)
    fig.update_yaxes(title_text="acres", row=1, col=1)
    fig.update_yaxes(title_text="ft/yr", type="log", row=2, col=1)
    fig.update_yaxes(title_text="psi", row=3, col=1)
    fig.update_xaxes(title_text="years from start of injection", row=3, col=1)
    fig.update_layout(
        template="plotly_white" if theme == "light" else "plotly_dark",
        paper_bgcolor=p["surface"], plot_bgcolor=p["surface"],
        height=760, hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.03),
        margin=dict(l=70, r=20, t=60, b=50))
    return fig


def save(fig, path: str, dpi: int = 150) -> str:
    """Save a matplotlib figure, keeping the theme background."""
    fig.savefig(path, dpi=dpi, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    return path


__all__ = [
    "LIGHT", "DARK", "palette", "aor_map", "evolution_map", "pisc_panels",
    "threshold_comparison", "tornado_chart", "probabilistic_aor_map",
    "monte_carlo_histogram", "migration_rose", "comparison_map",
    "cross_section", "plotly_aor_map", "plotly_pisc", "save",
]
