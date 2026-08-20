<script setup lang="ts">
import {
  createCourtSourceEntity,
  createDashboardPageProvenance,
  getDashboardEntityIds,
  PPD_HOMICIDE_SOURCE_URL,
  PPD_SHOOTING_SOURCE_URL,
} from "~/utils/structuredData";

const { canonicalBaseUrl } = useRuntimeConfig().public;
const siteUrl = String(canonicalBaseUrl).replace(/\/$/, "");
const canonicalUrl = `${siteUrl}/methodology`;
const entityIds = getDashboardEntityIds(siteUrl);
const description =
  "Sources, inclusion rules, processing steps, quality checks, and limitations for the records presented by the Philadelphia Gun Violence Dashboard.";

useSeoMeta({
  title: "Methodology | Philadelphia Gun Violence Dashboard",
  description,
  ogType: "website",
  ogTitle: "How the dashboard data is prepared",
  ogDescription: description,
  ogUrl: canonicalUrl,
  ogImage: `${siteUrl}/og-image.png`,
  twitterCard: "summary_large_image",
  twitterTitle: "How the dashboard data is prepared",
  twitterDescription: description,
  twitterImage: `${siteUrl}/og-image.png`,
});

useHead(() => ({
  link: [{ rel: "canonical", href: canonicalUrl }],
  script: [
    {
      type: "application/ld+json",
      innerHTML: JSON.stringify({
        "@context": "https://schema.org",
        "@type": "WebPage",
        "@id": entityIds.methodologyPage,
        name: "How the Philadelphia Gun Violence Dashboard data is prepared",
        url: canonicalUrl,
        description,
        ...createDashboardPageProvenance(entityIds),
        mainEntity: { "@id": entityIds.dashboardDataset },
        about: { "@id": entityIds.dashboardDataset },
        citation: [
          {
            "@type": "Dataset",
            "@id": entityIds.shootingSourceDataset,
            name: "Shooting Victims",
            url: PPD_SHOOTING_SOURCE_URL,
            publisher: { "@id": entityIds.policeDepartment },
          },
          {
            "@type": "Dataset",
            "@id": entityIds.homicideSourceDataset,
            name: "Philadelphia Police Department homicide statistics",
            url: PPD_HOMICIDE_SOURCE_URL,
            publisher: { "@id": entityIds.policeDepartment },
          },
          createCourtSourceEntity(entityIds),
        ],
      }).replace(/</g, "\\u003c"),
    },
  ],
}));
</script>

