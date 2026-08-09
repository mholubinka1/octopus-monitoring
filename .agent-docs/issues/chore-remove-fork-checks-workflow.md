# Issues: chore-remove-fork-checks-workflow

## Remove ci-fork-checks.yml and record the reversal (#483)

**Blocked by**: None

**User stories**: 1, 2

### What to build

Delete `.github/workflows/ci-fork-checks.yml`. Add ADR `0013` explaining the
reversal (never protected anything beyond what push-only already closed,
solo-maintainer project, CODEOWNERS is the real gate, complexity wasn't
earning its keep). Add a short superseded-by-`0013` pointer to ADR `0012`'s
fork-fallback paragraph without rewriting its original reasoning.

### Acceptance criteria

- [x] `.github/workflows/ci-fork-checks.yml` deleted
- [x] No remaining reference to `ci-fork-checks.yml` or `.trusted-config`
      anywhere in the repo (grep confirms)
- [x] `ci-checks.yml` and `ci-arm64.yml` unchanged (still push-only,
      self-hosted, using the composite action directly)
- [x] `.agent-docs/adr/0013-remove-fork-pr-fallback-workflow.md` added
- [x] `.agent-docs/adr/0012-...md` has a pointer note added to its
      fork-fallback paragraph, rest of the file unchanged
- [x] A real push on this branch triggers `ci-checks.yml`/`ci-arm64.yml`
      successfully on the self-hosted runner (verified via `gh run watch`
      after clearing a stale `/tmp/gitleaks.tmp` on the runner's persistent
      disk — unrelated to this diff, a leftover from earlier rapid pushes
      in a prior session)

---
