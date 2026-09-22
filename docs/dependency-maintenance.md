# Dependency maintenance

This repository uses weekly Dependabot review batches for a single maintainer.
The policy lives in [dependabot.yml](../.github/dependabot.yml).

## Update policy

- Keep the existing Monday schedule. Review compatible Python, frontend, and
  GitHub Actions minor/patch updates in groups instead of one PR per update.
- Keep major upgrades out of those routine groups. Python major upgrades are
  grouped by dependency name across packages, so a shared dependency's migration
  can be reviewed together. Incompatible constraints can still produce separate
  PRs. Frontend and Actions major upgrades remain individual PRs.
- Group Docker updates by image name across the API and ETL Dockerfiles. Each
  base image retains a separate review, including major tag changes.
- Give ordinary new releases seven days before considering them. Lower the
  configured open version-PR limits to three for Python and two for each other
  ecosystem. These are Dependabot update limits, not a guaranteed repository-wide
  count or a promise that the existing backlog will disappear.
- Keep security updates eligible immediately: the version-update cooldown and
  PR limits do not apply to them. Do not add blanket ignore rules to hide major
  upgrades or vulnerabilities.

These behaviors use GitHub's documented [grouping and cooldown options](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference)
and [cross-directory dependency grouping](https://github.blog/changelog/2026-02-24-dependabot-can-group-updates-by-dependency-name-across-multiple-directories/).

## Review and merging

Dependabot opens PRs; this configuration does not merge them. At the September
22, 2026 audit, repository auto-merge was disabled, no open Dependabot PR had an
auto-merge request, and `main` had no branch protection or ruleset. This cleanup
does not change repository merge permissions.

The same audit found Dependabot vulnerability alerts and automated security-fix
PRs disabled. Both repository settings were enabled and read back successfully
as part of this cleanup. Security-fix PR creation is separate from automatic
merging; those fixes still follow the review policy below.

Review routine batches weekly, prioritize security fixes, and schedule major
migrations deliberately. Require the relevant tests, type checks, browser/image
checks, and security audits to pass against the current base before merging.
Keep the existing lockfile/version constraints, immutable image and action pins,
and explicit production deployment gates. A minor/patch version is a review
category, not proof that a change is compatible.

For the existing backlog, compare each PR with current `main` and any grouped
replacement before closing it as superseded. A configuration change is not proof
that an old PR's update has landed. Keep linked runtime/type packages, such as
pandas and pandas-stubs, aligned when planning a major migration.

The separate [Chrome updater](../.github/workflows/chrome-update.yml) already
merges same-milestone updates after its explicit validation and commit checks.
Chrome milestone upgrades remain manual. That workflow is independent of
Dependabot and is unchanged by this policy.

## Before adding Dependabot auto-merge

First protect `main` with required CI checks that cover every PR. The current
workflows have path filters: do not blindly require a workflow that will never
start for some changes. Provide an always-running aggregate check that verifies
the relevant jobs. A solo maintainer need not require an approval from a second
person they do not have.

Then consider opt-in auto-merge for a narrow set of well-tested minor/patch
updates, with major upgrades and deployment credentials/workflows still reviewed.
Use GitHub's [native auto-merge](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/automatically-merging-a-pull-request)
to wait for enforced checks. Avoid a privileged workflow that checks out and runs
dependency PR code just to approve or merge it.
