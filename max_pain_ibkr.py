#!/usr/bin/env python3
"""Fetch an IBKR option chain and calculate open-interest max pain.

TWS or IB Gateway must be running with API access enabled.  Market-data
subscriptions are required for live prices/open interest; delayed data can be
requested with ``--market-data-type 3``.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import time
from dataclasses import dataclass
from typing import Iterable

asyncio.set_event_loop(asyncio.new_event_loop())

from ib_insync import IB, Option, Stock  # noqa: E402

TRADING_CLASS_BY_SYMBOL = {
    "ASML": "ASL",
    "ADYEN": "ADY",
    "BESI": "BESI",
    "ING": "ING",
}


@dataclass(frozen=True)
class OptionRow:
    strike: float
    right: str
    open_interest: float
    multiplier: float


def valid_number(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def calculate_max_pain(rows: Iterable[OptionRow]) -> dict[str, object]:
    """Calculate OI payout max pain and the ten lowest-payout strikes.

    Candidate settlement prices are the strikes present in the chain.  A call
    pays max(S-K, 0), while a put pays max(K-S, 0), per share.
    """
    rows = tuple(rows)
    strikes = sorted({row.strike for row in rows})
    if not strikes:
        raise ValueError("No option rows with strikes were supplied")

    payout_by_strike: dict[float, float] = {}
    for settlement in strikes:
        payout = 0.0
        for row in rows:
            contracts = max(0.0, row.open_interest) * row.multiplier
            intrinsic = (
                max(settlement - row.strike, 0.0)
                if row.right == "C"
                else max(row.strike - settlement, 0.0)
            )
            payout += intrinsic * contracts
        payout_by_strike[settlement] = payout

    oi_level = min(payout_by_strike, key=lambda strike: (payout_by_strike[strike], strike))
    top_ten = sorted(payout_by_strike.items(), key=lambda item: (item[1], item[0]))[:10]
    top_ten.sort(key=lambda item: item[0])
    return {
        "max_pain_strike": oi_level,
        "max_pain_payout": payout_by_strike[oi_level],
        "top_ten": top_ten,
        "payout_by_strike": payout_by_strike,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch an IBKR option chain and calculate max pain."
    )
    parser.add_argument("symbol", help="Underlying ticker, for example AAPL")
    parser.add_argument("expiration", help="Expiration in YYYYMMDD or YYYY-MM-DD format")
    parser.add_argument("--host", default=os.getenv("IB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("IB_PORT", "7496")))
    parser.add_argument("--client-id", type=int, default=int(os.getenv("IB_MAX_PAIN_CLIENT_ID", "779")))
    parser.add_argument("--exchange", default=os.getenv("IB_OPTION_EXCHANGE", "SMART"),
                        help="IBKR exchange for the underlying and options (default: SMART)")
    parser.add_argument("--currency", default=os.getenv("IB_OPTION_CURRENCY", "USD"),
                        help="Contract currency (default: USD; use EUR for FTA listings)")
    parser.add_argument("--trading-class", help="IBKR option trading class, e.g. ASL for ASML")
    parser.add_argument("--market-data-type", type=int, choices=(1, 2, 3, 4), default=3,
                        help="1 live, 2 frozen, 3 delayed, 4 delayed-frozen (default: 3)")
    parser.add_argument("--timeout", type=float, default=12.0,
                        help="Seconds to wait for option market-data ticks (default: 12)")
    parser.add_argument("--output", help="Optional CSV output path")
    parser.add_argument("--chain-output", help="Optional CSV path for the fetched option quotes")
    return parser.parse_args()


def normalize_expiration(value: str) -> str:
    digits = value.replace("-", "")
    if len(digits) != 8 or not digits.isdigit():
        raise ValueError("expiration must be YYYYMMDD or YYYY-MM-DD")
    return digits


def connect(args: argparse.Namespace) -> IB:
    ib = IB()
    ib.connect(args.host, args.port, clientId=args.client_id, timeout=8)
    ib.reqMarketDataType(args.market_data_type)
    return ib


def fetch_rows(ib: IB, args: argparse.Namespace, expiration: str) -> tuple[list[OptionRow], float]:
    print(f"Qualifying underlying {args.symbol.upper()}...")
    underlying = Stock(args.symbol.upper(), args.exchange, args.currency)
    trading_class = args.trading_class or TRADING_CLASS_BY_SYMBOL.get(args.symbol.upper())
    # FTA option contracts identify the underlying through their trading class;
    # the corresponding stock may not qualify under the option exchange code.
    if trading_class:
        print(f"Using option trading class {trading_class}.")
    else:
        qualified = ib.qualifyContracts(underlying)
        if not qualified:
            raise RuntimeError(f"Could not qualify underlying {args.symbol}")
        underlying = qualified[0]

    # Ask for the exact expiration first.  Unlike reqSecDefOptParams (which
    # returns separate strike/expiry sets whose Cartesian product can contain
    # invalid combinations), reqContractDetails returns actual contracts.
    template = Option(
        underlying.symbol, expiration, 0, "", args.exchange,
        currency=args.currency, tradingClass=trading_class or "",
    )
    details = ib.reqContractDetails(template)
    contracts = [detail.contract for detail in details if detail.contract.conId]
    print(f"Found {len(contracts)} valid contracts for expiration {expiration}.")

    # Some instruments/venues do not answer the exact contract-details query.
    # Fall back to the security-definition route in that case.
    definitions = ib.reqSecDefOptParams(
        underlying.symbol, "", underlying.secType, underlying.conId
    ) if not contracts and getattr(underlying, "conId", 0) else []
    matching = [d for d in definitions if expiration in d.expirations]
    if not contracts and not matching:
        if trading_class:
            raise RuntimeError(
                f"No valid {trading_class} option contracts were found for "
                f"{underlying.symbol} {expiration} on {args.exchange}"
            )
        available = sorted({e for d in definitions for e in d.expirations})
        raise RuntimeError(f"Expiration {expiration} is unavailable. Recent expirations: {available[:8]}")
    if contracts:
        multiplier = float(next((c.multiplier for c in contracts if c.multiplier), "100"))
    else:
        print("Falling back to option-chain definitions...")
        # Use SMART when IBKR returned a SMART definition.  Otherwise use the
        # exchange attached to the returned definition; forcing SMART onto an
        # exchange-specific trading class can produce "Unknown contract" errors.
        definition = next((d for d in matching if d.exchange == args.exchange), matching[0])
        option_exchange = definition.exchange
        multiplier = float(definition.multiplier or 100)
        strikes = sorted(float(s) for s in definition.strikes if valid_number(s) and float(s) > 0)
        candidates = [
            Option(underlying.symbol, expiration, strike, right, option_exchange,
                   currency=args.currency, multiplier=str(int(multiplier)),
                   tradingClass=definition.tradingClass)
            for strike in strikes for right in ("C", "P")
        ]
        qualified_contracts = ib.qualifyContracts(*candidates)
        contracts = [contract for contract in qualified_contracts if getattr(contract, "conId", 0)]
        if not contracts:
            raise RuntimeError(
                f"No valid option contracts were found for {underlying.symbol} {expiration}"
            )
    print(f"Requesting open interest for {len(contracts)} contracts...")
    # Use streaming requests, matching the working Greeks service.
    tickers = [ib.reqMktData(contract, "101", snapshot=False, regulatorySnapshot=False)
               for contract in contracts]
    deadline = time.monotonic() + args.timeout
    print(f"Waiting up to {args.timeout:g} seconds for open-interest ticks...")
    while time.monotonic() < deadline:
        ib.sleep(0.25)

    rows: list[OptionRow] = []
    for contract, ticker in zip(contracts, tickers):
        oi = ticker.callOpenInterest if contract.right == "C" else ticker.putOpenInterest
        if not valid_number(oi) or float(oi) < 0:
            continue
        rows.append(OptionRow(
            strike=float(contract.strike), right=contract.right,
            open_interest=float(oi),
            multiplier=multiplier,
        ))
    for contract in contracts:
        ib.cancelMktData(contract)
    print(f"Received open interest for {len(rows)} of {len(contracts)} contracts.")
    return rows, multiplier


def write_csv(path: str, result: dict[str, object]) -> None:
    import csv
    payout = result["payout_by_strike"]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("settlement_strike", "oi_expiration_payout"))
        for strike in sorted(payout):
            writer.writerow((strike, payout[strike]))


def write_chain_csv(path: str, rows: Iterable[OptionRow]) -> None:
    import csv
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("strike", "right", "open_interest", "multiplier"))
        for row in sorted(rows, key=lambda item: (item.strike, item.right)):
            writer.writerow((row.strike, row.right, row.open_interest, row.multiplier))


def main() -> int:
    args = parse_args()
    expiration = normalize_expiration(args.expiration)
    print(f"Connecting to IBKR at {args.host}:{args.port} (market data type {args.market_data_type})...")
    ib = connect(args)
    print("Connected.")
    try:
        rows, multiplier = fetch_rows(ib, args, expiration)
        if not rows:
            raise RuntimeError(
                "No option open-interest quotes were returned. Check that the "
                "expiration has open interest and that TWS/Gateway permits the "
                "selected live or delayed option market data."
            )
        print("Calculating expiration payouts by candidate settlement strike...")
        result = calculate_max_pain(rows)
        print(f"{args.symbol.upper()} {expiration}: {len(rows)} option legs, multiplier {multiplier:g}")
        print(f"OI max pain:        {result['max_pain_strike']:.2f} "
              f"(expiration payout ${result['max_pain_payout']:,.0f})")
        print("Top 10 lowest expiration payouts (ordered by strike):")
        for rank, (strike, payout) in enumerate(result["top_ten"], start=1):
            print(f"  {rank}. {strike:.2f} -> ${payout:,.0f}")
        if args.output:
            write_csv(args.output, result)
            print(f"Wrote strike scores to {args.output}")
        if args.chain_output:
            write_chain_csv(args.chain_output, rows)
            print(f"Wrote option chain to {args.chain_output}")
    finally:
        ib.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
