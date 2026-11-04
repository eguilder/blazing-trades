#!/usr/bin/env python3
"""Download historical OHLCV candles from IBKR and save them as CSV.

TWS or IB Gateway must be running with API access enabled.  Intraday requests
are split into chunks that fit IBKR's historical-data duration limits.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import re
import time
from collections import deque
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

asyncio.set_event_loop(asyncio.new_event_loop())

from ib_insync import IB, Stock  # noqa: E402


BAR_SIZE_BY_MINUTES = {
    1: "1 min",
    2: "2 mins",
    3: "3 mins",
    5: "5 mins",
    10: "10 mins",
    15: "15 mins",
    20: "20 mins",
    30: "30 mins",
    60: "1 hour",
    120: "2 hours",
    180: "3 hours",
    240: "4 hours",
    360: "6 hours",
    480: "8 hours",
    1440: "1 day",
}

# Conservative request sizes for the intraday bar sizes accepted by IBKR.
CHUNK_DAYS_BY_MINUTES = {
    1: 1,
    2: 1,
    3: 1,
    5: 7,
    10: 7,
    15: 7,
    20: 7,
    30: 30,
    60: 30,
    120: 30,
    180: 30,
    240: 30,
    360: 30,
    480: 30,
    1440: 365,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download historical IBKR OHLCV candles to a CSV file.",
        epilog=(
            "Example: py -3 .\\ibkr_historical.py AAPL 2y 5m "
            "--output aapl_5m.csv"
        ),
    )
    parser.add_argument("ticker", help="Stock ticker, e.g. AAPL")
    parser.add_argument("history", help="Lookback period, e.g. 2y")
    parser.add_argument(
        "timeframe",
        help="Candle size with unit, e.g. 5m, 2h, or 1d",
    )
    parser.add_argument("--host", default=os.getenv("IB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("IB_PORT", "7496")))
    parser.add_argument(
        "--client-id", type=int, default=int(os.getenv("IB_HISTORICAL_CLIENT_ID", "780"))
    )
    parser.add_argument("--exchange", default=os.getenv("IB_STOCK_EXCHANGE", "SMART"))
    parser.add_argument("--currency", default=os.getenv("IB_STOCK_CURRENCY", "USD"))
    parser.add_argument(
        "--market-data-type",
        type=int,
        choices=(1, 2, 3, 4),
        default=3,
        help="1 live, 2 frozen, 3 delayed, 4 delayed-frozen (default: 3)",
    )
    parser.add_argument(
        "--what-to-show",
        choices=("TRADES", "MIDPOINT", "BID", "ASK", "ADJUSTED_LAST"),
        default="TRADES",
        help="IBKR historical data series (default: TRADES)",
    )
    parser.add_argument(
        "--include-extended-hours",
        action="store_true",
        help="Include pre-market and after-hours candles (default: regular hours only)",
    )
    parser.add_argument("--output", type=Path, help="CSV path (default: TICKER_TIMEFRAME.csv)")
    parser.add_argument(
        "--request-pause",
        type=float,
        default=0.25,
        help="Seconds between requests (default: 0.25)",
    )
    args = parser.parse_args()
    try:
        args.years = parse_history(args.history)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    try:
        args.timeframe_minutes = parse_timeframe(args.timeframe)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    if args.timeframe_minutes not in BAR_SIZE_BY_MINUTES:
        allowed = ", ".join(str(value) for value in BAR_SIZE_BY_MINUTES)
        parser.error(
            "timeframe must use a supported interval; equivalent minute values "
            f"are: {allowed}"
        )
    if args.request_pause < 0:
        parser.error("--request-pause cannot be negative")
    if args.output is None:
        args.output = Path(f"{args.ticker.upper()}_{args.timeframe_minutes}m.csv")
    return args


def parse_timeframe(value: str) -> int:
    match = re.fullmatch(r"(\d+)([mhd])", value.strip().lower())
    if not match:
        raise argparse.ArgumentTypeError("timeframe must look like 5m, 2h, or 1d")
    amount = int(match.group(1))
    multiplier = {"m": 1, "h": 60, "d": 1440}[match.group(2)]
    return amount * multiplier


def parse_history(value: str) -> int:
    match = re.fullmatch(r"(\d+)y", value.strip().lower())
    if not match or int(match.group(1)) < 1:
        raise argparse.ArgumentTypeError("history must look like 1y, 2y, etc.")
    return int(match.group(1))


def format_end_datetime(value: datetime) -> str:
    """Format a timezone-aware UTC datetime accepted by IBKR."""
    return value.astimezone(timezone.utc).strftime("%Y%m%d %H:%M:%S UTC")


def bar_timestamp(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def wait_for_pacing(request_times: deque[float]) -> None:
    """Respect IBKR's 60 historical requests per 10-minute pacing limit."""
    now = time.monotonic()
    while request_times and now - request_times[0] >= 600:
        request_times.popleft()
    if len(request_times) >= 60:
        time.sleep(max(0.0, 600 - (now - request_times[0]) + 0.05))
        request_times.popleft()


