# Data Sources

The dashboard uses public data sources and stores processed outputs in S3 with
metadata describing freshness, row counts, and source health.

## Shooting Victims

- Source: City of Philadelphia open data, published through OpenDataPhilly.
- Update cadence: generally daily on weekdays.
- Processing: the ETL normalizes fields, validates schema expectations, enriches
  geospatial attributes, and writes year-addressable processed data.
- Caveat: records are preliminary and may be revised by the source agency.

## Homicide Totals

- Source: Philadelphia Police Department public crime statistics.
- Update cadence: scheduled ETL refreshes check the source for new totals.
- Processing: the ETL writes annual and year-to-date summary data for API use.
- Caveat: homicide totals include all homicide types, not only firearm-related
  incidents.

## Court Case Matches

- Source: Pennsylvania Unified Judicial System public web portal.
- Update cadence: weekly or manually triggered scraper runs.
- Processing: incident identifiers are searched in the portal, per-incident scrape
  results are written to S3, then aggregated into a processed court-status dataset.
- Caveat: matches depend on portal availability, source data latency, and the
  presence/quality of incident identifiers.

## Boundaries And Streets

- Source: public Philadelphia geospatial reference datasets.
- Processing: ETL jobs normalize boundary and street-block data for API and
  frontend map layers.
- Caveat: geographic boundaries and street geometry may change over time as source
  datasets are updated.

## Data Freshness

Core processed datasets write metadata alongside the data payloads. Metadata
includes timestamps, source status, row counts, and source-specific validation
details where available.
