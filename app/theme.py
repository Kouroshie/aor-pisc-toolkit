"""Visual theme for the browser app.

The palette is not invented here: it is read from :mod:`aorpisc.viz`, so the
page chrome and the figures drawn into it are one system rather than two that
happen to sit next to each other.  Only the page furniture lives in this
module; figure styling stays in ``viz``.

Two things are deliberately not done here.

Headings are not restyled in CSS.  Streamlit sets heading fonts through its
own theme with a specificity a plain ``h1`` selector cannot beat, so the
display face is set in ``.streamlit/config.toml`` as ``headingFont``, which is
the supported lever.  ``serif`` there means the Source Serif that Streamlit
already ships, so nothing is fetched from a font CDN at page load.

No web fonts are loaded.  An ``@import`` of Google Fonts here looked fine and
silently did nothing, leaving every rule that named those families on its
fallback.  Both faces below ship with Streamlit itself.

A note on selectors.  Streamlit's internal class names move between versions,
so everything below keys off ``data-testid`` hooks, and where a hook has been
renamed the old spelling is listed alongside the new one: 1.63 moved the tab
strip from BaseWeb to React Aria, renaming ``[data-baseweb="tab"]`` to
``[data-testid="stTab"]``.  The styling is additive, so a hook that is renamed
again leaves that element stock rather than breaking the page.
"""

from __future__ import annotations

import streamlit as st

from aorpisc import viz

_UI = "'Source Sans', 'Segoe UI', system-ui, -apple-system, sans-serif"
_DISPLAY = "'Source Serif', Georgia, 'Times New Roman', serif"


