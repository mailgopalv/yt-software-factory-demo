from factory.__main__ import print_event  # noqa: F401  (the CLI and pipeline import cleanly)
from factory.pipeline import STAGES
from factory.pipeline import test_summary as summarise_tests


def test_seven_stage_cards_plus_the_gate():
    assert list(STAGES) == ["requirements", "analysis", "design", "build", "qa", "review", "approval", "release"]


def test_summary_shows_before_and_after_counts():
    baseline = {"api": {"name": "API (pytest)", "passed": 17, "ok": True}}
    results = {"api": {"name": "API (pytest)", "passed": 29, "ok": True}}

    assert summarise_tests(results, baseline) == "API (pytest) 17->29 ok"
