'''
Live smoke test for the Bybit allLiquidation channel.

Connects to the public linear endpoint, subscribes to allLiquidation for a
single perpetual, and asserts that the exchange acknowledges the subscription.
No API keys are required for public streams.

Liquidations are sporadic, so this deliberately does not wait for an event. It
verifies that the topic name this fork sends is one Bybit actually accepts,
which is what broke when Bybit deprecated the old 'liquidation' topic.

Exits 0 on success, 1 on failure.

    python examples/demo_bybit_all_liquidation.py [SYMBOL]
'''
import asyncio
import sys

import websockets
from yapic import json

from cryptofeed.defines import LIQUIDATIONS
from cryptofeed.exchanges import Bybit


ADDRESS = 'wss://stream.bybit.com/v5/public/linear'
TIMEOUT = 30


async def smoke_test(pair: str):
    # Build the topic the same way Bybit.subscribe does, from the channel map,
    # so that this exercises the value the feed actually sends.
    topic = f'{Bybit.std_channel_to_exchange(LIQUIDATIONS)}.{pair}'
    print(f'Connecting to {ADDRESS}')

    async with websockets.connect(ADDRESS) as ws:
        print(f'Subscribing to {topic}')
        await ws.send(json.dumps({'op': 'subscribe', 'args': [topic]}))

        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=TIMEOUT))

            if 'success' not in msg:
                # a data message arrived before the ack, ignore it and keep reading
                continue

            assert msg['success'], f'Bybit rejected the subscription: {msg}'
            assert msg['op'] == 'subscribe', f'Unexpected ack for op {msg["op"]}: {msg}'
            print(f'Subscription acknowledged: {msg}')
            return


def main():
    pair = sys.argv[1] if len(sys.argv) > 1 else 'BTCUSDT'

    try:
        asyncio.run(smoke_test(pair))
    except AssertionError as e:
        print(f'FAILED: {e}')
        return 1
    except asyncio.TimeoutError:
        print(f'FAILED: no subscription response within {TIMEOUT}s')
        return 1

    print('OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
