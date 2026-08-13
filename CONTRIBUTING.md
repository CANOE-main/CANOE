# Contributing to CANOE

Thanks for your interest in contributing to CANOE. This guide covers how to report issues and how
to submit code changes.

## Reporting issues

Issues (bugs, feature requests, and questions) are tracked on [GitHub
Issues](https://github.com/CANOE-main/CANOE/issues) and are open to both internal team members and external users.

Before opening a new issue, please search existing issues to see if it's already been reported.

When filing a bug report, please include:

```
**Schema version:**
**Commit/tag:**
**Platform (Windows/macOS/Linux):**

**What is happening:**

**Expected behavior:**

**Error message (if any):**

**Configuration file:**
(paste your config here)
```

Tag your issue as accurately as you can (`bug`, `feature-request`, or `question`) so it's easy to
triage.

## Contributing code

### Branching

- `main` holds the latest, battle-tested code. **Direct pushes to `main` are
  forbidden**, and this rule is enforced by the repo.
- All development happens on `dev`. To make a change:

    1. Create a new branch off `dev`, named `initials/feature-name` (e.g. `yep/isolate-data-sources`).
    2. Make your changes and open a Pull Request from your branch into `dev`.
    3. Request approval from at least one dev team member.
    4. Once approved and all CI/CD checks pass, merge into `dev`.

- Squashing on merge is optional
- **Deleting the branch after merging is mandatory.** This doesn't delete your code: a branch is
  just a pointer to a commit, and merging into `dev` guarantees that commit is preserved. Leaving
  branches around just clutters the repo over time.

### Before opening a PR

- Make sure the **DCO (Developer Certificate of Origin) check** passes. This can break after a
  rebase, merge, or when committing with certain tools (e.g. Copilot).
- Run style checks locally before pushing:

    ```bash
    ruff check .
    ```

- All CI/CD checks must pass before a PR can be merged, please don't merge with failing checks,
  even if the failure looks unrelated to your change.

### Releases and versioning

Periodically, `dev` is merged into `main` and tagged. Tags follow the format `<schema>.<release>`. 
For example, `4.0.3` means schema version `4.0`, release `3`. If you're making a change that
affects the database schema, flag this explicitly in your PR description so it's reflected correctly
in the next tag.

## Questions

If something in this guide is unclear, or you're not sure where a change belongs, open an issue
with the `question` tag or reach out to the dev team ([Contact](contact.md)).
