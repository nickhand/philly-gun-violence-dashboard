<script setup lang="ts">
import {
  getPublicDownloadUrl,
  parsePublicDownloadManifest,
  type PublicDownloadManifestEntry,
} from "#shared/publicDownloads";

import {
  formatDataDate,
  formatIsoDateInTimeZone,
} from "~/utils/formatData";

const { apiBaseUrl, canonicalBaseUrl, downloadsBaseUrl } =
  useRuntimeConfig().public;
const { baseURL } = useRuntimeConfig().app;
const siteUrl = String(canonicalBaseUrl).replace(/\/$/, "");
const canonicalUrl = `${siteUrl}/data`;
const legacyPublicDownloadFilename = "philadelphia-shooting-victims.csv";
const geographicReferenceFiles = [
  {
    dataset: "zip_codes",
    label: "ZIP code boundaries",
    joinField: "zip_code",
    filename: "geography/philadelphia-zip-codes.geojson",
  },
  {
    dataset: "neighborhoods",
    label: "Neighborhood boundaries",
    joinField: "neighborhood",
    filename: "geography/philadelphia-neighborhoods.geojson",
  },
  {
    dataset: "police_districts",
    label: "Police district boundaries",
    joinField: "police_district",
    filename: "geography/philadelphia-police-districts.geojson",
  },
  {
    dataset: "council_districts",
    label: "City Council district boundaries",
    joinField: "council_district",
    filename: "geography/philadelphia-city-council-districts.geojson",
  },
  {
    dataset: "pa_house_districts",
    label: "Pennsylvania House district boundaries",
    joinField: "house_district",
    filename: "geography/philadelphia-pa-house-districts.geojson",
  },
  {
    dataset: "pa_senate_districts",
    label: "Pennsylvania Senate district boundaries",
    joinField: "senate_district",
    filename: "geography/philadelphia-pa-senate-districts.geojson",
  },
  {
    dataset: "school_catchments",
    label: "Elementary school catchment boundaries",
    joinField: "school_name",
    filename: "geography/philadelphia-elementary-school-catchments.geojson",
  },
  {
    dataset: "street_blocks",
    label: "Street blocks",
    joinField: "segment_id",
    filename: "geography/philadelphia-street-blocks.geojson",
  },
] as const;
const description =
  "View and download Philadelphia shooting-victim records, learn what the fields mean, check the dates covered, and understand the data's limits.";

const appBaseUrl = String(baseURL ?? "/").replace(/\/+$/, "");
const publicDownloadManifestEndpoint = `${appBaseUrl}/api/public-download-manifest`;
const downloadsConfigured = Boolean(
  getPublicDownloadUrl(
    downloadsBaseUrl,
    apiBaseUrl,
    "manifest.json",
  ),
);
const [metaRequest, manifestRequest] = await Promise.all([
  useDatasetMeta(),
  useFetch<unknown>(publicDownloadManifestEndpoint, {
    immediate: downloadsConfigured,
    key: "public-download-manifest",
    timeout: 6_000,
  }),
]);
const { data: meta, error: metaError } = metaRequest;
const { data: publicDownloadManifest } = manifestRequest;

const parsedPublicDownloadManifest = computed(() =>
  parsePublicDownloadManifest(publicDownloadManifest.value),
);
const invalidV2Manifest = computed(() => {
  const value = publicDownloadManifest.value;
  return (
    Boolean(value) &&
    typeof value === "object" &&
    (value as Record<string, unknown>).schema_version === 2 &&
    !parsedPublicDownloadManifest.value
  );
});

function v2DownloadEntry(
  id: string,
  kind: "records" | "geography",
): PublicDownloadManifestEntry | null {
  const manifest = parsedPublicDownloadManifest.value;
  if (manifest?.schemaVersion !== 2) return null;
  return (
    manifest.downloads.find(
      (entry) => entry.id === id && entry.kind === kind,
    ) ?? null
  );
}

function downloadUrl(path: string): string | null {
  return getPublicDownloadUrl(
    downloadsBaseUrl,
    apiBaseUrl,
    path,
  );
}

