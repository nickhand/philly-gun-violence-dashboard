"""Contracts for the complete human-review IAM namespace inventory."""

from aws_batch_scraper.resolution_paths import (
    HUMAN_REVIEW_RESOLUTION_PATHS,
    RESULT_CONFLICT_RESOLUTION_PATH,
    RESULT_CONFLICT_RESOLUTION_ROOT,
    TERMINAL_DECISION_RESOLUTION_PATH,
)


def test_human_review_resolution_paths_include_both_adjudication_protocols() -> None:
    assert RESULT_CONFLICT_RESOLUTION_ROOT == "result-conflict-resolutions"
    assert RESULT_CONFLICT_RESOLUTION_PATH == "result-conflict-resolutions/v1"
    assert TERMINAL_DECISION_RESOLUTION_PATH == "terminal-decision-resolutions/v1"
    assert HUMAN_REVIEW_RESOLUTION_PATHS == (
        RESULT_CONFLICT_RESOLUTION_PATH,
        TERMINAL_DECISION_RESOLUTION_PATH,
    )
    assert len(set(HUMAN_REVIEW_RESOLUTION_PATHS)) == len(HUMAN_REVIEW_RESOLUTION_PATHS)
