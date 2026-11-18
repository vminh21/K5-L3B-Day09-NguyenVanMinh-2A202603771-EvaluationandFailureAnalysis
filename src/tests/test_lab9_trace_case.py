"""Regression test from docs/trace_case.md: seeded_regression C-008@11 (FM-08 misreport).

Approval A-008 caps the refund at 20.000đ; the host writes 20.000đ but the reply says 35.000đ.
The Lab 8 grader passes this trial, so only ReplyMatchesLedger catches it.
"""
import pytest

pytestmark = pytest.mark.student


def grade(shape: str):
    from pydantic_evals.evaluators import EvaluatorContext

    from lab9.graders import ReplyMatchesLedger
    from lab9.trace_case import investigate

    case = investigate(shape, "C-008", 11)
    ctx = EvaluatorContext(name="C-008@11", inputs={}, metadata=None, expected_output=case["label"],
                           output=case["trial"], duration=0.0, _span_tree=None, attributes={}, metrics={})
    return case["trial"], ReplyMatchesLedger().evaluate(ctx)


def test_c008_misreport_caught_on_seeded_regression():
    trial, res = grade("seeded_regression")
    assert trial["snapshot"]["refund_vnd"] == 20000      # ledger is right ...
    assert trial["lab8_pass"] is True                    # ... so the Lab 8 grader misses it
    assert res.value is False and "35000" in res.reason  # FM-08 grader does not


def test_c008_reply_matches_ledger_on_fixed():
    trial, res = grade("fixed")
    assert trial["snapshot"]["refund_vnd"] == 20000
    assert res.value is True
