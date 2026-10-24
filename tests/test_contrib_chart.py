"""Offline checks for the contributions chart: date math, SVG drawing and README update."""

import datetime as dt
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import contrib_chart as cc  # noqa: E402


@pytest.mark.parametrize("day, expected", [
    (dt.date(2026, 10, 24), dt.date(2026, 8, 24)),
    (dt.date(2026, 4, 30), dt.date(2026, 2, 28)),    # clamped to February's last day
    (dt.date(2026, 1, 15), dt.date(2025, 11, 15)),   # crosses the year
])
def test_months_back(day, expected):
    assert cc.months_back(day, 2) == expected


def sample_days():
    """Two months of fake days with every contribution level present."""
    start = dt.date(2026, 8, 24)
    return [{"date": start + dt.timedelta(days=i), "count": i % 5 * 2, "level": i % 5} for i in range(62)]


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_svg_is_valid_and_has_one_cell_per_day(theme):
    days = sample_days()
    svg = cc.render_svg(days, theme)
    root = ET.fromstring(svg)
    ns = "{http://www.w3.org/2000/svg}"
    day_cells = [r for r in root.iter(f"{ns}rect") if r.find(f"{ns}title") is not None]
    assert len(day_cells) == len(days)
    assert set(r.get("fill") for r in day_cells) == set(cc.THEMES[theme]["cells"])
    texts = [t.text for t in root.iter(f"{ns}text")]
    assert "Aug" in texts and "Sep" in texts and "Oct" in texts
    assert "Less" in texts and "More" in texts
    assert f"{sum(d['count'] for d in days)} contributions in the last 2 months" in texts


def test_first_day_sits_on_its_weekday_row():
    days = sample_days()                     # Aug 24, 2026 is a Monday: row 1
    root = ET.fromstring(cc.render_svg(days, "light"))
    ns = "{http://www.w3.org/2000/svg}"
    first = next(r for r in root.iter(f"{ns}rect") if r.find(f"{ns}title") is not None)
    assert int(first.get("y")) == cc.TOP + 1 * cc.PITCH


def test_readme_update_replaces_only_the_marked_section():
    text = f"intro\n{cc.START}\nold\n{cc.END}\noutro\n"
    out = cc.update_readme(text, sample_days())
    assert out.startswith("intro\n") and out.endswith("\noutro\n")
    assert "old" not in out and "assets/contributions-dark.svg" in out and out.count(cc.START) == 1
    with pytest.raises(ValueError):
        cc.update_readme("no markers here", sample_days())
