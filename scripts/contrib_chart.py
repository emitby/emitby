"""Draw a 2-month GitHub contributions chart and keep the profile README pointing at it.

GitHub's own contributions chart always covers a full year. This script asks the GitHub
GraphQL API for the last :data:`MONTHS` months of contribution counts and draws a shorter
chart in the same style, as two SVGs (light and dark theme). It then rewrites the README
section between :data:`START` and :data:`END`, so the image's alt text carries the current
total. A GitHub Action (``.github/workflows/contributions.yml``) runs it once a day.

Usage::

    printf '%s' "$GH_TOKEN" | python3 scripts/contrib_chart.py

The token is read from standard input, so the script never touches environment
variables or other system configuration.

Counting rules come from GitHub itself:

* GitHub decides what counts as a contribution and how strong each day's color is.
  Each day carries a ``contributionLevel`` (none, then four quartiles), and the chart
  maps that level to a color, exactly as the profile chart does.
* Private contributions are included only if "Private contributions" is turned on in
  the profile's contribution settings. The Action's token sees only what any visitor sees.
"""

import calendar
import datetime as dt
import html
import json
import sys
import urllib.request
from pathlib import Path

LOGIN = "emitby"
MONTHS = 2

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
README = ROOT / "README.md"
START = "<!-- contributions:start -->"
END = "<!-- contributions:end -->"

