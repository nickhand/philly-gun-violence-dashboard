# Learning Nuxt through this migration

The migration introduces Nuxt only where the current product needs it. The
standing rule is: **if it can be simpler, simplify it.**

Until legacy explorer parity is complete, each slice translates an existing
behavior. Additions and product redesigns require a separate decision.

## Phase 1: shell and About page

The first slice lives beside the production Vue/Vite app. Run it with
`npm run dev:nuxt`, then open
`http://localhost:3000/philly-gun-violence-map/about`.

### What Nuxt is doing

- `app/app.vue` is the application entry point.
- `app/layouts/default.vue` provides shared header and footer chrome.
- `app/pages/about.vue` automatically becomes the `/about` route.
- The About page runs on the server for the initial request, including its API
  request, headings, prose, source table, and metadata.
- `useSeoMeta` and `useHead` place route-specific metadata in the initial HTML.
- `runtimeConfig.public` provides values that are safe on both the server and
  client, such as the public API and canonical site URLs.
- The local `layers/civic-ui` layer supplies the USWDS Sass foundation, Public
  Sans, theme tokens, and shared site chrome.

### What this replaces

In the Vite app, routing, head management, and crawler snapshots are separate
pieces. Nuxt supplies the route and initial HTML from the page file itself, so
the visible page and crawler response no longer need parallel implementations.

### Server and browser boundary

The metadata request uses `useFetch` with server rendering enabled. Nuxt puts
the result into the rendered HTML and hydration payload, so the browser does
not repeat the request when it takes over. If the API is unavailable, the page
still renders its complete explanatory content and clearly marks live status as
unavailable.

There is no browser-only plugin in this slice. The About page does not need one.
MapLibre and DOM-driven charts will receive explicit client boundaries when
the explorer is migrated.

### How to verify the slice

```bash
npm run build:nuxt
npm run type-check:nuxt
```

The acceptance check is more than “the page hydrates”: requesting `/about`
directly must return its H1, explanation, source links, and canonical metadata
in the response HTML before JavaScript executes.

## Phase 2: authoritative Statistics page

The second slice adds `app/pages/stats.vue`, which Nuxt turns into `/stats`.
FastAPI exposes the same cached `StatsSnapshot` used by its existing HTML page
at `/stats.json`, so the Nuxt page does not duplicate aggregation logic.

### `useAsyncData` and `$fetch`

The page passes a `$fetch` request to `useAsyncData`. On a direct request, Nuxt
runs it on the server, renders the figures and annual table into the HTML, and
serializes the result into the hydration payload. The browser reuses that
payload instead of requesting the snapshot again during hydration.

On client-side navigation from About to Statistics, the same page code runs in
the browser and requests the API directly. That is why the API allows the Nuxt
development origin on port 3000 even though direct SSR requests are not subject
to browser CORS rules.

### Error boundary for data, not the whole page

If the snapshot cannot be loaded, the route still renders its title,
definitions, and source links. The current figures are replaced by an honest
unavailable state with a retry button; missing values are never displayed as
zero. This is ordinary page state, so it does not need a plugin, store, or
custom Nuxt error route.

### Metadata from the visible record

The title, description, source dates, and JSON-LD are derived from the same
snapshot as the visible page. The API JSON response is marked `noindex`; the
human-readable Nuxt route owns the canonical search result.

### How to verify the slice

Run the local API, then build and preview Nuxt against it:

```bash
cd packages/api
just api-dev

cd ../../frontend
NUXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000 npm run build:nuxt
NUXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000 npm run preview:nuxt
```

Request `/philly-gun-violence-map/stats` directly and confirm that the response
HTML contains the current total, fatal/nonfatal labels, source dates, annual
table, canonical URL, and structured data before JavaScript runs.

## Phase 3: content routes and crawler infrastructure

`app/pages/methodology.vue` and `app/pages/data.vue` become server-rendered
`/methodology` and `/data` routes through Nuxt's file-based routing. Their
headings, explanations, source links, metadata, and structured data are in the
initial response rather than separate crawler-only snapshots. The Data page
uses the dataset-metadata composable for its source dates. About stays evergreen
and makes no data request.

### Sitemap, robots, and errors

`@nuxtjs/sitemap` discovers the public page routes. The sitemap deliberately
omits `lastmod`: a source's data-through date describes record coverage, not the
time a page was last changed. Add `lastmod` only when the application exposes an
authoritative publication timestamp. With no dynamic source, `zeroRuntime`
prerenders the sitemap instead of adding a request-time server route.

The short `public/robots.txt` file is served beneath Nuxt's configured app base
and points to the canonical subpath sitemap. A custom `app/error.vue` keeps the
site chrome on errors; missing routes retain an HTTP 404 response, receive
`noindex, nofollow`, and do not claim a canonical URL.

### Origin, canonical URL, and app base

These settings are related but serve different purposes:

