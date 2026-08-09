# Remove the hosted-only fork-PR fallback workflow

## Problem Statement

`ci-fork-checks.yml` was added in the CI/CD hardening work (PR #482) to give
external contributors' fork PRs automated lint/type-check/test coverage on
`ubuntu-latest`, once the self-hosted runner was made push-only and could no
longer see `pull_request` events at all.

On review, the justification doesn't hold for this project. The workflow was
never actually protecting anything: it always ran on GitHub's own hosted,
ephemeral infrastructure, never the owner's self-hosted runner — the
self-hosted exposure was already fully closed by the push-only trigger
redesign alone. What it provided instead was a convenience: an automated
signal on incoming contribution PRs before a human looks at them. This is a
solo-maintainer project with no history of external contributors, and
CODEOWNERS already requires human review before any merge regardless of
whether an automated check ran. Keeping the workflow meant carrying real,
ongoing complexity — a trusted-checkout pattern across two files, two
Copilot-caught trust gaps already fixed, and one residual gap
(`pyproject.toml`-driven tool config) explicitly documented as accepted-not-fixed
— for a feature whose only value is convenience that may never be exercised.

## Solution

Delete `.github/workflows/ci-fork-checks.yml` entirely. Fork PRs against
`main` will get zero automated checks going forward; the owner reviews (and,
if ever accepting a genuine external contribution, manually pulls/tests)
before merging. `ci-checks.yml` and `ci-arm64.yml` keep their push-only
trigger redesign unchanged — that part closes a real, previously-live
exploit and stays exactly as shipped in PR #482.

Record the reversal as a new ADR (`0013`) rather than editing ADR `0012`'s
history in place, since ADRs are a historical record of a decision made at
the time — the "why" for going push-only-plus-fallback was correct given
what was known then. Add a short pointer note to `0012`'s fork-fallback
paragraph marking it superseded by `0013`, without rewriting the original
reasoning.

## User Stories

1. As the repo owner, I want to stop maintaining a check-integrity pattern
   for a scenario (external contributions) that doesn't currently exist, so
   that CI stays simple and I'm not carrying a documented, unfixed trust gap
   for no benefit.
2. As a future reader of `.agent-docs/adr/`, I want to see that the
   fork-fallback decision was reversed and why, without the original ADR's
   reasoning being silently rewritten out from under me.

## Implementation Decisions

- Delete `.github/workflows/ci-fork-checks.yml`.
- No changes to `.github/actions/code-quality-checks/action.yml` — it's
  still used directly by `ci-checks.yml` (same-repo trust, no untrusted
  checkout involved there).
- No changes to `ci-checks.yml` or `ci-arm64.yml`'s triggers.
- Add `.agent-docs/adr/0013-remove-fork-pr-fallback-workflow.md` explaining
  the reversal.
- Amend `.agent-docs/adr/0012-push-only-self-hosted-ci-with-hosted-fork-fallback.md`
  with a short note pointing to `0013` on the now-superseded fork-fallback
  paragraph — leave the rest of the file (the push-only rationale, which is
  still accurate) untouched.

## Testing Decisions

No automated tests apply to a workflow-file deletion. Verification is
direct: confirm the file is gone, confirm no other workflow references
`ci-fork-checks.yml` or the `.trusted-config` path, and confirm a real push
still triggers `ci-checks.yml`/`ci-arm64.yml` successfully on the
self-hosted runner (unaffected by this change, but worth reconfirming since
it's the part that must keep working).

## Out of Scope

- Any change to the push-only trigger design itself.
- The other 6 repos in the CI/CD hardening follow-up spec — their spec
  needs a separate update (not part of this repo's implementation) to drop
  the "add a hosted-only fork fallback workflow" step from their plan,
  since the same reasoning applies there too.

## Further Notes

This repo's `main` branch has moved since PR #482 merged, so this branch is
created fresh from the current `origin/main`, not a continuation of the
merged worktree.
