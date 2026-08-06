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

**The book feed's exchange timestamp is discarded.** Kraken's book frames *do* carry a real exchange
clock: all 27249 `book` frames in the capture, plus `book_snapshot`, include `"timestamp"` in epoch
milliseconds. `_book` and `_book_snapshot` both assign it to the `OrderBook`. That assignment is dead
code — `Feed.book_callback` (`cryptofeed/feed.py:242`) then executes an unconditional
`book.timestamp = timestamp` from its own keyword argument, which `kraken_futures` never passes, so it
is overwritten with `None`.

This answers the question the downstream project needs settled: **the book feed does not differ from
the ticker in what it delivers.** `Ticker` is constructed `timestamp=None` because `ticker_lite`
genuinely carries no time field at all (its keys are bid/ask/change/premium/volume/tag/pair/dtm/
maturityTime/volumeQuote/product_id/feed — confirmed against the capture). The book feed *has* the
timestamp and loses it downstream. Both arrive as `None`. Consumers that need Kraken's book clock must
read `book.raw['timestamp']` and normalize it themselves.

This is library-wide, not Kraken-specific: 10 of the exchanges that call `book_callback` never pass
`timestamp=` (`kraken`, `kraken_futures`, `kucoin`, `bitfinex`, `bitmex`, `dydx`, `gemini`,
`blockchain`, `probit`, `bitflyer`), and the rest do. Changing it would alter `L2_BOOK` output for a
third of the library. `tests/unit/test_kraken_futures.py::test_recorded_book_delta_exchange_timestamp_is_dropped`
pins the behavior as it actually is, so the gap is documented rather than assumed.