- `NUXT_PUBLIC_SITE_URL` is the origin only, such as
  `https://www.nickhand.dev`; the sitemap module uses it to form absolute URLs.
- `NUXT_PUBLIC_CANONICAL_BASE_URL` is the public URL of this site, including
  `/philly-gun-violence-map`; pages use it for canonicals, social metadata, and
  structured data.
- `NUXT_APP_BASE_URL` is the router, server, and asset mount path. It normally
  matches the canonical base pathname and includes leading and trailing slashes.
- `NUXT_PUBLIC_API_BASE_URL` is the separate FastAPI origin.

Keeping the origin and canonical base distinct prevents a subpath from being
applied twice by the sitemap module.

### How to verify the slice

```bash
npm run build:nuxt
npm run test:nuxt:seo
```

The SEO test starts the built Nitro server and a deterministic API stub, then
inspects raw HTTP responses without running browser JavaScript. It checks the
four content pages, base-prefixed links, canonicals, canonical sitemap entries,
the static robots policy and AI-readable guide, crawler-only duplicate guards,
and the 404 status and metadata.

This is still a parallel migration. The current Netlify rules serve the legacy
About snapshot, proxy Statistics and the sitemap to FastAPI, and turn other
subpath routes into the Vite shell with status 200. Those rules must be replaced
as one explicit deployment cutover before these Nuxt responses become
production behavior.

Finally, a robots file under `/philly-gun-violence-map/robots.txt` does not
control the entire `www.nickhand.dev` host. The host-level `/robots.txt` remains
the responsibility of the main site and should advertise this subsite's sitemap
when traffic is cut over.

## Phase 4: server-rendered dashboard shell

The Nuxt root route now renders the dashboard's heading, current figures,
source dates, year control, and supporting links instead of redirecting to the
legacy application. This is the dashboard shell, not the full interactive map
port.

### One shared statistics request

`useStatsSnapshot` owns the typed `/stats.json` request used by both the root
route and Statistics page. On a direct request, Nuxt fetches the snapshot on
the server and includes it in the HTML and hydration payload. Sharing the
composable keeps the two pages on the same API contract without adding another
endpoint or duplicating aggregation in Vue.

If that request fails, the route still returns its heading, explanation, and
links to Statistics, Data, and Methodology. It labels current figures and years
as unavailable and never substitutes zero for missing data. A retry is an
ordinary client interaction after hydration.

### Progressively enhanced filters

The first Vuetify-free control is a labeled native year select inside one `GET`
form. Submitting it requests the same route with query state such as
`?year=2024`, so year selection works before hydration and without JavaScript.
Missing, repeated, or invalid values fall back to the newest year.

The browser map controls preserve the legacy comma-separated `layers` grammar.
They support point locations, density, their combined view,
`hot-spots-by-street-block` and one of the seven legacy boundary aggregations.
Toggleable layers keep a stable order, boundary views are mutually exclusive,
and an explicit empty value preserves a map with no shooting-data layer. Point
and density modes reuse the same filtered GeoJSON source and selected-view
request.

The browser-only map adds an optional `map=zoom/latitude/longitude` value, for
example `map=12.76/39.97240/-75.14142`. The parser accepts only finite decimal
coordinates and the map's supported zoom range. Invalid or repeated values use
the Philadelphia default instead. After the map is ready, moving it replaces
the current URL with a rounded view value; it does not create a browser-history
entry for every pan. Submitting the ordinary filter form intentionally resets
the viewport, keeping the no-JavaScript form free of hidden client state.
If navigation changes only the map value, the client applies that view to the
existing MapLibre instance. Browser back/forward therefore does not refetch or
reparse the selected year's records.

These query strings describe an explorer view; they are not separate content
pages. Every year selection therefore keeps the queryless dashboard URL as its
canonical. This also avoids generating thin indexable pages for filter states.

The URL is the durable source of truth for these shareable choices, including
the initial map view and display mode. Temporary loading and map-lifecycle state
stays inside the client component. Charts, downloads, the address marker, and
overlays all consume the same selected-view rows owned by one parent, so adding
Pinia would currently duplicate a boundary rather than simplify one.

That matches the legacy division of responsibility: `useArquero` and
`useHistograms` own filter and histogram state locally, while Pinia stores
longer-lived shootings, homicides, and boundary data. The Nuxt port instead
lifts the selected view's rows into `DashboardExplorer.client.vue` and shares
the filtered result through props and small pure utilities. Pinia remains an
option only if a later capability creates genuinely independent consumers or
cross-route state.

### A small browser-only map boundary

`DashboardPointMap.client.vue` is the browser-only map boundary. Nuxt never
renders this component on the server. The explorer fetches `/shootings/meta`,
follows the manifest's versioned NDJSON URL for one selected year, and follows
all dated year URLs for All Years. It then lazily imports MapLibre and the
existing dark basemap. The server neither fetches detailed records nor
serializes them into the page.

