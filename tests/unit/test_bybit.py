'''
Copyright (C) 2017-2025 Bryant Moscon - bmoscon@gmail.com

Please see the LICENSE file for the terms and conditions
associated with this software.
'''
import asyncio
from decimal import Decimal

import pytest
from yapic import json

from cryptofeed.defines import BUY, BYBIT, LIQUIDATIONS, PERPETUAL, SELL
from cryptofeed.exchanges import Bybit
from cryptofeed.symbols import Symbols


@pytest.fixture(autouse=True)
def seeded_symbols():
    '''
    Seed the symbol cache so that Feed.__init__ does not reach out to the Bybit REST
    API for instrument metadata, keeping these tests offline.

    Symbols is a process wide singleton, so the previous state is restored afterwards.
    Leaking a two symbol mapping into the rest of the suite would quietly starve any
    later test that expects the real Bybit instrument list.
    '''
    previous = Symbols.data.get(BYBIT)

    Symbols.set(BYBIT,
                {'BTC-USDT-PERP': 'BTCUSDT', 'ETH-USDT-PERP': 'ETHUSDT', 'POPCAT-USDT-PERP': 'POPCATUSDT'},
                {'tick_size': {'BTC-USDT-PERP': Decimal('0.1'), 'ETH-USDT-PERP': Decimal('0.01'),
                               'POPCAT-USDT-PERP': Decimal('0.00001')},
                 'instrument_type': {'BTC-USDT-PERP': PERPETUAL, 'ETH-USDT-PERP': PERPETUAL,
                                     'POPCAT-USDT-PERP': PERPETUAL}})

    yield

    if previous is None:
        Symbols.data.pop(BYBIT, None)
    else:
        Symbols.data[BYBIT] = previous


class MockConnection:
    '''Minimal stand in for AsyncConnection, enough for message_handler and subscribe'''
    uuid = 'test'
    address = 'wss://stream.bybit.com/v5/public/linear'

    def __init__(self, subscription=None):
        self.subscription = subscription if subscription is not None else {}
        self.sent = []

    async def write(self, data):
        self.sent.append(json.loads(data))


def make_feed():
    liquidations = []

    async def callback(obj, receipt_timestamp):
        liquidations.append(obj)

    feed = Bybit(symbols=['BTC-USDT-PERP', 'ETH-USDT-PERP'], channels=[LIQUIDATIONS], callbacks={LIQUIDATIONS: callback})
    return feed, liquidations


# A real frame recorded off the Bybit linear websocket on 2026-08-05, captured before
# parsing and never re-serialized, so it is byte for byte what the exchange sent. Every
# other fixture in this file is hand written from Bybit's documentation - this one is
# the only evidence of what the wire actually carries. Do not reformat or prettify it.
RECORDED_FRAME_2026_08_05 = '{"topic":"allLiquidation.POPCATUSDT","type":"snapshot","ts":1785905987246,"data":[{"T":1785905986808,"s":"POPCATUSDT","S":"Buy","v":"16322","p":"0.04418"}]}'


def test_liquidation_recorded_frame():
    '''
    Full parsed surface of a recorded frame, fed in as the raw string so that routing
    and deserialization run exactly as they did live.

    This fixture exists to pin the fork's two deliberate deltas against upstream
    (FORK_NOTES sections 1.1 and 1.2) to real exchange output rather than to a reading
    of the docs.
    '''
    feed, liquidations = make_feed()

    asyncio.run(feed.message_handler(RECORDED_FRAME_2026_08_05, MockConnection(), 1785905987.5))

    assert len(liquidations) == 1
    liq = liquidations[0]
    assert liq.exchange == BYBIT
    assert liq.symbol == 'POPCAT-USDT-PERP'
    # S is 'Buy', the *position* side, so a long was liquidated - and a long is closed
    # by a sell. Liquidation.side is the forced order side, hence SELL. FORK_NOTES 1.2.
    # A verbatim upstream style mapping would emit BUY here.
    assert liq.side == SELL
    assert liq.quantity == Decimal('16322')
    assert liq.price == Decimal('0.04418')
    # The event's own T (1785905986808) and the batch envelope ts (1785905987246) differ
    # by 438ms in this frame, which is the whole point of recording it - a fixture where
    # the two matched could not tell an envelope/event mixup from correct behavior.
    # Float seconds from T, per FORK_NOTES 1.1.
    assert isinstance(liq.timestamp, float)
    assert liq.timestamp == 1785905986.808
    assert liq.timestamp != 1785905987.246
    # raw is the individual event, not the enclosing batch
    assert liq.raw == {"T": 1785905986808, "s": "POPCATUSDT", "S": "Buy", "v": "16322", "p": "0.04418"}


