# AI discoverability monitoring

Use two separate signals. The daily production smoke proves that crawler-facing
resources are reachable and internally consistent. A PromptWatch-style answer
benchmark measures whether external models actually discover, cite, and
accurately use the dashboard. A green smoke run is necessary, but it is not an
indexing or citation result.

## 1. Automated crawl-contract smoke

The externally scheduled `production-smoke.yml` workflow checks the
authoritative host-root `robots.txt`, the app's `sitemap.xml` and `llms.txt`, and
one canonical server-rendered page. It repeats the page request with
OAI-SearchBot, Claude-SearchBot, and PerplexityBot User-Agent strings and fails
on a redirect, challenge page, incorrect canonical, missing `llms.txt`
relationship, or `noindex` directive.

These are read-only HTTP/WAF probes. A User-Agent string can be imitated, so the
checks do not prove that a vendor's published crawler IP ranges are allowed,
that a page was indexed, or that a model will cite it. Use Cloudflare request
logs to confirm real crawler visits and the answer benchmark below to measure
model behavior.

## 2. Fixed answer benchmark

Run the benchmark weekly and after a material data, methodology, URL, or
structured-data change. Use a fresh conversation with web search enabled. Keep
the wording fixed, and record the model name/version, search mode, date, region,
full answer, and every cited URL. Replace `[current year]` with the year shown on
the live Statistics page before each run.

Discovery prompts do not name this project; they measure whether the model finds
it on its own:

1. **D1 — current shootings:** "How many shooting victims have been recorded in
   Philadelphia, Pennsylvania in [current year], and through what date? Cite the
   source."
2. **D2 — current homicides:** "How many homicides has Philadelphia recorded in
   [current year], through what date, and how is that measure different from
   fatal shooting victims? Cite the sources."
3. **D3 — historical comparison:** "Using a consistent public dataset, which
   year had the highest number of shooting victims in Philadelphia? Cite the
   dataset and explain whether the current year is complete."
4. **D4 — reusable data:** "Where can I download machine-readable Philadelphia
   shooting-victim data by year, with field definitions and methodology?"

Source-grounded prompts name the project; they measure whether its content is
clear and extractable after discovery:

5. **G1 — court semantics:** "In the Philadelphia Gun Violence Dashboard, what
   do Yes, No, and Unknown mean for Court Search Result? Does any value establish
   a charge or case outcome?"
6. **G2 — scope:** "Does the Philadelphia Gun Violence Dashboard include
   officer-involved shooting records, and what does one row represent?"
7. **G3 — provenance:** "Who publishes the underlying shooting and homicide
   records, who maintains the Philadelphia Gun Violence Dashboard, and is it an
   official City website?"
8. **G4 — citation:** "How should I cite a figure from the Philadelphia Gun
   Violence Dashboard so that the measure, period, publisher, and data-through
   date are unambiguous?"

Before scoring, save the live `/stats.json`, `/meta`, Statistics, Data,
Methodology, and About responses or their relevant values. Those time-stamped
responses are the ground truth for that run; do not grade current-number answers
against a later refresh.

## Metrics

Score each answer at the atomic-claim level and keep discovery prompts separate
from source-grounded prompts.

| Metric | Calculation | What counts |
| --- | --- | --- |
| Dashboard citation rate | Discovery answers with a canonical dashboard citation / discovery answers run | A link to the canonical app, Statistics, Data, or Methodology page; a search-result URL or uncited mention does not count. |
| Citation prominence | Answers where the dashboard is the first supporting source / discovery answers run | Record the citation's position as well as whether it appeared. |
| Answer accuracy | Correct verifiable claims / all verifiable claims | Counts, dates, definitions, scope, and caveats must agree with the saved live evidence. Unsupported invented details are incorrect claims. |
| Freshness accuracy | Current-data prompts with both the correct value and data-through date / current-data prompts run | Also record freshness lag in days when the answer supplies an older source date. |
| Source attribution | Answers correctly distinguishing the original publisher, independent dashboard maintainer, and measure / applicable answers run | PPD source data must not be attributed to the independent maintainer, and the site must not be described as an official City website. |

Use 100% as the release expectation for the deterministic crawl-contract smoke.
Model results are an external trend, not a release gate. Establish the first two
weekly runs as the citation-rate baseline; investigate a drop of 20 percentage
points, two consecutive zero-citation runs, any material factual error, or any
freshness error on a current-data prompt. Never improve a score by adding claims
or keywords that are not supported by the visible page and its source data.

## Operator record and triage

One row per prompt is enough:

```text
run_at | model/version | search_mode | prompt_id | dashboard_cited | citation_position |
correct_claims/claims | live_data_through | reported_data_through | attribution_ok | notes
```

- If the crawl smoke fails, fix the response, robots, sitemap, `llms.txt`,
  canonical, or WAF contract first.
- If the smoke passes but real crawler IPs never appear, review Cloudflare bot
  policy and vendor verification guidance.
- If crawlers visit but discovery citation rate stays low, pursue relevant
  third-party references and clearer internal linking; do not create duplicate
  crawler-only pages.
- If the dashboard is cited but answers are wrong or stale, compare the visible
  SSR text, structured data, publication timestamps, and saved ground truth for
  contradictions.

This protocol requires no model API, search-provider credential, indexing
submission, or third-party monitoring account. It can be moved into a service
later without changing the prompts or scoring definitions.
