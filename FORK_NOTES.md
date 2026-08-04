# Fork notes

`carloe/cryptofeed` is a maintenance fork of [bmoscon/cryptofeed](https://github.com/bmoscon/cryptofeed).

Upstream was archived (read-only) on 2026-07-08 at `v2.4.1` and will never receive fixes again.
This fork exists for one purpose: to keep the exchange integrations consumed by the downstream
`litquid` project working, as a pinned git dependency. It is not an adoption of the library, and no
attempt is made to maintain the parts of cryptofeed that `litquid` does not use.

Every change here is a deliberate, minimal delta against upstream. Upstream code is not refactored,
reformatted, or modernized. See `CLAUDE.md` for the full working rules.

**Fork point:** `fe5993b0`, identical to upstream `master` at the time of forking.

## Patch log

| Date | Commit | Files | Reason |
| --- | --- | --- | --- |
| 2026-08-04 | `0ea4d9ba` | `CLAUDE.md`, `FORK_NOTES.md` | Fork maintenance docs. New files, no upstream code touched. |
| 2026-08-04 | `79b70972` | `cryptofeed/exchanges/bybit.py` | [Migrate `LIQUIDATIONS` to the `allLiquidation` topic](#1-bybit-liquidations-allliquidation-migration). Includes two deliberate behavior changes: [timestamp units](#11-behavior-change-timestamp-units) and [side mapping](#12-behavior-change-side-mapping-inverted), plus a [minor `raw` scope change](#13-minor-raw-payload-scope). |
| 2026-08-04 | `111e3955` | `tests/unit/test_bybit.py`, `examples/demo_bybit_all_liquidation.py` | Test coverage and a live smoke script for the above. New files, no upstream code touched. |

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
