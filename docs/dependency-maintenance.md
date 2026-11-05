# Unattended dependency maintenance

Routine dependency updates should not require a weekly maintainer review. The
[Dependabot configuration](../.github/dependabot.yml) creates Monday minor/patch
batches after a seven-day release cooldown. The [merge policy](../.github/workflows/dependabot-auto-merge.yml)
requests native auto-merge for verified, eligible updates; GitHub waits for the
protected branch's required checks before merging.

## Eligible updates

Python and frontend minor/patch updates, minor/patch GitHub Actions updates, and
classified minor/patch Docker updates are eligible. Shared Docker pins are
grouped by image name. Routine Python and frontend proposals target only direct
dependencies declared in manifests (`allow.dependency-type: direct`), including
development tools. Their lockfile updates can still update transitive dependencies;
we do not request standalone version bumps for every transitive package. Python
updates preserve existing compatible requirements with `increase-if-necessary`,
reducing drift between linked package lockfiles. Version-update PR limits remain three for Python and two
for the other ecosystems; these are not a repository-wide total.

Every dependency in a group must qualify. The pinned official metadata action
verifies the Dependabot author and commit signatures. The repository policy
then requires the expected repository and head commit, a complete file inventory,
and modified files limited to the ecosystem's manifests, lockfiles, Dockerfiles,
or workflow files. Missing metadata, a major or unclassified change, a maintainer
change, a draft/fork, or unexpected files prevent automatic merging.

Ordinary major-version proposals are deferred using `allow.update-types`, rather
than accumulated as unattended review requests. That filter applies only to
version updates. Dependabot vulnerability alerts and security-fix PRs are enabled;
security-fix proposals remain enabled immediately, including those requiring a
major upgrade. Major/security exceptions still need a deliberate upgrade or repair;
failed checks are never overridden to clear the queue.

The options follow GitHub's [Dependabot reference](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference).
Production scraper monitoring and the signed Chrome updater run daily.

The [October 23 security review](security-hardening-2026-10-23.md) records the
eMudhra trust-store repairs, toolchain versions, CI failure causes, and deployment
work needed to activate the fixes.

## Enforced merge checks

The Fly scheduler dispatches `security-quality.yml` on `main` at 07:17 UTC.
Each run reads the courts production release pointer and pulls its exact ECR
digest using a read-only AWS session. The monitor verifies the image identity
and deployed Chrome lock, generates a fresh package inventory, and scans both
the image and the browser with a current vulnerability database. A
known-vulnerable Chrome control checks that browser advisories are being
detected. It also reads the last completed ECR scan for the same digest and
includes any outstanding registry findings with that scan's timestamp.
ECR Basic scans on each push. Daily coverage comes from fresh Grype data
even as the stored ECR result ages. A new release still needs a fresh ECR pass.
The monitor rechecks the release pointer before publishing a result.

* **Production findings** open one GitHub issue per affected package. The issue
  lists the blocker severities, advisories, available fixed versions and
  deployed digest. New production and coverage issues are assigned to the
  repository owner, or to the GitHub login set in `SECURITY_MAINTAINER`. Repeat findings reuse the issue. A verified observation of
  the active image closes issues for resolved packages.
* **Missing coverage** preserves open findings. An independent GitHub check
  runs every six hours and maintains one overdue issue when 48 hours pass
  without verified evidence. The next freshness check closes it after recovery.
* **Weekly maintenance** runs on Wednesday at 07:17 UTC. It audits all five
  dependency groups and performs a clean scraper build, browser smoke test
  and image scan. Failed checks appear in the weekly issue queue. Eligible
  dependency fixes continue through Dependabot. Public health and freshness
  monitoring keep their own alerts.

To request both the deployed scan and the weekly checks immediately, run
`gh workflow run security-quality.yml --ref main -f full_audit=true`.
On other branches a manual dispatch runs the candidate audits and full image
build. Required pull request and release gates keep their existing thresholds.
Scan evidence is retained for 30 days.

