"""Static contracts for the copyable production Dockerfile templates."""

from pathlib import Path

import pytest

TEMPLATES = Path(__file__).parents[1] / "examples" / "docker"


@pytest.mark.parametrize(
    "filename",
    ["Dockerfile.python", "Dockerfile.playwright", "Dockerfile.monorepo"],
)
def test_template_matches_fargate_runtime_contract(filename: str) -> None:
    template = (TEMPLATES / filename).read_text()

    assert "useradd --system --gid app" in template
    assert 'VOLUME ["/tmp"]' in template
    assert "USER app" in template
    assert "HOME=/tmp/app-home" in template
    assert "TMPDIR=/tmp" in template
    assert "chmod 1777 /tmp" in template
    assert 'CMD ["my-scraper", "scraper", "worker"]' in template


def test_playwright_template_installs_browser_outside_root_home() -> None:
    template = (TEMPLATES / "Dockerfile.playwright").read_text()

    assert "PLAYWRIGHT_BROWSERS_PATH=/ms-playwright" in template
    assert "chmod -R a+rX /ms-playwright" in template
