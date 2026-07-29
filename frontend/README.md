# Philadelphia Gun Violence Dashboard - Frontend

Interactive Vue 3 dashboard visualizing gun violence data in Philadelphia with maps, charts, and filtering capabilities.

## Tech Stack

- **Framework:** Vue 3 + Composition API
- **Language:** TypeScript
- **UI Library:** Vuetify 3
- **Mapping:** MapLibre GL
- **Charts:** D3.js
- **Data Filtering:** Arquero
- **State Management:** Pinia
- **Build Tool:** Vite

## Prerequisites

- Node.js 20.19+ or 22.12+
- npm 9+

## Getting Started

```bash
# Install dependencies
npm install

# Start development server
npm run dev

# Build for production
npm run build

# Check compressed production bundle budgets
npm run check:bundle

# Preview production build
npm run preview
```

The development server runs at `http://localhost:5173`.

## Testing

```bash
# Unit and component tests
npm test

# Unit tests with enforced coverage thresholds
npm run test:coverage

# Chromium, Firefox, WebKit, and mobile Chromium browser tests
npm run test:e2e

# WCAG 2.1 A/AA automated checks
npm run test:e2e:a11y

# Production Lighthouse audit with performance thresholds
npm run test:lighthouse
```

Browser tests use deterministic API fixtures and a browser-safe map placeholder,
so they do not depend on production data, third-party map services, or CI GPU
availability. See
[`ACCESSIBILITY.md`](./ACCESSIBILITY.md) for the manual WCAG 2.1 AA evaluation
checklist.

## Bundle budgets

The production build emits a Vite manifest and `npm run check:bundle` enforces
gzip budgets for the initial app shell, the asynchronously loaded map, their
combined core experience, and deferred analytics. The check also prevents the
full Material Design icon font from being bundled again. Lighthouse runs three
desktop audits against deterministic local data and a local map style, then
enforces scores and Core Web Vitals-oriented thresholds.

## Project Structure

```
src/
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
│   └── stores/             # Pinia stores (shootings, etc.)
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
- Filter by court case status

### Charts
- Breakdowns by time, location, and demographics
- Synchronized filtering across map and charts

## Environment Variables

Create a `.env` file for local development:

```env
VITE_API_BASE_URL=http://localhost:8000
VITE_POSTHOG_KEY=              # Optional: PostHog analytics key
```

For production, `VITE_API_BASE_URL` points to the Fly.io API deployment.

## Analytics

The frontend uses [PostHog](https://posthog.com/) for privacy-focused product analytics:

- **Pageviews & sessions** - Automatic page tracking
- **User interactions** - Year changes, filter usage, layer toggles
- **Data downloads** - Track when users export data
- **External links** - Track clicks to data sources and GitHub

Analytics are only enabled in production with a valid `VITE_POSTHOG_KEY`. In development, all tracking calls are no-ops.

Tracked events:
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

Other endpoints:
- `GET /boundaries/{dataset}` - Boundary polygons (districts, neighborhoods, etc.)
- `GET /streets?segment_ids=...` - Street segments for hot spot analysis
- `GET /homicides/{year}` - Annual and YTD homicide totals
- `GET /meta` - Data freshness metadata

## Build Output

Production builds are optimized with:
- Code splitting (About page lazy-loaded)
- CSS extraction
- Asset hashing for cache busting

Output is in the `dist/` directory, deployed to Netlify.

## Browser Support

Modern browsers with ES2020+ support:
- Chrome/Edge 88+
- Firefox 78+
- Safari 14+

## Related

- [API Documentation](../packages/api/README.md)
- [ETL Pipeline](../packages/etl/README.md)
- [Project Root](../README.md)
