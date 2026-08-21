# Philadelphia Gun Violence Dashboard - Frontend

Interactive dashboard visualizing gun violence data in Philadelphia with maps,
charts, and filtering capabilities.

The canonical production frontend is the Nuxt 4 application in `app/`, mounted
at `/philly-gun-violence-map/` on Cloudflare Workers. The former Vue/Vite
application in `src/` remains runnable only as a temporary Netlify rollback
artifact; keep its public data and terminology contracts aligned until that
rollback window closes.

## Tech Stack

- **Framework:** Nuxt 4 + Vue 3 Composition API
- **Language:** TypeScript
- **UI:** Local `civic-ui` Nuxt layer backed by USWDS; Vuetify remains only in
  the legacy rollback app
- **Mapping:** MapLibre GL
- **Charts:** D3.js
- **Data Filtering:** Arquero
- **State Management:** URL state and local Nuxt composables; Pinia remains in
  the legacy explorer only
- **Build Tool:** Nuxt/Nitro and Vite

## Prerequisites

- Node.js 22.19+, 24.11+, or 26+
- npm 11.18.0 (the exact version in `packageManager`)

## Getting Started

```bash
# Reproduce the locked dependency graph
npm ci

# Start the canonical Nuxt application
npm run dev:nuxt

# Type-check and build Nuxt
npm run type-check:nuxt
npm run build:nuxt

# Validate the retained legacy rollback bundle
npm run build:legacy
npm run check:bundle
```

The Nuxt development server runs at
`http://localhost:3000/philly-gun-violence-map/`.

### Cloudflare release artifacts

```bash
# Build and validate a non-indexable Cloudflare staging artifact
npm run build:nuxt:cloudflare:staging

# Build and validate the indexable production artifact without deploying it
npm run build:nuxt:cloudflare:production
```

Open `http://localhost:3000/philly-gun-violence-map/` for the dashboard shell.
The content routes are `/about`, `/stats`, `/methodology`, and `/data`. Nuxt
uses the public API by default; set
`NUXT_PUBLIC_API_BASE_URL=http://localhost:8000` to use a local API. See
[`NUXT_LEARNING.md`](./NUXT_LEARNING.md) records the concepts introduced in each
completed migration slice.

The shell uses the same server-rendered statistics snapshot as `/stats`. Its
year selector uses a regular `GET` form, so URLs such as `?year=2024` remain
useful without JavaScript; browser layer controls add values such as
`layers=heat-map`, and every filtered URL keeps the queryless dashboard
canonical. For a single year, the browser loads that year's versioned NDJSON;
All Years loads every dated feed from one manifest before committing the view.
MapLibre remains lazy and client-only.
It includes point, density, street-block hot-spot, and mutually exclusive
boundary aggregation layers plus the static city outline. Moving the map adds a
validated, rounded view such as
`map=12.76/39.97240/-75.14142` to the shareable URL without adding a history
entry for every movement. Back/forward view changes reuse the existing map and
record data. After the selected view loads, the legacy Fatal shootings
only, Court search returned a result, Gender, Race/Ethnicity, Day of Week, Time of Day,
Date, and Age filters run entirely in the browser. The range filters retain
their cross-filtered histograms, and Age keeps the legacy “Exclude unknown
values” choice. The same filtered rows update the five category breakdowns and
filtered/full CSV or GeoJSON downloads, including optional boundary
aggregation. The bounded Philadelphia address search and temporary map marker
are also client-only. Hovering a point shows a compact incident tooltip;
clicking pins it. Tooltip values are normalized and inserted as text, including
the honest nearest-street limitation, rather than passed through the legacy
raw-HTML formatter.

Before detailed rows hydrate, the existing five category charts render the
matching unfiltered counts from `/stats.json`. This keeps their content present
in raw HTML for crawlers without adding another visible dashboard section; the
browser replaces those counts from the same detailed rows as soon as filtering
is available. Court-run coverage text is shown only when `/meta` proves the
full-run publication contract and distinguishes terminal coverage from searches
that remained inconclusive.

The completed migration preserved the legacy capabilities; future product
features still require their own decision and regression coverage.

## Testing

```bash
# Unit and component tests
npm test

# Unit tests with enforced coverage thresholds
npm run test:coverage

# Build Nuxt, then inspect its raw SSR, sitemap, robots, and 404 responses
npm run build:nuxt
npm run test:nuxt:seo

# Hydrated Nuxt explorer in desktop and mobile Chromium
npm run test:e2e:nuxt

# Legacy Vite browser suite retained during cutover
npm run test:e2e

# WCAG 2.1 A/AA automated checks
npm run test:e2e:a11y

# Production Lighthouse audit with performance thresholds
npm run test:lighthouse

# Dependency advisories that meet the CI severity threshold
npm run audit:dependencies
```

