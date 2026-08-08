'''
Copyright (C) 2017-2025 Bryant Moscon - bmoscon@gmail.com

Please see the LICENSE file for the terms and conditions
associated with this software.
'''
import asyncio
from decimal import Decimal

import pytest

from cryptofeed.defines import (BINANCE, BINANCE_DELIVERY, BINANCE_FUTURES, BUY, CANDLES, FUNDING, L2_BOOK,
                                LIQUIDATIONS, PERPETUAL, SELL, SPOT, TICKER, TRADES)
from cryptofeed.exchanges import Binance, BinanceDelivery, BinanceFutures, BinanceTR, BinanceUS
from cryptofeed.symbols import Symbols


@pytest.fixture(autouse=True)
def seeded_symbols():
    '''
    Seed the symbol caches so Feed.__init__ does not reach out to Binance for instrument
    metadata, keeping these tests offline. Symbols is a process wide singleton, so the
    previous state is restored afterwards.
    '''
    previous = {ex: Symbols.data.get(ex) for ex in (BINANCE_FUTURES, BINANCE, BINANCE_DELIVERY)}

    Symbols.set(BINANCE_FUTURES,
                {'BTC-USDT-PERP': 'BTCUSDT', 'STG-USDT-PERP': 'STGUSDT'},
                {'tick_size': {'BTC-USDT-PERP': Decimal('0.1'), 'STG-USDT-PERP': Decimal('0.0001')},
                 'instrument_type': {'BTC-USDT-PERP': PERPETUAL, 'STG-USDT-PERP': PERPETUAL}})
    Symbols.set(BINANCE,
                {'BTC-USDT': 'BTCUSDT'},
                {'tick_size': {'BTC-USDT': Decimal('0.01')}, 'instrument_type': {'BTC-USDT': SPOT}})
    Symbols.set(BINANCE_DELIVERY,
                {'BTC-USD-PERP': 'BTCUSD_PERP'},
                {'tick_size': {'BTC-USD-PERP': Decimal('0.1')},
                 'instrument_type': {'BTC-USD-PERP': PERPETUAL}})

    yield

    for ex, prev in previous.items():
        if prev is None:
            Symbols.data.pop(ex, None)
        else:
            Symbols.data[ex] = prev


class MockConnection:
    '''Minimal stand in for AsyncConnection, enough for message_handler'''
    uuid = 'test'
    address = 'wss://fstream.binance.com/market/stream'


def make_futures(channels, symbols=None):
    received = []

    async def callback(obj, receipt_timestamp):
        received.append(obj)

    feed = BinanceFutures(symbols=symbols if symbols is not None else ['BTC-USDT-PERP'],
                          channels=channels, callbacks={c: callback for c in channels})
    return feed, received


def addresses(feed):
    addr = feed._address()
    return addr if isinstance(addr, list) else [addr]


# Frames recorded off the Binance USD-M futures websocket on 2026-08-08, captured before
# parsing and never re-serialized - byte for byte what the exchange sent, including the
# {"stream":..,"data":..} combined-stream envelope. Every one of these was captured on
# wss://fstream.binance.com/market and returns ZERO frames on the legacy root, which is
# the whole point: the stream names are unchanged, only the base path differs.
# Do not reformat or prettify these strings.
RECORDED_AGGTRADE_2026_08_08 = '{"stream":"btcusdt@aggTrade","data":{"e":"aggTrade","E":1786171884624,"a":3404749954,"s":"BTCUSDT","p":"64990.90","q":"0.002","nq":"0.002","f":7960913511,"l":7960913511,"T":1786171884471,"m":true,"st":1}}'
RECORDED_MARKPRICE_2026_08_08 = '{"stream":"btcusdt@markPrice","data":{"e":"markPriceUpdate","E":1786171884000,"s":"BTCUSDT","p":"64991.37858696","ap":"64991.37858696","P":"64980.01344384","i":"65016.05673913","r":"0.00003936","T":1786176000000,"st":1}}'
RECORDED_KLINE_2026_08_08 = '{"stream":"btcusdt@kline_1m","data":{"e":"kline","E":1786173360960,"s":"BTCUSDT","k":{"t":1786173300000, "T":1786173359999, "s":"BTCUSDT", "i":"1m", "f":7960920076, "L":7960920277, "o":"64970.80", "c":"64969.40", "h":"64970.90", "l":"64969.40", "v":"9.090", "n":194, "x":true, "q":"590577.96880", "V":"3.460", "Q":"224795.09440", "B":"0"}}}'
RECORDED_FORCEORDER_2026_08_08 = '{"stream":"stgusdt@forceOrder","data":{"e":"forceOrder","E":1786172557615,"o":{"s":"STGUSDT","S":"SELL","o":"LIMIT","f":"IOC","q":"5","p":"0.1336000","ap":"0.1355000","X":"FILLED","l":"5","z":"5","T":1786172556607,"ps":"STGUSDT","st":1}}}'