function legacyDownloadSize(path: string): number | null {
  const manifest = parsedPublicDownloadManifest.value;
  if (manifest?.schemaVersion !== 1) return null;
  return (
    manifest.downloads.find((entry) => entry.path === path)?.byteSize ?? null
  );
}

const publicRecordDownload = computed(() => {
  if (!downloadsConfigured || invalidV2Manifest.value) return null;
  const manifest = parsedPublicDownloadManifest.value;
  if (manifest?.schemaVersion === 2) {
    const entry = v2DownloadEntry("shooting_victims", "records");
    const url = entry ? downloadUrl(entry.path) : null;
    if (!entry || !url || !entry.mediaType.startsWith("text/csv")) return null;
    return {
      filename: entry.filename,
      path: entry.path,
      rowCount: entry.rowCount ?? null,
      sizeBytes: entry.byteSize,
      url,
    };
  }

  const url = downloadUrl(legacyPublicDownloadFilename);
  return url
    ? {
        filename: legacyPublicDownloadFilename,
        path: legacyPublicDownloadFilename,
        rowCount: null,
        sizeBytes: legacyDownloadSize(legacyPublicDownloadFilename),
        url,
      }
    : null;
});

const geographicReferenceDownloads = computed(() => {
  if (!downloadsConfigured || invalidV2Manifest.value) return [];
  const manifest = parsedPublicDownloadManifest.value;
  return geographicReferenceFiles.flatMap((item) => {
    if (manifest?.schemaVersion === 2) {
      const entry = v2DownloadEntry(item.dataset, "geography");
      const url = entry ? downloadUrl(entry.path) : null;
      if (
        !entry ||
        !url ||
        entry.dataset !== item.dataset ||
        entry.joinField !== item.joinField ||
        entry.mediaType !== "application/geo+json"
      ) {
        return [];
      }
      return [
        {
          ...item,
          filename: entry.filename,
          path: entry.path,
          sizeBytes: entry.byteSize,
          url,
        },
      ];
    }

    const url = downloadUrl(item.filename);
    const filename = item.filename.slice(item.filename.lastIndexOf("/") + 1);
    return url
      ? [
          {
            ...item,
            filename,
            path: item.filename,
            sizeBytes: legacyDownloadSize(item.filename),
            url,
          },
        ]
      : [];
  });
});

function publicDownloadContentSize(size: number | null): string | undefined {
  return size === null ? undefined : `${size} bytes`;
}

const publicDownloadDescription = computed(() => {
  const manifestCount = publicRecordDownload.value?.rowCount;
  const metaCount = meta.value?.shootings?.row_count;
  const count = manifestCount ?? metaCount;
  const hasCount =
    typeof count === "number" && Number.isInteger(count) && count >= 0;
  // The manifest is authoritative for the linked file. Use the API's date
  // only when its row count describes that same release.
  const throughDate =
    manifestCount === null ||
    manifestCount === undefined ||
    manifestCount === metaCount
      ? meta.value?.shootings?.data_through
      : undefined;
  const sentences = [
    "The CSV includes every available year and has one row for each person in the dashboard.",
  ];

  if (hasCount && throughDate) {
    sentences.push(
      `It contains ${count.toLocaleString("en-US")} records through ${formatDataDate(throughDate)}.`,
    );
  } else if (hasCount) {
    sentences.push(`It contains ${count.toLocaleString("en-US")} records.`);
  } else if (throughDate) {
    sentences.push(`It includes records through ${formatDataDate(throughDate)}.`);
  }

  return sentences.join(" ");
});
const citationAccessDate = useState(
  "data-citation-access-date",
  () => formatIsoDateInTimeZone(new Date(), "America/New_York"),
);
const citationAccessDateLabel = computed(() =>
  formatDataDate(citationAccessDate.value),
);
const citationRecordsThrough = computed(() =>
  meta.value?.shootings?.data_through
    ? `Shooting-victim records through ${formatDataDate(meta.value.shootings.data_through)}.`
    : "",
);
const citationText = computed(() =>
  [
    "Philadelphia Gun Violence Dashboard. “Data and downloads.”",
    citationRecordsThrough.value,
    "Data from the Philadelphia Police Department via OpenDataPhilly.",
    `Accessed ${citationAccessDateLabel.value}.`,
    `${canonicalUrl}.`,
  ]
    .filter(Boolean)
    .join(" "),
);

