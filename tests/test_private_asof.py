"""As-of semantics for private observations. Synthetic rows only: no provider data.

A `source_class=private` observation is available only from its own `retrieved_at`, whatever
its reference period or nominal release date. Public observations keep official release-date
semantics. (docs/data-policy.md rule 6; docs/wind-capability-note.md section 7.)
"""
from pathlib import Path

import pandas as pd
import pytest

from cnmacro.checks import asof_leakage
from cnmacro.claims import Binding, Claim
from cnmacro.store import OBS_COLUMNS, as_of, available_at, load_dictionary

FX = Path(__file__).parent / "fixtures"
T1 = "2026-10-05T00:00:00Z"   # before our retrieval
T2 = "2026-10-10T08:00:00Z"   # our retrieval
T3 = "2026-10-11T00:00:00Z"


def _row(source_class, release_date="", retrieved_at=T2, period="2026-08", value=1.0, source="TEST"):
    r = {c: "" for c in OBS_COLUMNS}
    r.update(metric_id="fx_ppi_yoy", reference_period=period, value=value, release_date=release_date,
             release_date_basis="official_calendar" if release_date else "unknown", retrieved_at=retrieved_at,
             source=source, source_class=source_class, quality_flag="ok", limitation="synthetic")
    return r


def _frame(*rows):
    df = pd.DataFrame(rows, columns=OBS_COLUMNS)
    df["value"] = pd.to_numeric(df["value"])
    df["consensus"] = pd.to_numeric(df["consensus"], errors="coerce")
    df["_file"] = "synthetic"
    return df


def test_private_row_is_not_available_before_its_retrieval_even_with_an_earlier_release_date():
    # reference period and nominal release are months before T1, retrieval is after T1
    df = _frame(_row("private", release_date="2026-09-09", retrieved_at=T2))
    assert as_of(df, T1).empty
    assert available_at(df.iloc[0]) == pd.Timestamp("2026-10-10 08:00")


def test_private_row_without_a_release_date_is_also_gated_by_retrieval():
    df = _frame(_row("private", release_date="", retrieved_at=T2))
    assert as_of(df, T1).empty


def test_private_row_becomes_usable_at_or_after_its_retrieval():
    df = _frame(_row("private", release_date="2026-09-09", retrieved_at=T2, value=7.0))
    at = as_of(df, T2)                      # exactly at retrieval
    assert list(at["value"]) == [7.0]
    later = as_of(df, T3)
    assert list(later["value"]) == [7.0]
    just_before = as_of(df, "2026-10-10T07:59:59Z")
    assert just_before.empty


def test_public_row_keeps_official_release_date_semantics():
    # released 2026-09-09 (Beijing), retrieved later: a public row is known from its release
    df = _frame(_row("public", release_date="2026-09-09", retrieved_at=T2))
    assert available_at(df.iloc[0]) == pd.Timestamp("2026-09-09 15:59:59")
    # still gated by what we actually held: a vintage retrieved after T1 is not in a T1 information
    # set when an earlier-retrieved vintage exists
    early = _row("public", release_date="2026-09-09", retrieved_at="2026-09-20T00:00:00Z", value=5.0)
    both = _frame(early, _row("public", release_date="2026-09-09", retrieved_at=T2, value=6.0))
    assert list(as_of(both, T1)["value"]) == [5.0]
    assert list(as_of(both, T3)["value"]) == [6.0]


def test_public_row_without_a_release_date_still_falls_back_to_retrieval():
    df = _frame(_row("public", release_date="", retrieved_at=T2))
    assert as_of(df, T1).empty
    assert len(as_of(df, T2)) == 1


def test_public_release_date_makes_a_public_row_available_before_the_release_is_retrieved():
    # the only public vintage was retrieved after `when`, but the release preceded `when`:
    # unchanged public behaviour is that the row is visible once nothing earlier was held
    df = _frame(_row("public", release_date="2026-09-09", retrieved_at=T2, value=3.0))
    assert list(as_of(df, T1)["value"]) == [3.0]


def test_private_rows_never_borrow_a_public_release_date_in_a_mixed_frame():
    pub = _row("public", release_date="2026-09-09", retrieved_at="2026-09-20T00:00:00Z", period="2026-08", value=5.0)
    priv = _row("private", release_date="2026-09-09", retrieved_at=T2, period="2026-08", value=9.0, source="Wind")
    df = _frame(pub, priv)
    assert list(as_of(df, T1)["value"]) == [5.0]      # the private vintage is not visible yet
    assert list(as_of(df, T3)["value"]) == [9.0]      # the latest vintage wins afterwards


def test_a_claim_citing_a_private_row_before_its_retrieval_is_flagged_as_leakage():
    metrics = load_dictionary(FX / "dictionary.yaml")
    df = _frame(_row("private", release_date="2026-09-09", retrieved_at=T2, value=9.0, source="Wind"))
    cite = "obs:fx_ppi_yoy@2026-08"

    def claim(when):
        return Claim(id="C1", type="FACT", text_en="x {v}", text_zh="x {v}", as_of=when, hypotheses=["H1"],
                     values={"v": Binding(ref=cite, recorded=9.0)})

    assert asof_leakage([claim("2026-10-05")], df, metrics).status == "fail"
    assert asof_leakage([claim("2026-10-10T09:00:00Z")], df, metrics).status == "pass"


@pytest.mark.parametrize("cls", ["private", "public"])
def test_available_at_accepts_plain_dict_rows(cls):
    row = {"release_date": "", "retrieved_at": "2026-10-04T08:00:00+08:00", "source_class": cls}
    assert available_at(row) == pd.Timestamp("2026-10-04 00:00")