def test_market_streams_use_market_base_path():
    '''
    aggTrade, markPrice, kline_ and forceOrder are served only under /market since the
    2026-04-23 decommission of the legacy root. Subscribed alone they must produce
    exactly one address, on /market.
    '''
    feed, _ = make_futures([TRADES, FUNDING, CANDLES, LIQUIDATIONS])
    addrs = addresses(feed)

    assert len(addrs) == 1
    addr = addrs[0]
    assert addr.startswith('wss://fstream.binance.com/market/stream?streams=')
    for stream in ('btcusdt@aggTrade', 'btcusdt@markPrice', 'btcusdt@kline_1m', 'btcusdt@forceOrder'):
        assert stream in addr


def test_public_streams_use_public_base_path():
    '''bookTicker and depth are the /public half of the split'''
    feed, _ = make_futures([TICKER, L2_BOOK])
    addrs = addresses(feed)

    assert len(addrs) == 1
    addr = addrs[0]
    assert addr.startswith('wss://fstream.binance.com/public/stream?streams=')
    assert 'btcusdt@bookTicker' in addr
    assert 'btcusdt@depth@100ms' in addr


def test_mixed_subscription_splits_into_one_connection_per_base_path():
    '''
    The litquid channel set spans both paths, so it can no longer share a single
    connection. _address returns one address per base path and Feed.connect opens one
    websocket per address.
    '''
    feed, _ = make_futures([TRADES, L2_BOOK, TICKER, FUNDING, LIQUIDATIONS, CANDLES])
    addrs = addresses(feed)

    assert len(addrs) == 2
    by_path = {}
    for addr in addrs:
        prefix, streams = addr.split('/stream?streams=')
        by_path[prefix] = set(streams.split('/'))

    assert by_path['wss://fstream.binance.com/market'] == {
        'btcusdt@aggTrade', 'btcusdt@markPrice', 'btcusdt@kline_1m', 'btcusdt@forceOrder'}
    assert by_path['wss://fstream.binance.com/public'] == {
        'btcusdt@bookTicker', 'btcusdt@depth@100ms'}


def test_no_address_uses_the_decommissioned_legacy_root():
    '''
    The regression guard. The legacy root still accepts the connection and still serves
    the /public streams, so a bad address does not raise - it silently starves the
    /market channels. Nothing may be built on the bare root.
    '''
    feed, _ = make_futures([TRADES, L2_BOOK, TICKER, FUNDING, LIQUIDATIONS, CANDLES])

    for addr in addresses(feed):
        assert not addr.startswith('wss://fstream.binance.com/stream?streams=')
        assert addr.startswith('wss://fstream.binance.com/public/') or \
            addr.startswith('wss://fstream.binance.com/market/')


def test_open_interest_is_rest_polled_and_not_in_any_address():
    '''OPEN_INTEREST is an HTTP poll on fapi, not a websocket stream, so it has no path'''
    from cryptofeed.defines import OPEN_INTEREST

    feed, _ = make_futures([TRADES, OPEN_INTEREST])
    addrs = addresses(feed)

    assert len(addrs) == 1
    assert 'open_interest' not in addrs[0]
    assert addrs[0].startswith('wss://fstream.binance.com/market/stream?streams=')


