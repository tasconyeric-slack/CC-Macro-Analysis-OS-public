"""Derived evidence with explicit lineage.

Every derived point records the observation refs it was computed from, so the
traceability check can recompute it and a reader can walk back to the source.

Reference grammar used across claims, tests and the website:
    obs:<metric_id>@<period>                e.g. obs:cn_ppi_yoy@2026-08
    drv:<fn>(<arg>[,<arg>...])@<period>     e.g. drv:ma(cn_ppi_yoy,3)@2026-08
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

from .store import Metric, series

REF_RE = re.compile(r"^(obs|drv):(.+)@([0-9A-Za-z-]+)$")
DRV_RE = re.compile(r"^(\w+)\((.*)\)$")


@dataclass
class Point:
    ref: str
    value: float
    inputs: list[str]


def obs_ref(metric_id: str, period) -> str:
    return f"obs:{metric_id}@{period}"


class Deriver:
    """Computes derived series from an as-of observation frame."""

    def __init__(self, obs: pd.DataFrame, metrics: dict[str, Metric]):
        self.obs = obs
        self.metrics = metrics
        self._cache: dict[str, pd.Series] = {}

    # ---- raw ------------------------------------------------------------
    def raw(self, metric_id: str) -> pd.Series:
        if metric_id not in self._cache:
            self._cache[metric_id] = series(self.obs, metric_id, self.metrics[metric_id].frequency)
        return self._cache[metric_id]

    def freq(self, metric_id: str) -> str:
        return self.metrics[metric_id].frequency

    def lag_for_yoy(self, metric_id: str) -> int:
        return {"M": 12, "Q": 4}[self.freq(metric_id)]

    # ---- derived functions: each returns {period: Point} ---------------
    def yoy(self, metric_id: str) -> dict:
        s, k = self.raw(metric_id), self.lag_for_yoy(metric_id)
        out = {}
        for p, v in s.items():
            q = p - k
            if q in s.index and s[q] not in (0, None):
                out[p] = Point(f"drv:yoy({metric_id})@{p}", (v / s[q] - 1) * 100,
                               [obs_ref(metric_id, p), obs_ref(metric_id, q)])
        return out

    def single(self, metric_id: str) -> dict:
        """Single-period value from a year-to-date cumulative level.

        First period of the year equals the cumulative value. For NBS monthly series
        published as Jan-Feb combined, February's single value is the Jan+Feb total
        and January is absent; the caller sees that through the lineage.
        """
        s = self.raw(metric_id)
        out = {}
        for p, v in s.items():
            prev = p - 1
            if prev.year == p.year and prev in s.index:
                out[p] = Point(f"drv:single({metric_id})@{p}", v - s[prev],
                               [obs_ref(metric_id, p), obs_ref(metric_id, prev)])
            elif prev.year != p.year or (self.freq(metric_id) == "M" and p.month == 2):
                out[p] = Point(f"drv:single({metric_id})@{p}", v, [obs_ref(metric_id, p)])
        return out

    def ma(self, metric_id: str, n: str | int) -> dict:
        n = int(n)
        s = self.raw(metric_id)
        out = {}
        for p in s.index:
            window = [p - i for i in range(n)]
            if all(w in s.index for w in window):
                out[p] = Point(f"drv:ma({metric_id},{n})@{p}", float(sum(s[w] for w in window) / n),
                               [obs_ref(metric_id, w) for w in window])
        return out

    def diff(self, metric_id: str, n: str | int = 1) -> dict:
        n = int(n)
        s = self.raw(metric_id)
        out = {}
        for p, v in s.items():
            if p - n in s.index:
                out[p] = Point(f"drv:diff({metric_id},{n})@{p}", v - s[p - n],
                               [obs_ref(metric_id, p), obs_ref(metric_id, p - n)])
        return out

    def deflator_yoy(self, nominal_yoy: str, real_yoy: str) -> dict:
        """GDP deflator YoY implied by nominal and real GDP growth (both in %)."""
        b = self.raw(real_yoy)
        if self.metrics[nominal_yoy].transform == "level":
            # nominal given as current-price levels: compute YoY first, keep its lineage
            pts = self.yoy(nominal_yoy)
            a = {p: (pt.value, pt.inputs) for p, pt in pts.items()}
        else:
            a = {p: (v, [obs_ref(nominal_yoy, p)]) for p, v in self.raw(nominal_yoy).items()}
        out = {}
        for p in sorted(set(a) & set(b.index)):
            nv, n_inputs = a[p]
            v = ((1 + nv / 100) / (1 + b[p] / 100) - 1) * 100
            out[p] = Point(f"drv:deflator_yoy({nominal_yoy},{real_yoy})@{p}", v,
                           n_inputs + [obs_ref(real_yoy, p)])
        return out

    def pctile(self, metric_id: str, years: str | int = 10) -> dict:
        """Percentile rank (0-100) of each value within the trailing window."""
        s = self.raw(metric_id)
        per_year = {"M": 12, "Q": 4, "D": 252}[self.freq(metric_id)]
        n = int(years) * per_year
        out = {}
        vals = list(s.items())
        for i, (p, v) in enumerate(vals):
            if i + 1 < n:
                continue
            window = [x for _, x in vals[i + 1 - n: i + 1]]
            rank = sum(1 for x in window if x <= v) / len(window) * 100
            out[p] = Point(f"drv:pctile({metric_id},{years})@{p}", rank,
                           [obs_ref(metric_id, vals[i + 1 - n][0]), obs_ref(metric_id, p)])
        return out

    FUNCS = {"yoy", "single", "ma", "diff", "deflator_yoy", "pctile"}

    def compute(self, fn: str, args: list[str]) -> dict:
        if fn not in self.FUNCS:
            raise KeyError(f"unknown derived function {fn}")
        return getattr(self, fn)(*args)

    # ---- resolution -----------------------------------------------------
    def resolve(self, ref: str) -> Point | None:
        m = REF_RE.match(ref)
        if not m:
            raise ValueError(f"malformed ref {ref!r}")
        kind, body, period = m.groups()
        if kind == "obs":
            s = self.raw(body)
            p = pd.Period(period, freq=self.freq(body))
            return Point(ref, float(s[p]), []) if p in s.index else None
        fn, args = parse_drv(body)
        first_metric = next(a for a in args if a in self.metrics)
        p = pd.Period(period, freq=self.freq(first_metric))
        return self.compute(fn, args).get(p)

    def series_for(self, spec: str) -> pd.Series:
        """Full series for `metric_id` or `fn(args)`; used by charts and tests."""
        if spec in self.metrics:
            return self.raw(spec)
        fn, args = parse_drv(spec)
        pts = self.compute(fn, args)
        return pd.Series({p: pt.value for p, pt in pts.items()}, dtype=float).sort_index()

    def ref_for(self, spec: str, period) -> str:
        return obs_ref(spec, period) if spec in self.metrics else f"drv:{spec}@{period}"


def parse_drv(body: str) -> tuple[str, list[str]]:
    m = DRV_RE.match(body)
    if not m:
        raise ValueError(f"malformed derived spec {body!r}")
    return m.group(1), [a.strip() for a in m.group(2).split(",") if a.strip()]
