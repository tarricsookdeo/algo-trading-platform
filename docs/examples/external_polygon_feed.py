"""Example: Stream Polygon.io data into the platform.

Run this separately from the platform. It connects to Polygon.io's
WebSocket and forwards market data to the platform's ingestion
WebSocket endpoint.

Prerequisites:
    - pip install websockets
    - Set POLYGON_API_KEY environment variable
    - The trading platform must be running with ingestion enabled

Usage:
    python docs/examples/external_polygon_feed.py
"""

from __future__ import annotations

import asyncio
import json
import os

import websockets


async def forward_to_platform(
    platform_url: str,
    api_key: str,
    symbols: list[str],
) -> None:
    """Connect to Polygon.io and forward data to the platform ingestion WS."""

    # Connect to the platform's ingestion WebSocket
    async with websockets.connect(platform_url) as platform_ws:
        print(f"Connected to platform at {platform_url}")

        # Connect to Polygon.io WebSocket
        polygon_ws_url = "wss://socket.polygon.io/stocks"
        async with websockets.connect(polygon_ws_url) as polygon_ws:
            # Authenticate with Polygon
            auth_msg = {"action": "auth", "params": api_key}
            await polygon_ws.send(json.dumps(auth_msg))
            response = await polygon_ws.recv()
            print(f"Polygon auth response: {response}")

            # Subscribe to trades and quotes
            trade_channels = ",".join(f"T.{s}" for s in symbols)
            quote_channels = ",".join(f"Q.{s}" for s in symbols)
            bar_channels = ",".join(f"AM.{s}" for s in symbols)
            sub_msg = {
                "action": "subscribe",
                "params": f"{trade_channels},{quote_channels},{bar_channels}",
            }
            await polygon_ws.send(json.dumps(sub_msg))
            response = await polygon_ws.recv()
            print(f"Polygon subscription response: {response}")

            # Forward messages
            count = 0
            async for raw in polygon_ws:
                messages = json.loads(raw)
                for msg in messages:
                    ev = msg.get("ev")

                    if ev == "AM":  # Aggregate (bar)
                        payload = {
                            "type": "bar",
                            "data": {
                                "symbol": msg["sym"],
                                "open": msg["o"],
                                "high": msg["h"],
                                "low": msg["l"],
                                "close": msg["c"],
                                "volume": msg["v"],
                                "timestamp": msg.get("s", msg.get("e", "")),
                            },
                        }
                    elif ev == "Q":  # Quote
                        payload = {
                            "type": "quote",
                            "data": {
                                "symbol": msg["sym"],
                                "bid_price": msg["bp"],
                                "bid_size": msg["bs"],
                                "ask_price": msg["ap"],
                                "ask_size": msg["as"],
                                "timestamp": msg.get("t", ""),
                            },
                        }
                    elif ev == "T":  # Trade
                        payload = {
                            "type": "trade",
                            "data": {
                                "symbol": msg["sym"],
                                "price": msg["p"],
                                "size": msg["s"],
                                "timestamp": msg.get("t", ""),
                            },
                        }
                    else:
                        continue

                    await platform_ws.send(json.dumps(payload))
                    count += 1
                    if count % 100 == 0:
                        print(f"Forwarded {count} messages")


async def main() -> None:
    api_key = os.environ.get("POLYGON_API_KEY", "YOUR_POLYGON_API_KEY")
    platform_url = os.environ.get("PLATFORM_WS_URL", "ws://localhost:8080/ws/data")
    symbols = ["AAPL", "MSFT", "TSLA"]

    print(f"Connecting to Polygon.io feed for {symbols}")
    print(f"Forwarding to platform at {platform_url}")
    await forward_to_platform(platform_url, api_key, symbols)


if __name__ == "__main__":
    asyncio.run(main())
