'''
Copyright (C) 2017-2025 Bryant Moscon - bmoscon@gmail.com

Please see the LICENSE file for the terms and conditions
associated with this software.
'''
import asyncio
from decimal import Decimal

import pytest

from cryptofeed.defines import ASK, BID, BUY, FUNDING, FUTURES, KRAKEN_FUTURES, L2_BOOK, OPEN_INTEREST, PERPETUAL, SELL, TICKER, TRADES
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
                {'BTC-USD-PERP': 'PF_XBTUSD', 'ETH-USD-PERP': 'PF_ETHUSD',
                 'BTC-USD-26Q07': 'FF_XBTUSD_260807'},
                {'tick_size': {'BTC-USD-PERP': Decimal('1'), 'ETH-USD-PERP': Decimal('0.01'),
                               'BTC-USD-26Q07': Decimal('1')},
                 'instrument_type': {'BTC-USD-PERP': PERPETUAL, 'ETH-USD-PERP': PERPETUAL,
                                     'BTC-USD-26Q07': FUTURES}})

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


def make_feed(channels, symbols=None):
    received = []

    async def callback(obj, receipt_timestamp):
        received.append(obj)

    feed = KrakenFutures(symbols=symbols if symbols is not None else ['BTC-USD-PERP'], channels=channels,
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

# Two more recorded captures, taken off the same endpoint on 2026-08-06, used to pin the
# book feed's exchange timestamp. Both are stored with the LOCAL RECEIPT TIME that was
# measured at the instant the frame arrived, so the gap between the two clocks below is
# a real measured gap and not a number chosen to make the test look convincing.
#
# The delta is the widest-diverging frame in a 31435 frame capture: the exchange clock ran
# 123ms behind receipt. Median divergence across that capture was -33ms.
RECORDED_BOOK_DELTA_TS_2026_08_06 = '{"feed":"book","product_id":"PF_XBTUSD","side":"buy","seq":17132345,"price":64382.0,"qty":7.8852,"timestamp":1786047745831}'
RECORDED_BOOK_DELTA_TS_RECEIPT = 1786047745.95403

# The snapshot is from a thin fixed-maturity contract whose book had not ticked for
# nearly six seconds when we subscribed, so its exchange clock sits 5.754s behind receipt.
# That gap is far larger than any network delay and makes the assertion unambiguous.
RECORDED_BOOK_SNAPSHOT_2026_08_06 = '{"feed":"book_snapshot","product_id":"FF_XBTUSD_260807","timestamp":1786047818552,"seq":140098,"tickSize":null,"bids":[{"price":64441.0,"qty":0.298},{"price":64420.0,"qty":0.2981},{"price":64400.0,"qty":0.8943}],"asks":[{"price":64443.0,"qty":0.298},{"price":64460.0,"qty":0.2981},{"price":64480.0,"qty":0.8943},{"price":65120.0,"qty":4.0}]}'
RECORDED_BOOK_SNAPSHOT_RECEIPT = 1786047824.30581


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


def test_recorded_book_snapshot_carries_exchange_timestamp():
    '''
    The book_snapshot path. _book_snapshot computes the exchange timestamp and must pass
    it to book_callback, which otherwise overwrites OrderBook.timestamp with None from its
    own default (cryptofeed/feed.py:242).

    The recorded frame's clocks are 5.754s apart: the exchange stamped it 1786047818552
    and it was received at 1786047824.30581. The contract was thin enough that its book
    had not ticked for nearly six seconds. Nothing but reading msg['timestamp'] produces
    the asserted value - the receipt time is almost six seconds away, and None is neither.
    '''
    feed, books = make_feed([L2_BOOK], symbols=['BTC-USD-26Q07'])

    asyncio.run(feed.message_handler(RECORDED_BOOK_SNAPSHOT_2026_08_06, MockConnection(),
                                     RECORDED_BOOK_SNAPSHOT_RECEIPT))

    assert len(books) == 1
    book = books[0]
    assert book.symbol == 'BTC-USD-26Q07'
    assert book.sequence_number == 140098
    assert book.book.bids[Decimal('64441.0')] == Decimal('0.298')
    assert book.book.asks[Decimal('65120.0')] == Decimal('4.0')
    # the exchange's own clock, normalized to float seconds
    assert book.timestamp == 1786047818.552
    # not the receipt time, and not None - the two failure modes this pins
    assert book.timestamp != RECORDED_BOOK_SNAPSHOT_RECEIPT
    assert book.timestamp is not None
    assert abs(RECORDED_BOOK_SNAPSHOT_RECEIPT - book.timestamp) > 5.0
    assert book.raw['timestamp'] == 1786047818552


def test_recorded_book_delta_carries_exchange_timestamp():
    '''
    The book delta path, which is a separate book_callback call site from the snapshot and
    needed the same fix independently. Four exchanges in this library pass the timestamp
    on one of the two paths and not the other, so both are pinned here.

    This is the widest-diverging frame in a 31435 frame capture: exchange clock 123ms
    behind the measured receipt time. Median divergence in that capture was -33ms, so a
    frame picked at random would discriminate far more weakly.
    '''
    feed, books = make_feed([L2_BOOK])
    # seed the book so the delta has something to apply to. This snapshot is hand written
    # rather than recorded - only the delta under test is a capture.
    asyncio.run(feed._book_snapshot(
        {'feed': 'book_snapshot', 'product_id': 'PF_XBTUSD', 'timestamp': 1786047745800,
         'seq': 17132344, 'bids': [{'price': 64382.0, 'qty': 0.1}],
         'asks': [{'price': 64390.0, 'qty': 0.1}]},
        'BTC-USD-PERP', 1786047745.9))

    asyncio.run(feed.message_handler(RECORDED_BOOK_DELTA_TS_2026_08_06, MockConnection(),
                                     RECORDED_BOOK_DELTA_TS_RECEIPT))

    assert len(books) == 2
    book = books[-1]
    assert book.symbol == 'BTC-USD-PERP'
    assert book.sequence_number == 17132345
    assert book.book.bids[Decimal('64382.0')] == Decimal('7.8852')
    assert book.delta == {BID: [(Decimal('64382.0'), Decimal('7.8852'))], ASK: []}
    # the exchange's own clock, normalized to float seconds
    assert book.timestamp == 1786047745.831
    # not the receipt time, and not None
    assert book.timestamp != RECORDED_BOOK_DELTA_TS_RECEIPT
    assert book.timestamp is not None
    # the two clocks are 123ms apart in this frame, which is what makes it load bearing
    assert abs(RECORDED_BOOK_DELTA_TS_RECEIPT - book.timestamp) > 0.1
    assert book.raw['timestamp'] == 1786047745831


def test_recorded_book_delta_symbol_dispatch():
    '''
    The original symbol case regression, kept on the book path. Distinct from the
    timestamp assertions above so a failure tells you which of the two broke.
    '''
    feed, books = make_feed([L2_BOOK])
    asyncio.run(feed._book_snapshot(
        {'feed': 'book_snapshot', 'product_id': 'PF_XBTUSD', 'timestamp': 1786046338114,
         'seq': 16733630, 'bids': [{'price': 64401.0, 'qty': 0.1239}],
         'asks': [{'price': 64416.0, 'qty': 0.1}]},
        'BTC-USD-PERP', 1786046338.2))

    asyncio.run(feed.message_handler(RECORDED_BOOK_DELTA_2026_08_06, MockConnection(), 1786046338.3))

    assert len(books) == 2
    book = books[-1]
    assert book.symbol == 'BTC-USD-PERP'
    assert book.book.asks[Decimal('64416.0')] == Decimal('0.0568')
    assert book.sequence_number == 16733631


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