def css() -> str:
    """The stylesheet, built from the figure palette."""
    p = viz.palette("light")
    return f"""
:root {{
  --surface: {p["surface"]};
  --panel: #ffffff;
  --panel-2: #f4f3f0;
  --line: {p["grid"]};
  --ink: {p["ink"]};
  --ink-2: {p["ink_2"]};
  --ink-3: {p["ink_3"]};
  --brand: {p["series"][0]};
  --brand-deep: {p["seq"][5]};
  --brand-wash: rgba(42, 120, 214, 0.08);
  --accent: {p["series"][1]};
  --good: {p["good"]};
  --warn: {p["warning"]};
  --bad: {p["critical"]};
  --radius: 12px;
  --shadow: 0 1px 2px rgba(16, 24, 40, 0.05), 0 1px 3px rgba(16, 24, 40, 0.04);
}}

.block-container {{ padding-top: 2.4rem; max-width: 1500px; }}

/* ---------------------------------------------------------- typography */
/* The face itself comes from theme.headingFont in config.toml; only the
   spacing is set here, which Streamlit leaves alone. */
h1, h2, h3, h4 {{ letter-spacing: -0.012em; color: var(--ink); }}
h1 {{ line-height: 1.15; margin-bottom: .15rem; }}
h2 {{ margin-top: 1.6rem; }}
[data-testid="stCaptionContainer"] p, .stCaption p {{
  color: var(--ink-2); font-size: .88rem; line-height: 1.5;
}}

/* The page header: eyebrow, title, standfirst, rule. */
.aor-hero {{
  border-bottom: 2px solid var(--line); padding-bottom: 1rem; margin-bottom: 1.4rem;
}}
.aor-eyebrow {{
  font-size: .74rem; font-weight: 700; letter-spacing: .14em; text-transform: uppercase;
  color: var(--brand); margin-bottom: .5rem;
}}
.aor-standfirst {{
  color: var(--ink-2); font-size: 1.02rem; max-width: 68ch; margin-top: .45rem;
}}
.aor-chip {{
  display: inline-block; margin: .7rem .4rem 0 0; padding: .2rem .6rem;
  border: 1px solid var(--line); border-radius: 999px; background: var(--panel);
  font-size: .76rem; font-weight: 600; color: var(--ink-2);
}}

/* --------------------------------------------------------------- tabs */
/* The result panels are the point of the page, so the tab strip reads as a
   real control: a segmented bar, with the open panel as a card beneath it. */
.stTabs [role="tablist"], .stTabs [data-baseweb="tab-list"] {{
  gap: .25rem; padding: .3rem; background: var(--panel-2);
  border: 1px solid var(--line); border-radius: 14px; flex-wrap: wrap;
}}
.stTabs [data-testid="stTab"], .stTabs [data-baseweb="tab"] {{
  height: auto; padding: .55rem 1.05rem; border-radius: 10px;
  font-family: {_UI}; font-size: .95rem; font-weight: 600; color: var(--ink-2);
  cursor: pointer; transition: background .15s ease, color .15s ease;
}}
.stTabs [data-testid="stTab"] p, .stTabs [data-baseweb="tab"] p {{
  font-size: .95rem; font-weight: 600; margin: 0; color: inherit;
}}
.stTabs [data-testid="stTab"]:hover, .stTabs [data-baseweb="tab"]:hover {{
  background: var(--brand-wash); color: var(--brand-deep);
}}
.stTabs [aria-selected="true"] {{
  background: var(--brand); color: #fff; box-shadow: 0 1px 3px rgba(16, 24, 40, .18);
}}
.stTabs [aria-selected="true"] p {{ color: #fff; }}
/* The open tab is a filled pill, so the underline marking it is redundant. */
.stTabs .react-aria-SelectionIndicator,
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] {{
  display: none;
}}
.stTabs [data-testid="stTabPanel"], .stTabs [data-baseweb="tab-panel"] {{
  border: 1px solid var(--line); border-radius: 16px; background: var(--panel);
  padding: 1.35rem 1.35rem .6rem; margin-top: .9rem; box-shadow: var(--shadow);
}}

/* ------------------------------------------------------------ metrics */
[data-testid="stMetric"], [data-testid="metric-container"] {{
  background: var(--panel); border: 1px solid var(--line);
  border-left: 4px solid var(--brand); border-radius: var(--radius);
  padding: .9rem 1.05rem; box-shadow: var(--shadow);
}}
[data-testid="stMetricValue"] {{
  font-family: {_DISPLAY}; font-size: 2.05rem; font-weight: 700;
  font-variant-numeric: tabular-nums; color: var(--ink);
}}
[data-testid="stMetricLabel"] p {{
  font-size: .76rem; font-weight: 700; letter-spacing: .07em;
  text-transform: uppercase; color: var(--ink-3);
}}
/* Our deltas are descriptions ("11.4 sq mi", "Method 1"), not changes. The
   call site passes delta_color="off"; the arrow and the green "this went up"
   wash survive that, and both state something untrue, so they go here. */
[data-testid="stMetricDelta"] svg {{ display: none; }}
[data-testid="stMetricDelta"] {{
  background: transparent !important; padding-left: 0;
  color: var(--ink-2) !important; font-size: .82rem; font-weight: 500;
}}
[data-testid="stMetricDelta"] div {{ color: var(--ink-2) !important; }}

/* ------------------------------------------------------------ sidebar */
[data-testid="stSidebar"] {{
  background: var(--panel-2); border-right: 1px solid var(--line);
}}
[data-testid="stSidebar"] h2 {{
  font-family: {_UI}; font-size: .78rem; font-weight: 700; letter-spacing: .1em;
  text-transform: uppercase; color: var(--brand-deep);
  border-bottom: 1px solid var(--line); padding-bottom: .4rem;
  margin: 1.5rem 0 .35rem;
}}
[data-testid="stSidebar"] label p {{
  font-size: .84rem; color: var(--ink-2); font-weight: 500;
}}

/* ------------------------------------------------- alerts and panels */
[data-testid="stAlert"], .stAlert {{
  border-radius: var(--radius); border: 1px solid var(--line);
  border-left-width: 4px; box-shadow: none;
}}
[data-testid="stExpander"] details {{
  border: 1px solid var(--line); border-radius: var(--radius);
  background: var(--panel); box-shadow: var(--shadow);
}}
[data-testid="stExpander"] summary {{ font-weight: 600; font-size: .95rem; }}
[data-testid="stJson"] {{
  border: 1px solid var(--line); border-radius: 10px; padding: .5rem .7rem;
  background: var(--panel-2);
}}
[data-testid="stDataFrame"] {{
  border-radius: 10px; overflow: hidden; border: 1px solid var(--line);
}}
[data-testid="stTooltipIcon"] svg {{ color: var(--brand); }}

/* ------------------------------------------------------------ buttons */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {{
  border-radius: 10px; font-family: {_UI}; font-weight: 600; letter-spacing: .01em;
  transition: transform .12s ease, box-shadow .12s ease, background .12s ease;
}}
.stButton > button[kind="primary"] {{
  background: linear-gradient(180deg, #3d8ae2, var(--brand));
  border: none; padding: .62rem 1.1rem; font-size: 1rem;
  box-shadow: 0 1px 2px rgba(16, 24, 40, .14);
}}
.stButton > button[kind="primary"]:hover {{
  box-shadow: 0 3px 10px rgba(42, 120, 214, .3); transform: translateY(-1px);
}}
.stDownloadButton > button {{
  border: 1px solid var(--line); background: var(--panel); color: var(--ink);
}}
.stDownloadButton > button:hover {{
  border-color: var(--brand); color: var(--brand-deep); background: var(--brand-wash);
}}

/* A lead paragraph at the top of a result panel: what the panel is for. */
.aor-lead {{
  border-left: 3px solid var(--brand); background: var(--brand-wash);
  border-radius: 0 10px 10px 0; padding: .7rem .95rem; margin-bottom: 1.1rem;
  color: var(--ink-2); font-size: .92rem; line-height: 1.55;
}}
.aor-lead b {{ color: var(--ink); }}

/* Glossary entries on the Help panel. */
.aor-term {{ margin: .1rem 0 .9rem; }}
.aor-term dt {{ font-weight: 700; color: var(--ink); font-size: .95rem; }}
.aor-term dd {{
  margin: .15rem 0 0; color: var(--ink-2); font-size: .92rem; line-height: 1.55;
}}
"""


def apply() -> None:
    """Inject the stylesheet.  Call once, right after ``set_page_config``."""
    st.markdown(f"<style>{css()}</style>", unsafe_allow_html=True)


def hero(title: str, standfirst: str, chips: tuple = ()) -> None:
    """The page header block."""
    tags = "".join(f'<span class="aor-chip">{c}</span>' for c in chips)
    st.markdown(
        f'<div class="aor-hero">'
        f'<div class="aor-eyebrow">UIC Class VI</div>'
        f'<h1>{title}</h1>'
        f'<div class="aor-standfirst">{standfirst}</div>{tags}</div>',
        unsafe_allow_html=True)


def lead(text: str) -> None:
    """A short "what this panel is for" note at the top of a result tab."""
    st.markdown(f'<div class="aor-lead">{text}</div>', unsafe_allow_html=True)