The Nuxt browser gate uses a deterministic cross-origin API fixture and creates
a real MapLibre map; only third-party basemap and geocoder traffic is stubbed.
It covers desktop browsers, Pixel-sized Chromium, and an iPhone WebKit profile
without depending on production data. The legacy Vite browser suite remains a
required rollback gate. See
[`ACCESSIBILITY.md`](./ACCESSIBILITY.md) for the manual WCAG 2.1 AA evaluation
checklist.

## Bundle budgets

The production build emits a Vite manifest and `npm run check:bundle` enforces
gzip budgets for the initial app shell, the asynchronously loaded map, their
combined core experience, and deferred analytics. The check also prevents the
full Material Design icon font from being bundled again. Lighthouse runs three
desktop audits against deterministic local data and a local map style. The
direct Lighthouse runner stores HTML and JSON for every run plus a machine-
readable summary, then enforces median scores and Core Web Vitals-oriented
thresholds.

## Project Structure

```
app/                       # Canonical Nuxt pages, components, and utilities
layers/civic-ui/           # Reusable civic UI Nuxt layer
server/                    # Same-origin server endpoints used during SSR
tests/                     # Unit, SSR/SEO, accessibility, and browser contracts
src/                       # Legacy Vite rollback application
├── app/                    # Application setup
│   ├── components/         # Shared layout components (AppNavbar, AppFooter)
│   ├── router.ts           # Vue Router configuration
│   └── vuetify.ts          # Vuetify theme and plugin setup
├── features/               # Feature modules
│   ├── charts/             # D3-based chart components
│   │   └── components/     # ChartDashboard, BarChart, etc.
│   └── map/                # MapLibre-based mapping
│       ├── components/     # MappingDashboard, FilterableMap, etc.
│       └── composables/    # Map-related hooks (useAggregation, etc.)
├── pages/                  # Page components
│   ├── AboutPage.vue       # About page (lazy-loaded)
│   ├── DashboardPage.vue   # Main dashboard
│   └── components/         # Page-specific components
├── shared/                 # Shared utilities
│   ├── api/                # API client functions
│   └── stores/             # Legacy Pinia stores (shootings, etc.)
├── types/                  # TypeScript type definitions
└── main.ts                 # Application entry point
```

## Key Features

### Interactive Map
- Point locations of shooting incidents
- Heat map visualization
- Aggregated views by district, neighborhood, ZIP code, etc.
- Street-level hot spot analysis

### Filtering
- Filter by date range, time of day, age
- Filter by victim demographics (race, gender)
- Filter by incident type (fatal/nonfatal)
- Filter by automated court-search result (Yes, No, or Unknown)

### Charts
- Breakdowns by time, location, and demographics
- Synchronized filtering across map and charts

## Environment Variables

Create a `.env` file for local development:

```env
VITE_API_BASE_URL=http://localhost:8000
VITE_POSTHOG_KEY=              # Optional: PostHog analytics key
```

For the legacy rollback build, `VITE_API_BASE_URL` points to the Fly.io API
deployment.

The canonical Nuxt app supports:

```env
NUXT_PUBLIC_API_BASE_URL=http://localhost:8000
NUXT_PUBLIC_DOWNLOADS_BASE_URL=https://data.example.org/downloads
NUXT_PUBLIC_SITE_URL=https://www.nickhand.dev
NUXT_PUBLIC_CANONICAL_BASE_URL=https://www.nickhand.dev/philly-gun-violence-map
NUXT_APP_BASE_URL=/philly-gun-violence-map/
NUXT_PUBLIC_INDEXABLE=true
```

The tracked default for `NUXT_PUBLIC_DOWNLOADS_BASE_URL` is
`https://d2cemhjkwenjmb.cloudfront.net`; override it only for an intentional
download-host migration. It must point to public files, not the dashboard's
internal application service. The public `manifest.json` supplies the current
content-addressed file paths, exact sizes, checksums, and record/feature counts.
Nuxt can still read the legacy schema-v1 stable paths during the first v2
publication. A same-origin Nuxt server route
fetches only that small manifest so server rendering and client-side navigation
can show the same metadata without requiring cross-origin browser access; the
CSV and GeoJSON links still point directly to the public download host.
`NUXT_PUBLIC_SITE_URL` is the origin used to
generate sitemap URLs;
`NUXT_PUBLIC_CANONICAL_BASE_URL` includes this app's public subpath; and
`NUXT_APP_BASE_URL` is the matching router/server mount path. Keep
`NUXT_PUBLIC_INDEXABLE=true` for the canonical production deployment.
The Cloudflare staging build command forces it to `false`, adding both page
metadata and an `X-Robots-Tag` response policy that keep previews out of search
results.

## Analytics

