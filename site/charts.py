"""Server-rendered SVG line charts, including same-unit shared-axis comparisons.

Specs follow the dataviz method: 2px line, recessive hairline grid, a labelled
reference line where the evidence test has a natural threshold (0 or 50), the last
value labelled at the line end, an end-dot with a surface ring, and point data
embedded for the hover tooltip (site/static/charts.js).
"""
from __future__ import annotations

import json
import math
from html import escape

W, H = 640, 240
PAD_L, PAD_R, PAD_T, PAD_B = 44, 64, 14, 26


def nice_ticks(lo: float, hi: float, n: int = 4) -> list[float]:
    if hi == lo:
        hi, lo = hi + 1, lo - 1
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = min((s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw), default=raw)
    start = math.floor(lo / step) * step
    # stop at the first tick at or above the maximum, so the axis always contains the data
    ticks, t = [], start
    while True:
        ticks.append(round(t, 10))
        if t >= hi - step * 1e-9:
            return ticks
        t += step


def fmt(v: float, unit: str) -> str:
    if abs(v) >= 1000:
        s = f"{v:,.0f}"
    elif abs(v) >= 100:
        s = f"{v:.0f}"
    else:
        s = f"{v:.1f}"
    return s + ("%" if unit == "%" else "")


def line_chart(points: list[tuple[str, float]], unit: str, ref: float | None = None,
               chart_id: str = "c", width: int = W, height: int = H,
               label: str = "line chart", empty: str = "Not enough data to chart.", details: list[str] | None = None,
               monthly: bool = False, break_before: tuple[str, ...] = ()) -> str:
    W_, H_ = width, height
    if len(points) < 2:
        return f'<p class="muted">{escape(empty)}</p>'
    vals = [v for _, v in points]
    lo, hi = min(vals + ([ref] if ref is not None else [])), max(vals + ([ref] if ref is not None else []))
    ticks = nice_ticks(lo, hi)
    y0, y1 = ticks[0], ticks[-1]
    iw, ih = W_ - PAD_L - PAD_R, H_ - PAD_T - PAD_B

    positions = [_month(p) for p, _ in points] if monthly else list(range(len(points)))
    def x(i):
        return PAD_L + iw * (positions[i] - positions[0]) / (positions[-1] - positions[0] or 1)

    def y(v):
        return PAD_T + ih * (1 - (v - y0) / (y1 - y0 or 1))

    parts = [f'<svg class="chart" id="{chart_id}" viewBox="0 0 {W_} {H_}" role="img" '
             f'aria-label="{escape(label)}">']
    for t in ticks:
        parts.append(f'<line class="grid" x1="{PAD_L}" x2="{W_ - PAD_R}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>')
        parts.append(f'<text class="tick" x="{PAD_L - 6}" y="{y(t) + 4:.1f}" text-anchor="end">{fmt(t, unit)}</text>')
    if ref is not None:
        parts.append(f'<line class="ref" x1="{PAD_L}" x2="{W_ - PAD_R}" y1="{y(ref):.1f}" y2="{y(ref):.1f}"/>')
    # x labels: first, middle, last
    for i in sorted({0, len(points) // 2, len(points) - 1}):
        anchor = "start" if i == 0 else ("end" if i == len(points) - 1 else "middle")
        parts.append(f'<text class="tick" x="{x(i):.1f}" y="{H_ - 6}" text-anchor="{anchor}">{escape(points[i][0])}</text>')
    d = " ".join(f"{'M' if i == 0 or any(points[i-1][0] < b <= points[i][0] for b in break_before) or (monthly and positions[i] - positions[i-1] != 1) else 'L'}{x(i):.1f},{y(v):.1f}" for i, (_, v) in enumerate(points))
    parts.append(f'<path class="series" d="{d}"/>')
    lx, ly = x(len(points) - 1), y(vals[-1])
    parts.append(f'<circle class="end" cx="{lx:.1f}" cy="{ly:.1f}" r="4"/>')
    parts.append(f'<text class="endlabel" x="{lx + 8:.1f}" y="{ly + 4:.1f}">{fmt(vals[-1], unit)}</text>')
    parts.append('<line class="cross" x1="0" x2="0" y1="0" y2="0" visibility="hidden"/>')
    parts.append("</svg>")
    data = {"x": [round(x(i), 1) for i in range(len(points))], "y": [round(y(v), 1) for v in vals],
            "labels": [p for p, _ in points], "values": [fmt(v, unit) for v in vals],
            "top": PAD_T, "bottom": H_ - PAD_B, "details": details or []}
    parts.append(f'<script type="application/json" data-for="{chart_id}">{json.dumps(data)}</script>')
    return "".join(parts)


def _month(period):
    year, month = map(int, period.split('-'))
    return year * 12 + month - 1


def comparison_chart(series, chart_id='comparison', width=W, height=H, label='Price chain'):
    """Existing SVG/tooltip contract, several monthly lines on one percentage scale.

    Missing months break paths. Union calendar spacing preserves elapsed time.
    """
    periods = sorted({p for _, points in series for p, _ in points})
    if len(periods) < 2:
        return ''
    values = [v for _, points in series for _, v in points]
    ticks = nice_ticks(min(values + [0]), max(values + [0]))
    iw, ih = width - PAD_L - PAD_R, height - PAD_T - PAD_B
    def x(p):
        return PAD_L + iw * (_month(p) - _month(periods[0])) / (_month(periods[-1]) - _month(periods[0]) or 1)
    def y(v):
        return PAD_T + ih * (1 - (v - ticks[0]) / (ticks[-1] - ticks[0] or 1))
    parts = [f'<svg class="chart" id="{escape(chart_id)}" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(label)}">']
    for t in ticks:
        parts += [f'<line class="grid" x1="{PAD_L}" x2="{width-PAD_R}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>',
                  f'<text class="tick" x="{PAD_L-6}" y="{y(t)+4:.1f}" text-anchor="end">{fmt(t,"%")}</text>']
    parts.append(f'<line class="ref" x1="{PAD_L}" x2="{width-PAD_R}" y1="{y(0):.1f}" y2="{y(0):.1f}"/>')
    maps = []
    for n, (name, points) in enumerate(series):
        maps.append((name, dict(points)))
        path = ' '.join(f'{"M" if i == 0 or _month(p)-_month(points[i-1][0]) != 1 else "L"}{x(p):.1f},{y(v):.1f}' for i, (p,v) in enumerate(points))
        parts.append(f'<path class="series price-line-{n}" d="{path}"/>')
    for p in (periods[0], periods[-1]):
        parts.append(f'<text class="tick" x="{x(p):.1f}" y="{height-6}" text-anchor="{"start" if p == periods[0] else "end"}">{p}</text>')
    parts.append('<line class="cross" visibility="hidden"/></svg>')
    data = {'x': [round(x(p),1) for p in periods], 'y': [height/2]*len(periods), 'labels': periods,
            'values': [' · '.join(f'{name}: {fmt(values[p], "%") if p in values else "—"}' for name,values in maps) for p in periods],
            'top': PAD_T, 'bottom': height-PAD_B}
    # Escape HTML delimiters in JSON embedded in a script element.
    encoded = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c')
    parts.append(f'<script type="application/json" data-for="{escape(chart_id)}">{encoded}</script>')
    return ''.join(parts)