def test_liquidation_single_event():
    '''
    A single event batch, as documented at
    https://bybit-exchange.github.io/docs/v5/websocket/public/all-liquidation
    '''
    feed, liquidations = make_feed()

    msg = {
        "topic": "allLiquidation.BTCUSDT",
        "type": "snapshot",
        "ts": 1739502303204,
        "data": [
            {
                "T": 1739502302929,
                "s": "BTCUSDT",
                "S": "Sell",
                "v": "0.003",
                "p": "43511.70"
            }
        ]
    }

    asyncio.run(feed._liquidation(msg, 1739502303.5))

    assert len(liquidations) == 1
    liq = liquidations[0]
    assert liq.exchange == BYBIT
    assert liq.symbol == 'BTC-USDT-PERP'
    # Bybit's S is the position side: 'Sell' means a short was liquidated, which is
    # closed by a buy order. Liquidation.side is the forced order side across the
    # library (binance/okx/bitmex/deribit), so the mapping is inverted on purpose.
    # This is not a bug - do not "fix" it back to a verbatim mapping.
    assert liq.side == BUY
    assert liq.quantity == Decimal('0.003')
    assert liq.price == Decimal('43511.70')
    assert liq.id is None
    assert liq.status is None
    # Normalized to float seconds from the event's own T, not the envelope ts
    # (1739502303204) and not raw milliseconds. A regression to either fails here.
    assert isinstance(liq.timestamp, float)
    assert liq.timestamp == 1739502302.929


def test_liquidation_side_inversion():
    '''
    Bybit documents S as the position side: "When you receive a Buy update, this
    means that a long position has been liquidated". A long is closed by a sell
    order, and Liquidation.side is the forced order side everywhere else in
    cryptofeed, so Buy maps to SELL and Sell maps to BUY.
    '''
    feed, liquidations = make_feed()

    msg = {
        "topic": "allLiquidation.BTCUSDT",
        "type": "snapshot",
        "ts": 1739502303204,
        "data": [
            {"T": 1739502302929, "s": "BTCUSDT", "S": "Buy", "v": "0.5", "p": "43511.70"},
            {"T": 1739502302930, "s": "BTCUSDT", "S": "Sell", "v": "0.5", "p": "43511.70"}
        ]
    }

    asyncio.run(feed._liquidation(msg, 1739502303.5))

    assert [liq.side for liq in liquidations] == [SELL, BUY]


def test_liquidation_multi_event_batch():
    '''allLiquidation batches at 500ms, so a message can carry several events'''
    feed, liquidations = make_feed()

    msg = {
        "topic": "allLiquidation.BTCUSDT",
        "type": "snapshot",
        "ts": 1739502303204,
        "data": [
            {"T": 1739502302929, "s": "BTCUSDT", "S": "Buy", "v": "0.003", "p": "43511.70"},
            {"T": 1739502303001, "s": "ETHUSDT", "S": "Sell", "v": "1.5", "p": "2600.05"},
            {"T": 1739502303100, "s": "BTCUSDT", "S": "Sell", "v": "0.125", "p": "43520.00"}
        ]
    }

    asyncio.run(feed._liquidation(msg, 1739502303.5))

    assert len(liquidations) == 3
    assert [liq.symbol for liq in liquidations] == ['BTC-USDT-PERP', 'ETH-USDT-PERP', 'BTC-USDT-PERP']
    assert [liq.side for liq in liquidations] == [SELL, BUY, BUY]
    assert [liq.quantity for liq in liquidations] == [Decimal('0.003'), Decimal('1.5'), Decimal('0.125')]
    assert [liq.price for liq in liquidations] == [Decimal('43511.70'), Decimal('2600.05'), Decimal('43520.00')]
    # each event carries its own timestamp, none of them the envelope ts
    assert [liq.timestamp for liq in liquidations] == [1739502302.929, 1739502303.001, 1739502303.100]
    # raw is the individual event, not the whole batch
    assert [liq.raw['s'] for liq in liquidations] == ['BTCUSDT', 'ETHUSDT', 'BTCUSDT']


def test_liquidation_message_routing():
    '''
    The topic is 'allLiquidation.BTCUSDT'. Routing on a 'liquidation' prefix does
    not match it, which would silently drop the whole channel.
    '''
    feed, liquidations = make_feed()

    msg = json.dumps({
        "topic": "allLiquidation.BTCUSDT",
        "type": "snapshot",
        "ts": 1739502303204,
        "data": [
            {"T": 1739502302929, "s": "BTCUSDT", "S": "Sell", "v": "0.003", "p": "43511.70"}
        ]
    })

    asyncio.run(feed.message_handler(msg, MockConnection(), 1739502303.5))

    assert len(liquidations) == 1
    assert liquidations[0].symbol == 'BTC-USDT-PERP'


def test_liquidation_channel_mapping():
    assert Bybit.std_channel_to_exchange(LIQUIDATIONS) == 'allLiquidation'
    assert Bybit.exchange_channel_to_std('allLiquidation') == LIQUIDATIONS


def test_liquidation_subscribe():
    '''Subscriptions are built generically as f"{channel}.{pair}"'''
    feed, _ = make_feed()
    conn = MockConnection(subscription={'allLiquidation': ['BTCUSDT', 'ETHUSDT']})

    asyncio.run(feed.subscribe(conn))

    assert conn.sent == [
        {'op': 'subscribe', 'args': ['allLiquidation.BTCUSDT']},
        {'op': 'subscribe', 'args': ['allLiquidation.ETHUSDT']}
    ]
