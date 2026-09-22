# Court recovery and monitoring rollout — September 21–22, 2026

The [incident investigation](actions-investigation-2026-09-21.md) found a swallowed browser timeout, an indefinitely running worker, and a monitor that crashed when stopped ECS tasks expired. A successful submission and fresh shootings data had concealed the missing court publication.

[PR #34](https://github.com/nickhand/philly-gun-violence-dashboard/pull/34) merged as `68b8b436a8c6234a62490ff1e59bdde5b10effc6`, including the reviewed Chrome and Ubuntu updates from PRs #31 and #27. Production recovery and rollout were explicitly authorized. All times here are UTC.

Recovery and the independent monitoring were deployed September 21. The remaining scraper runtime activation completed September 22 after the full Fargate promotion gate passed. The production worker and monitor now use revisions `ujs-scraper:12` and `ujs-scraper-monitor:6` with the verified image digest below.

## Recovery evidence

The original run is `2026-09-18T021541Z-70ad`. Its stranded worker `d3bbed02a879462589bfe6013ac93f5c` was stopped at 21:56:25, and its actual exit code 137 was retained. Eight expired worker records were reconciled through append-only operator-review evidence bound to the original inputs, task set, and lease generation. Their unavailable exit codes remain unknown; they were not rewritten as successful exits.

The read-only recovery preview validated all 15,811 inputs: 15,810 result objects and one explicit invalid-input failure, with zero missing inputs or unresolved conflicts. The main queue was empty and stable. Recovery revalidates the full inventory before mutations and publication; it does not submit duplicate work or delete the unresolved lease. The two pre-existing DLQ messages were left untouched.

Finalization completed at 23:00:06 and dispatched exactly one [court-processing workflow](https://github.com/nickhand/philly-gun-violence-dashboard/actions/runs/35665468510). Processing published at 23:01:00 and released the lease with `status=success`. The [shootings refresh](https://github.com/nickhand/philly-gun-violence-dashboard/actions/runs/35665591512) then adopted that court snapshot. The live `/meta/courts` response identifies this run, `selection_mode=full`, `coverage_complete=true`, zero missing/extra results, and zero unresolved conflicts. Its `partial` status preserves the single invalid input as unknown.

## Prevention and visibility

- The activated scraper image supervises browser work in a child process with bounded scrape, startup, reset, and shutdown operations. Hard timeouts escape broad scraper exception handlers. A failed worker leaves its message available for normal redelivery.
- The new monitor code retains validated terminal task evidence, worker progress, and monitor heartbeat/failure records. The deployed hourly independent watchdog checks unresolved leases, overdue runs, stopped/absent tasks, and stale progress.
- The daily production smoke requires a valid, coverage-complete full court publication no more than eight days old before reporting its external success heartbeat. An explicitly unknown observation remains compatible with complete coverage.
- The Fly scheduler runs the watchdog at minute 45 each hour. Deployment retained exactly one scheduler Machine and no scheduler in the public API app.
- Worker and GitHub workload roles have an explicit write boundary on operator-review evidence. The watchdog uses a read-only session policy; the GitHub role received only the additional ECS describe permission required for the probe.

The [first live watchdog run](https://github.com/nickhand/philly-gun-violence-dashboard/actions/runs/35664851592) failed as intended on the 10.51-day-old court publication and independently reported the expired lease, overdue run, unsuccessful stranded worker, and unavailable terminal records. Its AWS read permissions worked even after the public freshness step failed.

After recovery, that same watchdog passed. A separate [watchdog dispatched from the deployed Fly scheduler](https://github.com/nickhand/philly-gun-violence-dashboard/actions/runs/35665783885) also passed. The [frontend deployment and production smoke](https://github.com/nickhand/philly-gun-violence-dashboard/actions/runs/35664641396) are green: before recovery the court gate withheld the heartbeat; afterward the failed smoke job alone was rerun and the external heartbeat was accepted. This verifies the workflow and heartbeat endpoint, not delivery to a particular person's notification inbox.

## Release validation

Validation included 562 scraper tests, 307 ETL tests, 162 API tests, 51 configuration tests, 226 frontend unit tests, strict type/lint/format checks, Chromium/mobile, Firefox, WebKit and Nuxt browser suites, Cloudflare artifact checks, and the unchanged Lighthouse policy. One Lighthouse run narrowly exceeded its 2.5-second LCP limit; the same-head retry passed without a policy change.

The dependency fixes include AnyIO 4.14.2, Chrome 153.0.8010.52, patched libaom, and patched frontend dependencies with zero npm audit findings. [Ubuntu reverted its Bubblewrap fix](https://ubuntu.com/security/notices/USN-8779-2), so the image builds the checksum-pinned [upstream 0.12.0 fix](https://github.com/containers/bubblewrap/security/advisories/GHSA-pxhw-h44j-8pfx) as an installed Debian package, retaining its license and actual package identity. Both local and ECR release gates still reject Critical, High, and Undefined vulnerabilities; no advisory was suppressed.

The API deployment was verified healthy and running AnyIO 4.14.2. The final scraper image passed a restricted, network-isolated supervised Chrome start/scrape/reset/close test. Local Docker cache exhaustion delayed packaging; only this task's rejected image and identified build-cache records were removed.

A read-only browser check of the deployed site rendered the map, loaded its bundled MapLibre worker from the production namespace, and recorded no page runtime errors. Analytics endpoints were unreachable from the test environment; the map and public data remained functional.

The verified scraper source tag is `0b910dd7d55db96cc10ce3e04946d9d5211f8bf7`; the ECR digest is `sha256:846baa1b3eb23c9c930c05d63ff14a9ac0353a8e7dd66f71f9250022a4f0dedc`. Both local and ECR gates passed. The receipt, SBOMs, scan reports, and filesystem audit are retained locally under `.artifacts/aws-batch-scraper/releases/0b910dd7d55db96cc10ce3e04946d9d5211f8bf7/`.

| Component | Deployed version |
| --- | --- |
| Fly API | `deployment-01M331TBK25YV25V0VVWEE9EAY` |
| Fly scheduler | `deployment-01M332JQMFPREQE41TKDF1TKKA` |
| Cloudflare production | `03ee168c-b7ac-49c6-8578-3c0f2fcb1edb` |
| ECS worker | `ujs-scraper:12` |
| ECS monitor | `ujs-scraper-monitor:6` |

## Completed scraper activation gate

On September 21, ECS `RunTask` repeatedly returned `ServerException: Internal Error` before creating a task. Later bounded tests returned an explicit capacity-unavailable failure for each of the three existing production availability zones; a no-op test on the previous production definition also failed. The cluster and definitions were ACTIVE, subnets had available addresses, and the On-Demand quota was 64 vCPUs with no running tasks. The exact cause of AWS's earlier generic errors remains unconfirmed. The production variables stayed on worker revision 11 and monitor revision 5 during this interruption.

On September 22, Fargate accepted the same reviewed image and runtime configuration. The first probe, `afa489d0eb474ae8a597d4f5c02e2654`, exited zero and emitted the success marker, but its ENI evidence was incomplete: the limited profile lacked EC2 read permission and the deployment login had expired. That probe was preserved without approving promotion. After the login was refreshed, a fresh isolated probe captured the complete evidence; runtime settings and promotion requirements were unchanged.

The successful promotion probe was `arn:aws:ecs:us-east-1:985454606291:task/ujs-scraper/dba14864a900449785847e2f0c0b8b26`, running from 15:40:46 to 15:41:14. It used the exact worker revision and digest, Linux Fargate platform `1.4.0`, and disabled execute-command. EC2 resolved its ENI `eni-06224ed3103575546` in production subnet `subnet-0a3defe7f496101d9` with exactly security group `sg-08ba9aae13af9631b`. The live browser/runtime checks passed; the sole essential container exited zero and CloudWatch contained exactly one `COURTS_FARGATE_SMOKE_OK_V1` marker. No probe tasks remained. This satisfies the unchanged [Fargate promotion gate](../packages/etl/README.md).

Before activation, fresh checks confirmed no active cluster tasks or court submission/processing workflows and zero visible, in-flight, or delayed main-queue messages. Both new definitions passed semantic preflight; the published ECR scan still reported no blocking findings. GitHub's worker, monitor, and expected-image variables were then updated to the exact revisions and matching digest, read back, and validated by semantic preflight again. Browser supervision and durable monitor evidence are now configured for subsequent scraper runs. This activation did not submit another scrape or change the recovered court data.

The post-activation [court watchdog](https://github.com/nickhand/philly-gun-violence-dashboard/actions/runs/35749175348) and [production smoke](https://github.com/nickhand/philly-gun-violence-dashboard/actions/runs/35749178756) both passed. The hourly watchdog had also stayed green overnight. The recovered September 18 run remained the current valid, coverage-complete full publication; a full production scrape with the new revisions will occur on the normal schedule.

The local `.artifacts/courts-rollout-2026-09-21/` directory retains credential-free before/proposed configurations, AWS request IDs, the verified release reference, and guarded probe/activation scripts with a README. Those operational artifacts are intentionally outside Git; do not publish raw task logs or credentials.

## Rollback boundaries

Restore worker and monitor definitions together with their matching verified digest; never mix revisions or use `latest`. Prior definitions were `ujs-scraper:11` and `ujs-scraper-monitor:5`. Rollback must not delete recovered court evidence or republish an older data pointer.

The prior Fly API image was `deployment-01M0J77DE4B6KYN8DNWDCKQHE9`, and the prior scheduler image was `deployment-01M1HBP6D9SGCMNVFCVPS6D3K2`, in their respective app registries. Keep the scheduler at one Machine during any rollback. Reverting its image removes the hourly watchdog, so restore equivalent monitoring before doing so. The added inline IAM policies are named `operator-review-evidence-boundary` and `courts-watchdog-read`; removing the former would reopen writes to reviewed recovery evidence and is not a routine application rollback step.

The prior Cloudflare version is `1d7f71d8-1758-49b8-898e-6c135a6cbc56`. An application rollback does not require or authorize rolling back recovered court data.
