# Unattended dependency maintenance

Routine dependency updates should not require a weekly maintainer review. The
[Dependabot configuration](../.github/dependabot.yml) creates Monday minor/patch
batches after a seven-day release cooldown. The [merge policy](../.github/workflows/dependabot-auto-merge.yml)
requests native auto-merge for verified, eligible updates; GitHub waits for the
protected branch's required checks before merging.

## Eligible updates

Python and frontend minor/patch updates, minor/patch GitHub Actions updates, and
classified minor/patch Docker updates are eligible. Shared Docker pins are
grouped by image name. Python updates preserve existing compatible requirements
with `increase-if-necessary`, reducing drift between linked package lockfiles. Version-update PR limits remain three for Python and two
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
Deferring an ordinary major upgrade does not disable the weekly dependency audits
or the daily Chrome updater.

## Enforced merge checks

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

The privileged policy workflow runs only trusted base-branch code. It never
checks out, installs, caches, or executes PR code or artifacts. Read-only PR
workflows perform the actual tests. The policy neither grants itself a protection
bypass nor approves PRs on the maintainer's behalf.

## Chrome updates and production

The [Chrome updater](../.github/workflows/chrome-update.yml) retains its signed
release checks, same-milestone policy, and exact head/base guards. It explicitly
dispatches and waits for all required quality workflows and the policy status,
so it also works when its GitHub token does not trigger PR workflows. Chrome
milestone upgrades remain exceptions.

Automatic merging updates source control. It does not bypass immutable image
promotion, Fargate smoke, or deployment gates. Native auto-merge uses the built-in
GitHub token; push workflows are not guaranteed to run for token-originated merges.
The pre-merge checks and independent production monitoring therefore remain
required. Do not assume an auto-merged dependency is already deployed.

Existing PRs are closed only after their update is superseded by a validated
replacement, or explicitly recorded as a deferred, nonsecurity major migration.
Security alerts are not dismissed as part of backlog cleanup.

## Deferred migrations recorded on 2026-09-22

These ordinary version proposals are deferred because they require coordinated
compatibility work; they are not outstanding review assignments:

| Migration | Existing PRs | Reason |
| --- | --- | --- |
| pandas and pandas-stubs 2.x to 3.x | #9, #12, #43, #44 | Keep the runtime, shared package, and typing contracts aligned. |
| Vite 7 to 8 | #40 | Requires a compatible frontend toolchain migration. |
| Node type definitions 20 to 26 | #41 | Requires coordinated runtime and type compatibility. |
| setup-uv 8 to 10 | #28 | A separate action runtime migration; uv itself stays pinned to 0.12.0. |

GitHub reported no open Dependabot vulnerability alerts when this inventory was
recorded. Closing these version proposals does not dismiss any security alert.