The API keeps only its current data version. If the version changes between the
manifest and NDJSON requests, the loader refreshes both once. A second mismatch
becomes an honest error instead of an unbounded retry.

`ClientOnly` supplies the fixed map-and-sidebar footprint in the initial HTML.
For All Years, the loader requests every dated feed atomically and retries the
manifest plus all rows once if any version becomes stale. Browser filters
update the map and the two dynamic header counts; the sidebar separately
reports mapped locations and records missing coordinates. Point, density,
street-block, and boundary displays use that source plus only the requested
overlay geometry. The city outline is a static reference layer. Point hover
opens a compact incident tooltip and click pins it. Its date, time, location,
demographics, incident number, and court-match flag are normalized before they
enter GeoJSON and are built with DOM text nodes rather than raw tooltip HTML.
The street note repeats the nearest-centerline limitation.

### Existing dashboard filters

The browser-only explorer now owns the selected-view request instead of the map
component. It retains those rows only in browser memory and passes a summarized,
filtered record set to the map. The Nuxt explorer now reproduces Fatal shootings
only, Has public court record, Gender, Race/Ethnicity, Day of Week, Time of Day,
Date, and Age. Category filters keep the legacy individual checkbox, “only,” and
reset behavior. Age retains “Exclude unknown values.” Each range histogram
respects every other active filter while ignoring its own current range. Filter
changes update counts and the existing MapLibre source without refetching the
year or reconstructing the map.

These browser filter values deliberately stay local, matching the legacy app;
they are not new query parameters. The server-rendered total and no-JavaScript
fallback remain the unfiltered selected view.

The same filtered rows drive the five legacy view-only breakdowns: Outcome,
Public Court Record, Gender, Race/Ethnicity, and Age Group. Accessible HTML/CSS
bars replace the old chart lifecycle without adding a chart dependency or a new
interaction. The download modal exports filtered or full selected-view records
as CSV or GeoJSON and can aggregate by the same seven boundaries.
Unmapped rows remain in raw exports with null GeoJSON geometry.

Address search retains the bounded Philadelphia autocomplete, keyboard
combobox behavior, and temporary map marker. Boundary geometry and filtered
street segments load only when requested; failures leave the base map, summary,
filters, charts, and downloads intact.

### How to verify the slice

```bash
npm run type-check:nuxt
npm run build:nuxt
npm test
npm run test:nuxt:seo
npm run test:e2e:nuxt
```

Request the dashboard directly with no query, a valid year, `All Years`, each
display mode, a valid map view, and invalid or repeated
values. Its initial HTML should contain the selected controls and summary, one
queryless canonical URL, ordinary internal links, and the honest unavailable
state when the statistics API fixture fails. The initial server asset graph
must not contain MapLibre; a browser request for one year loads only that
year's manifest-provided NDJSON feed, while All Years loads every dated feed.
Unit tests cover layer and map-view
parsing, heat, point, street, boundary, city, and address-layer behavior, URL
replacement, and listener cleanup without requiring WebGL or tile requests.
They also cover boolean, category, range, “only,” reset, cross-filtered
histogram, unknown-age, synchronized category charts, raw and aggregated
downloads, one-request ownership, reactive map-source updates, retries, and
request cleanup. Point-popup tests cover hover, pinned click, cleanup, and the
safe text-only detail builder.

## Phase 6 preparation: one application, another Nitro target

Nuxt separates the application from the server runtime that delivers it. The
ordinary `npm run build:nuxt` command produces the Node/Nitro output used by the
raw SSR acceptance suite. Setting `NITRO_PRESET=cloudflare_module` builds those
same routes, components, server handlers, and assets for a Cloudflare Worker.
No second frontend or platform-specific page implementation is needed.

The repository wraps that preset in one bounded command:

```bash
npm run build:nuxt:cloudflare
```

That command also forces `NUXT_PUBLIC_INDEXABLE=false`. The application emits
`noindex, nofollow` metadata and Nitro emits the matching `X-Robots-Tag` policy
for the base path. A small post-build check verifies the Worker entry, nested
base-path assets, explicit staging Wrangler configuration, observability, and
the crawler policy. Keeping this check next to the build makes a missing asset
or accidentally indexable preview fail before deployment.

`wrangler.jsonc` is intentionally a staging configuration: its Worker name ends
in `-staging`, it defines no production route or custom domain, and no deploy
script is installed. Nitro is also told not to generate a hidden Wrangler
redirect file. Configuration stays visible and reviewable at the project root.

This is build portability, not a hosting cutover. The next deployment step is a
separately approved staging canary with runtime SSR, API failure, cache,
observability, and crawler checks. Production routing changes only after that
canary is stable; rollback returns the public route to the existing Netlify
site without moving or modifying the FastAPI service.
