#!/usr/bin/env python3
"""Approximate one-year daily-bar backtest for the short-strangle rules.

This is intentionally separate from the live IBKR scanner.  It consumes the
CSV written by ``ibkr_historical.py`` and estimates option prices/Greeks with
Black-Scholes because historical option-chain quotes are not available.

The result is directional and comparative, not an execution-quality P&L:
daily OHLC bars cannot show the exact intraday alert, fill, spread, or IV.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import NormalDist

import short_strangle_rules as shared_rules
from short_strangle_rules import (
    ALERT_DELTA,
    CLOSE_REVIEW_DELTA,
    CONTRACT_MULTIPLIER,
    ENTRY_DELTA,
    ENTRY_DTE,
    HEDGE_MAX_CALL_DELTA,
    REPLACEMENT_DELTA,
    THREAT_DELTA,
    VOL_SPIKE_RATIO,
    VOL_WINDOW,
    VOL_BASELINE_WINDOW,
    SHARES_PER_CONTRACT,
    RULESET_PATH,
    configure_ruleset,
    load_ruleset,
    classify_position,
)


NORM = NormalDist()
RULE_CONSTANT_NAMES = (
    "ALERT_DELTA", "CLOSE_REVIEW_DELTA", "CONTRACT_MULTIPLIER", "ENTRY_DELTA",
    "ENTRY_DTE", "HEDGE_MAX_CALL_DELTA", "REPLACEMENT_DELTA", "THREAT_DELTA",
    "VOL_SPIKE_RATIO", "VOL_WINDOW", "VOL_BASELINE_WINDOW", "SHARES_PER_CONTRACT",
)


def activate_ruleset(path: Path) -> dict:
    selected = configure_ruleset(path)
    for name in RULE_CONSTANT_NAMES:
        globals()[name] = getattr(shared_rules, name)
    return selected


@dataclass(frozen=True)
class Bar:
    day: date
    open: float
    high: float
    low: float
    close: float


@dataclass
class Leg:
    right: str
    strike: float
    expiry: date
    quantity: int = -1


@dataclass
class Trade:
    day: date
    action: str
    leg: str
    expiry: date | None
    strike: float | None
    delta: float | None
    price: float | None
    spot: float
    cash_flow: float
    note: str
    total_delta: float | None = None


def parse_args() -> argparse.Namespace:
    selection = argparse.ArgumentParser(add_help=False)
    selection.add_argument("--ruleset", type=Path, default=RULESET_PATH)
    selection_args, _ = selection.parse_known_args()
    parameters = load_ruleset(selection_args.ruleset)["parameters"]
    parser = argparse.ArgumentParser(
        description="Approximate daily-bar backtest for the short-strangle rules."
    )
    parser.add_argument("csv", type=Path, help="OHLC CSV from ibkr_historical.py")
    parser.add_argument("--ruleset", type=Path, default=selection_args.ruleset,
                        help="Ruleset JSON to use (default: selected by SHORT_STRANGLE_RULESET or repository ruleset)")
    parser.add_argument("--start", help="Backtest start date YYYY-MM-DD; default is last year in the CSV")
    parser.add_argument("--end", help="Backtest end date YYYY-MM-DD; default is latest date in the CSV")
    parser.add_argument("--entry-dte", type=int, default=parameters["entry_dte"], help=f"Calendar DTE for each new strangle (default: {parameters['entry_dte']})")
    parser.add_argument("--entry-delta", type=float, default=parameters["entry_delta"], help=f"Absolute delta target for new legs (default: {parameters['entry_delta']})")
    parser.add_argument("--alert-delta", type=float, default=parameters["alert_delta"], help=f"General action alert delta (default: {parameters['alert_delta']})")
    parser.add_argument("--threat-delta", type=float, default=parameters["threat_delta"], help=f"Long-DTE threatened-leg delta (default: {parameters['threat_delta']})")
    parser.add_argument("--close-review-delta", type=float, default=parameters["close_review_delta"], help=f"Temporary-close review delta (default: {parameters['close_review_delta']})")
    parser.add_argument("--replacement-delta", type=float, default=parameters["replacement_delta"], help=f"Target delta for replacement legs (default: {parameters['replacement_delta']})")
    parser.add_argument("--risk-free-rate", type=float, default=0.05)
    parser.add_argument("--vol-window", type=int, default=parameters["vol_window"], help=f"Rolling realized-volatility window (default: {parameters['vol_window']} bars)")
    parser.add_argument("--vol-baseline-window", type=int, default=parameters["vol_baseline_window"], help=f"Baseline volatility window (default: {parameters['vol_baseline_window']} bars)")
    parser.add_argument("--vol-spike-ratio", type=float, default=parameters["vol_spike_ratio"])
    parser.add_argument("--hedge-max-call-delta", type=float, default=parameters["hedge_max_call_delta"])
    parser.add_argument("--strike-step", type=float, default=5.0, help="Synthetic option strike increment (default: 5)")
    parser.add_argument("--multiplier", type=int, default=parameters["contract_multiplier"])
    parser.add_argument("--shares-per-contract", type=int, default=parameters["shares_per_contract"])
    args = parser.parse_args()
    activate_ruleset(args.ruleset)
    return args


def read_bars(path: Path) -> list[Bar]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = csv.DictReader(handle)
        bars = []
        for row in rows:
            timestamp = str(row["timestamp"])[:10]
            bars.append(Bar(
                day=datetime.strptime(timestamp, "%Y-%m-%d").date(),
                open=float(row["open"]), high=float(row["high"]),
                low=float(row["low"]), close=float(row["close"]),
            ))
    return sorted({bar.day: bar for bar in bars}.values(), key=lambda bar: bar.day)


def select_period(bars: list[Bar], args: argparse.Namespace) -> list[Bar]:
    if not bars:
        raise ValueError("CSV contains no daily bars")
    end = datetime.strptime(args.end, "%Y-%m-%d").date() if args.end else bars[-1].day
    start = datetime.strptime(args.start, "%Y-%m-%d").date() if args.start else end - timedelta(days=365)
    selected = [bar for bar in bars if start <= bar.day <= end]
    if len(selected) < max(args.vol_baseline_window, args.vol_window) + 2:
        raise ValueError("The selected period does not contain enough bars for the volatility windows")
    return selected


def log_returns(bars: list[Bar]) -> list[float]:
    return [math.log(current.close / previous.close) for previous, current in zip(bars, bars[1:])]


def realized_vol(bars: list[Bar], window: int) -> float | None:
    if len(bars) < window + 1:
        return None
    returns = log_returns(bars[-(window + 1):])
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / max(1, len(returns) - 1)
    return math.sqrt(variance * 252.0)


def norm_cdf(value: float) -> float:
    return NORM.cdf(value)


def bs_values(spot: float, strike: float, years: float, volatility: float,
              rate: float, right: str) -> tuple[float, float, float]:
    """Return option price, delta, and theta per share per day."""
    years = max(years, 1.0 / 365.0)
    volatility = max(volatility, 1e-6)
    root = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * volatility ** 2) * years) / (volatility * root)
    d2 = d1 - volatility * root
    discount = math.exp(-rate * years)
    pdf = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
    common_theta = -(spot * pdf * volatility) / (2.0 * root)
    if right == "C":
        price = spot * norm_cdf(d1) - strike * discount * norm_cdf(d2)
        delta = norm_cdf(d1)
        theta = common_theta - rate * strike * discount * norm_cdf(d2)
    else:
        price = strike * discount * norm_cdf(-d2) - spot * norm_cdf(-d1)
        delta = norm_cdf(d1) - 1.0
        theta = common_theta + rate * strike * discount * norm_cdf(-d2)
    return price, delta, theta / 365.0


def round_strike(value: float, step: float, direction: str) -> float:
    units = value / step
    if direction == "down":
        return math.floor(units) * step
    return math.ceil(units) * step


def choose_strike(spot: float, expiry: date, day: date, volatility: float,
                  target_delta: float, right: str, args: argparse.Namespace,
                  enforce_cap: bool = True) -> tuple[float, float, float]:
    """Find a strike near target, optionally enforcing an absolute-delta cap."""
    years = max((expiry - day).days, 1) / 365.0
    if right == "P":
        center = round_strike(spot, args.strike_step, "down")
        strikes = [center - args.strike_step * offset for offset in range(0, 101)]
    else:
        center = round_strike(spot, args.strike_step, "up")
        strikes = [center + args.strike_step * offset for offset in range(0, 101)]
    candidates = []
    for strike in strikes:
        if strike <= 0:
            continue
        price, delta, theta = bs_values(spot, strike, years, volatility, args.risk_free_rate, right)
        if not enforce_cap or abs(delta) <= target_delta:
            candidates.append((abs(target_delta - abs(delta)), strike, delta, theta))
    if not candidates:
        raise ValueError(f"Could not find a {right} strike at or below delta {target_delta}")
    _, strike, delta, theta = min(candidates)
    return strike, delta, theta


def option_value(leg: Leg, spot: float, day: date, volatility: float, args: argparse.Namespace) -> tuple[float, float, float]:
    years = max((leg.expiry - day).days, 1) / 365.0
    return bs_values(spot, leg.strike, years, volatility, args.risk_free_rate, leg.right)


def trade_leg(trades: list[Trade], day: date, action: str, leg: Leg,
              spot: float, volatility: float, args: argparse.Namespace,
              opening: bool, note: str, total_delta: float | None = None) -> float:
    price, delta, _ = option_value(leg, spot, day, volatility, args)
    contracts = abs(leg.quantity)
    # Short opening = credit; buying back a short = debit.
    cash_flow = price * contracts * args.multiplier * (1 if opening else -1)
    trades.append(Trade(day, action, leg.right, leg.expiry, leg.strike, delta, price, spot, cash_flow, note, total_delta))
    return cash_flow


def total_short_delta(legs: dict[str, Leg], spot: float, day: date, volatility: float, args: argparse.Namespace) -> dict[str, tuple[float, float, float]]:
    return {right: option_value(leg, spot, day, volatility, args) for right, leg in legs.items()}


def combo_delta(legs: dict[str, Leg], spot: float, day: date,
                volatility: float, args: argparse.Namespace) -> float:
    """Return the signed delta of the currently open short-option combo."""
    return sum(option_value(leg, spot, day, volatility, args)[1]
               for leg in legs.values())


def close_all(trades: list[Trade], legs: dict[str, Leg], day: date, spot: float,
             volatility: float, args: argparse.Namespace, note: str,
             action: str = "EXIT") -> float:
    cash = 0.0
    remaining = dict(legs)
    for right in list(remaining):
        leg = remaining.pop(right)
        cash += trade_leg(
            trades, day, action, leg, spot, volatility, args, False, note,
            combo_delta(remaining, spot, day, volatility, args),
        )
    return cash


def format_money(value: float) -> str:
    return f"{value:,.2f}"


def active_day_summary(trades: list[Trade], limit: int = 10) -> list[tuple[date, int, dict[str, int]]]:
    """Return the busiest days by non-exit ledger action rows."""
    by_day: dict[date, Counter[str]] = defaultdict(Counter)
    for trade in trades:
        if trade.action in {"EXIT", "HEDGE_EXIT"}:
            continue
        by_day[trade.day][trade.action] += 1
    ranked = sorted(
        ((day, sum(counts.values()), dict(counts)) for day, counts in by_day.items()),
        key=lambda item: (-item[1], item[0]),
    )
    return ranked[:limit]


def run_backtest(bars: list[Bar], args: argparse.Namespace) -> tuple[list[Trade], float, list[str]]:
    trades: list[Trade] = []
    messages: list[str] = []
    cash = 0.0
    hedge_shares = 0
    hedge_entry_price = None
    legs: dict[str, Leg] = {}
    expiry = None
    history: list[Bar] = []

    # Reserve the terminal bar for closing the remaining position.  This
    # prevents a final-day roll/reposition from creating an artificial open
    # trade with no subsequent holding period.
    for bar in bars[:-1]:
        history.append(bar)
        vol = realized_vol(history, args.vol_window)
        baseline = realized_vol(history, args.vol_baseline_window)
        if vol is None:
            continue
        baseline = baseline or vol
        vol_spike = vol >= baseline * args.vol_spike_ratio

        if not legs:
            expiry = bar.day + timedelta(days=args.entry_dte)
            try:
                put_strike, _, _ = choose_strike(bar.close, expiry, bar.day, vol, args.entry_delta, "P", args, enforce_cap=False)
                call_strike, _, _ = choose_strike(bar.close, expiry, bar.day, vol, args.entry_delta, "C", args, enforce_cap=False)
            except ValueError as exc:
                messages.append(f"{bar.day} SKIP entry: {exc}; trying the next available bar")
                continue
            legs = {
                "P": Leg("P", put_strike, expiry),
                "C": Leg("C", call_strike, expiry),
            }
            entry_values = total_short_delta(legs, bar.close, bar.day, vol, args)
            current_combo_delta = 0.0
            for leg in legs.values():
                current_combo_delta += entry_values[leg.right][1]
                cash += trade_leg(trades, bar.day, "ENTRY", leg, bar.close, vol, args, True, f"new {args.entry_dte} DTE strangle", current_combo_delta)
            messages.append(f"{bar.day} ENTRY spot {bar.close:.2f}, vol {vol:.3f}, combo delta {current_combo_delta:.3f}, strikes P{put_strike:g}/C{call_strike:g}")
            continue

        values = total_short_delta(legs, bar.close, bar.day, vol, args)
        abs_put = abs(values["P"][1])
        abs_call = abs(values["C"][1])
        max_delta = max(abs_put, abs_call)
        current_combo_delta = values["P"][1] + values["C"][1]
        dte = (expiry - bar.day).days

        if dte <= 0:
            action = "ROLL"
            reason = "synthetic expiration reached"
            replacement_rights = ("P", "C")
        else:
            rule_result = classify_position(
                dte=dte,
                put_delta=values["P"][1],
                call_delta=values["C"][1],
                spot=bar.close,
                put_strike=legs["P"].strike,
                call_strike=legs["C"].strike,
                put_iv=vol,
                call_iv=vol,
                historical_vol=baseline,
                vol_spike_ratio=args.vol_spike_ratio,
                alert_delta=args.alert_delta,
                threat_delta=args.threat_delta,
                close_review_delta=args.close_review_delta,
                hedge_max_call_delta=args.hedge_max_call_delta,
            )
            action = rule_result.action
            reason = "; ".join(rule_result.reasons)
            replacement_rights = rule_result.replacement_rights

        if action == "TEMPORARY_CLOSE_REVIEW":
            note = f"temporary close after review trigger: {reason}"
            cash += close_all(
                trades, legs, bar.day, bar.close, vol, args, note, action="CLOSE",
            )
            legs.clear()
            expiry = None
            messages.append(
                f"{bar.day} CLOSE both legs at spot {bar.close:.2f}, "
                f"combo delta {current_combo_delta:.3f}; realized PnL recorded: {reason}"
            )
            continue
        if action == "HEDGE" and hedge_shares == 0:
            hedge_shares = math.ceil(abs(values["C"][1]) * args.shares_per_contract)
            hedge_entry_price = bar.close
            hedge_cash = -bar.close * hedge_shares
            cash += hedge_cash
            trades.append(Trade(bar.day, "HEDGE", "STOCK", None, None, None, bar.close, bar.close, hedge_cash, reason, current_combo_delta))
            messages.append(f"{bar.day} HEDGE buy {hedge_shares} shares at {bar.close:.2f}, combo delta {current_combo_delta:.3f}: {reason}")
            continue
        if action not in {"ROLL", "REPOSITION"}:
            continue

        if action == "ROLL":
            new_expiry = bar.day + timedelta(days=args.entry_dte)
            try:
                new_strikes = {
                    right: choose_strike(bar.close, new_expiry, bar.day, vol, args.replacement_delta, right, args)[0]
                    for right in ("P", "C")
                }
            except ValueError as exc:
                messages.append(f"{bar.day} SKIP ROLL: {exc}; keeping the current position")
                continue
            for right in ("P", "C"):
                old_leg = legs.pop(right)
                cash += trade_leg(
                    trades, bar.day, action, old_leg, bar.close, vol, args,
                    False, f"close old {right}; {reason}",
                    combo_delta(legs, bar.close, bar.day, vol, args),
                )
            expiry = new_expiry
            for right in ("P", "C"):
                new_leg = Leg(right, new_strikes[right], expiry)
                legs[right] = new_leg
                cash += trade_leg(
                    trades, bar.day, action, new_leg, bar.close, vol, args,
                    True, "open new expiry",
                    combo_delta(legs, bar.close, bar.day, vol, args),
                )
        else:
            rights = list(replacement_rights)
            for right in rights:
                try:
                    new_strike, _, _ = choose_strike(bar.close, expiry, bar.day, vol, args.replacement_delta, right, args)
                except ValueError as exc:
                    messages.append(f"{bar.day} SKIP {action} {right}: {exc}; keeping the leg unchanged")
                    continue
                old_leg = legs.pop(right)
                cash += trade_leg(
                    trades, bar.day, action, old_leg, bar.close, vol, args,
                    False, f"close old {right}; {reason}",
                    combo_delta(legs, bar.close, bar.day, vol, args),
                )
                new_leg = Leg(right, new_strike, expiry)
                legs[right] = new_leg
                cash += trade_leg(
                    trades, bar.day, action, new_leg, bar.close, vol, args,
                    True, f"open replacement {right}",
                    combo_delta(legs, bar.close, bar.day, vol, args),
                )
        messages.append(f"{bar.day} {action} spot {bar.close:.2f}: {reason}")

    if legs:
        final = bars[-1]
        vol = realized_vol(bars, args.vol_window) or 0.30
        cash += close_all(trades, legs, final.day, final.close, vol, args, "end of backtest")
    if hedge_shares and hedge_entry_price is not None:
        final = bars[-1]
        hedge_exit_cash = final.close * hedge_shares
        cash += hedge_exit_cash
        trades.append(Trade(final.day, "HEDGE_EXIT", "STOCK", None, None, None, final.close, final.close, hedge_exit_cash, "sell hedge shares at end", None))
    return trades, cash, messages


def print_report(trades: list[Trade], pnl: float, messages: list[str], bars: list[Bar], args: argparse.Namespace) -> None:
    print(f"Backtest period: {bars[0].day} to {bars[-1].day} ({len(bars)} daily bars)")
    print(f"Ruleset: {args.ruleset}")
    print("Approximation: daily closes + Black-Scholes prices using rolling realized volatility; no historical option quotes.")
    print(f"Entry DTE: {args.entry_dte}; entry delta: {args.entry_delta:.2f}; replacement delta: {args.replacement_delta:.2f}; alert delta: {args.alert_delta:.2f}; long-DTE reposition delta: {args.threat_delta:.2f}")
    print(f"Temporary close: delta >= {args.close_review_delta:.2f} and either a strike breach or rolling realized volatility >= baseline x {args.vol_spike_ratio:.2f}; close both legs at that bar's close, realize PnL, then allow entry on the next eligible bar.")
    print("\nTRADES")
    columns = (
        ("Date", 10), ("Action", 12), ("Leg", 3), ("Expiry", 10),
        ("Strike", 8), ("Delta", 6), ("TDelta", 9), ("Price", 8),
        ("Spot", 8), ("CashFlow", 9), ("PnL", 10),
    )
    header = " | ".join(label.ljust(width) for label, width in columns)
    separator = "-+-".join("-" * width for _, width in columns)
    print(header + " | Note")
    print(separator + "-+-----")
    running_pnl = 0.0
    for trade in trades:
        expiry = trade.expiry.isoformat() if trade.expiry else "-"
        strike = f"{trade.strike:.2f}" if trade.strike is not None else "-"
        delta = f"{trade.delta:.3f}" if trade.delta is not None else "-"
        price = f"{trade.price:.3f}" if trade.price is not None else "-"
        total_delta = f"{trade.total_delta:.3f}" if trade.total_delta is not None else "-"
        running_pnl += trade.cash_flow
        opening = trade.action in {"ENTRY", "HEDGE"} or trade.note.startswith("open")
        values = (
            str(trade.day), trade.action, trade.leg, expiry, strike, delta,
            total_delta, price, f"{trade.spot:.2f}", f"{trade.cash_flow:.2f}",
            f"{running_pnl:.2f}" if not opening else "",
        )
        rendered = " | ".join(
            value.ljust(width) if index < 4 else value.rjust(width)
            for index, (value, (_, width)) in enumerate(zip(values, columns))
        )
        print(rendered + " | " + trade.note)
    print("\nSUMMARY")
    print(f"Estimated P&L: {format_money(pnl)}")
    print(f"Trade cash-flow rows: {len(trades)}")
    busiest = active_day_summary(trades)
    print("\nMOST ACTIVE DAYS (non-exit ledger action rows)")
    if not busiest:
        print("  None")
    else:
        for day, count, breakdown in busiest:
            details = ", ".join(f"{action}={number}" for action, number in sorted(breakdown.items()))
            print(f"  {day}: {count} action rows ({details})")


def main() -> int:
    args = parse_args()
    bars = select_period(read_bars(args.csv), args)
    trades, pnl, messages = run_backtest(bars, args)
    print_report(trades, pnl, messages, bars, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