useSeoMeta({
  title: "Data and downloads | Philadelphia Gun Violence Dashboard",
  description,
  ogType: "website",
  ogTitle: "Philadelphia shooting-victim data and downloads",
  ogDescription: description,
  ogUrl: canonicalUrl,
  ogImage: `${siteUrl}/og-image.png`,
  twitterCard: "summary_large_image",
  twitterTitle: "Philadelphia shooting-victim data and downloads",
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
        "@graph": [
          {
            "@type": "WebPage",
            "@id": `${canonicalUrl}#webpage`,
            name: "Philadelphia shooting-victim data and downloads",
            url: canonicalUrl,
            description,
            mainEntity: { "@id": `${canonicalUrl}#dataset` },
          },
          {
            "@type": "Dataset",
            "@id": `${canonicalUrl}#dataset`,
            name: "Philadelphia shooting-victim data",
            description:
              "Public Philadelphia Police Department shooting-victim records prepared for the Philadelphia Gun Violence Dashboard. Each row represents one person reported by the Philadelphia Police Department as a shooting victim. The dashboard does not include records that the source identifies as officer-involved.",
            url: canonicalUrl,
            spatialCoverage: "Philadelphia, Pennsylvania",
            ...(meta.value?.shootings?.last_updated
              ? { dateModified: meta.value.shootings.last_updated }
              : {}),
            ...(meta.value?.shootings?.data_through
              ? {
                  temporalCoverage: `2015-01-01/${meta.value.shootings.data_through}`,
                }
              : {}),
            ...(publicRecordDownload.value
              ? {
                  distribution: {
                    "@type": "DataDownload",
                    name: "All Philadelphia shooting-victim records",
                    description: publicDownloadDescription.value,
                    contentUrl: publicRecordDownload.value.url,
                    contentSize: publicDownloadContentSize(
                      publicRecordDownload.value.sizeBytes,
                    ),
                    encodingFormat: "text/csv",
                  },
                }
              : {}),
            isBasedOn:
              "https://opendataphilly.org/datasets/shooting-victims/",
            isAccessibleForFree: true,
          },
          ...(geographicReferenceDownloads.value.length
            ? [
                {
                  "@type": "Dataset",
                  "@id": `${canonicalUrl}#geographic-reference-data`,
                  name: "Philadelphia geographic reference files used by the dashboard",
                  description:
                    "Current boundary and street-block GeoJSON files that match geographic join fields in the Philadelphia shooting-victim record download.",
                  url: `${canonicalUrl}#geographic-reference-downloads`,
                  spatialCoverage: "Philadelphia, Pennsylvania",
                  isAccessibleForFree: true,
                  distribution: geographicReferenceDownloads.value.map((item) => ({
                    "@type": "DataDownload",
                    name: item.label,
                    description: `GeoJSON reference file matched with the ${item.joinField} field.`,
                    contentUrl: item.url,
                    contentSize: publicDownloadContentSize(item.sizeBytes),
                    encodingFormat: "application/geo+json",
                  })),
                },
              ]
            : []),
        ],
      }).replace(/</g, "\\u003c"),
    },
  ],
}));
</script>

