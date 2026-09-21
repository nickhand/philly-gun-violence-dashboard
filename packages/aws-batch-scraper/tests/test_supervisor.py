"""Real subprocess regressions for swallowed deadlines and hung browser teardown."""

import contextlib
import os
import signal
import time

import pytest
from aws_batch_scraper.supervisor import (
    ScraperProcessError,
    ScraperProcessTimeout,
    SupervisedScraper,
)
from aws_batch_scraper.types import FailureArtifact, ScrapeResult, ScrapeStatus, WorkItem


class FakeBrowser:
    def __init__(self):
        self.last_item = ""
        self.count = 0

    def __call__(self, item):
        self.last_item = item.item_id
        self.count += 1
        if item.item_id == "hang":
            # The child can even ignore signals and swallow TimeoutError; the
            # parent deadline and SIGKILL must remain effective.
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            while True:
                with contextlib.suppress(TimeoutError):
                    time.sleep(60)
        if item.item_id == "crash":
            os._exit(1)
        return ScrapeResult(status=ScrapeStatus.NO_RESULTS, data={"count": self.count})

    def reset(self):
        if self.last_item == "reset-hang":
            time.sleep(60)

    def close(self):
        if self.last_item == "close-hang":
            time.sleep(60)

    def failure_artifacts(self, item):
        return [FailureArtifact("html", b"<html>evidence</html>", "text/html")]


def test_browser_process_reuse_and_artifact_round_trip():
    scraper = SupervisedScraper(FakeBrowser, control_timeout=5)
    try:
        assert scraper(WorkItem("first")).data == {"count": 1}
        scraper.reset()
        assert scraper(WorkItem("second")).data == {"count": 2}
        assert scraper.failure_artifacts(WorkItem("second"))[0].body == b"<html>evidence</html>"
    finally:
        scraper.close()
    assert scraper._process is None


def test_swallowed_timeout_and_ignored_termination_cannot_strand_parent():
    scraper = SupervisedScraper(FakeBrowser, scrape_timeout=0.15, control_timeout=5, stop_grace=0.1)
    scraper(WorkItem("warmup"))
    started = time.monotonic()
    with pytest.raises(ScraperProcessTimeout):
        scraper(WorkItem("hang"))
    assert time.monotonic() - started < 3
    assert scraper._process is None
    with pytest.raises(ScraperProcessError, match="restart"):
        scraper(WorkItem("later"))


@pytest.mark.parametrize("operation", ["reset", "close"])
def test_teardown_has_its_own_parent_deadline(operation):
    scraper = SupervisedScraper(FakeBrowser, control_timeout=5, stop_grace=0.1)
    scraper(WorkItem(f"{operation}-hang"))
    scraper.control_timeout = 0.15
    started = time.monotonic()
    with pytest.raises(ScraperProcessTimeout):
        getattr(scraper, operation)()
    assert time.monotonic() - started < 3
    assert scraper._process is None


def test_child_crash_is_not_an_empty_scrape_success():
    scraper = SupervisedScraper(FakeBrowser, control_timeout=5, stop_grace=0.1)
    with pytest.raises(ScraperProcessError, match="no valid response"):
        scraper(WorkItem("crash"))
    assert scraper._process is None


class HungStartupBrowser(FakeBrowser):
    def __init__(self):
        time.sleep(60)


def test_browser_startup_has_a_parent_deadline():
    scraper = SupervisedScraper(HungStartupBrowser, control_timeout=0.5, stop_grace=0.1)
    started = time.monotonic()
    with pytest.raises(ScraperProcessTimeout):
        scraper(WorkItem("first"))
    assert time.monotonic() - started < 3
    assert scraper._process is None