<template>
  <main id="main-content" class="civic-reference-page" tabindex="-1">
    <header class="grid-container civic-container civic-page-intro">
      <h1>Methodology</h1>
      <p class="usa-intro">
        These records describe people who were killed or injured by gunfire in
        Philadelphia. Each row represents one person, and decisions about
        inclusion, classification, and mapping affect what the dashboard shows.
        This page documents those decisions and the limits of the data.
      </p>
    </header>

    <div class="grid-container civic-container civic-content-section">
      <article class="usa-prose civic-prose">
        <section aria-labelledby="record-scope">
          <h2 id="record-scope">What the dashboard includes</h2>
          <p>
            The main source is the
            <a
              href="https://opendataphilly.org/datasets/shooting-victims/"
              rel="external"
            >Philadelphia Police Department (PPD) shooting-victim dataset</a>.
            One incident may produce several records. The dashboard includes
            only rows marked <code>N</code> (“No”) in the source's
            officer-involved field. Officer-involved records remain available
            in the City source but are excluded from this project.
          </p>
          <p>
            The resulting counts describe the records in that dataset after this
            exclusion. They should not be read as a count of every incident
            involving a firearm or as a complete measure of firearm-related harm
            in Philadelphia.
          </p>
          <p>
            <a
              href="https://www.phillypolice.com/crime-data/crime-statistics/"
              rel="external"
            >PPD homicide statistics</a> cover all homicides citywide, whether or
            not a gun was involved. The dashboard reports them separately from
            shooting-victim records.
          </p>
          <p>
            For each police incident number, the project runs an automated search
            of the
            <a href="https://ujsportal.pacourts.us/CaseSearch" rel="external">
              Pennsylvania Unified Judicial System (UJS) public court portal</a
            >. It records whether the search returned a result but does not copy
            case details into the dashboard.
          </p>
        </section>

        <section class="civic-rule-section" aria-labelledby="pipeline">
          <h2 id="pipeline">From source to dashboard</h2>
          <p>
            Four stages prepare a new version of the data. The previously
            published version remains available unless every stage succeeds.
          </p>
          <ol class="usa-process-list civic-process-list">
            <li class="usa-process-list__item">
              <h3 class="usa-process-list__heading">Collect</h3>
              <p>
                On a schedule, the system retrieves shooting-victim records and
                homicide totals from their public sources and runs automated
                searches of the UJS public court portal. Geographic reference
                files are refreshed separately.
              </p>
            </li>
            <li class="usa-process-list__item">
              <h3 class="usa-process-list__heading">Prepare</h3>
              <p>
                The system standardizes dates and categories, checks and
                supplements coordinates, adds geographic fields, estimates
                street and block fields, and adds a court-search flag.
              </p>
            </li>
            <li class="usa-process-list__item">
              <h3 class="usa-process-list__heading">Check</h3>
              <p>
                Automated checks confirm required fields and valid output, then
                compare the newest date, record count, and fatal-record count
                with the current published version. A failed check stops
                publication.
              </p>
            </li>
            <li class="usa-process-list__item">
              <h3 class="usa-process-list__heading">Publish</h3>
              <p>
                Only a version that passes the checks replaces the dashboard's
                current data. The published files include source dates so readers
                can see how current each measure is.
              </p>
            </li>
          </ol>
        </section>

        <section class="civic-rule-section" aria-labelledby="transformations">
          <h2 id="transformations">Important transformations</h2>
          <div
            class="usa-table-container--scrollable"
            role="region"
            aria-labelledby="transformations"
            tabindex="0"
          >
            <table
              class="usa-table usa-table--borderless civic-table civic-table--wrap civic-table--two-column"
            >
              <caption>
                Changes made while preparing shooting-victim records
              </caption>
              <thead>
                <tr>
                  <th scope="col">Field or issue</th>
                  <th scope="col">Treatment</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th scope="row">Date and time</th>
                  <td>
                    Dates are standardized. A missing source time is stored as
                    midnight, so a midnight value should not always be
                    interpreted as the exact time. Records dated in the future at
                    the time of processing are excluded.
                  </td>
                </tr>
                <tr>
                  <th scope="row">Fatal outcome</th>
                  <td>
                    Accepted values from the PPD fatal field are converted to
                    true or false. Missing or unrecognized values stop
                    publication rather than being assigned a category.
                  </td>
                </tr>
                <tr>
                  <th scope="row">Race and ethnicity</th>
                  <td>
                    The source's Latino indicator is combined with the source
                    race field. Values outside the displayed categories are
                    grouped as Other/Unknown. The dashboard does not independently
                    verify these source fields.
                  </td>
                </tr>
                <tr>
                  <th scope="row">Age group</th>
                  <td>
                    Ages are grouped as younger than 18, 18–30, 31–45, older
                    than 45, or unknown.
                  </td>
                </tr>
                <tr>
                  <th scope="row">Point validation and backfill</th>
                  <td>
                    A source point is checked against Philadelphia's boundary.
                    If the point is missing or outside that boundary, the system
                    looks for a PPD crime-incident record with the same incident
                    number and uses its coordinates when available.
                  </td>
                </tr>
                <tr>
                  <th scope="row">Records without coordinates</th>
                  <td>
                    Records that still lack usable coordinates remain in totals
                    and downloadable files but do not appear on the point map or
                    in geographic summaries.
                  </td>
                </tr>
                <tr>
                  <th scope="row">Street and block fields</th>
                  <td>
                    The fields come from a nearest-street comparison. When the
                    comparison returns more than one candidate, the system
                    prefers a matching hundred-block number; otherwise it uses
                    the nearest segment. There is no maximum distance. These
                    fields are approximations, not verified addresses.
                  </td>
                </tr>
                <tr>
                  <th scope="row">Geographic districts</th>
                  <td>
                    ZIP code, neighborhood, police and City Council districts,
                    state legislative districts, and school catchment are joined
                    from public boundary files when a record has usable
                    coordinates. A boundary can be missing even when the point
                    can be mapped.
                  </td>
                </tr>
                <tr>
                  <th scope="row">Court search</th>
                  <td>
                    An automated search checks the UJS public portal using the
                    PPD incident number. The published field records only whether
                    that search returned a result at the time it was run.
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section class="civic-rule-section" aria-labelledby="quality-revisions">
          <h2 id="quality-revisions">Quality checks and revisions</h2>
          <p>
            Before a new version is published, automated checks reject empty
            source responses, missing required fields, unsupported outcome
            values, dates that move backward, and implausible changes in the
            total number of records or fatal records. Each output row must also
            match the expected field types.
          </p>
          <p>
            If a check fails, publication stops and the last version that passed
            remains available. These checks are designed to catch processing and
            source-format failures; they do not confirm every fact in an
            individual record.
          </p>
          <p>
            PPD can add, remove, or revise preliminary records after their first
            publication. A data-through date identifies the most recent event
            date in the version loaded by the dashboard. It does not guarantee
            that every event through that date has already been entered or will
            remain unchanged.
          </p>
        </section>

        <section class="civic-rule-section" aria-labelledby="known-limitations">
          <h2 id="known-limitations">How to interpret the data</h2>
          <ul class="usa-list">
            <li>
              The map and geographic totals are not population-adjusted rates.
              When comparing places, consider population, the time period, and
              records that could not be assigned usable coordinates.
            </li>
            <li>
              The dashboard does not routinely shift coordinates published by
              the source. Some locations are missing or imprecise, and a mapped
              point or estimated street field should not be treated as a verified
              address.
            </li>
            <li>
              Locations and reported demographic categories can help describe
              patterns in the records. They do not explain causes, neighborhood
              conditions, or a person's circumstances, and they should not be
              used to make claims about an individual.
            </li>
            <li>
              A positive court-search flag means only that the automated UJS
              search returned a result for the PPD incident number. It does not
              identify a defendant, establish a charge or disposition, or show
              how a court record relates to a particular victim. A negative flag
              means a completed search returned an explicit no-results response;
              it does not prove that no case exists. An unknown flag means the
              incident has not yet been checked or the search was unavailable,
              incomplete, or inconclusive. New incidents remain unknown until a
              later completed court search. None of these values reports a case
              outcome.
            </li>
          </ul>
        </section>

        <section class="civic-rule-section" aria-labelledby="reproduce-work">
          <h2 id="reproduce-work">Code and reproducibility</h2>
          <p>
            The
            <a
              href="https://github.com/nickhand/philly-gun-violence-dashboard"
              rel="external"
            >
              project repository</a
            > contains the processing code, schemas, and automated checks. The
            <NuxtLink to="/data">data page</NuxtLink> provides downloadable
            records and field definitions. To report a possible data or
            documentation problem, see
            <NuxtLink to="/about#corrections">Corrections</NuxtLink>.
          </p>
        </section>
      </article>
    </div>
  </main>
</template>