Security repairs must cover all four independent Python locks. The shared
urllib3 constraint prevents a routine resolution from returning below 2.8.0,
and repository contracts require the locked versions to agree. Keep the normal
one-week release cooldown; for an urgent fix inside that window, review and
document a package-specific exception instead of disabling the policy globally.
Dedicated `security-updates` groups let Dependabot propose vulnerable Python
dependencies across the four directories together, and batch frontend security
repairs separately from routine updates. The direct-only boundary for ordinary
version updates remains in place. See GitHub's
[security grouping rules](https://docs.github.com/en/code-security/concepts/supply-chain-security/dependabot-security-updates).

The temporary [node-forge backport](../frontend/vendor/README.md) includes a
reproducible archive and regression tests because no patched upstream release
was available. Revisit it when upstream ships the fix. Vulnerability thresholds
and release gates remain enforced.

`main` requires an up-to-date PR and these checks, including for administrators:

- `API quality gate`
- `ETL quality gate`
- `Frontend quality gate`
- `Dependency security gate`
- `CI routing and deployment contracts`
- `Dependency merge policy`

The five quality workflows start on every PR. Their existing path router keeps
unrelated product jobs skipped, while each final gate verifies that all selected
jobs actually passed. Thus a documentation-only PR can satisfy the required
checks without running browser tests, and a dependency change cannot bypass its
tests, image smoke, browser coverage, or audits. Push routing and production
deployment conditions remain unchanged. No second-person approval is required.

The policy status is tied to the exact PR head. Before releasing that status,
the policy removes any previous queued auto-merge request from a Dependabot PR;
it requests auto-merge again only for an eligible head. This prevents an earlier
eligible commit's request surviving an ineligible replacement. An ineligible PR
can still be deliberately merged after its tests pass: a successful policy
status means the auto-merge decision was enforced, not that auto-merge was granted.
Verification failures are different: missing/truncated metadata, a failed metadata
action, merge conflicts on an eligible PR, or failure to request auto-merge leave a
**failed** required policy status and workflow. The status links to the workflow
run with the recovery reason; it must never report success for these failures.

The privileged policy workflow runs only trusted base-branch code. It never
checks out, installs, caches, or executes PR code or artifacts. Read-only PR
workflows perform the actual tests. The policy neither grants itself a protection
bypass nor approves PRs on the maintainer's behalf.

## Chrome updates and production

The [Chrome updater](../.github/workflows/chrome-update.yml) retains its signed
release checks and exact head/base guards. Strictly newer Chrome-only updates,
including milestones, can merge after their checks pass. Same-version
republishes need maintainer review. Before promotion, the candidate worker
must complete a live synthetic court lookup and its monitor must pass the
health probe. The release process retains its conditional rollback.

Automatic merging updates source control. It does not bypass immutable image
promotion, Fargate smoke, or deployment gates. Native auto-merge uses the built-in
GitHub token; push workflows are not guaranteed to run for token-originated merges.
The pre-merge checks and independent production monitoring therefore remain
required. Do not assume an auto-merged dependency is already deployed.

Existing PRs are closed only after their update is superseded by a validated
replacement, or explicitly recorded as a deferred, nonsecurity major migration.
Security alerts are not dismissed as part of backlog cleanup.

## Recovery from oversized batches

On September 22, PRs #49 and #50 were produced from commit `7924371`, before
the validated cleanup in #46. The wildcard `allow.dependency-name: "*"`
unintentionally admitted indirect dependencies, expanding those groups to 189
frontend and 50 Python updates. Both commit messages were truncated at 65,535
characters, losing the complete metadata required by `dependabot/fetch-metadata`.
Both branches also conflicted with the cleanup already on `main`.

The recovery is to restore the direct-dependency boundary, then let Dependabot
regenerate against current `main`. Retire the obsolete broad proposals only after
checking their direct target versions against `main`; any genuinely outstanding
direct update must remain eligible for a fresh proposal. Do not bypass signature
verification, infer approval from the PR title, or merge the conflicted lockfiles.
Dependabot configuration edits can start update jobs immediately, so the Monday
schedule does not mean no PR can appear during a configuration rollout.

The comparison found 17 of 19 frontend direct targets and 26 of 29 Python direct
targets already on `main`. Remaining targets were Node typings 20.19.43, Vuetify
3.13.4, boto3-stubs 1.43.94 in the scraper/shared packages, and Python Playwright
1.63.0 in ETL. These remain ordinary maintenance candidates, not ignored versions.

## Deferred migrations recorded on 2026-09-22

These ordinary version proposals are deferred because they require coordinated
compatibility work; they are not outstanding review assignments:

| Migration | Existing PRs | Reason |
| --- | --- | --- |
| pandas and pandas-stubs 2.x to 3.x | #9, #12, #43, #44 | Keep the runtime, shared package, and typing contracts aligned. |
| Vite 7 to 8 | #40 | Requires a compatible frontend toolchain migration. |
| Node type definitions 20 to 26 | #41 | Requires coordinated runtime and type compatibility. |
| setup-uv 8 to 10 | #28 | Completed with setup-uv 10.3.2 and uv 0.13.5 in the October 23 security repair. |

GitHub reported no open Dependabot vulnerability alerts when this inventory was
recorded. Closing these version proposals does not dismiss any security alert.
