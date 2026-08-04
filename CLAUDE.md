# CLAUDE.md

This repo is a **maintenance fork** of [bmoscon/cryptofeed](https://github.com/bmoscon/cryptofeed),
which was archived (read-only) on 2026-07-08 and will never receive fixes again. The fork exists
only to keep a small number of exchange integrations working. It is not an adoption of the library.

## Fork discipline (non-negotiable)

- **Minimal delta against upstream.** Never refactor, reformat, re-lint, or modernize upstream code.
- **No repo-wide formatters.** Do not run black/isort/autopep8/ruff-format or equivalent on any file.
- **Match local style.** Follow the existing style of the file you are editing, even where it is dated.
- **Leave the build alone.** Do not touch `setup.py`, `pyproject.toml`, or CI beyond what a change
  strictly requires.
- **Log every divergence** in `FORK_NOTES.md`: add a row to the patch log table (date, commit, files,
  reason) for each behavioral or structural change against upstream. This is mandatory, not optional.
- **No new config, tooling, or directories** unless explicitly requested.

## Workflow

- Work on a feature branch (`feat/<topic>`), never directly on `master`.
- Atomic commits: one logical change each.
- Integrate with a **fast-forward merge** to `master`. No merge commits, no squash.
- Run only the tests relevant to a change; much of the suite hits live exchanges and some upstream
  tests are stale. Report pre-existing failures, do not fix them.
