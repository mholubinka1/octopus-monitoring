# CI/CD & Copilot Pipeline Hardening (octopus-monitoring)

## Problem Statement

Two problems surfaced from analysing Aug 1–6 2026 GitHub usage:

1. Copilot AI credits (~$4.12 gross so far, ~$25/mo run rate) are largely unattributed by
   repository, but automatic Copilot code review — with its 13x model multiplier — is the
   most likely single driver.
2. The self-hosted ARM64 runner (`octopus-runner`) is attached to this repo, which is
   **public**. Investigation during this session found `ci-arm64.yml` already triggers on
   `pull_request` and unconditionally checks out and executes PR code (including, in
   principle, a stranger's fork) on that runner today — a live code-execution exposure, not
   a hypothetical one. No ruleset or "require approval for outside collaborators" setting
   currently exists to close this gap.

Separately, `ci-checks.yml` still runs on GitHub-hosted minutes (~71 min/mo) that could move
to the same self-hosted runner, and `auto_request_review.yml` duplicates reviewer-assignment
that a native CODEOWNERS rule can provide for free.

## Solution

For `octopus-monitoring` only (other repos in the original spec's scope — hypervolt-agile,
bromley-bin-reminder, skills, hueshift2, learning-react, music-library-search — are handled
by a follow-up spec, not this one):

1. Redesign CI triggers so the self-hosted runner never executes a `pull_request`-triggered
   job. Self-hosted workflows (`ci-checks.yml`, `ci-arm64.yml`) trigger on `push` only.
   Required-status-checks on PRs are satisfied because GitHub matches checks to the PR's head
   commit SHA regardless of which event produced them — a `push`-triggered run on a branch
   already covers that branch's own PR. A new `ci-fork-checks.yml` workflow, triggered on
   `pull_request` and gated to run only when the PR's head repo differs from this repo (i.e.
   genuine fork PRs), stays on `ubuntu-latest` and covers the one case `push` can't: external
   contributors.
2. Add `.github/CODEOWNERS` (`* @mholubinka1`) and require Code Owner review via a ruleset on
   `main`, replacing `auto_request_review.yml`'s reviewer assignment (which today only ever
   assigns `mholubinka1` — confirmed via `.github/reviewers.yml`, so nothing else needs
   replicating).
3. Disable automatic Copilot code review (repo setting/ruleset).
4. Delete `auto_request_review.yml` once CODEOWNERS is confirmed working for one review
   cycle.
5. Set "Require approval for all outside collaborators" on fork PR workflow execution as a
   defence-in-depth backstop, independent of the trigger redesign in (1).
6. Confirm no other workflow uses `pull_request_target` combined with a fork checkout
   (audited: only `auto_request_review.yml` uses `pull_request_target`, doesn't check out
   fork code, and is being deleted anyway — no other file needs restructuring).

## User Stories

1. As the repo owner, I want the self-hosted ARM64 runner to never execute code from a PR
   opened by someone other than me, so that a stranger can't run arbitrary code on my home
   network hardware.
2. As the repo owner, I want my own PRs to keep getting the full set of required checks
   (lint, type-check, tests), so that hardening the runner doesn't cost me CI coverage.
3. As the repo owner, I want external contributors' fork PRs to still be checked (on
   GitHub-hosted infrastructure), so that outside contributions aren't silently unchecked.
4. As the repo owner, I want every PR automatically assigned a human reviewer without a
   custom workflow, so that review coverage doesn't depend on Actions minutes.
5. As the repo owner, I want automatic Copilot code review off by default, so that Copilot
   credit spend only happens when I explicitly request a review.
6. As the repo owner, I want `ci-checks.yml`'s GitHub-hosted minutes eliminated, so that CI
   cost drops without losing coverage.

## Implementation Decisions

- **`ci-checks.yml`**: trigger becomes `push` only (`branches: ['**']`, unchanged); runner
  becomes `[self-hosted, linux, ARM64]`. Drop the existing `pull_request` trigger entirely.
