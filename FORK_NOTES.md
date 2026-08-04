# Fork notes

`carloe/cryptofeed` is a maintenance fork of [bmoscon/cryptofeed](https://github.com/bmoscon/cryptofeed).

Upstream was archived (read-only) on 2026-07-08 at `v2.4.1` and will never receive fixes again.
This fork exists for one purpose: to keep the exchange integrations consumed by the downstream
`litquid` project working, as a pinned git dependency. It is not an adoption of the library, and no
attempt is made to maintain the parts of cryptofeed that `litquid` does not use.

## Ground rules

Every change here is a deliberate, minimal delta against upstream. Upstream code is not refactored,
reformatted, or modernized. See `CLAUDE.md` for the full working rules.

**Fork point:** `fe5993b0` (upstream `master`, identical to it at the time of forking).

## Patch log

| Date | Commit | Files | Reason |
| --- | --- | --- | --- |
