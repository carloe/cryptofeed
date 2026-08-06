'''
Copyright (C) 2017-2025 Bryant Moscon - bmoscon@gmail.com

Please see the LICENSE file for the terms and conditions
associated with this software.
'''
import asyncio
from decimal import Decimal

import pytest

from cryptofeed.defines import BUY, FUNDING, KRAKEN_FUTURES, L2_BOOK, OPEN_INTEREST, PERPETUAL, SELL, TICKER, TRADES
from cryptofeed.exchanges import KrakenFutures
from cryptofeed.symbols import Symbols


@pytest.fixture(autouse=True)
def seeded_symbols():
    '''
    Seed the symbol cache so that Feed.__init__ does not reach out to the Kraken Futures
    REST API for instrument metadata, keeping these tests offline.

    The mapping values are the exchange symbols exactly as the REST instruments endpoint
    returns them - uppercase, e.g. PF_XBTUSD. That casing is the whole point of these
    tests, so it must not be normalized here.

    Symbols is a process wide singleton, so the previous state is restored afterwards.
    '''
    previous = Symbols.data.get(KRAKEN_FUTURES)

    Symbols.set(KRAKEN_FUTURES,
                {'BTC-USD-PERP': 'PF_XBTUSD', 'ETH-USD-PERP': 'PF_ETHUSD'},
                {'tick_size': {'BTC-USD-PERP': Decimal('1'), 'ETH-USD-PERP': Decimal('0.01')},
                 'instrument_type': {'BTC-USD-PERP': PERPETUAL, 'ETH-USD-PERP': PERPETUAL}})

    yield

    if previous is None:
        Symbols.data.pop(KRAKEN_FUTURES, None)
    else:
        Symbols.data[KRAKEN_FUTURES] = previous


class MockConnection:
    '''Minimal stand in for AsyncConnection, enough for message_handler and subscribe'''
    uuid = 'test'
    address = 'wss://futures.kraken.com/ws/v1'

    def __init__(self):
        self.sent = []

    async def write(self, data):
        self.sent.append(data)


def make_feed(channels):
    received = []

    async def callback(obj, receipt_timestamp):
        received.append(obj)

    feed = KrakenFutures(symbols=['BTC-USD-PERP'], channels=channels,
                         callbacks={chan: callback for chan in channels})
    # subscribe() is what initializes the per connection caches (_l2_book, seq_no,
    # _open_interest_cache) live, so run it here rather than reaching for the private
    # __reset - this keeps the tests on the same path the feed handler takes.
    asyncio.run(feed.subscribe(MockConnection()))
    return feed, received


# Real frames recorded off wss://futures.kraken.com/ws/v1 on 2026-08-06, subscribed to
# PF_XBTUSD, captured before parsing and never re-serialized - byte for byte what the
# exchange sent. They are the evidence that the wire product_id is 'PF_XBTUSD', matching
# the REST instruments symbol verbatim, and NOT the lowercase form the old dispatch
# assumed. Do not reformat, prettify, or "normalize" the casing in these strings.
RECORDED_TRADE_2026_08_06 = '{"product_id":"PF_XBTUSD","feed":"trade","uid":"896cb851-8322-4946-a123-945c453aa17f","side":"sell","type":"fill","time":1786046342957,"qty":0.0046,"price":64401.0,"seq":45847}'
RECORDED_TICKER_LITE_2026_08_06 = '{"premium":0.0,"product_id":"PF_XBTUSD","feed":"ticker_lite","bid":64401.0,"ask":64402.0,"change":-0.68,"volume":3669.9134,"tag":"perpetual","pair":"XBT:USD","dtm":0,"maturityTime":0,"volumeQuote":236982977.0066}'
RECORDED_BOOK_DELTA_2026_08_06 = '{"feed":"book","product_id":"PF_XBTUSD","side":"sell","seq":16733631,"price":64416.0,"qty":0.0568,"timestamp":1786046338116}'


def test_recorded_trade_product_id_case():
    '''
    The dispatch point in message_handler resolves msg['product_id'] against the reverse
    symbol map, which is keyed by the REST symbol verbatim ('PF_XBTUSD'). Applying
    .lower() to the wire value produced 'pf_xbtusd', which is in no map, so every inbound
    message raised UnsupportedSymbol - the entire exchange was dead, not just trades.

    Fed in as the raw string so routing and deserialization run exactly as they did live.
    '''
    feed, trades = make_feed([TRADES])

    asyncio.run(feed.message_handler(RECORDED_TRADE_2026_08_06, MockConnection(), 1786046343.0))

    assert len(trades) == 1
    t = trades[0]
    assert t.exchange == KRAKEN_FUTURES
    assert t.symbol == 'BTC-USD-PERP'
    assert t.side == SELL
    assert t.amount == Decimal('0.0046')
    assert t.price == Decimal('64401.0')
    assert t.id == '896cb851-8322-4946-a123-945c453aa17f'
    assert t.timestamp == 1786046342.957


