"""Tests for scraper outcome semantics around parser drift."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from etl.courts.scraper import classifier, core
from etl.courts.scraper.classifier import Classification, ClassificationResult
from etl.courts.scraper.core import RetryableScrapeError, UJSPortalScraper
from etl.courts.scraper.net_observer import NetworkObserver


class FakePage:
    """Minimal Playwright page fake for scraper core tests."""

    url = "https://ujsportal.pacourts.us/CaseSearch/Results"

    def fill(self, selector: str, value: str) -> None:
        pass

    def click(self, selector: str) -> None:
        pass

    def content(self) -> str:
        return "<html></html>"


def test_visible_results_parse_failure_is_retryable_ui_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    """A results page that cannot be parsed should not become SUCCESS with no rows."""
    scraper = UJSPortalScraper(errors="ignore")
    scraper._net_observer = NetworkObserver()
    monkeypatch.setattr(scraper, "_ensure_page", lambda: FakePage())
    monkeypatch.setattr(core, "_parse_results", MagicMock(side_effect=ValueError("drift")))
    monkeypatch.setattr(
        classifier,
        "classify_case_search",
        MagicMock(
            return_value=ClassificationResult(
                classification=Classification.HAS_RESULTS,
                row_count=1,
                final_url=FakePage.url,
            )
        ),
    )

    with pytest.raises(RetryableScrapeError) as exc_info:
        scraper._scrape_once("1234567890", 1)

    assert exc_info.value.result.classification == Classification.UI_DRIFT_OR_UNKNOWN


def test_parse_results_accepts_fixture_rows() -> None:
    """Visible portal rows should parse even when the row exposes only one link."""
    html = (Path(__file__).parent / "fixtures/ujs/results_with_rows.html").read_text()

    results = core._parse_results(html)

    assert results is not None
    assert len(results) == 2
    assert results[0].docket_number == "CP-51-CR-0001234-2024"
    assert results[0].court_summary_url.endswith(
        "/Report/CpCourtSummary?docketNumber=CP-51-CR-0001234-2024"
    )


def test_parse_results_accepts_partial_rows() -> None:
    """A vendor grid column change should not erase an otherwise visible hit."""
    html = """
    <div id="caseSearchResultGrid">
      <table>
        <tbody>
          <tr>
            <td><a href="/Report/CpCourtSummary?docketNumber=CP-51-CR-0001234-2024">
              CP-51-CR-0001234-2024
            </a></td>
            <td>Criminal</td>
            <td>Comm. v. Smith, John</td>
          </tr>
        </tbody>
      </table>
    </div>
    """

    results = core._parse_results(html)

    assert results is not None
    assert results[0].docket_number == "CP-51-CR-0001234-2024"
    assert results[0].court_type == "Criminal"
    assert results[0].case_status == ""
