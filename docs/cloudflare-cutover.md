# Cloudflare migration and dashboard cutover

The migration has two separate changes:

1. make Cloudflare authoritative for `nickhand.dev` and move the main site;
2. route only `/philly-gun-violence-map` and its subtree to the Nuxt Worker.

Do not combine those changes. Keeping them separate preserves the current
Netlify dashboard as the rollback origin while the DNS and main-site migration
settle.

Cloudflare references:

- [Primary DNS setup](https://developers.cloudflare.com/dns/zone-setups/full-setup/setup/)
- [Worker routes](https://developers.cloudflare.com/workers/configuration/routing/routes/)
- [Wrangler environments](https://developers.cloudflare.com/workers/wrangler/environments/)
- [Workers Static Assets headers](https://developers.cloudflare.com/workers/static-assets/headers/)

## 1. Finish and freeze the release candidate

- Commit every intended Nuxt, API, ETL, test, and deployment file.
- Run all Python, unit, SEO, bundle, and browser gates from a clean checkout.
- Publish one schema-v2 public-download release and verify its immutable links.
- Confirm the GitHub OIDC role can write `public/downloads/releases/*` and the
  stable `public/downloads/manifest.json` pointer.
- Keep the existing Netlify deployment available.

## 2. Deploy the API contract first

Deploy the new Fly image rather than merely restarting the old image. Verify:

```text
/health
/meta
/shootings/meta
/stats.json
/boundaries/zip_codes
```

The canary browser origin must be added through `API_CORS_ORIGINS` before the
canary is tested. Keep that value to exact comma-separated origins.

## 3. Move `nickhand.dev` DNS to Cloudflare without moving traffic

1. Export and save every current DNS record, including MX, TXT, verification,
   and mail-security records.
2. Add `nickhand.dev` to Cloudflare and compare the imported record set with
   the export. Keep the existing web origins in place. Start web records as
   DNS-only if there is any uncertainty; mail records must remain DNS-only.
3. If DNSSEC is enabled at the registrar, disable it before changing
   nameservers. Changing nameservers with the old DS record present can make
   the domain unreachable.
4. Replace the registrar nameservers with the two assigned by Cloudflare.
5. Verify the apex, `www`, email, redirects, TLS, and the existing dashboard
   from multiple resolvers. Re-enable DNSSEC through Cloudflare only after the
   zone is active and stable.

At this point Cloudflare is authoritative DNS, but the current Netlify site and
dashboard should still be serving traffic.

## 4. Move the main `nickhand.dev` site

The main-site source is in `~/Public/nickhand.dev`. Deploy that project to its
own Cloudflare canary first, verify every public route and redirect, and then
move the `www` origin. Its Worker must retain compatibility proxies to the
legacy Netlify dashboard and Fair Measure deployments before the origin moves;
otherwise those path-mounted apps would disappear during this step. Use a
Cloudflare zone redirect to send the apex to `www` while preserving the full
path and query string. Do not add the new dashboard Worker route in this step.

Verify the host-root `robots.txt` advertises:

```text
Sitemap: https://www.nickhand.dev/philly-gun-violence-map/sitemap.xml
```

## 5. Deploy the dashboard canary

From `frontend/`:

```bash
npm run deploy:nuxt:staging
```

The staging build is explicitly `noindex`. Add its exact `workers.dev` origin
to the API CORS setting, redeploy the API, and verify hydrated navigation, map
layers, all nine public downloads, mobile layout, accessibility, Letter/A4
printing, error behavior, response headers, and console/network logs.

## 6. Cut over only the dashboard path

The production Wrangler environment owns these route patterns:

```text
www.nickhand.dev/philly-gun-violence-map
www.nickhand.dev/philly-gun-violence-map/*
```

These are Worker **routes**, not a custom domain: they run in front of the
main-site Worker custom domain while leaving other main-site paths alone.
Cloudflare matches the full URL, including its query string. The main-site
Worker redirects a bare dashboard path with a query to the slash form, which
enters the slash-subtree route without capturing nearby paths such as
`/philly-gun-violence-mapper`.

After the canary gate passes:

```bash
npm run deploy:nuxt:production
```

Immediately verify the canonical URL, trailing-slash behavior, navigation,
real API data, all downloads, sitemap, host-root robots file, 404 behavior,
security headers, analytics decision, and that production contains no
`noindex` response or metadata.

## Rollback

Disable or remove the two production Worker routes. The request then reaches
the main-site Worker, whose compatibility proxy returns the legacy Netlify
dashboard without changing the API or data pipeline. Keep both that proxy and
the legacy deployment until the Nuxt release has completed its monitoring
window.