def test_recorded_ticker_lite_product_id_case():
    '''ticker_lite carries no time field of its own, hence Ticker(timestamp=None)'''
    feed, tickers = make_feed([TICKER])

    asyncio.run(feed.message_handler(RECORDED_TICKER_LITE_2026_08_06, MockConnection(), 1786046343.0))

    assert len(tickers) == 1
    t = tickers[0]
    assert t.symbol == 'BTC-USD-PERP'
    assert t.bid == Decimal('64401.0')
    assert t.ask == Decimal('64402.0')
    # Kraken's ticker_lite frame has no timestamp field at all - confirmed against the
    # recorded capture, whose keys are bid/ask/change/premium/volume/tag/pair/dtm/
    # maturityTime/volumeQuote/product_id/feed. The book feed does carry one.
    assert t.timestamp is None


def test_recorded_book_delta_exchange_timestamp_is_dropped():
    '''
    Unlike ticker_lite, Kraken's book frames DO carry a real exchange timestamp in epoch
    milliseconds - every one of the 27249 book frames in the 2026-08-06 capture had one.

    It does not reach the consumer, though. _book assigns it to the OrderBook, but
    Feed.book_callback (cryptofeed/feed.py:242) then does an unconditional
    `book.timestamp = timestamp` from its own keyword argument, which kraken_futures
    never passes, so it is overwritten with None. The assignment in _book is dead.

    This is a pre-existing upstream defect, unrelated to the symbol case fix, and is left
    alone here under minimal-delta discipline. The test pins the behavior as it actually
    is so the gap is documented rather than assumed: downstream must read the exchange
    time off `book.raw['timestamp']`, not `book.timestamp`.
    '''
    feed, books = make_feed([L2_BOOK])
    # seed the book so the delta has something to apply to
    asyncio.run(feed._book_snapshot(
        {'feed': 'book_snapshot', 'product_id': 'PF_XBTUSD', 'timestamp': 1786046338114,
         'seq': 16733630, 'bids': [{'price': 64401.0, 'qty': 0.1239}],
         'asks': [{'price': 64416.0, 'qty': 0.1}]},
        'BTC-USD-PERP', 1786046338.2))

    asyncio.run(feed.message_handler(RECORDED_BOOK_DELTA_2026_08_06, MockConnection(), 1786046338.3))

    assert len(books) == 2
    book = books[-1]
    # the fix is what got us here at all - dispatch resolved PF_XBTUSD
    assert book.symbol == 'BTC-USD-PERP'
    assert book.book.asks[Decimal('64416.0')] == Decimal('0.0568')
    assert book.sequence_number == 16733631
    # the exchange clock is on the wire and survives on raw ...
    assert book.raw['timestamp'] == 1786046338116
    # ... but book.timestamp is nulled by book_callback. Not 1786046338.116, and also
    # not the receipt time 1786046338.3 - just None.
    assert book.timestamp is None


def test_recorded_funding_and_open_interest_product_id_case():
    '''
    The 'ticker' feed drives both FUNDING and OPEN_INTEREST through _funding, and shares
    the same dispatch point, so it died with everything else.
    '''
    feed, received = make_feed([FUNDING, OPEN_INTEREST])

    ticker = '{"time":1786046338005,"product_id":"PF_XBTUSD","funding_rate":0.1767923925826881,"funding_rate_prediction":-0.045351956680625,"relative_funding_rate":2.747066666667e-6,"relative_funding_rate_prediction":-7.043125e-7,"next_funding_rate_time":1786046400000,"leverage":"100x","premium":0.0,"feed":"ticker","bid":64401.0,"ask":64402.0,"bid_size":0.1239,"ask_size":0.1179,"volume":3669.9134,"dtm":0,"index":64401.07,"last":64403.0,"change":-0.68,"suspended":false,"tag":"perpetual","pair":"XBT:USD","openInterest":2157.6281,"markPrice":64399.68035588646,"maturityTime":0,"post_only":false,"volumeQuote":236982977.0066,"open":64843.0,"high":64976.0,"low":64104.0}'

    asyncio.run(feed.message_handler(ticker, MockConnection(), 1786046338.5))

    assert [type(o).__name__ for o in received] == ['Funding', 'OpenInterest']
    assert all(o.symbol == 'BTC-USD-PERP' for o in received)
    assert received[0].rate == Decimal('0.1767923925826881')
    assert received[0].timestamp == 1786046338.005
    assert received[1].open_interest == Decimal('2157.6281')


def test_wire_product_id_is_verbatim_rest_symbol():
    '''
    The invariant the fix rests on, stated directly: the string the websocket sends is
    the same string the REST instruments endpoint returns, so it is a map key as-is.
    Lowercasing it - or uppercasing the map - breaks the lookup.
    '''
    feed, _ = make_feed([TRADES])

    assert 'PF_XBTUSD' in feed.exchange_symbol_mapping
    assert 'pf_xbtusd' not in feed.exchange_symbol_mapping
    # outbound and inbound now agree on casing
    assert feed.std_symbol_to_exchange_symbol('BTC-USD-PERP') == 'PF_XBTUSD'
    assert feed.exchange_symbol_to_std_symbol('PF_XBTUSD') == 'BTC-USD-PERP'
