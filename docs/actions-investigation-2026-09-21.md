# GitHub Actions and courts investigation — September 21, 2026

Investigation only: no production tasks, queues, leases, releases, credentials, or workflows were changed. Times below are UTC. GitHub main was `9042aa0d96387c73ab16a73a5154fdf4e52d85c4`; the local checkout was one Chrome-pin update behind main. The relevant scraper and monitoring code is unchanged by that update.

## Findings

The weekly court submission ran, but its asynchronous AWS work never reached publication. The last published court metadata is from September 11, despite a green September 18 submission and green daily production smoke runs. Separate dependency-security failures explain the current frontend and Chrome-update failures.

### Court run timeline

| Time | Evidence |
| --- | --- |
| September 11, 10:40:23 | Last published courts metadata, run `2026-09-11T021539Z-d300`. |
| September 18, 02:15–02:16 | [Successful submission](https://github.com/nickhand/philly-gun-violence-dashboard/actions/runs/35298608744) created run `2026-09-18T021541Z-70ad`, queued 15,811 inputs, launched nine workers and one monitor, then exited successfully. |
| September 18, 02:33:05 | Worker `d3bbed02a879462589bfe6013ac93f5c` began a search that timed out. |
| September 18, 02:38:05 | Its final CloudWatch message reported `Retrying after NETWORK_OR_SERVER_ERROR (attempt 1/8): Failed to get page content: scrape exceeded 300s`. No later worker logs were present. |
| September 18, 10:51–10:52 | Eight other workers wrote final stats. The monitor subsequently reported `RUNNING:1, STOPPED:8`. |
| September 18, 11:51:55 | The monitor crashed with `RuntimeError: ECS failed to describe run tasks`, identifying four previously stopped tasks as `MISSING`. |
| September 21, investigation | The stranded worker was still `RUNNING`; all eight other worker records and the monitor record were no longer available through ECS DescribeTasks. No September 18 processing workflow exists. |

CloudWatch log group: `/ecs/ujs-scraper`. Relevant streams:

- `worker/ujs-scraper/d3bbed02a879462589bfe6013ac93f5c`
- `monitor/ujs-scraper/7cd9bada6cc546978593714e210ca21b`

### Failure mechanism

1. **The hard scrape timeout is swallowed.** `worker.py` arms a one-shot SIGALRM that raises built-in `TimeoutError` after 300 seconds. In `etl/courts/scraper/classifier.py:227`, a broad `except Exception` catches that timeout while reading page content and returns a retryable classification. The outer worker therefore does not enter its timeout handler, which would requeue the item and arm a separate reset deadline.
2. **The retry enters browser teardown after the alarm has fired.** `core.py:_before_retry` calls `_reset_page()` immediately after the final logged warning. The timeout conversion was reproduced locally with a mock page raising `TimeoutError('scrape exceeded 300s')`; the classifier returned `NETWORK_OR_SERVER_ERROR` with `is_retryable=True`. A hang during browser reset is strongly consistent with the code and final log, but the exact blocking call and original browser failure cannot be proved without process inspection.
3. **The monitor re-queries completed tasks indefinitely.** `aws_batch_scraper/orchestrate.py:1111` describes every original task on each poll and fails when any disappear. It never saves durable terminal task evidence. AWS only guarantees stopped tasks remain in [DescribeTasks results for at least one hour](https://docs.aws.amazon.com/AmazonECS/latest/APIReference/API_DescribeTasks.html). The monitor's last observed stopped tasks disappeared while it waited for the stranded worker.
4. **This error path has no durable run-failure record or external notification.** The describe failure is raised before the monitor's finalization error handling. The manifest has no `completed_at`, and the active lease still belongs to this run, with expiration `2026-09-19T11:51:54.555748Z` and no terminal-release object.

### Current state and recovery limits

- The main queue reports zero visible, in-flight, and delayed messages.
- The run has 15,810 result objects and one failure JSON, plus that failure's HTML/PNG diagnostics. Those counts suggest terminal coverage but do not establish validated input identities, content, or conflict-free publication.
- The dead-letter queue contains two visible messages; their relationship to this run was not established. No messages were received, deleted, or redriven.
- Eight final worker-stat objects exist. The stranded worker has none.
- [Published court metadata](https://philly-gun-violence-dashboard-api.fly.dev/meta/courts) still identifies September 11. Its `status=partial` reflects one invalid/unknown input with complete coverage; that status alone is not evidence of the September 18 failure.
- The expired unresolved lease will block a new submission under the existing terminal-evidence rules. A fresh weekly launch is not a recovery strategy.
- The existing `courts resume` preflight also requires every prior worker to be describable and stopped (`recovery.py:964`). It cannot currently handle these expired ECS records. Stopping the stranded worker alone would not resolve that limitation.

Recovery should preserve the same run and its retained evidence: capture available task evidence, stop the stranded worker in a controlled operation, establish durable terminal evidence for the expired task records through a reviewed recovery path, validate the exact-run input/results/failures/conflicts and stable queue state, and only then finalize and process. The current incomplete manifest is not eligible for the documented process-only dispatch recovery. Do not delete the lease or assume `MISSING` means successful completion.

## Why monitoring stayed green

- `courts-scrape.yml` uses `--monitor-in-ecs` and exits after launch. Its green check measures submission, not completion.
- `courts-process.yml` only runs when dispatched by the monitor. A dead monitor creates no failing processing run.
- `/ready` checks shootings and homicide dates, with a 14-day threshold; it has no courts freshness entry.
- `production-smoke.yml:44` checks only shootings/homicides freshness, then reports a successful external heartbeat. On September 21, `/ready` returned `ready` with both datasets through September 20 while courts remained September 11.
- No court-specific CloudWatch metric/composite alarm was present in the inspected region. The default EventBridge bus returned no rules.

## Recommended visibility changes

1. **Add court freshness to the existing daily production smoke before its success heartbeat.** Require valid, timezone-aware metadata for a full, coverage-complete court publication and a last-success age no greater than eight days (weekly cadence plus one day of grace). Reject missing/malformed/future timestamps. Report the run ID, last publication timestamp, age, and threshold as a GitHub error annotation and job summary. Do not require `status=success` blindly: a valid complete publication may explicitly contain unknown observations. This would flag the current incident immediately and withhold the existing success heartbeat.
2. **Add an independent run watchdog.** Alert when a submitted run has not reached processing/publication after a proposed 12-hour deadline, when its monitor fails, when a worker stops progressing, or when its lease is expired but unresolved. Recent successful runs took roughly 6–10 hours. Use the existing external scheduler for periodic checks, and route alerts through the configured notification service; do not depend on the failing monitor to report its own death.
3. **Surface run status clearly.** Rename the submission job to describe launch, include the scraper run ID and CloudWatch links in its summary, and expose distinct submitted/running/failed/published states. A GitHub check tied to the run could remain pending until publication and be failed by the watchdog. Give the public data page an explicit overdue court-update message when the freshness threshold is crossed.
4. **Fix the causes and preserve diagnostics.** Make the worker deadline escape broad scraper exception handlers; bound browser reset/teardown independently. Persist validated STOPPED task records as they are observed, then stop polling those tasks. Record monitor failures durably across the entire polling loop. Add regression tests for timeout propagation, a hung reset, tasks aging out after a saved terminal record, a missing task without evidence, and watchdog stale/missing/future metadata.

## Other failing Actions

| Workflow | Confirmed cause | Corrective work |
| --- | --- | --- |
| [Frontend quality, September 21](https://github.com/nickhand/philly-gun-violence-dashboard/actions/runs/35584576300) | `npm audit --package-lock-only --audit-level=high` fails before type/build/unit checks: 10 findings, including 1 critical and 4 high. Critical: MapLibre sanitizer advisory `GHSA-jrc7-96c5-q579`. High: Sharp/libheif and SVGO, including propagated parent-package findings. | Update affected dependencies and their lockfile; test map behavior and Cloudflare builds. The audit proposes a major MapLibre upgrade from the currently locked 2.4.0, so avoid an unreviewed force-fix. The canonical map uses DOM popup content; legacy map helpers still use HTML popups. No exploitability assessment was performed. |
| [Dependency security, September 15](https://github.com/nickhand/philly-gun-violence-dashboard/actions/runs/34956952137) | The frontend dependency audit fails for the same dependency family (9 findings at that time). | Same frontend dependency remediation. |
| [ETL image scan, September 21](https://github.com/nickhand/philly-gun-violence-dashboard/actions/runs/35577141663), causing [Chrome updater failure](https://github.com/nickhand/philly-gun-violence-dashboard/actions/runs/35577094140) | Saved Grype evidence identifies `anyio 4.12.0`, critical `GHSA-82r6-8w77-94w6` / `CVE-2026-63374`. Image build and smoke passed; the vulnerability gate failed. Chrome update PR #31 consequently cannot merge. | Upgrade AnyIO in the affected lockfiles to patched 4.14.2 or later, rebuild, and rerun the image gate. Both API and ETL lockfiles currently contain 4.12.0. The [maintainer advisory](https://github.com/agronholm/anyio/security/advisories/GHSA-82r6-8w77-94w6) confirms the patched version. Do not weaken the scanner threshold. |
| [Ubuntu Dependabot PR validation, September 14](https://github.com/nickhand/philly-gun-violence-dashboard/actions/runs/34853853301) | PR #27 changes the Docker base digest, but `test_courts_image_pins_supported_ubuntu_snapshot_and_chrome` asserts the previous exact digest. One test fails; 302 pass. | Review the new base and update the coordinated image contract, or centralize the approved pin so automation does not leave an independent literal stale. |

Older September 16 Chrome-branch PR-triggered configuration/ETL failures contain no jobs or downloadable logs. The separately dispatched configuration and ETL validations on that update succeeded; the current configuration dispatch also passed. They are distinct from the reproducible September 21 security failures.

Daily shootings, daily homicides, and the existing production smoke were succeeding at investigation time. Their success does not establish court freshness.

## Validation performed

Read GitHub run histories, failed logs, the image scan artifact, current repository variables, live API metadata/readiness, S3 run manifests and object listings, queue counts, ECS task states, CloudWatch logs, and alert configuration. Reproduced timeout misclassification locally without portal or AWS mutation. No application changes or full test suite were run for this investigation.
