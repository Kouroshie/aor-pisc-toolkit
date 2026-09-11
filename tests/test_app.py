"""The browser app renders, and its controls carry the help text they claim to.

The app script is not importable in the usual sense: it runs top to bottom on
every rerun and talks to a live Streamlit session.  Streamlit's own AppTest
harness runs it the way the server does, which is the only way to catch the
class of bug where a widget looks like every other widget but rejects an
argument.  That is not hypothetical: ``st.data_editor`` takes no ``help``,
unlike every other input on the page, and this test is why that was found
before it reached the deployed app rather than after.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("plotly")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "app", "streamlit_app.py")


def test_app_renders_without_running_a_model():
    at = AppTest.from_file(APP, default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]
    assert [b.label for b in at.button] == ["Run"]


def test_every_sidebar_control_explains_itself():
    """The sidebar is the whole model, so no knob may be unlabelled."""
    at = AppTest.from_file(APP, default_timeout=120).run()
    bare = [w.label for group in (at.sidebar.number_input, at.sidebar.slider,
                                  at.sidebar.selectbox, at.sidebar.radio)
            for w in group if not (w.help or "").strip()]
    assert not bare, f"controls with no help text: {bare}"


@pytest.mark.slow
def test_a_full_run_fills_every_panel():
    at = AppTest.from_file(APP, default_timeout=600).run()
    at.button[0].click().run()
    assert not at.exception, [e.value for e in at.exception]

    labels = [t.label for t in at.tabs]
    assert labels == ["AoR map", "AoR over time", "GIS map", "Threshold", "PISC",
                      "Corrective action", "Uncertainty", "Export", "Help"]
    assert "Zones" not in labels          # a single-zone project has no stack
    labels = [m.label for m in at.metric]
    assert labels == ["AoR area", "Threshold dP", "CO2 injected",
                      "PISC supported by model"]

    page = " ".join(m.value for m in at.markdown)
    assert "aor-lead" in page                     # per-panel orientation notes
    assert "Glossary" in page                     # the Help panel rendered


@pytest.mark.slow
def test_ticking_stacked_completion_adds_a_zones_panel():
    """The stacked path has its own widgets, its own tab and its own figures,
    none of which the single-zone run exercises."""
    at = AppTest.from_file(APP, default_timeout=900).run()
    box = [c for c in at.checkbox if "more than one formation" in c.label]
    assert box, [c.label for c in at.checkbox]
    box[0].check().run()
    assert not at.exception, [e.value for e in at.exception]

    at.button[0].click().run()
    assert not at.exception, [e.value for e in at.exception]

    labels = [t.label for t in at.tabs]
    assert "Zones" in labels
    assert "AoR over time" in labels

    page = " ".join(m.value for m in at.markdown)
    assert "union" in page.lower()