- **`ci-arm64.yml`**: trigger becomes `push` only, same rationale. Runner label stays
  `[self-hosted, linux, ARM64]`. The docker build/push steps already gate on
  `github.event_name == 'push'`, so behaviour for push events is unchanged; only the (unsafe)
  `pull_request` path is removed.
- **New `ci-fork-checks.yml`**: triggers on `pull_request` (`branches: ['main']`), with a
  job-level `if: github.event.pull_request.head.repo.full_name != github.repository` so it
  only runs for genuine fork PRs (same-repo PRs are already covered by the `push`-triggered
  runs on their branch). Runs on `ubuntu-latest`. Combines the lint/type-check steps from
  `ci-checks.yml` and the `pytest` step from `ci-arm64.yml` into one job — no docker
  build/push (that stays push-only/self-hosted, and was never meaningfully exercised for PR
  events anyway since it was already gated to `push`).
- **`.github/CODEOWNERS`**: single line, `* @mholubinka1`.
- **Ruleset on `main`**: enable "Require review from Code Owners"; enable/confirm "Require
  approval for all outside collaborators" on fork PR workflow runs; disable "Automatically
  request Copilot code review" if present as a ruleset rule (else via repo Settings → Code
  review).
- **Delete `.github/workflows/auto_request_review.yml`** only after the CODEOWNERS ruleset
  has been observed assigning `mholubinka1` on a real PR.
- An ADR is warranted for the trigger-redesign decision (push-only self-hosted + SHA-matched
  status checks + hosted-only fork fallback) since it's non-obvious without context and a
  real alternative (keep `pull_request` + rely solely on the approval gate) was considered
  and rejected. Will be added as the next-numbered ADR in `.agent-docs/adr/`.

## Testing Decisions

There is no application code under test here — verification is direct, per the confirmed
approach:

- After the CODEOWNERS + ruleset change: open or inspect a real PR and confirm `mholubinka1`
  is auto-requested as a reviewer via `gh pr view --json reviewRequests`.
- After the Copilot toggle: confirm via `gh api` (or the ruleset config itself) that automatic
  Copilot review is off.
- After deleting `auto_request_review.yml`: confirm it no longer appears in
  `gh run list --workflow=auto_request_review.yml`.
- After the fork-PR-approval setting: confirm via `gh api repos/.../actions/permissions`
  (or equivalent) that the setting reflects "require approval for all outside collaborators."
- After the trigger redesign: push a commit on a same-repo branch and confirm
  `ci-checks.yml`/`ci-arm64.yml` fire on `push` and their check runs attach to the PR's head
  SHA; confirm neither workflow lists `pull_request` in its `on:` block anymore; confirm
  `ci-fork-checks.yml` has the fork-only `if:` guard.

## Out of Scope

- The other 6 repos named in the original spec (hypervolt-agile, bromley-bin-reminder,
  skills, hueshift2, learning-react, music-library-search) — covered by a follow-up spec
  written after this one lands, based on pulling and inspecting each repo's actual current
  state rather than assuming the original doc's numbers still hold.
- Dependabot scheduling changes (~46 min/mo, separate lower-priority cleanup per the original
  spec).
- Migrating `actions_storage` usage (negligible cost impact).
- Any change to Copilot Pro/Pro+ plan tier or budget alerts.

## Further Notes

- Original spec's Fix 1 (self-host `ci-checks.yml`) and Fix 5 (fork execution hardening) are
  reordered and merged here: the `ci-arm64.yml` exposure found during investigation is fixed
  first since it's a live gap, not a forward-looking safeguard.
- Rollout order for issues: (1) trigger redesign for `ci-checks.yml`/`ci-arm64.yml` +
  `ci-fork-checks.yml` + fork-approval setting — closes the live exposure first; (2)
  CODEOWNERS + ruleset; (3) disable automatic Copilot review; (4) delete
  `auto_request_review.yml` (depends on 2 being observed working).