API = "https://api.github.com/graphql"
QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        weeks { contributionDays { date contributionCount contributionLevel } }
      }
    }
  }
}
"""

#: GitHub's contribution levels, lowest first. The index picks the color.
LEVELS = ("NONE", "FIRST_QUARTILE", "SECOND_QUARTILE", "THIRD_QUARTILE", "FOURTH_QUARTILE")

#: One green ramp, light to dark: a sequential scale, since only magnitude matters.
#: These are GitHub's own contribution colors, so the chart reads like the real one.
#: The dark theme has its own steps, chosen against its own background, not inverted.
THEMES = {
    "light": {"bg": "#ffffff", "text": "#1f2328", "muted": "#59636e",
              "cells": ("#eff2f5", "#aceebb", "#4ac26b", "#2da44e", "#116329")},
    "dark": {"bg": "#0d1117", "text": "#f0f6fc", "muted": "#9198a1",
             "cells": ("#151b23", "#033a16", "#196c2e", "#2ea043", "#56d364")},
}

# Layout, in SVG pixels. Each day is a cell; a week is a column, Sunday at the top, as on GitHub.
CELL, GAP = 11, 3
PITCH = CELL + GAP
LEFT, TOP = 34, 50          # room for weekday labels, and for the title and month labels
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif"


def months_back(day, months):
    """The same day-of-month ``months`` months earlier, clamped to that month's last day.

    Example: ``months_back(date(2026, 12, 31), 2)`` is ``date(2026, 10, 31)``, and
    ``months_back(date(2026, 4, 30), 2)`` is ``date(2026, 2, 28)``.
    """
    month = day.month - months
    year = day.year
    while month < 1:
        month += 12
        year -= 1
    return dt.date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def fetch_days(token, start, end):
    """Ask GitHub for each day's contribution count and level from ``start`` to ``end``.

    Args:
        token: A GitHub token (the Action's ``GITHUB_TOKEN`` is enough).
        start: First date to include.
        end: Last date to include.

    Returns:
        ``[{"date": date, "count": int, "level": int}, ...]`` in date order, covering only
        dates from ``start`` to ``end``.

    Raises:
        RuntimeError: If the API answers with errors or without the user.
    """
    body = json.dumps({"query": QUERY, "variables": {
        "login": LOGIN, "from": f"{start}T00:00:00Z", "to": f"{end}T23:59:59Z"}}).encode()
    req = urllib.request.Request(API, data=body, headers={
        "Authorization": f"bearer {token}", "Content-Type": "application/json",
        "User-Agent": f"{LOGIN}-contributions-chart"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    if data.get("errors") or not (data.get("data") or {}).get("user"):
        raise RuntimeError(f"GitHub API error: {data.get('errors') or data}")
    weeks = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    days = [{"date": dt.date.fromisoformat(d["date"]), "count": d["contributionCount"],
             "level": LEVELS.index(d["contributionLevel"])}
            for w in weeks for d in w["contributionDays"]]
    return sorted((d for d in days if start <= d["date"] <= end), key=lambda d: d["date"])


def _plural(n, word):
    """``"1 contribution"`` / ``"5 contributions"``."""
    return f"{n:,} {word}{'' if n == 1 else 's'}"


def summary(days):
    """One sentence for the chart title and the image's alt text."""
    total = sum(d["count"] for d in days)
    first, last = days[0]["date"], days[-1]["date"]
    return (f"{_plural(total, 'contribution')} in the last {MONTHS} months "
            f"({first:%b} {first.day}, {first.year} to {last:%b} {last.day}, {last.year})")


def render_svg(days, theme):
    """Draw the chart as a standalone SVG string.

    Layout follows GitHub's chart: one column per week (Sunday at the top), month names
    above the first column that contains a month's 1st (or the first column), Mon/Wed/Fri
    labels on the left, and a Less-to-More legend at the bottom right. Every cell has a
    ``<title>`` tooltip ("Oct 3, 2026: 4 contributions") for when the SVG is opened directly.

    Args:
        days: Output of :func:`fetch_days` (must not be empty).
        theme: ``"light"`` or ``"dark"``.

    Returns:
        The SVG document as text.
    """
    t = THEMES[theme]
    first = days[0]["date"]
    week0 = first - dt.timedelta(days=(first.weekday() + 1) % 7)   # the Sunday on or before the first day
    columns = (days[-1]["date"] - week0).days // 7 + 1
    width = LEFT + columns * PITCH + 12
    height = TOP + 7 * PITCH + 34
    total = sum(d["count"] for d in days)
    title = summary(days)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" aria-labelledby="t d">',
        f'<title id="t">{html.escape(title)}</title>',
        f'<desc id="d">A calendar heatmap with one square per day; darker green means more contributions.</desc>',
        f'<rect width="{width}" height="{height}" rx="6" fill="{t["bg"]}"/>',
        f'<g font-family="{FONT}">',
        f'<text x="{LEFT}" y="20" font-size="14" font-weight="600" fill="{t["text"]}">'
        f'{_plural(total, "contribution")} in the last {MONTHS} months</text>',
    ]
    # Month labels: at the first column, and at each column that holds a month's 1st day.
    seen = set()
    for d in days:
        col = (d["date"] - week0).days // 7
        key = (d["date"].year, d["date"].month)
        if key not in seen and (d["date"].day == 1 or d is days[0]):
            seen.add(key)
            parts.append(f'<text x="{LEFT + col * PITCH}" y="{TOP - 8}" font-size="10" fill="{t["muted"]}">'
                         f'{d["date"]:%b}</text>')
    # Weekday labels on rows 1, 3 and 5 (Mon, Wed, Fri), as GitHub does.
    for row, name in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        parts.append(f'<text x="{LEFT - 6}" y="{TOP + row * PITCH + CELL - 2}" font-size="9" '
                     f'text-anchor="end" fill="{t["muted"]}">{name}</text>')
    for d in days:
        offset = (d["date"] - week0).days
        x, y = LEFT + (offset // 7) * PITCH, TOP + (offset % 7) * PITCH
        tip = f'{d["date"]:%b} {d["date"].day}, {d["date"].year}: {_plural(d["count"], "contribution")}'
        parts.append(f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2" '
                     f'fill="{t["cells"][d["level"]]}"><title>{tip}</title></rect>')
    # Legend, right-aligned under the grid.
    ly = TOP + 7 * PITCH + 12
    lx = width - 12 - 5 * PITCH - 28
    parts.append(f'<text x="{lx - 6}" y="{ly + CELL - 2}" font-size="9" text-anchor="end" fill="{t["muted"]}">Less</text>')
    for i, color in enumerate(t["cells"]):
        parts.append(f'<rect x="{lx + i * PITCH}" y="{ly}" width="{CELL}" height="{CELL}" rx="2" fill="{color}"/>')
    parts.append(f'<text x="{lx + 5 * PITCH + 2}" y="{ly + CELL - 2}" font-size="9" fill="{t["muted"]}">More</text>')
    parts.append("</g></svg>")
    return "\n".join(parts) + "\n"


def readme_block(days):
    """The README section between the markers: a ``<picture>`` that follows GitHub's theme."""
    return (f"{START}\n<picture>\n"
            f'  <source media="(prefers-color-scheme: dark)" srcset="assets/contributions-dark.svg">\n'
            f'  <img alt="GitHub contributions chart: {html.escape(summary(days))}" '
            f'src="assets/contributions-light.svg">\n'
            f"</picture>\n{END}")


def update_readme(text, days):
    """Replace the marked section of the README text (the markers must already be there).

    Raises:
        ValueError: If either marker is missing, so the README is never silently left stale.
    """
    if START not in text or END not in text:
        raise ValueError(f"README needs both {START} and {END}.")
    before, rest = text.split(START, 1)
    after = rest.split(END, 1)[1]
    return before + readme_block(days) + after


def main():
    """Fetch the last two months, write both SVGs and refresh the README section."""
    token = sys.stdin.read().strip()
    if not token:
        raise SystemExit("Pipe a GitHub token on standard input.")
    end = dt.datetime.now(dt.timezone.utc).date()
    days = fetch_days(token, months_back(end, MONTHS), end)
    if not days:
        raise SystemExit("GitHub returned no days.")
    ASSETS.mkdir(exist_ok=True)
    for theme in THEMES:
        (ASSETS / f"contributions-{theme}.svg").write_text(render_svg(days, theme), encoding="utf-8")
    README.write_text(update_readme(README.read_text(encoding="utf-8"), days), encoding="utf-8")
    print(summary(days))


if __name__ == "__main__":
    main()
