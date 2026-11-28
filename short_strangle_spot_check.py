#!/usr/bin/env python3
"""Stateless, read-only IBKR spot-check for short strangles.

The script reads option positions from the connected IBKR account, requests
model Greeks for the current short legs and nearby chain contracts, and prints
one of HOLD, REPOSITION, ROLL, HEDGE, or TEMPORARY_CLOSE_REVIEW.  It never submits
orders and writes no files.

Delayed or delayed-frozen market data can be selected, so the report can also
be run outside regular market hours.  IBKR must still be connected and able to
return contract definitions/model data for the account's instruments.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import math
import os
from dataclasses import dataclass
from datetime import date, datetime
from types import SimpleNamespace
from typing import Iterable

asyncio.set_event_loop(asyncio.new_event_loop())

from ib_insync import IB, Option, Stock  # noqa: E402


DEFAULT_HOST = os.getenv("IB_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("IB_PORT", "7496"))
DEFAULT_CLIENT_ID = int(os.getenv("IB_STRANGLE_CLIENT_ID", "780"))
DEFAULT_EXCHANGE = os.getenv("IB_OPTION_EXCHANGE", "SMART")
DEFAULT_STOCK_EXCHANGE = os.getenv("IB_STOCK_EXCHANGE", "SMART")
DEFAULT_CURRENCY = os.getenv("IB_OPTION_CURRENCY", "USD")
# Delayed-frozen (4) is the useful outside-hours mode.  IBKR can return the
# last available quote/model values after the regular session has closed.
DEFAULT_MARKET_DATA_TYPE = int(os.getenv("IB_MARKET_DATA_TYPE", "4"))
DEFAULT_WAIT = float(os.getenv("IB_STRANGLE_WAIT", "8"))
DEFAULT_TARGET_DELTA = float(os.getenv("IB_STRANGLE_TARGET_DELTA", "0.25"))
DEFAULT_THREAT_DELTA = float(os.getenv("IB_STRANGLE_THREAT_DELTA", "0.35"))
DEFAULT_CLOSE_DELTA = float(os.getenv("IB_STRANGLE_CLOSE_DELTA", "0.45"))
DEFAULT_VOL_RATIO = float(os.getenv("IB_STRANGLE_VOL_RATIO", "1.25"))
DEFAULT_HEDGE_MAX_CALL_DELTA = float(os.getenv("IB_STRANGLE_HEDGE_MAX_CALL_DELTA", "0.35"))


@dataclass
class Leg:
    contract: object
    quantity: float
    delta: float | None = None
    theta: float | None = None
    implied_volatility: float | None = None
    underlying_price: float | None = None
    premium: float | None = None
    mid_price: float | None = None

    @property
    def symbol(self) -> str:
        return str(getattr(self.contract, "symbol", "")).upper()

    @property
    def right(self) -> str:
        return str(getattr(self.contract, "right", "")).upper()

    @property
    def strike(self) -> float:
        return float(getattr(self.contract, "strike", 0.0))

    @property
    def expiry(self) -> str:
        return normalize_expiry(getattr(self.contract, "lastTradeDateOrContractMonth", ""))

    @property
    def dte(self) -> int:
        expiry = parse_expiry(self.expiry)
        return max(0, (expiry - date.today()).days)


@dataclass
class ChainQuote:
    contract: object
    delta: float | None
    theta: float | None
    implied_volatility: float | None
    mid_price: float | None = None
    quote_price: float | None = None

    @property
    def abs_delta(self) -> float | None:
        return abs(self.delta) if self.delta is not None else None


def valid_number(value: object) -> bool:
    try:
        return value is not None and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def normalize_expiry(value: object) -> str:
    text = str(value or "").replace("-", "")
    return text[:8]


def parse_expiry(value: str) -> date:
    return datetime.strptime(normalize_expiry(value), "%Y%m%d").date()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only IBKR short-strangle spot-check for portfolio option positions."
    )
    parser.add_argument("--symbol", help="Only inspect this underlying; default is all portfolio underlyings")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--client-id", type=int, default=DEFAULT_CLIENT_ID)
    parser.add_argument("--exchange", default=DEFAULT_EXCHANGE, help="Option exchange fallback")
    parser.add_argument("--stock-exchange", default=DEFAULT_STOCK_EXCHANGE)
    parser.add_argument("--currency", default=DEFAULT_CURRENCY)
    parser.add_argument("--market-data-type", type=int, choices=(1, 2, 3, 4), default=DEFAULT_MARKET_DATA_TYPE,
                        help="1 live, 2 frozen, 3 delayed, 4 delayed-frozen (default: %(default)s)")
    parser.add_argument("--wait", type=float, default=DEFAULT_WAIT, help="Seconds to wait for each model quote")
    parser.add_argument("--target-delta", type=float, default=DEFAULT_TARGET_DELTA)
    parser.add_argument("--threat-delta", type=float, default=DEFAULT_THREAT_DELTA)
    parser.add_argument("--close-delta", type=float, default=DEFAULT_CLOSE_DELTA)
    parser.add_argument("--vol-spike-ratio", type=float, default=DEFAULT_VOL_RATIO,
                        help="IV/HV ratio treated as a volatility spike")
    parser.add_argument("--hedge-max-call-delta", type=float, default=DEFAULT_HEDGE_MAX_CALL_DELTA,
                        help="Upper call delta for the HEDGE alternative (default: %(default)s)")
    parser.add_argument("--risk-free-rate", type=float, default=0.05,
                        help="Annualized rate used only for the outside-hours fallback model")
    return parser.parse_args()


def connect(args: argparse.Namespace) -> IB:
    ib = IB()
    ib.connect(args.host, args.port, clientId=args.client_id, timeout=8)
    ib.reqMarketDataType(args.market_data_type)
    return ib


def fetch_option_positions(ib: IB, symbol: str | None = None) -> list[object]:
    wanted = symbol.upper() if symbol else None
    return [
        position for position in ib.positions()
        if getattr(position.contract, "secType", "").upper() == "OPT"
        and float(position.position) != 0
        and (wanted is None or position.contract.symbol.upper() == wanted)
    ]


def market_contract(contract: object, exchange: str) -> object:
    result = copy.copy(contract)
    if not getattr(result, "exchange", ""):
        result.exchange = exchange
    return result


def ticker_values(ticker: object) -> Iterable[object]:
    for name in ("marketPrice", "last", "markPrice", "close", "bid", "ask",
                 "delayedLast", "delayedClose", "delayedBid", "delayedAsk"):
        value = getattr(ticker, name, None)
        if callable(value):
            try:
                value = value()
            except Exception:
                value = None
        yield value


def underlying_price_candidates(ticker: object) -> Iterable[object]:
    """Prefer current/mark prices; leave the prior close as a last resort."""
    for name in ("markPrice", "last", "delayedLast", "bid", "ask", "delayedBid", "delayedAsk", "close", "delayedClose"):
        value = getattr(ticker, name, None)
        if callable(value):
            try:
                value = value()
            except Exception:
                value = None
        yield value


def available_greeks(ticker: object) -> object | None:
    """Return the best Greeks snapshot available from live or frozen ticks."""
    for name in ("modelGreeks", "lastGreeks", "bidGreeks", "askGreeks"):
        greeks = getattr(ticker, name, None)
        if greeks is not None:
            return greeks
    return None


def estimated_delta(contract: object, spot: float | None, volatility: float | None,
                    risk_free_rate: float) -> float | None:
    """Estimate delta from IBKR spot/HV when no option Greeks tick is returned."""
    if not (valid_number(spot) and float(spot) > 0 and valid_number(volatility) and float(volatility) > 0):
        return None
    try:
        expiry = parse_expiry(getattr(contract, "lastTradeDateOrContractMonth", ""))
        years = max((expiry - date.today()).days, 1) / 365.0
        strike = float(contract.strike)
        vol = float(volatility)
        d1 = (
            math.log(float(spot) / strike)
            + (risk_free_rate + 0.5 * vol * vol) * years
        ) / (vol * math.sqrt(years))
        normal_cdf = 0.5 * (1.0 + math.erf(d1 / math.sqrt(2.0)))
        return normal_cdf if str(contract.right).upper() == "C" else normal_cdf - 1.0
    except (AttributeError, TypeError, ValueError, ZeroDivisionError):
        return None


def estimated_theta(contract: object, spot: float | None, volatility: float | None,
                    risk_free_rate: float) -> float | None:
    """Estimate option theta per share per day from IBKR spot/HV."""
    if not (valid_number(spot) and float(spot) > 0 and valid_number(volatility) and float(volatility) > 0):
        return None
    try:
        expiry = parse_expiry(getattr(contract, "lastTradeDateOrContractMonth", ""))
        years = max((expiry - date.today()).days, 1) / 365.0
        strike = float(contract.strike)
        vol = float(volatility)
        sqrt_years = math.sqrt(years)
        d1 = (
            math.log(float(spot) / strike)
            + (risk_free_rate + 0.5 * vol * vol) * years
        ) / (vol * sqrt_years)
        d2 = d1 - vol * sqrt_years
        normal_pdf = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
        normal_cdf_d2 = 0.5 * (1.0 + math.erf(d2 / math.sqrt(2.0)))
        discount = math.exp(-risk_free_rate * years)
        common = -(float(spot) * normal_pdf * vol) / (2.0 * sqrt_years)
        if str(contract.right).upper() == "C":
            annual_theta = common - risk_free_rate * strike * discount * normal_cdf_d2
        else:
            annual_theta = common + risk_free_rate * strike * discount * (1.0 - normal_cdf_d2)
        return annual_theta / 365.0
    except (AttributeError, TypeError, ValueError, ZeroDivisionError):
        return None
def bid_ask_mid(ticker: object) -> float | None:
    bid = getattr(ticker, "bid", None)
    ask = getattr(ticker, "ask", None)
    if valid_number(bid) and valid_number(ask) and float(bid) >= 0 and float(ask) >= float(bid):
        return (float(bid) + float(ask)) / 2.0
    return None


def implied_move_limits(spot: float | None, put_price: float | None,
                        call_price: float | None) -> tuple[float, float] | None:
    if spot is None or put_price is None or call_price is None:
        return None
    width = put_price + call_price
    return spot - width, spot + width


def request_model(ib: IB, contract: object, wait: float, exchange: str) -> tuple[object | None, float | None, float | None]:
    requested = market_contract(contract, exchange)
    # Explicitly ask for option quote/IV ticks.  This is important for
    # delayed-frozen data: Mosaic may display a model value while an API
    # request with an empty generic-tick list returns no modelGreeks object.
    try:
        qualified = ib.qualifyContracts(requested)
        requested = qualified[0] if qualified else requested
    except Exception:
        # A position contract can already be fully qualified.  Keep using it
        # if contract qualification is temporarily unavailable.
        pass
    ticker = ib.reqMktData(requested, "100,101,104,106", False, False)
    try:
        elapsed = 0.0
        while elapsed < wait:
            greeks = available_greeks(ticker)
            if greeks is not None:
                return greeks, next((float(v) for v in ticker_values(ticker) if valid_number(v) and float(v) >= 0), None), bid_ask_mid(ticker)
            ib.sleep(0.25)
            elapsed += 0.25
        return available_greeks(ticker), next((float(v) for v in ticker_values(ticker) if valid_number(v) and float(v) >= 0), None), bid_ask_mid(ticker)
    finally:
        ib.cancelMktData(requested)


def request_underlying(ib: IB, symbol: str, args: argparse.Namespace) -> tuple[float | None, float | None]:
    stock = Stock(symbol, args.stock_exchange, args.currency)
    qualified = ib.qualifyContracts(stock)
    requested = qualified[0] if qualified else stock
    ticker = ib.reqMktData(requested, "104,106,221,233", False, False)
    try:
        elapsed = 0.0
        while elapsed < args.wait:
            candidates = list(underlying_price_candidates(ticker))
            # Do not treat the prior close as the current spot while IBKR is
            # still delivering mark/last data.  This matters outside hours,
            # when close can be materially stale while markPrice is current.
            spot = next((float(v) for v in candidates[:7] if valid_number(v) and float(v) > 0), None)
            historical_vol = getattr(ticker, "histVolatility", None)
            if spot is not None:
                return spot, float(historical_vol) if valid_number(historical_vol) else None
            ib.sleep(0.25)
            elapsed += 0.25
        candidates = list(underlying_price_candidates(ticker))
        spot = next((float(v) for v in candidates[:7] if valid_number(v) and float(v) > 0), None)
        if spot is None:
            spot = next((float(v) for v in candidates[7:] if valid_number(v) and float(v) > 0), None)
        historical_vol = getattr(ticker, "histVolatility", None)
        return spot, float(historical_vol) if valid_number(historical_vol) else None
    finally:
        ib.cancelMktData(requested)


def actual_contracts(ib: IB, symbol: str, expiry: str, exchange: str, currency: str) -> list[object]:
    template = Option(symbol, expiry, 0, "", exchange, currency=currency)
    details = ib.reqContractDetails(template)
    return [detail.contract for detail in details if getattr(detail.contract, "conId", 0)]


def nearby_contracts(contracts: Iterable[object], spot: float | None, limit_per_side: int = 80) -> list[object]:
    """Keep model requests bounded while retaining strikes around spot."""
    contracts = list(contracts)
    if spot is None:
        return contracts[: limit_per_side * 2]
    selected = []
    for right in ("P", "C"):
        side = [contract for contract in contracts if getattr(contract, "right", "").upper() == right]
        side.sort(key=lambda contract: abs(float(contract.strike) - spot))
        selected.extend(side[:limit_per_side])
    return selected


def chain_quotes(ib: IB, contracts: list[object], wait: float, exchange: str,
                 spot: float | None, historical_vol: float | None,
                 risk_free_rate: float) -> list[ChainQuote]:
    """Request nearby chain Greeks concurrently and wait once for the batch."""
    requested = []
    for contract in contracts:
        market = market_contract(contract, exchange)
        try:
            qualified = ib.qualifyContracts(market)
            market = qualified[0] if qualified else market
        except Exception:
            pass
        requested.append(market)
    tickers = [ib.reqMktData(contract, "100,101,104,106", False, False) for contract in requested]
    elapsed = 0.0
    try:
        while elapsed < wait and not all(available_greeks(ticker) is not None for ticker in tickers):
            ib.sleep(0.25)
            elapsed += 0.25
        quotes = []
        for contract, ticker in zip(requested, tickers):
            greeks = available_greeks(ticker)
            delta = float(greeks.delta) if greeks is not None and valid_number(greeks.delta) else estimated_delta(
                contract, spot, historical_vol, risk_free_rate
            )
            implied_volatility = (
                float(greeks.impliedVolatility)
                if greeks is not None and valid_number(getattr(greeks, "impliedVolatility", None))
                else historical_vol
            )
            quotes.append(ChainQuote(
                contract=contract,
                delta=delta,
                theta=float(greeks.theta) if greeks is not None and valid_number(getattr(greeks, "theta", None)) else estimated_theta(
                    contract, spot, historical_vol, risk_free_rate
                ),
                implied_volatility=implied_volatility,
                mid_price=bid_ask_mid(ticker),
                quote_price=next((float(v) for v in ticker_values(ticker) if valid_number(v) and float(v) >= 0), None),
            ))
        return quotes
    finally:
        for contract in requested:
            ib.cancelMktData(contract)


def nearest_delta(quotes: Iterable[ChainQuote], right: str, target: float) -> ChainQuote | None:
    candidates = [q for q in quotes if getattr(q.contract, "right", "").upper() == right and q.abs_delta is not None]
    # A replacement is only acceptable when it is no more aggressive than the
    # requested target.  Choose the closest available delta from below rather
    # than silently returning a higher-delta strike.
    acceptable = [q for q in candidates if q.abs_delta <= target + 1e-9]
    return max(acceptable, key=lambda q: (q.abs_delta, -float(q.contract.strike))) if acceptable else None


def group_legs(positions: Iterable[object]) -> dict[tuple[str, str], dict[str, Leg]]:
    groups: dict[tuple[str, str], dict[str, Leg]] = {}
    for position in positions:
        contract = position.contract
        right = str(getattr(contract, "right", "")).upper()
        if right not in {"C", "P"} or float(position.position) >= 0:
            continue
        leg = Leg(contract=contract, quantity=float(position.position))
        groups.setdefault((leg.symbol, leg.expiry), {})[right] = leg
    return groups


def is_strike_breach(leg: Leg, spot: float | None) -> bool:
    return spot is not None and ((leg.right == "P" and spot <= leg.strike) or (leg.right == "C" and spot >= leg.strike))


def is_volatility_spike(legs: Iterable[Leg], historical_vol: float | None, ratio: float) -> bool:
    if historical_vol is None or historical_vol <= 0:
        return False
    return any(leg.implied_volatility is not None and leg.implied_volatility >= historical_vol * ratio for leg in legs)


def decision(legs: dict[str, Leg], spot: float | None, historical_vol: float | None,
             vol_ratio: float, threat_delta: float, close_delta: float,
             hedge_max_call_delta: float = DEFAULT_HEDGE_MAX_CALL_DELTA) -> tuple[str, list[str]]:
    active = [leg for leg in legs.values() if leg.delta is not None]
    threatened = [leg for leg in active if abs(leg.delta) >= threat_delta]
    breaches = [leg for leg in legs.values() if is_strike_breach(leg, spot)]
    vol_spike = is_volatility_spike(active, historical_vol, vol_ratio)
    severe = [leg for leg in threatened if abs(leg.delta) >= close_delta]
    reasons = []
    if severe and (vol_spike or breaches):
        reasons.append("short-leg delta is at least %.2f" % close_delta)
        if vol_spike:
            reasons.append("implied volatility is elevated versus historical volatility")
        if breaches:
            reasons.append("spot has breached a short strike")
        return "TEMPORARY_CLOSE_REVIEW", reasons
    if not active:
        return "HOLD", ["model delta unavailable for the short legs"]
    put = legs.get("P")
    call = legs.get("C")
    if (
        put is not None and call is not None
        and put.delta is not None and call.delta is not None
        and 0.25 < abs(call.delta) <= hedge_max_call_delta
        and 0.20 <= abs(put.delta) <= 0.35
        and not vol_spike
    ):
        return "HEDGE", [
            "short call delta is above 0.25 but not materially elevated",
            "untested short put is between 0.20 and 0.35 delta inclusive and IV is not spiked",
            "buy stock to offset the short call delta instead of repositioning",
        ]
    abs_deltas = {leg.right: abs(leg.delta) for leg in active}
    if (
        len(active) == 2
        and all(delta < 0.25 for delta in abs_deltas.values())
        and any(delta < 0.15 for delta in abs_deltas.values())
    ):
        return "REPOSITION", [
            "both short-leg deltas are below 0.25, but at least one is below 0.15",
            "tighten only legs below 0.20 toward approximately 0.25 delta",
        ]
    if max(abs(leg.delta) for leg in active) < threat_delta:
        return "HOLD", ["both short-leg deltas remain below the threat threshold"]
    dte = next(iter(legs.values())).dte
    max_delta = max(abs(leg.delta) for leg in active)
    total_abs_delta = sum(abs(leg.delta) for leg in active)
    # Avoid an early full roll when the position is only moderately stressed:
    # at DTE 21-24, reposition if the threatened leg is 0.25-0.40 delta and
    # the combined absolute delta remains below 0.40.
    if (
        20 < dte <= 24
        and 0.25 <= max_delta < 0.40
        and total_abs_delta < 0.40
    ):
        return "REPOSITION", [
            "DTE is above 20, so repositioning is preferred over an early full roll",
            "the threatened leg is between 0.25 and 0.40 delta and combined absolute delta is below 0.40",
        ]
    if dte <= 20:
        return "ROLL", ["DTE is 20 or less and a short leg is threatened"]
    if 28 <= dte <= 40:
        return "REPOSITION", ["DTE is still long (28-40), so repositioning is preferred over an early full roll"]
    if dte <= 24:
        return "ROLL", ["DTE is 21-24 but the early-roll guard is not satisfied"]
    return "HOLD", ["a short leg is threatened, but DTE is outside the reposition window"]


def print_rules(args: argparse.Namespace) -> None:
    print_block("RULES", [
        "Short-strangle spot check: read-only portfolio and option-chain review",
        f"Replacement strikes: absolute delta <= {args.target_delta:.2f} (default target)",
        "DTE 40-28: reposition a threatened leg toward the replacement delta target",
        "DTE 27-25: hold unless another higher-priority review condition applies",
        "DTE 24-21: reposition when threatened-leg delta is 0.25-0.40 and combined absolute delta is < 0.40",
        "DTE 20 or less: prefer a full roll when a short leg is threatened",
        "Low-delta tightening: if both legs are < 0.25 and one is < 0.15, reposition legs < 0.20 toward 0.25",
        f"HEDGE: call delta > 0.25 and <= {args.hedge_max_call_delta:.2f}, untested put delta >= 0.20 and <= 0.35, and no IV spike; buy stock to offset the call",
        f"Temporary-close review: delta >= {args.close_delta:.2f} plus strike breach or IV/HV >= {args.vol_spike_ratio:.2f}x",
        "Outside-hours fallback: use IBKR spot and historical volatility for estimated deltas when option Greeks are unavailable",
    ])


def print_block(title: str, lines: Iterable[str]) -> None:
    lines = [str(line) for line in lines]
    width = max(78, len(title) + 6, *(len(line) + 4 for line in lines))
    print("\n+" + "=" * (width - 2) + "+")
    print("|" + f" {title} ".center(width - 2) + "|")
    print("+" + "-" * (width - 2) + "+")
    for line in lines:
        print("| " + line.ljust(width - 4) + " |")
    print("+" + "=" * (width - 2) + "+")


def replacement_rights(legs: dict[str, Leg], action: str, threat_delta: float) -> list[str]:
    if action == "ROLL":
        return ["P", "C"]
    if action != "REPOSITION":
        return []
    deltas = [abs(leg.delta) for leg in legs.values() if leg.delta is not None]
    if (
        len(deltas) == 2
        and all(delta < 0.25 for delta in deltas)
        and any(delta < 0.15 for delta in deltas)
    ):
        return [right for right, leg in legs.items() if leg.delta is not None and abs(leg.delta) < 0.20]
    return [right for right, leg in legs.items() if leg.delta is not None and abs(leg.delta) >= threat_delta]


def print_group(ib: IB, symbol: str, expiry: str, legs: dict[str, Leg], args: argparse.Namespace) -> None:
    spot, historical_vol = request_underlying(ib, symbol, args)
    ibkr_greeks_available = True
    for leg in legs.values():
        greeks, premium, mid_price = request_model(ib, leg.contract, args.wait, args.exchange)
        if greeks is None:
            ibkr_greeks_available = False
        leg.delta = float(greeks.delta) if greeks is not None and valid_number(greeks.delta) else estimated_delta(
            leg.contract, spot, historical_vol, args.risk_free_rate
        )
        leg.theta = float(greeks.theta) if greeks is not None and valid_number(getattr(greeks, "theta", None)) else estimated_theta(
            leg.contract, spot, historical_vol, args.risk_free_rate
        )
        leg.implied_volatility = (
            float(greeks.impliedVolatility)
            if greeks is not None and valid_number(getattr(greeks, "impliedVolatility", None))
            else historical_vol
        )
        leg.underlying_price = float(greeks.undPrice) if greeks is not None and valid_number(getattr(greeks, "undPrice", None)) else spot
        leg.premium = premium
        leg.mid_price = mid_price
    action, reasons = decision(
        legs, spot, historical_vol, args.vol_spike_ratio, args.threat_delta,
        args.close_delta, args.hedge_max_call_delta
    )
    action_lines = [
        f"Decision: {action} | {symbol} {expiry} | {next(iter(legs.values())).dte} DTE",
        f"Spot: {spot:.2f}" if spot is not None else "Spot: unavailable",
    ]
    if not ibkr_greeks_available:
        action_lines.append("Note: IBKR option Greeks unavailable; deltas/IV use an outside-hours historical-volatility estimate.")
    for right in ("P", "C"):
        leg = legs.get(right)
        if leg is None:
            continue
        delta = f"{leg.delta:.3f}" if leg.delta is not None else "n/a"
        theta = f"{leg.theta:.4f}" if leg.theta is not None else "n/a"
        iv = f"{leg.implied_volatility:.3f}" if leg.implied_volatility is not None else "n/a"
        breach = " BREACH" if is_strike_breach(leg, spot) else ""
        action_lines.append(f"Short {right}: strike {leg.strike:g}, qty {leg.quantity:g}, delta {delta}, theta/day {theta}, IV {iv}{breach}")
    for reason in reasons:
        action_lines.append(f"Reason: {reason}")

    if spot is None:
        spot = next((leg.underlying_price for leg in legs.values() if leg.underlying_price is not None), None)
    same_expiry = nearby_contracts(
        actual_contracts(ib, symbol, expiry, args.exchange, args.currency), spot
    )
    same_quotes = chain_quotes(ib, same_expiry, args.wait, args.exchange, spot, historical_vol, args.risk_free_rate)
    later_expiry = next_later_expiry(ib, symbol, expiry, args.exchange, args.currency)
    replacement_quotes = same_quotes
    replacement_label = expiry
    if action == "ROLL" and later_expiry:
        replacement_label = later_expiry
        replacement_quotes = chain_quotes(
            ib,
            nearby_contracts(
                actual_contracts(ib, symbol, later_expiry, args.exchange, args.currency), spot
            ),
            args.wait,
            args.exchange,
            spot,
            historical_vol,
            args.risk_free_rate,
        )
    replacement_by_right = {
        right: nearest_delta(replacement_quotes, right, args.target_delta)
        for right in ("P", "C")
    }
    current_prices = {
        right: (legs[right].mid_price if legs[right].mid_price is not None else legs[right].premium)
        for right in ("P", "C")
    }
    current_limits = implied_move_limits(spot, current_prices["P"], current_prices["C"])
    current_source = "bid/ask mids" if all(legs[right].mid_price is not None for right in ("P", "C")) else "mid/last/close fallback"
    if current_limits is not None:
        action_lines.append(f"Current implied move limits ({current_source}): {current_limits[0]:.2f} to {current_limits[1]:.2f}")
    else:
        action_lines.append("Current implied move limits: unavailable")
    if action in {"ROLL", "REPOSITION"}:
        for right in ("P", "C"):
            replacement = replacement_by_right[right]
            if replacement is not None:
                suggestion = f"Suggested {right}: {float(replacement.contract.strike):g} ({replacement_label}, |delta| {replacement.abs_delta:.3f})"
                replacement_theta = f"{replacement.theta:.4f}" if replacement.theta is not None else "n/a"
                suggestion += f", theta/day {replacement_theta}"
                action_lines.append(suggestion)
            else:
                action_lines.append(f"Suggested {right}: unavailable (no chain contract at or below |delta| {args.target_delta:.2f})")
    elif action == "HEDGE":
        call = legs["C"]
        multiplier = int(getattr(call.contract, "multiplier", 100) or 100)
        shares = math.ceil(abs(call.delta) * abs(call.quantity) * multiplier)
        action_lines.append(f"Suggested hedge: buy approximately {shares} shares to offset the short call delta")

    if action in {"ROLL", "REPOSITION"}:
        rights_to_replace = replacement_rights(legs, action, args.threat_delta)
        action_lines.append(f"Legs to change: {', '.join(rights_to_replace) if rights_to_replace else 'none'}")
        current_thetas = [legs[right].theta for right in rights_to_replace]
        proposed_thetas = [replacement_by_right[right].theta for right in rights_to_replace if replacement_by_right[right] is not None]
        current_theta_sum = sum(current_thetas) if all(theta is not None for theta in current_thetas) else None
        proposed_theta_sum = sum(proposed_thetas) if len(proposed_thetas) == len(rights_to_replace) and all(theta is not None for theta in proposed_thetas) else None
        action_lines.append(
            f"Current theta sum/day: {current_theta_sum:.4f}" if current_theta_sum is not None
            else "Current theta sum/day: unavailable"
        )
        action_lines.append(
            f"Proposed theta sum/day: {proposed_theta_sum:.4f}" if proposed_theta_sum is not None
            else "Proposed theta sum/day: unavailable"
        )
        proposed_prices = {}
        proposed_source_is_mid = True
        for right in ("P", "C"):
            replacement = replacement_by_right[right]
            if right in rights_to_replace:
                proposed_prices[right] = (
                    replacement.mid_price if replacement is not None and replacement.mid_price is not None
                    else (replacement.quote_price if replacement is not None else None)
                )
                proposed_source_is_mid = proposed_source_is_mid and replacement is not None and replacement.mid_price is not None
            else:
                proposed_prices[right] = current_prices[right]
                proposed_source_is_mid = proposed_source_is_mid and legs[right].mid_price is not None
        proposed_limits = implied_move_limits(spot, proposed_prices["P"], proposed_prices["C"])
        proposed_source = "bid/ask mids" if proposed_source_is_mid else "mid/last/close fallback"
        if proposed_limits is not None:
            action_lines.append(f"Proposed implied move limits ({proposed_source}): {proposed_limits[0]:.2f} to {proposed_limits[1]:.2f}")
        else:
            action_lines.append("Proposed implied move limits: unavailable")
    print_block("ACTION", action_lines)

    if action in {"ROLL", "REPOSITION"}:
        rights_to_replace = replacement_rights(legs, action, args.threat_delta)
        cost_lines = ["Estimated cash flow using bid/ask mids only:"]
        total_cash_flow = 0.0
        estimate_available = True
        for right in rights_to_replace:
            current = legs[right]
            replacement = replacement_by_right.get(right)
            multiplier = int(getattr(current.contract, "multiplier", 100) or 100)
            quantity = abs(current.quantity)
            if current.mid_price is None or replacement is None or replacement.mid_price is None:
                estimate_available = False
                continue
            close_debit = current.mid_price * quantity * multiplier
            open_credit = replacement.mid_price * quantity * multiplier
            leg_cash_flow = open_credit - close_debit
            total_cash_flow += leg_cash_flow
            label = "credit" if leg_cash_flow >= 0 else "debit"
            cost_lines.append(
                f"{right}: close {current.mid_price:.2f} / open {replacement.mid_price:.2f} "
                f"-> {abs(leg_cash_flow):,.2f} {label}"
            )
        if estimate_available:
            label = "credit" if total_cash_flow >= 0 else "debit"
            cost_lines.append(f"Net estimated {label}: {abs(total_cash_flow):,.2f} (contract currency)")
        else:
            cost_lines.append("Net estimate unavailable: IBKR did not provide bid/ask mids for every leg.")
    elif action == "HEDGE":
        call = legs["C"]
        shares = math.ceil(abs(call.delta) * abs(call.quantity) * int(getattr(call.contract, "multiplier", 100) or 100))
        if spot is not None:
            cost_lines = [f"Stock hedge notional: approximately {shares} shares x {spot:.2f} = {shares * spot:,.2f} (contract currency)"]
        else:
            cost_lines = [f"Stock hedge size: approximately {shares} shares; notional unavailable without spot"]
    else:
        cost_lines = ["No roll or reposition cost applies to this decision."]
    print_block("COST", cost_lines)


def next_later_expiry(ib: IB, symbol: str, expiry: str, exchange: str, currency: str) -> str | None:
    underlying = Stock(symbol, "SMART", currency)
    qualified = ib.qualifyContracts(underlying)
    if not qualified:
        return None
    definitions = ib.reqSecDefOptParams(symbol, "", "STK", qualified[0].conId)
    expiries = sorted({normalize_expiry(exp) for definition in definitions for exp in definition.expirations})
    return next((exp for exp in expiries if exp > expiry), None)


def main() -> int:
    args = parse_args()
    print_rules(args)
    ib = connect(args)
    try:
        groups = group_legs(fetch_option_positions(ib, args.symbol))
        if not groups:
            print("No short call/put positions were found in the connected IBKR portfolio.")
            return 0
        for (symbol, expiry), legs in sorted(groups.items()):
            if "P" in legs and "C" in legs:
                print_group(ib, symbol, expiry, legs, args)
            else:
                print(f"\n{symbol} {expiry}: skipped (both a short put and short call are required)")
        return 0
    finally:
        ib.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
