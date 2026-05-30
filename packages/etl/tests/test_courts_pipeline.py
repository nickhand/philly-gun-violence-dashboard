"""Tests for courts post-processing helpers."""

import pandas as pd
from aws_batch_scraper.types import ScrapeResult, ScrapeStatus

from etl.courts.pipeline import _result_coverage


def test_result_coverage_counts_missing_and_extra_results() -> None:
    input_df = pd.DataFrame({"dc_key": ["100", "200", "300"]})
    results = {
        "100": ScrapeResult(status=ScrapeStatus.SUCCESS),
        "200": ScrapeResult(status=ScrapeStatus.NO_RESULTS),
        "999": ScrapeResult(status=ScrapeStatus.SUCCESS),
    }

    missing_count, extra_count = _result_coverage(results, input_df)

    assert missing_count == 1
    assert extra_count == 1
