"""The chart's y axis always contains the series it draws."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "site"))

from charts import nice_ticks  # noqa: E402


def test_axis_covers_the_maximum_when_it_sits_well_above_a_tick():
    # M1 YoY: a 2021 peak near 15% over a -7% low used to stop the axis at 10%
    ticks = nice_ticks(-7.4, 14.7)
    assert ticks[0] <= -7.4 and ticks[-1] >= 14.7
    assert ticks == [-10, 0, 10, 20]


def test_axis_unchanged_when_the_maximum_is_near_a_tick():
    assert nice_ticks(-5.0, 5.7) == [-5, 0, 5, 10]
    assert nice_ticks(0.0, 15.4) == [0, 5, 10, 15, 20]


def test_axis_handles_a_flat_series():
    ticks = nice_ticks(3.0, 3.0)
    assert ticks[0] <= 3.0 <= ticks[-1]