The legacy Vite frontend uses [PostHog](https://posthog.com/) when a production
`VITE_POSTHOG_KEY` is configured. The Nuxt release does not initialize PostHog;
make an explicit privacy and analytics decision before adding it rather than
assuming the legacy integration carried over.

Legacy tracked events include:

- **Pageviews & sessions** - Automatic page tracking
- **User interactions** - Year changes, filter usage, layer toggles
- **Data downloads** - Track when users export data
- **External links** - Track clicks to data sources and GitHub

Analytics are only enabled in the legacy production build with a valid
`VITE_POSTHOG_KEY`. In development, all tracking calls are no-ops.

Legacy event names:
- `year_changed` - User changes the year filter
- `filter_toggled` - User modifies any filter (checkbox, slider, switch)
- `map_layer_changed` - User toggles a map layer
- `aggregation_changed` - User changes aggregation geography
- `location_searched` - User searches for an address
- `data_downloaded` - User exports data (CSV/GeoJSON)
- `external_link_clicked` - User clicks an external link

## API Integration

The frontend consumes a FastAPI backend with a versioned caching strategy:

1. **Fetch metadata**: `GET /shootings/meta` returns version hash and per-year URLs
2. **Load year data**: `GET /shootings/rows/{version}/{year}.ndjson` (cached for 1 year)
3. **Build GeoJSON client-side**: Rows are converted to GeoJSON for map rendering

The Nuxt point-map loader follows the row URL returned by the manifest rather
than constructing it. If that version becomes stale before the row request, it
refreshes the manifest and rows once, then reports an error rather than
retrying indefinitely.

Other endpoints:
- `GET /boundaries/{dataset}` - Boundary polygons (districts, neighborhoods, etc.)
- `GET /streets?segment_ids=...` - Street segments for hot spot analysis
- `GET /homicides/{year}` - Annual and YTD homicide totals
- `GET /meta` - Data freshness metadata
- `GET /stats.json` - Authoritative snapshot for the server-rendered dashboard shell and Statistics page

## Build Output

Production builds are optimized with:
- Code splitting (About page lazy-loaded)
- CSS extraction
- Asset hashing for cache busting

The legacy output is in `dist/` and remains the temporary Netlify rollback build.
Nuxt emits its server build in `.output/`. The pinned Wrangler configuration
has separate environments:

- `npm run deploy:nuxt:staging` builds a `noindex` Workers preview and deploys
  only to its `workers.dev` hostname.
- `npm run deploy:nuxt:production` builds an indexable release and deploys the
  exact and slash-subtree Worker routes for
  `www.nickhand.dev/philly-gun-violence-map`.

Cloudflare includes the query string when matching Worker routes. The main-site
Worker redirects a bare dashboard path with a query to the slash form so it
enters the slash-subtree route without capturing nearby path prefixes.

The Cloudflare build copies the static `_headers` file to the Workers Assets
root and validates base-path assets, indexability, security headers, account,
and Worker identity. On `main`, the frontend quality workflow archives that
exact tested `.output`, uploads a commit-tagged Worker version without changing
routes, and activates it only after all selected gates pass. It verifies the
exact Nuxt build on all five public pages and confirms the terminal active
version; a frontend-specific failure restores the captured prior version. The
full production smoke runs afterward as a health report and cannot trigger an
automatic rollback. `npm run deploy:nuxt:production` remains an operator-only
emergency command. Follow [the cutover runbook](../docs/cloudflare-cutover.md).

The Nuxt dashboard owns the production Explore route and its map, filter,
chart, address-search, and download interactions. Netlify remains outside the
normal request path as a frozen temporary rollback origin; `netlify.toml`
cancels every Git-triggered build. The main
`www.nickhand.dev/robots.txt` advertises the subpath sitemap because the app's
own subpath robots file cannot set host-wide policy.

The subpath sitemap resolves its five canonical content URLs at request time.
Only data-driven pages receive `lastmod`: the Explore and Statistics dates come
from the relevant datasets' `last_updated` publication timestamps, while the
Data page also considers the public download manifest's `published_at` value.
About and Methodology stay undated until the project has an authoritative page
publication timestamp. If the freshness sources are temporarily unavailable,
the sitemap remains complete but omits `lastmod` rather than substituting a
build time or a data-coverage date. The complete XML response receives a
content-derived ETag, so conditional requests cannot incorrectly reuse an older
route set merely because its latest publication timestamp stayed the same.

Every HTML page links the scoped `llms.txt` guide with `rel="describedby"`. The
guide's resource lists use the Markdown-link form defined by the llms.txt
proposal. Do not advertise `rel="alternate" type="text/markdown"` unless real,
maintained Markdown representations of the corresponding pages exist.

## Browser Support

Modern browsers with ES2020+ support:
- Chrome/Edge 88+
- Firefox 78+
- Safari 14+

## Related

- [API Documentation](../packages/api/README.md)
- [ETL Pipeline](../packages/etl/README.md)
- [Project Root](../README.md)