<template>
  <main id="main-content" class="civic-reference-page" tabindex="-1">
    <header class="grid-container civic-container civic-page-intro">
      <h1>Data and downloads</h1>
      <p class="usa-intro">
        View and download the Philadelphia Police Department shooting-victim
        records used in this dashboard. Learn what each row means, the latest
        date included, and what the records can and cannot show.
      </p>
    </header>

    <div class="grid-container civic-container civic-content-section">
      <article class="usa-prose civic-prose">
        <section aria-labelledby="about-records">
          <h2 id="about-records">About the records</h2>
          <p>
            The records come from the
            <a
              href="https://opendataphilly.org/datasets/shooting-victims/"
              rel="external"
            >Philadelphia Police Department (PPD) shooting-victim dataset</a>.
            Each row represents one person whom PPD reported as a shooting
            victim. One incident can have more than one row if more than one
            person was harmed. Records begin in 2015. The dashboard does not
            include records that PPD marks as officer-involved.<template
              v-if="meta?.shootings?.data_through"
            >
              The latest data in the dashboard runs through
              {{ formatDataDate(meta.shootings.data_through) }}.</template
            >
          </p>
          <p>
            Downloads contain shooting-victim records only. They do not include
            the citywide homicide totals on the
            <NuxtLink to="/stats">Statistics</NuxtLink> page.
          </p>
        </section>

        <section class="civic-rule-section" aria-labelledby="explore-download">
          <h2 id="explore-download">Download the records</h2>
          <div v-if="publicRecordDownload" class="civic-data-download">
            <p id="all-records-download-description">
              {{ publicDownloadDescription }}
            </p>
            <p>
              <CivicFileDownloadLink
                :href="publicRecordDownload.url"
                :filename="publicRecordDownload.filename"
                format="CSV"
                :size-bytes="publicRecordDownload.sizeBytes"
                variant="button"
                type="text/csv"
                aria-describedby="all-records-download-description"
              >Download all <span class="usa-sr-only">shooting-victim </span>records</CivicFileDownloadLink>
            </p>
          </div>

          <h3>Choose a year, filters, or another file type</h3>
          <p>
            Use the Explore page to download one year, download records that
            match your filters, or choose GeoJSON for mapping software. You can
            also view and map the same records there.
          </p>
          <p>
            <NuxtLink class="usa-button usa-button--outline" to="/">
              Explore the records
            </NuxtLink>
          </p>

          <h3>How to download a smaller set</h3>
          <ol class="usa-list">
            <li>
              Choose a year or choose All Years. Use the filters if you want a
              smaller set of records.
            </li>
            <li>
              Select the <strong>Download Data</strong> button in the Explore
              controls.
            </li>
            <li>
              Choose <strong>Filtered Data</strong> for the records that match
              your filters. Choose <strong>All Data</strong> to include every
              record for the selected year. If you selected All Years, All Data
              includes every available year.
            </li>
            <li>
              Choose CSV for a table you can open in a spreadsheet program.
              Choose GeoJSON for mapping software. If you choose
              <strong>Aggregate By</strong>, the download shows totals for each
              area instead of one row for each person.
            </li>
          </ol>
          <p>
            Area totals are counts, not rates. They do not adjust for
            differences in population. Consider population and other context
            before comparing areas. These records and maps cannot show the full
            harm shootings cause to people and communities or explain why they
            occur.
          </p>
        </section>

        <section class="civic-rule-section" aria-labelledby="source-records">
          <h2 id="source-records">Sources and dates</h2>
          <p>
            “Records through” shows the latest incident date in the data used
            by this dashboard. It does not mean every incident up to that date
            has been added. PPD and other source agencies may add or change
            records later.
          </p>
          <p>
            The dashboard checks PPD shooting-victim and homicide sources each
            day. PPD may not post new data on weekends or holidays, so the dates
            shown may stay the same. The automated search of UJS court records
            runs once a week.
          </p>
          <div
            class="usa-table-container--scrollable"
            role="region"
            aria-labelledby="source-records"
            tabindex="0"
          >
            <table
              class="usa-table usa-table--borderless civic-table civic-table--wrap civic-data-stacked-table civic-source-table"
            >
              <caption>
                Public sources and dates used by this dashboard
              </caption>
              <thead>
                <tr>
                  <th scope="col">Source</th>
                  <th scope="col">How it is used</th>
                  <th scope="col">Dates in this dashboard</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th scope="row">
                    <span
                      class="civic-data-stacked-table__label"
                      aria-hidden="true"
                    >Source:</span>
                    <a
                      href="https://opendataphilly.org/datasets/shooting-victims/"
                      rel="external"
                    >
                      PPD shooting victims through OpenDataPhilly
                    </a>
                  </th>
                  <td>
                    <span
                      class="civic-data-stacked-table__label"
                      aria-hidden="true"
                    >How it is used:</span>
                    Victim details, fatal or nonfatal outcome, incident date,
                    location, race, sex, and age.
                  </td>
                  <td>
                    <span
                      class="civic-data-stacked-table__label"
                      aria-hidden="true"
                    >Dates in this dashboard:</span>
                    <template v-if="meta?.shootings?.data_through">
                      Records through
                      {{ formatDataDate(meta.shootings.data_through) }}.
                    </template>
                    <template v-if="meta?.shootings?.last_updated">
                      <br v-if="meta?.shootings?.data_through" />
                      Dashboard updated
                      {{ formatDataDate(meta.shootings.last_updated) }}.
                    </template>
                    <template
                      v-if="
                        !meta?.shootings?.data_through &&
                        !meta?.shootings?.last_updated
                      "
                    >
                      Date unavailable.
                    </template>
                  </td>
                </tr>
                <tr>
                  <th scope="row">
                    <span
                      class="civic-data-stacked-table__label"
                      aria-hidden="true"
                    >Source:</span>
                    <a
                      href="https://www.phillypolice.com/crime-data/crime-statistics/"
                      rel="external"
                    >
                      PPD homicide statistics
                    </a>
                  </th>
                  <td>
                    <span
                      class="civic-data-stacked-table__label"
                      aria-hidden="true"
                    >How it is used:</span>
                    All homicides citywide, whether or not a gun was involved.
                  </td>
                  <td>
                    <span
                      class="civic-data-stacked-table__label"
                      aria-hidden="true"
                    >Dates in this dashboard:</span>
                    <template v-if="meta?.homicides?.data_through">
                      Records through
                      {{ formatDataDate(meta.homicides.data_through) }}.
                    </template>
                    <template v-else>Date unavailable.</template>
                  </td>
                </tr>
                <tr>
                  <th scope="row">
                    <span
                      class="civic-data-stacked-table__label"
                      aria-hidden="true"
                    >Source:</span>
                    <a
                      href="https://ujsportal.pacourts.us/CaseSearch"
                      rel="external"
                    >
                      Pennsylvania public court records
                    </a>
                  </th>
                  <td>
                    <span
                      class="civic-data-stacked-table__label"
                      aria-hidden="true"
                    >How it is used:</span>
                    Results from an automated search of public court records
                    using the police incident number.
                  </td>
                  <td>
                    <span
                      class="civic-data-stacked-table__label"
                      aria-hidden="true"
                    >Dates in this dashboard:</span>
                    <template v-if="meta?.courts?.last_updated">
                      Court search checked
                      {{ formatDataDate(meta.courts.last_updated) }}.
                    </template>
                    <template v-else>Date unavailable.</template>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-if="metaError" role="status">
            Dates could not be loaded. Source links remain available.
          </p>
        </section>

        <section class="civic-rule-section" aria-labelledby="using-records">
          <h2 id="using-records">What to consider before using the data</h2>
          <ul class="usa-list">
            <li>
              Some locations are missing or imprecise. Records without usable
              coordinates remain in totals and downloads but do not appear as
              points on the map. A mapped point should not be treated as an
              exact address.
            </li>
            <li>
              A positive court-search flag means the automated search found a
              result for the police incident number in the public court portal.
              A negative flag means a completed search returned an explicit
              no-results response; it does not prove that no case exists. An
              unknown flag means the search was unavailable, incomplete, or
              inconclusive. None of these values proves that someone was
              charged, shows how a case ended, or establishes how a record
              relates to a victim.
            </li>
          </ul>
          <p>
            Read the <NuxtLink to="/methodology">Methodology</NuxtLink> for the
            full details on what is included, how the data is prepared and
            checked, and its limits.
          </p>
        </section>

        <section class="civic-rule-section" aria-labelledby="record-fields">
          <h2 id="record-fields">Field guide</h2>
          <p>
            CSV and GeoJSON downloads with one row per person include fields
            from the source and fields created while preparing the data. The
            table lists the key fields and their meanings.
          </p>
          <div
            class="usa-table-container--scrollable"
            role="region"
            aria-labelledby="record-fields"
            tabindex="0"
          >
            <table
              class="usa-table usa-table--borderless civic-table civic-table--wrap civic-table--two-column civic-data-stacked-table"
            >
              <caption>
                Key fields in record-level downloads
              </caption>
              <thead>
                <tr>
                  <th scope="col">Field</th>
                  <th scope="col">Meaning</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th scope="row"><code>dc_key</code></th>
                  <td>
                    Police incident number. The same number may appear in more
                    than one victim row.
                  </td>
                </tr>
                <tr>
                  <th scope="row"><code>date</code></th>
                  <td>
                    Source incident date and time, stored in a standard format.
                  </td>
                </tr>
                <tr>
                  <th scope="row"><code>fatal</code></th>
                  <td>Whether PPD marks the victim record as fatal.</td>
                </tr>
                <tr>
                  <th scope="row"><code>age</code> and <code>age_group</code></th>
                  <td>Reported age, when available, and a derived age group.</td>
                </tr>
                <tr>
                  <th scope="row"><code>race</code> and <code>sex</code></th>
                  <td>
                    Race and sex as reported in the source data. The displayed
                    race value also uses the source's Latino field.
                  </td>
                </tr>
                <tr>
                  <th scope="row"><code>latitude</code> and <code>longitude</code></th>
                  <td>
                    Usable coordinates for the record, when available. GeoJSON
                    stores these as a map point.
                  </td>
                </tr>
                <tr>
                  <th scope="row">
                    <code>street_name</code>, <code>block_number</code>, and
                    <code>segment_id</code>
                  </th>
                  <td>
                    Street and block values added while preparing the data.
                    These are estimates, not exact addresses.
                  </td>
                </tr>
                <tr>
                  <th scope="row">Geographic districts</th>
                  <td>
                    ZIP code, neighborhood, police and City Council districts,
                    state legislative districts, and school catchment when a
                    location can be matched to an area.
                  </td>
                </tr>
                <tr>
                  <th scope="row"><code>has_court_case</code></th>
                  <td>
                    <code>true</code> means the automated court-portal search
                    returned a result for the PPD incident number.
                    <code>false</code> means a completed search returned an
                    explicit no-results response. A blank CSV value or GeoJSON
                    <code>null</code> means the search was unavailable,
                    incomplete, or inconclusive. This field does not establish
                    how a record relates to a victim or report a case outcome.
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <section
            v-if="geographicReferenceDownloads.length"
            aria-labelledby="geographic-reference-downloads"
          >
            <h3 id="geographic-reference-downloads">
              Download map reference files
            </h3>
            <p>
              Each file below is GeoJSON, a common format for mapping software.
              Match the field listed in the shooting-victim CSV to the field with
              the same name in the map file. Mapping software often calls this a
              join. Blank values will not match a shape.
            </p>
            <p>
              These files match the current dashboard download; they are not
              historical boundary files. Download the CSV and map files together
              because the dashboard-created street-block <code>segment_id</code>
              may change when street data are rebuilt.
            </p>
            <div
              class="usa-table-container--scrollable"
              role="region"
              aria-labelledby="geographic-reference-downloads"
              tabindex="0"
            >
              <table
                class="usa-table usa-table--borderless civic-table civic-table--wrap civic-table--two-column civic-data-stacked-table civic-reference-download-table"
              >
                <caption>
                  Map reference downloads and their matching record fields
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Reference file</th>
                    <th scope="col">Match this field</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="reference in geographicReferenceDownloads"
                    :key="reference.joinField"
                  >
                    <th scope="row">
                      <CivicFileDownloadLink
                        :href="reference.url"
                        :filename="reference.filename"
                        format="GeoJSON"
                        :size-bytes="reference.sizeBytes"
                        type="application/geo+json"
                      >Download {{ reference.label }}</CivicFileDownloadLink>
                    </th>
                    <td>
                      <span
                        class="civic-data-stacked-table__label"
                        aria-hidden="true"
                      >
                        Match this field:
                      </span>
                      <code>{{ reference.joinField }}</code>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>
        </section>

        <section class="civic-rule-section" aria-labelledby="cite-dashboard">
          <h2 id="cite-dashboard">Citing this dashboard</h2>
          <p>
            When citing a number, map, or download, include the Philadelphia Gun
            Violence Dashboard, the measure and time period, the source's
            “records through” date, the date you accessed the page, and the page
            URL. Name the Philadelphia Police Department as the original
            publisher when appropriate.
          </p>
          <blockquote class="civic-citation-block" :cite="canonicalUrl">
            <p>
              Philadelphia Gun Violence Dashboard. “Data and downloads.”
              <template v-if="citationRecordsThrough">
                {{ citationRecordsThrough }}
              </template>
              Data from the Philadelphia Police Department via OpenDataPhilly.
              Accessed {{ citationAccessDateLabel }}.
              <a :href="canonicalUrl">{{ canonicalUrl }}</a>.
            </p>
          </blockquote>
          <div class="civic-citation-copy">
            <CivicCopyButton
              :text="citationText"
              label="Copy citation"
              success-message="Citation copied."
              error-message="Could not copy. Select and copy the citation manually."
            />
          </div>
        </section>

        <section class="civic-rule-section" aria-labelledby="terms-methods">
          <h2 id="terms-methods">Licensing and documentation</h2>
          <p>
            The project's code is available under the
            <a
              href="https://github.com/nickhand/philly-gun-violence-dashboard/blob/main/LICENSE"
              rel="external"
            >
              MIT License</a
            >. The MIT License covers the project code. It does not cover the
            source records. City and court records are still governed by their
            publishers' rules, including the
            <a href="https://ujsportal.pacourts.us/Home/Terms" rel="external">
              UJS terms</a
            >.
          </p>
          <p>
            The <NuxtLink to="/methodology">Methodology</NuxtLink> explains how
            the records are prepared. The
            <NuxtLink to="/about#corrections">About page</NuxtLink> explains
            how to report a possible error.
          </p>
        </section>
      </article>
    </div>
  </main>
