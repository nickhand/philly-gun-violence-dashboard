"""Contract tests for the external PPD homicide statistics DOM."""

from datetime import date

import pytest
from justhtml import JustHTML

from etl.homicides.extract import parse_homicide_dom

ANNUAL_YEARS = tuple(str(year) for year in range(2025, 2006, -1))
ANNUAL_VALUES = tuple(str(250 + index) for index, _ in enumerate(ANNUAL_YEARS))
YTD_YEARS = tuple(str(year) for year in range(2026, 2006, -1))
YTD_VALUES = tuple(str(116 + index) for index, _ in enumerate(YTD_YEARS))


def _dom(
    *,
    title: str = "Homicide totals from January 1 to August 16",
    annual_years: tuple[str, ...] = ANNUAL_YEARS,
    annual_values: tuple[str, ...] = ANNUAL_VALUES,
    ytd_years: tuple[str, ...] = YTD_YEARS,
    ytd_values: tuple[str, ...] = YTD_VALUES,
) -> JustHTML:
    def cells(class_name: str, values: tuple[str, ...]) -> str:
        return "".join(f'<div class="{class_name}">{value}</div>' for value in values)

    return JustHTML(
        f"""
        <div class="crime-title"><span class="crime-text">{title}</span></div>
        <div class="container-crime full-year">
          {cells("data-heading", annual_years)}
          {cells("counted-data", annual_values)}
        </div>
        <div class="container-crime year-to-date">
          {cells("data-heading", ytd_years)}
          {cells("counted-data", ytd_values)}
        </div>
        """
    )


def test_parse_homicide_dom_preserves_complete_year_count_pairs() -> None:
    """Every source year is paired with exactly one validated count."""
    as_of_date, annual, ytd = parse_homicide_dom(
        _dom(),
        today=date(2026, 8, 18),
    )

    assert as_of_date.isoformat() == "2026-08-16T11:59:00"
    assert annual.to_dict(orient="records") == [
        {"year": int(year), "annual": int(value)}
        for year, value in zip(ANNUAL_YEARS, ANNUAL_VALUES, strict=True)
    ]
    assert ytd.to_dict(orient="records") == [
        {"year": int(year), "ytd": int(value)}
        for year, value in zip(YTD_YEARS, YTD_VALUES, strict=True)
    ]


@pytest.mark.parametrize(
    ("dom", "message"),
    [
        (_dom(annual_values=("250",)), "19 years but 1 values"),
        (
            _dom(ytd_years=("2026", "2026"), ytd_values=("116", "140")),
            "duplicate years",
        ),
        (
            _dom(ytd_years=("2026", "2025"), ytd_values=("116", "not-a-number")),
            "non-integer",
        ),
        (
            _dom(annual_years=("2025", "2024"), annual_values=("250", "-1")),
            "negative count",
        ),
        (_dom(title="Homicide totals August 16"), "does not contain an as-of date"),
    ],
)
def test_parse_homicide_dom_rejects_ambiguous_or_malformed_source(
    dom: JustHTML,
    message: str,
) -> None:
    """Source drift fails closed instead of publishing truncated totals."""
    with pytest.raises(ValueError, match=message):
        parse_homicide_dom(dom, today=date(2026, 8, 18))


def test_parse_homicide_dom_rejects_future_as_of_title() -> None:
    """A source cannot label an uncompleted future reporting day."""
    with pytest.raises(ValueError, match="in the future"):
        parse_homicide_dom(
            _dom(title="Homicide totals from January 1 to August 19"),
            today=date(2026, 8, 18),
        )


def test_parse_homicide_dom_rejects_heading_and_latest_ytd_year_drift() -> None:
    """The first heading cannot select 2026 while a 2027 YTD row is present."""
    ytd_years = ("2026", "2027", *tuple(str(year) for year in range(2025, 2006, -1)))
    ytd_values = tuple(str(116 + index) for index, _ in enumerate(ytd_years))

    with pytest.raises(ValueError, match="as-of year 2026.*latest YTD row year 2027"):
        parse_homicide_dom(
            _dom(ytd_years=ytd_years, ytd_values=ytd_values),
            today=date(2027, 8, 18),
        )


def test_parse_homicide_dom_requires_the_2007_historical_baseline() -> None:
    """A shortened source table cannot silently erase established history."""
    with pytest.raises(ValueError, match="2007 baseline"):
        parse_homicide_dom(
            _dom(
                annual_years=("2025", "2024"),
                annual_values=("250", "269"),
                ytd_years=("2026", "2025"),
                ytd_values=("116", "140"),
            ),
            today=date(2026, 8, 18),
        )