def test_recorded_aggtrade_parses():
    '''TRADES, recovered by moving to /market'''
    feed, trades = make_futures([TRADES])

    asyncio.run(feed.message_handler(RECORDED_AGGTRADE_2026_08_08, MockConnection(), 1786171884.7))

    assert len(trades) == 1
    t = trades[0]
    assert t.exchange == BINANCE_FUTURES
    assert t.symbol == 'BTC-USDT-PERP'
    # "m": true means the buyer is the market maker, so the aggressor sold
    assert t.side == SELL
    assert t.amount == Decimal('0.002')
    assert t.price == Decimal('64990.90')
    assert t.timestamp == 1786171884.471


def test_recorded_markprice_parses_as_funding():
    '''
    FUNDING is derived from the markPrice stream, not a dedicated funding stream -
    websocket_channels[FUNDING] is 'markPrice' and the payload event is markPriceUpdate.
    That stream moved to /market, so funding died with the trades.
    '''
    feed, funding = make_futures([FUNDING])

    asyncio.run(feed.message_handler(RECORDED_MARKPRICE_2026_08_08, MockConnection(), 1786171884.2))

    assert len(funding) == 1
    f = funding[0]
    assert f.exchange == BINANCE_FUTURES
    assert f.symbol == 'BTC-USDT-PERP'
    assert f.mark_price == Decimal('64991.37858696')
    assert f.rate == Decimal('0.00003936')
    assert f.next_funding_time == 1786176000.0


def test_recorded_kline_parses_as_candle():
    '''
    CANDLES, recovered by moving to /market.

    A closed candle (k.x true) on purpose: candle_closed_only defaults to True, so an
    in-progress candle is dropped by _candle before any of this would be reached and the
    fixture would assert nothing.
    '''
    feed, candles = make_futures([CANDLES])

    asyncio.run(feed.message_handler(RECORDED_KLINE_2026_08_08, MockConnection(), 1786173361.1))

    assert len(candles) == 1
    c = candles[0]
    assert c.symbol == 'BTC-USDT-PERP'
    assert c.interval == '1m'
    assert c.open == Decimal('64970.80')
    assert c.close == Decimal('64969.40')
    assert c.high == Decimal('64970.90')
    assert c.low == Decimal('64969.40')
    assert c.trades == 194
    assert c.closed is True


def test_recorded_forceorder_parses_as_liquidation():
    '''
    LIQUIDATIONS. This is the channel the downstream consumer was losing outright: the
    per-symbol forceOrder stream delivers on /market and returns nothing on the legacy
    root, confirmed live across 120 symbols.
    '''
    feed, liquidations = make_futures([LIQUIDATIONS], symbols=['STG-USDT-PERP'])

    asyncio.run(feed.message_handler(RECORDED_FORCEORDER_2026_08_08, MockConnection(), 1786172557.7))

    assert len(liquidations) == 1
    liq = liquidations[0]
    assert liq.exchange == BINANCE_FUTURES
    assert liq.symbol == 'STG-USDT-PERP'
    assert liq.side == SELL
    assert liq.quantity == Decimal('5')
    assert liq.price == Decimal('0.1336000')


def test_other_binance_venues_keep_the_root_address():
    '''
    Blast radius. _address is defined once on Binance and shared by all five venues, so
    the split is carried by data - stream_base_paths - rather than by branching. Every
    venue but USD-M futures leaves it empty and is unaffected.

    Only USD-M futures was split: the COIN-M root still serves every stream, verified
    live on 2026-08-08 (aggTrade, markPrice, kline, bookTicker and depth all delivered on
    wss://dstream.binance.com).
    '''
    for cls in (Binance, BinanceUS, BinanceTR, BinanceDelivery):
        assert cls.stream_base_paths == {}, f'{cls.id} must not carry a base path split'

    spot = Binance(symbols=['BTC-USDT'], channels=[TRADES, L2_BOOK], callbacks={TRADES: None, L2_BOOK: None})
    spot_addrs = spot._address()
    assert isinstance(spot_addrs, str)
    assert spot_addrs.startswith('wss://stream.binance.com:9443/stream?streams=')

    delivery = BinanceDelivery(symbols=['BTC-USD-PERP'], channels=[TRADES, LIQUIDATIONS],
                               callbacks={TRADES: None, LIQUIDATIONS: None})
    delivery_addrs = delivery._address()
    assert isinstance(delivery_addrs, str)
    assert delivery_addrs.startswith('wss://dstream.binance.com/stream?streams=')
