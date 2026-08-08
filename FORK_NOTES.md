# Fork notes

`carloe/cryptofeed` is a maintenance fork of [bmoscon/cryptofeed](https://github.com/bmoscon/cryptofeed).

Upstream was archived (read-only) on 2026-07-08 and will never receive fixes again. It was archived
with `master` ahead of its last release: `v2.4.1` was tagged and published to PyPI on 2025-02-08, and
`master` then ran on for nine further commits over roughly a year, up to `fe5993b0` on 2026-01-31,
without another release ever being cut. This fork is taken from that unreleased `master`, not from
the `v2.4.1` release.

This fork exists for one purpose: to keep the exchange integrations consumed by the downstream
`litquid` project working, as a pinned git dependency. It is not an adoption of the library, and no
attempt is made to maintain the parts of cryptofeed that `litquid` does not use.

Every change here is a deliberate, minimal delta against upstream. Upstream code is not refactored,
reformatted, or modernized. See `CLAUDE.md` for the full working rules.

**Fork point:** `fe5993b0`, identical to upstream `master` at the time of forking.

**On the `v2.4.1-litquid.N` tag scheme:** the `v2.4.1` part is a naming convention only. It anchors
on the last upstream *release* because that is the only version number upstream ever published, and
because `pyproject.toml` still declares `version = "2.4.1"`. It is **not** a claim that the fork
point equals that release. Nine upstream commits, spanning 2025-02-08 to 2026-01-31, sit between
`v2.4.1` and the fork point — including the `setup.py`-to-`pyproject.toml` packaging migration
(see [section 2.1](#21-the-defect-is-inherited-not-introduced-here)). Anyone diffing this fork
against PyPI's `cryptofeed 2.4.1` will see those commits too, and they are upstream's work, not
this fork's. To see only the fork's delta, diff against `fe5993b0`.

## Patch log

| Date | Commit | Files | Reason |
| --- | --- | --- | --- |
| 2026-08-04 | `0ea4d9ba` | `CLAUDE.md`, `FORK_NOTES.md` | Fork maintenance docs. New files, no upstream code touched. |
| 2026-08-04 | `79b70972` | `cryptofeed/exchanges/bybit.py` | [Migrate `LIQUIDATIONS` to the `allLiquidation` topic](#1-bybit-liquidations-allliquidation-migration). Includes two deliberate behavior changes: [timestamp units](#11-behavior-change-timestamp-units) and [side mapping](#12-behavior-change-side-mapping-inverted), plus a [minor `raw` scope change](#13-minor-raw-payload-scope). |
| 2026-08-04 | `111e3955` | `tests/unit/test_bybit.py`, `examples/demo_bybit_all_liquidation.py` | Test coverage and a live smoke script for the above. New files, no upstream code touched. |
| 2026-08-04 | `ab6d776c` | `pyproject.toml` | [Ship the `cryptofeed` subpackages in source builds](#2-packaging-subpackages-excluded-from-source-builds). Inherited upstream defect; the only change to a build file, made under [strict necessity](#22-why-a-build-file-was-touched). |
| 2026-08-06 | `6b8b6a91` | `tests/unit/test_bybit.py` | [Pin the liquidation deltas to a recorded `allLiquidation` frame](#3-recorded-allliquidation-fixture). Test only, no behavior change. |
| 2026-08-06 | `91320542` | `cryptofeed/exchanges/kraken_futures.py` | [Stop lowercasing the websocket `product_id` at the dispatch point](#4-kraken-futures-websocket-product_id-case-drift). Kraken's REST instruments endpoint now returns uppercase symbols, so the transform broke every inbound message. Includes a [known test consequence](#45-known-consequence-test_exchange_playbackkraken_futures-now-fails). |
| 2026-08-06 | `2eb24a8a` | `tests/unit/test_kraken_futures.py` | Recorded-capture coverage for the above. New file, no upstream code touched. |
| 2026-08-06 | `706a937c` | `cryptofeed/exchanges/kraken_futures.py` | [Pass the book's exchange timestamp to `book_callback`](#5-kraken-futures-book-exchange-timestamp) on both the snapshot and delta paths. `OrderBook.timestamp` was delivered as `None`; conforms the outlier to the library's majority contract. |
| 2026-08-06 | `3c498d38` | `tests/unit/test_kraken_futures.py` | Recorded-capture coverage for both book paths, plus [the other exchanges reported but not changed](#53-the-rest-of-the-library-reported-not-changed). Test only. |
| 2026-08-06 | `ce382cba` | `cryptofeed/exchanges/kraken_futures.py` | One comment per book call site noting the positional argument is receipt time and the `timestamp=` kwarg is the exchange clock. [Comment only](#5-kraken-futures-book-exchange-timestamp), no behavior change. |
| 2026-08-06 | `4d164b86` | `tests/unit/test_exchange.py` | [Mark the `KRAKEN_FUTURES` playback case `xfail(strict=True)`](#6-the-kraken_futures-playback-case-is-now-xfailstrict). Restores the 42-failure baseline; only that one parameter is wrapped, the test body is untouched. |
| 2026-08-08 | `84bf6280` | `cryptofeed/exchanges/binance.py`, `cryptofeed/exchanges/binance_futures.py` | [Route USD-M futures streams to their required websocket base path](#8-binance-usd-m-futures-websocket-base-path-split). Binance decommissioned the legacy root on 2026-04-23; trades, liquidations, funding and candles were silently receiving nothing. Confined to futures by data - the [other four venues are byte-identical](#83-blast-radius-shared-code-confined-behavior). |
| 2026-08-08 | `4eaca29f` | `tests/unit/test_binance_futures.py` | Path-selection tests plus recorded-capture coverage for each recovered stream. New file, no upstream code touched. |

## Details

### 1. Bybit `LIQUIDATIONS` → `allLiquidation` migration

Bybit deprecated the `liquidation` websocket topic and throttled it to at most one order per second
per symbol, making it a sample rather than the full stream. `allLiquidation` publishes every
liquidation event, batched at 500ms, and covers USDT, USDC and inverse contracts. This fork must
emit the complete stream, so `LIQUIDATIONS` was migrated.

Docs: <https://bybit-exchange.github.io/docs/v5/websocket/public/all-liquidation>

Change sites in `cryptofeed/exchanges/bybit.py`:

- `websocket_channels[LIQUIDATIONS]`: `'liquidation'` → `'allLiquidation'`. This one value also
  drives the linear endpoint's `channel_filter` (a lookup into the same map) and the generic
  `f"{channel}.{pair}"` subscribe path, which now emits `allLiquidation.BTCUSDT`.
- `message_handler`: routed on `msg['topic'].startswith('liquidation')`, which does **not** match
  `allLiquidation.BTCUSDT` and would have silently dropped the channel. Now routes on
  `startswith('allLiquidation')`.
- `_liquidation`: `data` is now a list of `{T, s, S, v, p}` events rather than a single
  `{updatedTime, symbol, side, size, price}` object. The parser emits one `Liquidation` per element.

Inverse contracts need no counterpart change: `_parse_symbol_data` only queries the `linear` and
`spot` REST categories, so inverse instruments never enter the symbol universe at all. USDC perps
are `linear` category and already route through the linear websocket endpoint — verified live, both
`allLiquidation.BTCUSDT` and `allLiquidation.BTCPERP` are accepted there.

#### 1.1 Behavior change: timestamp units

**Upstream:** raw integer milliseconds, taken from the batch envelope (`msg['ts']`).
**Fork:** normalized float seconds, taken from each event's own `T`
(`self.timestamp_normalize(int(entry['T']))`).

Upstream passed `msg['ts']` straight into `Liquidation.timestamp`, which made Bybit liquidations the
only callback in the library not emitting float seconds — every other parser, including Bybit's own
`_trade` and `_book`, normalizes. `types.pyx` even asserts `isinstance(timestamp, float)`, but the
compiled extension let the integer through, so it went unnoticed.

This is deliberate and downstream-visible. Cross-exchange timestamp consistency is a hard
requirement for the consumer of this fork, and nothing depends on the old units. **Anyone diffing
fork output against upstream output will see this delta.**

#### 1.2 Behavior change: side mapping inverted

**Upstream:** `BUY if side == 'Buy' else SELL`.
**Fork:** `SELL if entry['S'] == 'Buy' else BUY`.

Bybit documents `S` as the *position* side: "When you receive a `Buy` update, this means that a long
position has been liquidated"
(<https://bybit-exchange.github.io/docs/v5/websocket/public/all-liquidation>). The deprecated
`liquidation` topic documented its `side` field with identical wording, so this is **not** a
semantic change introduced by the new topic — it is a pre-existing upstream bug that the migration
would otherwise have carried forward.

The library's de facto `Liquidation.side` contract is the side of the *forced order*, not the
liquidated position. All four other liquidation parsers emit `SELL` when a long is liquidated:

| Parser | Mapping | Source field |
| --- | --- | --- |
| `cryptofeed/exchanges/binance.py:245` | `SELL if o.S == 'SELL' else BUY` | forced order side |
| `cryptofeed/exchanges/bitmex.py:754` | `BUY if side == 'Buy' else SELL` | liquidation order side |
| `cryptofeed/exchanges/deribit.py:130` | `BUY if direction == 'buy' else SELL` | executed forced trade direction |
| `cryptofeed/exchanges/okx.py:120` | `BUY if side == 'buy' else SELL` | liquidation order side |

Bybit was the sole outlier. The mapping is inverted here to conform. No other exchange's parser was
modified — they already comply. The inversion is pinned by
`tests/unit/test_bybit.py::test_liquidation_side_inversion`, which carries a comment explaining why
it looks wrong but is right.

#### 1.3 Minor: `raw` payload scope

Upstream attached the whole message envelope (`raw=msg`). Since `allLiquidation` batches events, the
parser now emits one `Liquidation` per element with `raw=entry`, matching how `_trade` and `_candle`
handle list payloads. Attaching the full batch to each of N objects would be misleading.

### 2. Packaging: subpackages excluded from source builds

Upstream's `pyproject.toml` declared:

```toml
[tool.setuptools]
packages = ["cryptofeed"]
```

That is an explicit, non-recursive package list. It names exactly one package, so `cryptofeed.exchanges`,
`cryptofeed.backends` and `cryptofeed.util` were excluded from every wheel built from source. The failure is
total rather than partial: `cryptofeed/__init__.py` imports `FeedHandler`, and `cryptofeed/feedhandler.py`
imports `EXCHANGE_MAP` from `cryptofeed.exchanges`, so even a bare `import cryptofeed` raises
`ModuleNotFoundError: No module named 'cryptofeed.exchanges'`.

Replaced with a recursive find directive:

```toml
[tool.setuptools.packages.find]
include = ["cryptofeed*"]
```

Nothing else in the file was altered. No second package declaration exists anywhere that could reintroduce
this: `setup.py` carries only the Cython `ext_modules`, `MANIFEST.in` governs sdist file inclusion only, and
there is no `setup.cfg`.

#### 2.1 The defect is inherited, not introduced here

It predates the fork point. Upstream commit `de2f69a2` ("Move to pyproject.toml file for uv", 2026-01-31)
migrated packaging metadata out of `setup.py` and, in doing so, replaced `setup.py`'s `find_packages()` call
with the hand-written one-element list above. That commit is six commits before the fork point `fe5993b0`.
At the fork point, and up to this change, `git diff fe5993b0 -- pyproject.toml` was empty — the fork had
never touched the file.

Upstream's *published* artifacts never exhibited this. `v2.4.1` was released to PyPI on 2025-02-08, built
from a tree where packaging was still driven by `setup.py`'s `find_packages()`; the published
`cryptofeed-2.4.1-*.whl` files therefore contain all 90 modules. The `pyproject.toml` migration landed
almost a year later, on 2026-01-31, and upstream was archived on 2026-07-08 without ever cutting a release
from the migrated tree. No published artifact was ever built from the broken declaration, which is why the
defect sat unnoticed on `master`. (`build-wheels.sh` runs `pip wheel /io/`, which honors `pyproject.toml`;
it would not have masked the defect had it been run — it simply never was, post-migration.)

A git-dependency install has no such luck. `uv`/`pip` installing `cryptofeed @ git+https://…@<ref>` clones
the ref and runs a PEP 517 source build against exactly this `pyproject.toml`, so the consumer gets the
truncated wheel. That is the only way this fork is ever installed.

#### 2.2 Why a build file was touched

`CLAUDE.md` says to leave the build alone. This is the exception it allows for: *what a change strictly
requires*. The fork's sole purpose is to be installed as a pinned git dependency, and without this the
package does not import at all — there is no smaller change that yields a working install, and no
source-side workaround, because the defect is in the packaging declaration itself. The delta is two lines in
one declaration.

Verified by wheel manifest rather than by import alone. Built from the fixed tree, `RECORD` lists 99 entries
against the published `cryptofeed-2.4.1-cp313-cp313-macosx_11_0_arm64.whl`'s 97 (23 before the fix). The
sets of `.py` modules are identical in both directions — 90 each, zero difference. The four remaining
entries are all accounted for: `AUTHORS.md` and `LICENSE` moved from `*.dist-info/` to
`*.dist-info/licenses/`, which is a setuptools ≥ 77 relocation, not a content change; and `types.c` and
`types.pyx` are extra, both of which the *unfixed* build also produced, so neither is attributable to this
change (`types.pyx` comes from upstream's `[tool.setuptools.package-data]`, which did not exist at
`v2.4.1`; `types.c` is generated in-tree by `cythonize` during the build). Every non-`.py` data file
upstream ships is present.

#### 2.3 Source builds require setuptools >= 77

Recorded here as pre-existing documentation debt, not a new finding, and not changed by the above.

Upstream's `pyproject.toml` sets `license = "XFree86-1.1"` — a PEP 639 SPDX license *expression*. Support
for the string form landed in setuptools 77.0.0. Older setuptools accepts only the `{file = …}` or
`{text = …}` table forms and rejects the string during metadata generation:

```
ValueError: invalid pyproject.toml config: `project.license`.
configuration error: `project.license` must be valid exactly by one definition (2 matches found)
```

The `[build-system] requires` pin is the unversioned `"setuptools"`, so under PEP 517 build isolation — how
`uv` and `pip` build by default, including for git dependencies — a current setuptools is fetched and this
is satisfied automatically. Only a deliberate `--no-build-isolation` build against a pre-77 setuptools in
the ambient environment will fail. The `requires` pin is left alone rather than tightened, per minimal-delta
discipline; this note exists so the failure mode is recognizable if anyone hits it.

### 3. Recorded `allLiquidation` fixture

Sections [1.1](#11-behavior-change-timestamp-units) and [1.2](#12-behavior-change-side-mapping-inverted)
are the fork's two deliberate, downstream-visible deltas against upstream. Until now they were argued from
Bybit's documentation and pinned by fixtures hand-written from that same documentation — the tests and the
reasoning shared a single source, so neither could catch a misreading of it.

`tests/unit/test_bybit.py::test_liquidation_recorded_frame` closes that loop with a real frame, recorded off
the Bybit linear websocket on 2026-08-05, captured before parsing and never re-serialized. It is stored as
the raw string exactly as received and fed through `message_handler`, so routing and deserialization run as
they did live. It is the only fixture in the file that is evidence rather than interpretation, and it is
commented as such to keep it distinguishable from the doc-derived ones beside it.

The frame is useful specifically because its two clocks disagree: the event's own `T` is `1785905986808`
and the batch envelope `ts` is `1785905987246`, 438ms apart. A frame where they matched would parse
identically whether the code read the right field or the wrong one. The test asserts the full parsed
surface — symbol, side, quantity, price, timestamp — and both deltas are load-bearing in it: `S` is `Buy`,
so a long was liquidated, and the assertion is `SELL`.

Both assertions were confirmed to bite by mutating the parser and observing the failure: reverting the side
mapping to upstream's verbatim form fails it, and sourcing the timestamp from the envelope `ts` fails it.
The parser was restored immediately; no upstream source file was modified by this change.

The capture came from a 30-minute live run by the downstream `litquid` collector on 2026-08-05, which
recorded 35 `allLiquidation` events across 55 symbols, all of which reconciled to correctly parsed rows.
One representative frame is vendored here; the fork does not carry the capture set.

### 4. Kraken Futures websocket `product_id` case drift

`KRAKEN_FUTURES` was **entirely non-functional** in this fork before this change — not degraded on one
channel, dead on all of them. `message_handler` has a single dispatch point that resolves the symbol
before routing to any parser:

```python
# As per Kraken support: websocket product_id is uppercase version of the REST API symbols
pair = self.exchange_symbol_to_std_symbol(msg['product_id'].lower())
```

Every inbound message — trades, `ticker_lite`, `ticker` (which drives both funding and open interest),
`book` and `book_snapshot` — passes through that one line, so a failing lookup takes out the whole
exchange. It raised `UnsupportedSymbol` on every message.

The `.lower()` is now removed; the wire value is used verbatim. The comment above it, which documented
the assumption that no longer holds, was corrected in the same two-line change. Nothing else in the file
was touched.

#### 4.1 The assumption was true when written, and Kraken changed it

This is exchange-API drift, not an upstream mistake. The repo contains the proof at both ends of the
timeline, because upstream's own playback fixture is a 2021 capture of *both* sides of the API:

| | REST `/derivatives/api/v3/instruments` `symbol` | Websocket `product_id` |
| --- | --- | --- |
| `sample_data/KRAKEN_FUTURES.0`, captured 2021-07-22 | `pi_xbtusd` (27/27 lowercase) | `FI_XBTUSD_210730` (uppercase) |
| Live, fetched 2026-08-06 | `PI_XBTUSD` (298/298 uppercase, 0 lowercase) | `PF_XBTUSD` (uppercase) |

In 2021 the REST endpoint returned lowercase and the websocket returned uppercase, so lowercasing the
wire value was exactly right and the comment was accurate. Kraken has since changed the REST instruments
endpoint to return uppercase. The websocket never changed. The two sides now agree verbatim, and the
transform is what breaks them apart.

#### 4.2 Evidence: the wire value and the map keys, verbatim

The reverse map is built in `Exchange.__init__` as `{value: key for key, value in
normalized_symbol_mapping.items()}`, and `_parse_symbol_data` stores `ret[s.normalized] =
entry['symbol']` — the REST string **untransformed**. So the map keys are whatever case Kraken's REST
returns.

Captured 2026-08-06 off `wss://futures.kraken.com/ws/v1`, subscribed to `PF_XBTUSD`, 27449 frames in
60 seconds. The only `product_id` value that appeared, across all 27444 data frames:

```
'PF_XBTUSD'  x27444
```

The reverse symbol map built from the live REST endpoint, 288 entries, first few:

```
'PF_XBTUSD' -> 'BTC-USD-PERP'
'PF_ETHUSD' -> 'ETH-USD-PERP'
'PF_LTCUSD' -> 'LTC-USD-PERP'
```

288 of 288 keys contain an uppercase character; 0 contain a lowercase character. `'PF_XBTUSD' in map`
is `True`, `'pf_xbtusd' in map` is `False`. The two agree exactly, in verbatim uppercase — there is no
prefix or separator difference, so removing the transform is the whole fix and nothing more is needed.

Reproduced against a recorded trade frame before fixing:

```
cryptofeed/exchanges/kraken_futures.py:250, in message_handler
    pair = self.exchange_symbol_to_std_symbol(msg['product_id'].lower())
cryptofeed.exceptions.UnsupportedSymbol: pf_xbtusd is not supported on KRAKEN_FUTURES
```

#### 4.3 Audit: every case transform in the file

The file contains exactly two, and only one is a defect. Both are listed because the assumption behind
the broken one could plausibly recur:

| Line | Site | Transform | Verdict |
| --- | --- | --- | --- |
| 61 | `_parse_symbol_data` | `entry['symbol'].upper().split("_", maxsplit=1)` | **Harmless, left alone.** |
| 250 | `message_handler` dispatch | `msg['product_id'].lower()` | **The defect. Removed.** |

Line 61 is safe for two independent reasons. It is currently a no-op — all 298 live REST symbols are
already uppercase — and, more importantly, its result is used *only* to derive the parsed pieces
(`ftype`, `base`, `quote`, `expiry`). The value actually stored in the map is `entry['symbol']`,
the original untransformed string, so line 61 cannot affect a map key no matter what Kraken returns.
Verified: every stored map value appears verbatim in the REST response, and none differs from its
source by case. It is also load-bearing for the `_kraken_futures_product_type[ftype]` lookup, whose
keys are uppercase, so it is left exactly as it is.

For completeness, the outbound path applies no transform at all: `subscribe` sends
`self.subscription[chan]`, which `Feed` populates via `std_symbol_to_exchange_symbol` — again the
verbatim REST string. It emits `product_ids: ['PF_XBTUSD']`, which the exchange accepts. Outbound was
therefore always correct; only inbound applied a transform, and the two paths disagreed. They now agree.

No other file was audited or changed under this entry.

#### 4.4 How it surfaced

The downstream `litquid` collector ran `KRAKEN_FUTURES` and recorded **zero parsed events** alongside a
reconnect storm consuming **6.41 GB/day**. The failure mode is self-sustaining: `UnsupportedSymbol`
escapes `message_handler`, kills the connection handler, the feed reconnects, replays a `book_snapshot`,
and raises again on the first message. Bandwidth is consumed at full rate while nothing is ever parsed.

#### 4.5 Known consequence: `test_exchange_playback[KRAKEN_FUTURES]` now fails

This test passed before the change and fails after it. It is **not** a pre-existing failure and is
recorded here rather than papered over.

`tests/unit/test_exchange.py::test_exchange_playback` replays `sample_data/KRAKEN_FUTURES.*`, which
seeds the symbol map from the *recorded 2021 REST response* — the lowercase one in the table above —
and then feeds it 2021 websocket frames carrying uppercase `product_id`s. That pairing only resolves if
the code lowercases, so the fixture pins the pre-drift API contract by construction:

```
cryptofeed.exceptions.UnsupportedSymbol: FI_BCHUSD_210730 is not supported on KRAKEN_FUTURES
Playback failed on message: {"feed":"book_snapshot","product_id":"FI_BCHUSD_210730", ...}
```

`FI_BCHUSD_210730` is a fixed-maturity contract that expired on 2021-07-30 and has not existed for five
years. The test cannot pass against both the 2021 fixture and the 2026 exchange; passing it and working
against live Kraken are mutually exclusive.

It is left failing deliberately. Fixing it would mean re-recording upstream's `sample_data` capture and
rewriting the `lookup_table` callback counts in `tests/unit/test_exchange.py` — a large delta to
upstream test assets, well beyond this change, and it would amount to fabricating a new upstream
fixture. Making the lookup case-insensitive instead was rejected for a different reason: it would keep
the stale test green precisely by masking the class of drift this fork exists to detect.

Aside from this one test, the fix introduces no other change in suite results — the before/after failure
sets are otherwise identical.

**Update:** it is no longer a bare failure. As of [section 6](#6-the-kraken_futures-playback-case-is-now-xfailstrict)
it carries `xfail(strict=True)`, which restores the suite baseline to its original 42 failures while
keeping the condition asserted rather than ignored.

#### 4.6 Unrelated findings, reported but not changed

Two pre-existing upstream defects were found while gathering the evidence above. Neither is touched.

**`PI_XBTUSD` is not delisted, it is shadowed.** It is present and `tradeable: true` in the live REST
response, but absent from the symbol map. `_parse_symbol_data` writes `ret[s.normalized]`, and
`PI_XBTUSD` (inverse perp) and `PF_XBTUSD` (linear multi-collateral perp) both normalize to
`BTC-USD-PERP`. Last write wins, so `PF_` overwrites `PI_`. Ten normalized symbols collide this way —
298 tradeable instruments produce only 288 map entries:

```
BTC-USD-PERP  <- ['PI_XBTUSD', 'PF_XBTUSD']   (map keeps 'PF_XBTUSD')
ETH-USD-PERP  <- ['PI_ETHUSD', 'PF_ETHUSD']   (map keeps 'PF_ETHUSD')
BTC-USD-26U25 <- ['FF_XBTUSD_260925', 'FI_XBTUSD_260925']   (map keeps 'FI_XBTUSD_260925')
```

The inverse perpetuals and half the fixed-maturity contracts are therefore unreachable by normalized
symbol. Fixing it requires a normalization scheme that distinguishes the product types, which changes
public symbol names — far outside this change.

**The book feed's exchange timestamp is discarded.** — **Superseded by [section 5](#5-kraken-futures-book-exchange-timestamp),
which fixes it. Left here for the record of what was found.** Kraken's book frames *do* carry a real
exchange clock: all 27249 `book` frames in the capture, plus `book_snapshot`, include `"timestamp"` in
epoch milliseconds. `_book` and `_book_snapshot` both assign it to the `OrderBook`. That assignment was
dead code — `Feed.book_callback` (`cryptofeed/feed.py:242`) then executes an unconditional
`book.timestamp = timestamp` from its own keyword argument, which `kraken_futures` did not pass, so it
was overwritten with `None`.

At the time this section was written the answer to the downstream question was that the book feed did
*not* differ from the ticker in what it delivers — both arrived as `None`, for different reasons.
`Ticker` is constructed `timestamp=None` because `ticker_lite` genuinely carries no time field at all
(its keys are bid/ask/change/premium/volume/tag/pair/dtm/maturityTime/volumeQuote/product_id/feed —
confirmed against the capture). The book feed *had* the timestamp and lost it downstream. **That is no
longer true of the book feed as of section 5**; the `ticker_lite` half of the answer still stands.

### 5. Kraken Futures book exchange timestamp

`OrderBook.timestamp` was delivered as `None` on every `L2_BOOK` callback, so consumers could not tell
when the exchange actually produced a book update and had to fall back on local receipt time. The
exchange timestamp was present on the wire and correctly parsed the whole time — it was thrown away one
line later.

Both book paths compute it and neither passed it on:

```python
self._l2_book[pair].timestamp = self.timestamp_normalize(msg["timestamp"]) if "timestamp" in msg else None

await self.book_callback(L2_BOOK, self._l2_book[pair], timestamp, raw=msg, sequence_number=msg['seq'])
```

`Feed.book_callback` (`cryptofeed/feed.py:242`) then runs `book.timestamp = timestamp` unconditionally
from its own keyword argument, which defaults to `None`. The assignment above it was therefore dead,
and the `timestamp` passed positionally is the *receipt* time filling `receipt_timestamp`, not this.

The fix adds `timestamp=self._l2_book[pair].timestamp` to both calls. Nothing is deleted and the two
upstream computation lines are untouched — they simply become load-bearing again instead of dead. This
is the same category as the [§1.2 side inversion](#12-behavior-change-side-mapping-inverted): conforming
an outlier to the library's de facto majority contract, not inventing new behavior.

Each call site carries a one-line comment saying the positional argument is the receipt time and the
kwarg is Kraken's own clock. Both now read `book_callback(L2_BOOK, book, timestamp, timestamp=...)`,
which scans as a duplicate argument and would otherwise be a standing invitation to "clean up". Same
standard as the do-not-revert comment on the [§1.2](#12-behavior-change-side-mapping-inverted) side
inversion: a line that looks wrong and is right gets a comment saying so.

#### 5.1 Both book paths, and both needed it

`KrakenFutures` has exactly two `book_callback` call sites, one per websocket feed. Kraken sends a
`book_snapshot` on subscribe and after any resync, then a `book` delta per change:

| Path | Method | Feed | Call site | Passed `timestamp=` before | Changed |
| --- | --- | --- | --- | --- | --- |
| Snapshot | `_book_snapshot` | `book_snapshot` | line 175 | No | **Yes** |
| Delta | `_book` | `book` | line 208 | No | **Yes** |

There is no third path — no partial-book or REST-seeded variant, unlike `binance.py`, whose `_snapshot`
is REST-seeded. Both were broken identically and both are fixed.

Fixing only one would have been the realistic failure, since the two call sites are 33 lines apart and
look different (one carries `delta=`, the other does not) — and four exchanges in this library
demonstrably have exactly that bug already (see [5.3](#53-the-rest-of-the-library-reported-not-changed)).
The two paths are therefore pinned by two separate tests, and each was mutation-checked on its own; see
[5.2](#52-evidence).

#### 5.2 Evidence

Two recorded frames, captured off `wss://futures.kraken.com/ws/v1` on 2026-08-06, stored byte-for-byte
as received and never re-serialized. Each is stored alongside the **local receipt time measured at the
instant the frame arrived**, so the clock gaps quoted below are real measurements, not numbers chosen to
make the assertions look strong.

**Delta** — the widest-diverging frame in a 31435-frame capture:

```
{"feed":"book","product_id":"PF_XBTUSD","side":"buy","seq":17132345,"price":64382.0,"qty":7.8852,"timestamp":1786047745831}
```

Exchange clock `1786047745.831`, measured receipt `1786047745.95403` — **123ms apart**. Across that
capture the divergence ran min −36ms, median −33ms, max +123ms, so this is the strongest discriminator
the wire actually offered; a frame picked at random would separate the two clocks by roughly 33ms.

**Snapshot** — a thin fixed-maturity contract whose book had not ticked for nearly six seconds:

```
{"feed":"book_snapshot","product_id":"FF_XBTUSD_260807","timestamp":1786047818552,"seq":140098,"tickSize":null,"bids":[...],"asks":[...]}
```

Exchange clock `1786047818.552`, measured receipt `1786047824.30581` — **5.754s apart**. `PF_XBTUSD`'s
own snapshot was unusable as a fixture for two reasons: it is 93986 characters (1800 bids, 1281 asks),
and its clocks sat only 30ms apart. Subscribing to an illiquid instrument produced a 341-character
snapshot with a gap two orders of magnitude wider.

The gaps are what make the fixtures load-bearing. A frame whose exchange timestamp and receipt time
coincided would assert equally well against code that read `msg['timestamp']`, code that substituted the
receipt time, and code that fabricated a plausible-looking value. These separate all three, and the
tests assert the inequality explicitly (`> 5.0` and `> 0.1` seconds respectively) rather than only the
equality.

**Mutation.** Reverting the fix fails the tests — checked three ways, because "fixed one path, missed
the other" is the failure mode that matters here:

| Mutation | Result |
| --- | --- |
| Revert both call sites (upstream state) | `2 failed, 5 passed` — both timestamp tests |
| Revert **only** line 175 (snapshot), delta left fixed | `1 failed, 6 passed` — snapshot test only |
| Revert **only** line 208 (delta), snapshot left fixed | `1 failed, 6 passed` — delta test only |

```
>       assert book.timestamp == 1786047745.831
E       assert None == 1786047745.831
E        +  where None = exchange: KRAKEN_FUTURES symbol: BTC-USD-PERP ... timestamp: None.timestamp
```

Each path fails independently and only its own test, so neither test is carrying the other. The parser
was restored immediately after each mutation.

**Live.** Confirmed against all three venues the downstream project consumes, same run, after the fix:

```
BINANCE_FUTURES  book.timestamp = 1786048037.884   raw['E']         = 1786048037884
BYBIT            book.timestamp = 1786048036.128   raw['ts']        = 1786048036128
KRAKEN_FUTURES   book.timestamp = 1786048036.99    raw['timestamp'] = 1786048036990
```

Kraken previously delivered `None` here. All three now deliver the exchange's own clock as normalized
float seconds, so `book.timestamp` is directly comparable across the three venues.

#### 5.3 The rest of the library: reported, not changed

Scope is `KRAKEN_FUTURES` only — this fork maintains what `litquid` uses. The same defect exists
elsewhere and is deliberately left alone; recorded here so anyone who later depends on one of these
knows before trusting `book.timestamp`. Counted by AST over every `book_callback` call site in
`cryptofeed/exchanges/`, not by grep, so multi-line calls are included.

Of 32 files that call `book_callback`, 18 always pass `timestamp=`, 10 never do, and 4 pass it on one
path but not the other.

**Never pass it — `book.timestamp` is always `None`** (9 remaining after this change):

`bitfinex.py`, `bitflyer.py`, `bitmex.py`, `blockchain.py`, `dydx.py`, `gemini.py`, `kraken.py`,
`kucoin.py`, `probit.py`

**Split between paths — `book.timestamp` is populated on some callbacks and `None` on others**, which
is the more dangerous shape because it looks like it works until it intermittently does not:

| File | Passes | Drops |
| --- | --- | --- |
| `coinbase.py` | line 148 | line 130 |
| `gateio.py` | line 193 | line 131 |
| `gateio_futures.py` | line 236 | line 174 |
| `independent_reserve.py` | line 184 | line 207 |

`kraken.py` (spot) is the notable omission from this change: it is the sibling of the exchange fixed
here and has the same defect on both its call sites (lines 134 and 161). It is untouched because
`litquid` does not consume Kraken spot. Fixing it would be a two-line change of the same shape if that
ever changes.

Consumers of any exchange in either list must read the exchange clock off `book.raw` and normalize it
themselves. The key differs per exchange — `'timestamp'` for Kraken Futures, `'E'` for Binance, `'ts'`
for Bybit — and the raw values are unnormalized integer milliseconds, so a fallback written as
`book.timestamp or book.raw.get(...)` would silently mix seconds and milliseconds.

### 6. The `KRAKEN_FUTURES` playback case is now `xfail(strict)`

[Section 4.5](#45-known-consequence-test_exchange_playbackkraken_futures-now-fails) explains why
`tests/unit/test_exchange.py::test_exchange_playback[KRAKEN_FUTURES]` cannot pass: its `sample_data`
fixture seeds the symbol map from a 2021 REST response carrying **lowercase** symbols, then replays
websocket frames carrying **uppercase** `product_id`s. That pairing resolves only if the code lowercases
the wire value, which is exactly the drift [section 4](#4-kraken-futures-websocket-product_id-case-drift)
removed. It fails on `FI_BCHUSD_210730`, a fixed-maturity contract that expired on 2021-07-30.

It now carries `pytest.mark.xfail(strict=True)` on that one parameter. Only the `KRAKEN_FUTURES` entry
in the existing `parametrize` list is wrapped in `pytest.param(...)`; every other exchange is passed
through unchanged, and the test body is not touched.

**Why strict.** A plain `xfail` would silently swallow a later pass, which is the failure mode that
matters here — the marker would outlive the condition it documents and quietly assert nothing. Under
`strict=True` the marker is itself an assertion: if the fixtures are ever re-recorded against the
current API, the case starts passing, `XPASS(strict)` fails the suite, and whoever did the re-recording
is told to delete the marker. Verified by restoring `.lower()`, which makes the case replay again:

```
tests/unit/test_exchange.py::test_exchange_playback[KRAKEN_FUTURES] FAILED
[XPASS(strict)] 2021 fixture pins the pre-drift lowercase REST symbols, see FORK_NOTES 4.5
```

The parser was restored immediately.

**What was not done, and why.** `sample_data` was not re-recorded — that is a large delta to upstream
test assets and would mean authoring a new upstream fixture, including rewriting the `lookup_table`
callback counts. The symbol lookup was not made case-insensitive — that would turn the case green
precisely by masking the class of drift this fork exists to catch, which is the worse outcome of the
two even though it is the smaller diff.

**Effect on the baseline.** The unit suite returns to **42 pre-existing failures**, the count from
before [section 4](#4-kraken-futures-websocket-product_id-case-drift), and the failure set is otherwise
byte-identical to that baseline — verified by diffing the sorted `FAILED` lines, not by comparing
totals. The 42 are upstream staleness in `test_symbol_normalization` (39, live REST calls) and
`test_exchange_playback` (3: `BIT.COM`, `BYBIT`, `COINBASE`). None are touched.

### 7. `order_book` 0.7.0 build gate

Report only. No fork change follows from this and none was made; recorded because the downstream
project's Python 3.13 decision was verified against `order_book` 0.6.1 and a clean install from this
fork now resolves 0.7.0. `pyproject.toml` pins `order_book>=0.6.0` and was **not** modified.

**Result: PASS**, on all four checks.

| Check | Result |
| --- | --- |
| Clean venv resolves | `order-book==0.7.0` on Python 3.13.12 |
| Builds from sdist | Yes — `uv pip install --no-binary order-book` → `Built order-book==0.7.0` |
| Imports on 3.13 | Yes — `order_book.cpython-313-darwin.so`, macOS 26.5.2 arm64 |
| bid/ask roundtrip | Yes — see below |

```
best bid         : (Decimal('64401.0'), Decimal('0.1239'))
best ask         : (Decimal('64402.0'), Decimal('0.1179'))
after update, bid 64401 : 7.8852
after delete, best ask  : (Decimal('64416.0'), Decimal('0.0568'))
sorted bid keys         : [Decimal('64401.0'), Decimal('64400.0'), Decimal('64399.0')]
value type roundtrip    : Decimal == Decimal('7.8852')
```

Insert, keyed lookup, in-place update, delete, descending/ascending ordering and `SortedDict(ordering=
'DESC')` all behave, and `Decimal` survives the C boundary in both directions rather than degrading to
`float` — which matters because every cryptofeed parser feeds `Decimal` prices and sizes into the book.

**One premise correction.** The gate was framed on the assumption that `order_book` publishes no cp313
or macOS ARM64 wheels and so builds from sdist every time. That is no longer true at 0.7.0, which
publishes six wheels:

```
order_book-0.7.0-cp312-cp312-macosx_11_0_arm64.whl
order_book-0.7.0-cp312-cp312-manylinux2014_x86_64...whl
order_book-0.7.0-cp313-cp313-macosx_11_0_arm64.whl
order_book-0.7.0-cp313-cp313-manylinux2014_x86_64...whl
order_book-0.7.0-cp314-cp314-macosx_26_0_arm64.whl
order_book-0.7.0-cp314-cp314-manylinux2014_x86_64...whl
order_book-0.7.0.tar.gz
```

A default `uv`/`pip` install on cp313 macOS ARM64 or manylinux x86-64 therefore takes the **wheel** and
compiles nothing — confirmed: a clean venv install pulled the wheel without a build step. The sdist path
above was forced with `--no-binary` specifically to test the case the gate was worried about. Both paths
work, so the concern is resolved from both directions; note only that cp314 macOS wheels are built
against `macosx_26_0`, so a cp314 install on an older macOS falls back to sdist.

Additionally verified end to end rather than in isolation: this fork installed clean into a fresh 3.13
venv against the sdist-built 0.7.0 (`cryptofeed 2.4.1`, `order-book 0.7.0`), imported, and ran its
Kraken Futures suite — `7 passed`. So the fork's Cython `types.pyx` `OrderBook` works against 0.7.0, not
just the extension in isolation.

### 8. Binance USD-M futures websocket base path split

Binance split the USD-M futures websocket into three purpose-specific base paths — `/public`,
`/market` and `/private` — and **permanently decommissioned the legacy root on 2026-04-23**.

The critical property, and the reason this went unnoticed: **the stream names did not change. The base
path is what now selects which streams a connection may receive.** `btcusdt@aggTrade` is still spelled
`btcusdt@aggTrade`; it simply no longer delivers anything unless you asked for it under `/market`.

Docs: <https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Important-WebSocket-Change-Notice>

> After the upgrade, any connections not migrated will ONLY be able to receive data from
> `wss://fstream.binance.com/public`. Channels under `/market` and `/private` will stop pushing data.

The fork built every subscription on the bare root, so it was an unmigrated connection: it kept
receiving the `/public` streams and silently received nothing for everything else.

#### 8.1 Why it was invisible at every layer above

The legacy root does not reject an unmigrated connection. It accepts the TCP connect, completes the
websocket handshake, accepts the combined-stream URL including the `/market` stream names, returns no
error frame, does not close, and then simply never sends those streams. Meanwhile the `/public` streams
on the same connection keep flowing normally.

Every signal a consumer could reasonably monitor therefore looks healthy:

- the connection is up, so no reconnect loop and no connection alarm
- `bookTicker` and `depth` keep arriving, so the feed is demonstrably "working" and traffic volume
  stays high — this is what makes it worse than an outright outage
- no exception is raised anywhere, so `log_message_on_error` and the exception handler see nothing
- cryptofeed's `message_handler` routes on `msg['stream']`, and a stream that never arrives is not an
  unknown message — there is no "unexpected message" warning to log

The failure is indistinguishable from a genuinely quiet market unless you know the expected rate of a
specific channel. Liquidations in particular are sparse and bursty by nature, so zero liquidations for
an hour is not obviously wrong. The downstream consumer lost Binance liquidations outright and the only
symptom was an absence.

Reproduced end to end. The same live smoke, same 60 symbols, same channel set, run against the legacy
root (90s) and against the fix (180s):

| Channel | Stream | Legacy root | Fixed |
| --- | --- | --- | --- |
| TRADES | `aggTrade` | **0** | 4667 |
| LIQUIDATIONS | `forceOrder` | **0** | 1 |
| FUNDING | `markPrice` | **0** | 3600 |
| CANDLES | `kline_1m` | **0** | 180 |
| TICKER | `bookTicker` | 34452 | 71147 |
| L2_BOOK | `depth` | 18820 | 39442 |
| OPEN_INTEREST | REST poll | 234 | 432 |

Four channels at exactly zero, with no error, no disconnect, and two other channels streaming tens of
thousands of messages beside them.

#### 8.2 Channel to base path mapping

Every row was verified twice: against Binance's current documentation, and against a live frame
captured on 2026-08-08 on the path in question. Counts are frames received in a single 30s window with
all six streams on one combined connection per path.

| cryptofeed channel | Stream built | Path | Live on legacy root | Live on `/market` |
| --- | --- | --- | --- | --- |
| `TRADES` | `<sym>@aggTrade` | `/market` | 0 | 62 |
| `FUNDING` | `<sym>@markPrice` | `/market` | 0 | 10 |
| `CANDLES` | `<sym>@kline_<interval>` | `/market` | 0 | 45 |
| `LIQUIDATIONS` | `<sym>@forceOrder` | `/market` | 0 | see below |
| `TICKER` | `<sym>@bookTicker` | `/public` | 3858 | 0 |
| `L2_BOOK` | `<sym>@depth@<interval>` | `/public` | 293 | 0 |
| `OPEN_INTEREST` | — | n/a | REST poll on `fapi`, not a websocket stream |

Note the mapping is not "everything moved" — `bookTicker` and `depth` return **zero** on `/market`. A
blanket switch of the base path would have restored trades and liquidations while silently killing the
order book and ticker, converting one outage into another. Per-channel selection is required.

**`FUNDING` is markPrice-derived, confirmed in code and on the wire.**
`BinanceFutures.websocket_channels[FUNDING]` is `'markPrice'`, and `Binance.message_handler` routes
`msg['e'] == 'markPriceUpdate'` to `_funding`. There is no separate funding stream. So funding lives on
`/market` and died with trades and candles, which is not obvious from the channel name.

**`LIQUIDATIONS` needed its own check.** The per-symbol `<sym>@forceOrder` stream — which is what
cryptofeed builds, *not* the market-wide `!forceOrder@arr` — is sparse enough that a short window
proves nothing. Two runs settled it:

- 200s, 6 major symbols: 0 per-symbol events on every path, but `!forceOrder@arr` returned 37 on
  `/market` and 0 on the legacy root in the same concurrent window. Conclusive for the array form,
  inconclusive for per-symbol.
- 260s, 10 symbols, `!forceOrder@arr` and per-symbol on the same connection: the array reported 3
  liquidations for watched symbols and the per-symbol streams reported exactly those same 3, 1:1. So
  per-symbol `forceOrder` is **alive** on `/market` — the earlier zero was a quiet window, not death.
- 240s, 120 perpetuals, legacy root and `/market` concurrently: **0** events on the legacy root, **6**
  on `/market`, including `btcusdt@forceOrder`.

No change to the liquidation stream name was needed; it was purely a path problem.

#### 8.3 Blast radius: shared code, confined behavior

`_address()` is defined **once**, on `Binance` (`cryptofeed/exchanges/binance.py:91`), and inherited
unmodified by all five venues in the family — `BINANCE`, `BINANCE_FUTURES`, `BINANCE_DELIVERY`,
`BINANCE_US`, `BINANCE_TR`. No subclass overrides it. So the change could not be made in
`binance_futures.py` alone without duplicating the whole method.

It is confined by **data rather than by branching**. `Binance` gains an empty class attribute
`stream_base_paths = {}`; `_address()` groups the streams it builds by
`stream_base_paths.get(normalized_chan, '')` and emits one address per group. Only `BinanceFutures`
populates the map. Every other venue looks up an empty dict, gets `''`, and produces exactly the URL it
produced before.

Verified by dumping every venue's built addresses before and after the change under a pinned
`PYTHONHASHSEED` (the stream order within a URL varies per process otherwise, which would have made a
naive diff look like a change). The complete diff across all five venues:

```
15c15,16
<   "wss://fstream.binance.com/stream?streams=btcusdt@depth@100ms/btcusdt@markPrice/btcusdt@bookTicker/btcusdt@kline_1m/btcusdt@forceOrder/btcusdt@aggTrade"
---
>   "wss://fstream.binance.com/market/stream?streams=btcusdt@markPrice/btcusdt@kline_1m/btcusdt@forceOrder/btcusdt@aggTrade",
>   "wss://fstream.binance.com/public/stream?streams=btcusdt@depth@100ms/btcusdt@bookTicker"
```

`BINANCE`, `BINANCE_US`, `BINANCE_TR` and `BINANCE_DELIVERY` are byte-identical.

**COIN-M (`BINANCE_DELIVERY`) is genuinely unaffected, not merely untouched.** Probed live on
2026-08-08: `wss://dstream.binance.com` (the legacy root) still delivers every stream —
`btcusd_perp@aggTrade`, `@markPrice`, `@kline_1m`, `@bookTicker` and `@depth@100ms` all returned frames
in a 25s window. The split is USD-M only. Had COIN-M been changed to match, it would have broken a
working feed.

#### 8.4 Consequence: futures now opens two connections

A subscription spanning both paths can no longer share one websocket, so `_address()` returns a list
and `Feed.connect` opens one connection per address. This is not new machinery — `_address()` already
returned a list when the stream count exceeded `per_connection_limit`, and `connect()` already handled
it (`cryptofeed/feed.py:210`). What changes is that multiple connections become the normal case for
futures rather than a rarity at 1024+ streams.

One knock-on worth recording. `Binance.subscribe()` calls `self._reset()`, which clears `_l2_book` and
`last_update_id` for **all** pairs. With two connections, a reconnect on the `/market` connection resets
the book state owned by the `/public` connection. This self-heals rather than corrupting: `_book()`
re-fetches a REST snapshot when a pair is missing (`binance.py:317`), so the cost is an extra snapshot
fetch, not a wrong book. The behavior is pre-existing and is left alone under minimal-delta discipline;
it is noted here because this change makes it reachable in ordinary operation.

#### 8.5 Not changed: the authenticated `/private` path

`_address()` still builds authenticated connections as `<root>/ws/<listenKey>`, which per the same
notice should now be `/private`. This is **not** fixed here, for two reasons: `litquid` consumes only
public market data, and verifying it requires live API credentials that were not available, so any
change would have been unverified. Anyone using `BinanceFutures` with `BALANCES`, `ORDER_INFO` or
`POSITIONS` should expect the user-data stream to be affected and should test before relying on it.

Likewise `!markPrice@arr`, `miniTicker`, `ticker`, `continuousKline`, `compositeIndex`, `contractInfo`
and `assetIndex` are documented as `/market` streams but are not channels this fork's `BinanceFutures`
subscribes, so no mapping entry exists for them.
