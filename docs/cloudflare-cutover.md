# Cloudflare migration and dashboard cutover

Status: completed. Cloudflare became the canonical dashboard host on August 18,
2026; the first attested automated release completed on August 21, and the
dashboard Netlify project was then stopped and repository-unlinked. Sections
1–6 preserve the original migration sequence as a historical record.

The migration had two separate changes:

1. make Cloudflare authoritative for `nickhand.dev` and move the main site;
2. route only `/philly-gun-violence-map` and its subtree to the Nuxt Worker.

They were intentionally separated so DNS, main-site routing, and the dashboard
could be verified independently.

Cloudflare references:

- [Primary DNS setup](https://developers.cloudflare.com/dns/zone-setups/full-setup/setup/)
- [Worker routes](https://developers.cloudflare.com/workers/configuration/routing/routes/)
- [Wrangler environments](https://developers.cloudflare.com/workers/wrangler/environments/)
- [Workers Static Assets headers](https://developers.cloudflare.com/workers/static-assets/headers/)

## 1. Finish and freeze the release candidate

- Commit every intended Nuxt, API, ETL, test, and deployment file.
- Run all Python, unit, SEO, bundle, and browser gates from a clean checkout.
- Save and inspect the current schema-v2 manifest before pointer publication.
- Confirm the GitHub OIDC role can write `public/downloads/releases/*`, and can
  read and write the stable `public/downloads/manifest.json` pointer.
- Confirm the Fly API identity can read `public/downloads/manifest.json`, and
  that no S3 lifecycle rule can expire a release still named by the current or
  previous application-data pointer.
- Keep the then-existing rollback origin available until Cloudflare cutover was
  verified.

## 2. Deploy the API contract first

Deploy the new Fly image rather than merely restarting the old image. Verify:

```text
/health
/ready
/meta
/shootings/meta
/stats.json
/boundaries/zip_codes
```

The canary browser origin must be added through `API_CORS_ORIGINS` before the
canary is tested. Keep that value to exact comma-separated origins.

Only after the pointer-aware API is healthy should data migration continue.
First complete and verify the courts semantics-v2 migration: the flags CSV and
courts metadata must both report version 2, legacy false must be unknown, and
only explicit current no-results observations may be false. Then let the updated
shootings ETL publish `application_data`. Run it once, verify the pointer and
current URL, then run it a second time (or wait for the next normal release),
restart the API, and verify both current and previous immutable row URLs.
Publish the homicide pointer after that contract is green. Do not publish the
new pointer format before the API and manifest-read IAM grant are deployed.

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

At this historical checkpoint Cloudflare was authoritative DNS while the old
dashboard origin was still retained temporarily.

## 4. Move the main `nickhand.dev` site

The main-site source is in `~/Public/nickhand.dev`. Deploy that project to its
own Cloudflare canary first, verify every public route and redirect, and then
move the `www` origin. During the migration its Worker retained compatibility
proxies for the legacy dashboard and Fair Measure origins so those path-mounted
apps did not disappear during this step. Use a
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

Every automated release captures the sole active production Worker version
before activation. A frontend-specific verification failure restores that
version automatically, provided the active-version compare-and-swap guard still
matches the release. For a manual rollback, verify the current active version
has not changed, then use Wrangler's version rollback command recorded in the
GitHub deployment summary. The retired Netlify project is not a supported
rollback path.