</template>

<style scoped>
.civic-reference-download-table.civic-table--two-column th:first-child {
  width: 55%;
}

.civic-citation-block {
  margin: 1.5rem 0 0.85rem 1rem;
  padding: 0.2rem 0 0.2rem 1rem;
  border-left: 0.25rem solid var(--civic-color-rule);
  color: var(--civic-color-ink-muted);
}

.civic-citation-block p {
  margin: 0;
}

.civic-citation-copy {
  margin-left: 2.25rem;
}

.civic-data-stacked-table__label {
  display: none;
}

@media (max-width: 35.99em) {
  .civic-data-stacked-table {
    display: block;
    min-width: 0;
    table-layout: auto;
  }

  .civic-data-stacked-table caption {
    display: block;
  }

  .civic-data-stacked-table thead {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
    border: 0;
  }

  .civic-data-stacked-table tbody,
  .civic-data-stacked-table tbody tr,
  .civic-data-stacked-table tbody th,
  .civic-data-stacked-table tbody td {
    display: block;
    width: 100%;
  }

  .civic-data-stacked-table.civic-table--two-column tbody th:first-child {
    width: 100%;
  }

  .civic-data-stacked-table tbody tr {
    padding: 0.8rem 0;
    border-bottom: 1px solid var(--civic-color-rule-subtle);
  }

  .civic-data-stacked-table tbody th,
  .civic-data-stacked-table tbody td {
    padding-right: 0.5rem;
    padding-left: 0.5rem;
    border: 0;
  }

  .civic-data-stacked-table tbody th {
    padding-top: 0;
    padding-bottom: 0.2rem;
  }

  .civic-data-stacked-table tbody td {
    padding-top: 0.2rem;
    padding-bottom: 0;
  }

  .civic-data-stacked-table code {
    overflow-wrap: normal;
    word-break: normal;
    white-space: nowrap;
  }

  .civic-data-stacked-table__label {
    display: inline;
    margin-right: 0.25rem;
    color: var(--civic-color-ink-subtle);
    font-size: 0.88rem;
  }

  .civic-reference-download-table tbody th {
    padding-bottom: 0.35rem;
  }

  .civic-source-table tbody th {
    padding-bottom: 0.35rem;
    font-weight: 600;
  }

  .civic-source-table tbody td + td {
    padding-top: 0.45rem;
  }
}
</style>
