"""Example: Stream Alpaca SIP data into the platform.

Run this separately from the platform. It connects to Alpaca's
WebSocket via the alpaca-py SDK and forwards data to the platform's
ingestion WebSocket endpoint.

Prerequisites:
    - pip install alpaca-py websockets
    - Set ALPACA_API_KEY and ALPACA_API_SECRET environment variables
    - The trading platform must be running with ingestion enabled

Usage:
    python docs/examples/external_alpaca_feed.py
"""

from __future__ import annotations

import asyncio
import json
import os

import websockets


async def forward_to_platform(
    platform_url: str,
    api_key: str,
    api_secret: str,
    symbols: list[str],
) -> None:
    """Connect to Alpaca and forward data to the platform ingestion WS."""

    # Connect to the platform's ingestion WebSocket
    async with websockets.connect(platform_url) as platform_ws:
        print(f"Connected to platform at {platform_url}")

        # Connect to Alpaca's SIP WebSocket
        alpaca_ws_url = "wss://stream.data.alpaca.markets/v2/sip"
        async with websockets.connect(alpaca_ws_url) as alpaca_ws:
            # Authenticate with Alpaca
            auth_msg = {"action": "auth", "key": api_key, "secret": api_secret}
            await alpaca_ws.send(json.dumps(auth_msg))
            response = await alpaca_ws.recv()
            print(f"Alpaca auth response: {response}")

            # Subscribe to symbols
            sub_msg = {
                "action": "subscribe",
                "trades": symbols,
                "quotes": symbols,
                "bars": symbols,
            }
            await alpaca_ws.send(json.dumps(sub_msg))
            response = await alpaca_ws.recv()
            print(f"Alpaca subscription response: {response}")

            # Forward messages
            count = 0
            async for raw in alpaca_ws:
                messages = json.loads(raw)
                for msg in messages:
                    msg_type = msg.get("T")

                    if msg_type == "b":  # Bar
                        payload = {
                            "type": "bar",
                            "data": {
                                "symbol": msg["S"],
                                "open": msg["o"],
                                "high": msg["h"],
                                "low": msg["l"],
                                "close": msg["c"],
                                "volume": msg["v"],
                                "timestamp": msg["t"],
                            },
                        }
                    elif msg_type == "q":  # Quote
                        payload = {
                            "type": "quote",
                            "data": {
                                "symbol": msg["S"],
                                "bid_price": msg["bp"],
                                "bid_size": msg["bs"],
                                "ask_price": msg["ap"],
                                "ask_size": msg["as"],
                                "timestamp": msg["t"],
                            },
                        }
                    elif msg_type == "t":  # Trade
                        payload = {
                            "type": "trade",
                            "data": {
                                "symbol": msg["S"],
                                "price": msg["p"],
                                "size": msg["s"],
                                "timestamp": msg["t"],
                            },
                        }
                    else:
                        continue

                    await platform_ws.send(json.dumps(payload))
                    count += 1
                    if count % 100 == 0:
                        print(f"Forwarded {count} messages")


async def main() -> None:
    api_key = os.environ.get("ALPACA_API_KEY", "YOUR_ALPACA_API_KEY")
    api_secret = os.environ.get("ALPACA_API_SECRET", "YOUR_ALPACA_API_SECRET")
    platform_url = os.environ.get("PLATFORM_WS_URL", "ws://localhost:8080/ws/data")
    symbols = ["AAPL", "MSFT", "TSLA"]

    print(f"Connecting to Alpaca SIP feed for {symbols}")
    print(f"Forwarding to platform at {platform_url}")
    await forward_to_platform(platform_url, api_key, api_secret, symbols)


if __name__ == "__main__":
    asyncio.run(main())
