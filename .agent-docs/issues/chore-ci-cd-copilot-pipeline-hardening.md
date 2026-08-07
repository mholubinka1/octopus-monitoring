# Issues: chore-ci-cd-copilot-pipeline-hardening

## Harden self-hosted runner against fork PR execution (#478)

**Blocked by**: None

**User stories**: 1, 2, 3

### What to build

Close the live exposure first: the self-hosted ARM64 runner must never execute a
`pull_request`-triggered job. Change `ci-checks.yml` and `ci-arm64.yml` to trigger on `push`
only (dropping `pull_request` entirely) while keeping/adding the self-hosted ARM64 runner
label. Add a new `ci-fork-checks.yml` workflow on `ubuntu-latest`, triggered on
`pull_request`, gated to run only when the PR's head repo differs from this repo, combining
the lint/type-check steps from `ci-checks.yml` and the `pytest` step from `ci-arm64.yml` (no
docker build/push). Set the repo's fork PR workflow approval requirement to "Require approval
for all outside collaborators." Record the trigger-design decision as a new ADR.

### Acceptance criteria

- [x] `ci-checks.yml`: `on:` is `push` only; `runs-on: [self-hosted, linux, ARM64]`
- [x] `ci-arm64.yml`: `on:` is `push` only; runner label unchanged; build/push steps unchanged
- [x] `ci-fork-checks.yml` exists: `on: pull_request`, `runs-on: ubuntu-latest`, job gated by
      `if: github.event.pull_request.head.repo.full_name != github.repository`
- [ ] Fork PR workflow approval set to "Require approval for all outside collaborators" —
      **manual step required**: no public REST API endpoint found for this setting
      (checked `actions/permissions` and `actions/permissions/workflow`, neither exposes it).
      Set it yourself at Settings → Actions → General → Fork pull request workflows.
- [x] New ADR added to `.agent-docs/adr/` documenting the push-only + SHA-matched
      status-checks + hosted-only fork fallback design (`0012-push-only-self-hosted-ci-with-hosted-fork-fallback.md`)
- [x] A real push on this branch triggers `ci-checks.yml`/`ci-arm64.yml` successfully on the
      self-hosted runner (verified via `gh run watch`: both completed successfully)

**Post-review follow-up**: the shared lint/type-check/security-scan steps in `ci-checks.yml`
and `ci-fork-checks.yml` were originally duplicated verbatim (a code-review Duplicated Code
finding). Extracted into `.github/actions/lint-checks/action.yml`, a composite action both
workflows now call. Re-verified working on a real push after the refactor.

---

## Add CODEOWNERS and require Code Owner review (#479)

**Blocked by**: None

**User stories**: 4

### What to build

Add `.github/CODEOWNERS` assigning every path to `mholubinka1`. Enable "Require review from
Code Owners" in a ruleset on `main` so it's enforced, not just advisory.

### Acceptance criteria

- [x] `.github/CODEOWNERS` contains `* @mholubinka1`
- [x] Ruleset on `main` has "Require review from Code Owners" enabled (verified via
      `gh api repos/.../rulesets`: ruleset id 20551010, enforcement "active")

---

## Disable automatic Copilot code review (#480)

**Blocked by**: None

**User stories**: 5

### What to build

Turn off "Automatically request Copilot code review" for this repo (via ruleset if available
there, else the repo's code review settings), leaving on-demand/manual Copilot review intact.

### Acceptance criteria

- [x] Automatic Copilot code review confirmed off at the repo-ruleset level (verified via
      `gh api repos/.../rulesets`: only the CODEOWNERS ruleset exists, no `copilot_code_review`
      rule present anywhere). **Manual follow-up recommended**: since no repo ruleset ever
      enabled this, the auto-review credits you observed likely come from your personal
      GitHub account's Copilot settings (Settings → Copilot → Code review), not a per-repo
      toggle — worth checking there directly, and it would apply across all 7 repos in scope
      at once rather than needing repeating per-repo.

---

## Remove auto_request_review.yml (#481)

**Blocked by**: #479

**User stories**: 4, 6

### What to build

Disable `auto_request_review.yml` via the Actions API/UI, then delete the workflow file and
its now-unused `.github/reviewers.yml` config in this same PR (accepting that end-to-end
CODEOWNERS reviewer-assignment coverage is proven post-merge, not pre-merge, since CODEOWNERS
is evaluated from the base branch).

### Acceptance criteria

- [x] `auto_request_review.yml` disabled via `gh api` before deletion (workflow id 140718204,
      state confirmed `disabled_manually`)
- [x] `.github/workflows/auto_request_review.yml` deleted
- [x] `.github/reviewers.yml` deleted
- [x] Follow-up note recorded for the user: after this PR merges, confirm `mholubinka1` is
      auto-assigned via CODEOWNERS on the next real PR

---