def fetch_bars(
    ib: IB,
    contract: Any,
    years: int,
    timeframe_minutes: int,
    pause: float,
    what_to_show: str = "TRADES",
    use_rth: bool = True,
) -> list[Any]:
    bar_size = BAR_SIZE_BY_MINUTES[timeframe_minutes]
    chunk_days = CHUNK_DAYS_BY_MINUTES[timeframe_minutes]
    start = datetime.now(timezone.utc) - timedelta(days=365 * years)
    end = datetime.now(timezone.utc)
    request_times: deque[float] = deque()
    bars_by_timestamp: dict[str, Any] = {}

    while end > start:
        wait_for_pacing(request_times)
        request_end = end
        duration_days = min(chunk_days, max(1, (end - start).days + 1))
        print(f"Requesting {bar_size} bars ending {format_end_datetime(request_end)}...")
        bars = ib.reqHistoricalData(
            contract,
            endDateTime=format_end_datetime(request_end),
            durationStr=f"{duration_days} D",
            barSizeSetting=bar_size,
            whatToShow=what_to_show,
            useRTH=int(use_rth),
            formatDate=2,
            keepUpToDate=False,
            chartOptions=[],
        )
        request_times.append(time.monotonic())
        for bar in bars:
            bars_by_timestamp[bar_timestamp(bar.date)] = bar
        if bars:
            oldest = min(bar_timestamp(bar.date) for bar in bars)
            oldest_value = next(bar.date for bar in bars if bar_timestamp(bar.date) == oldest)
            if isinstance(oldest_value, datetime):
                candidate_end = oldest_value.astimezone(timezone.utc) - timedelta(seconds=1)
                # A defensive fallback prevents a faulty/mock response that
                # contains only bars newer than the requested end from causing
                # an endless loop.
                end = candidate_end if candidate_end < end else end - timedelta(days=duration_days)
            else:
                end -= timedelta(days=duration_days)
        else:
            end -= timedelta(days=duration_days)
        if pause:
            time.sleep(pause)

    return [bars_by_timestamp[key] for key in sorted(bars_by_timestamp)]


def write_csv(path: Path, bars: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume", "average", "bar_count"])
        for bar in bars:
            writer.writerow([
                bar_timestamp(bar.date),
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume,
                bar.average,
                bar.barCount,
            ])


def main() -> int:
    args = parse_args()
    contract = Stock(args.ticker.upper(), args.exchange, args.currency)
    ib = IB()
    print(f"Connecting to IBKR at {args.host}:{args.port}...")
    ib.connect(args.host, args.port, clientId=args.client_id, timeout=10)
    ib.reqMarketDataType(args.market_data_type)
    try:
        ib.qualifyContracts(contract)
        bars = fetch_bars(
            ib,
            contract,
            args.years,
            args.timeframe_minutes,
            args.request_pause,
            what_to_show=args.what_to_show,
            use_rth=not args.include_extended_hours,
        )
        write_csv(args.output, bars)
        print(f"Wrote {len(bars):,} candles to {args.output}")
    finally:
        ib.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
