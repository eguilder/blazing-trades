#!/usr/bin/env python3
"""
Connect to IBKR, read current option positions, and summarize total delta/theta per underlying.
"""

import argparse
import asyncio
import copy
import math
import os
from collections import defaultdict

# Create a fresh asyncio event loop before importing ib_insync
# This is required on Python 3.11+ when no loop exists in the main thread.
asyncio.set_event_loop(asyncio.new_event_loop())

from ib_insync import IB, Stock


DEFAULT_HOST = os.getenv('IB_HOST', '127.0.0.1')
DEFAULT_PORT = int(os.getenv('IB_PORT', '7496'))
DEFAULT_CLIENT_ID = int(os.getenv('IB_OPTION_GREEKS_CLIENT_ID', '778'))
DEFAULT_CLIENT_ID_ATTEMPTS = int(os.getenv('IB_CLIENT_ID_ATTEMPTS', '10'))
DEFAULT_CONNECT_TIMEOUT = float(os.getenv('IB_CONNECT_TIMEOUT', '4'))
DEFAULT_OPTION_EXCHANGE = os.getenv('IB_OPTION_EXCHANGE', 'SMART')
DEFAULT_STOCK_EXCHANGE = os.getenv('IB_STOCK_EXCHANGE', 'SMART')


def parse_args():
    parser = argparse.ArgumentParser(
        description='Compute total delta/theta for IBKR option positions by ticker.'
    )
    parser.add_argument(
        '--host', default=DEFAULT_HOST,
        help='IBKR TWS/Gateway host (default: %(default)s)'
    )
    parser.add_argument(
        '--port', type=int, default=DEFAULT_PORT,
        help='IBKR TWS/Gateway port (default: %(default)s)'
    )
    parser.add_argument(
        '--client-id', type=int, default=DEFAULT_CLIENT_ID,
        help='IBKR API clientId (default: %(default)s)'
    )
    parser.add_argument(
        '--option-exchange', default=DEFAULT_OPTION_EXCHANGE,
        help='Exchange to use when an option position has no exchange (default: %(default)s)'
    )
    parser.add_argument(
        '--stock-exchange', default=DEFAULT_STOCK_EXCHANGE,
        help='Exchange to use for underlying stock prices (default: %(default)s)'
    )
    parser.add_argument(
        '--client-id-attempts', type=int, default=DEFAULT_CLIENT_ID_ATTEMPTS,
        help='Number of sequential clientIds to try (default: %(default)s)'
    )
    parser.add_argument(
        '--connect-timeout', type=float, default=DEFAULT_CONNECT_TIMEOUT,
        help='Seconds to wait for each IBKR API connection attempt (default: %(default)s)'
    )
    parser.add_argument(
        '--wait', type=float, default=6.0,
        help='Seconds to wait for model greeks per contract (default: %(default)s)'
    )
    return parser.parse_args()


def safe_int(value, default=1):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def valid_number(value):
    return (
        isinstance(value, (int, float))
        and not math.isnan(value)
        and not math.isinf(value)
    )


def connect_ib(host, port, client_id, client_id_attempts=10, connect_timeout=4):
    attempted = set()
    base_id = client_id
    attempts = max(1, client_id_attempts)
    last_exception = None

    for offset in range(attempts):
        attempt_id = base_id + offset
        if attempt_id in attempted:
            continue
        attempted.add(attempt_id)

        ib = IB()
        ib_errors = []

        def record_ib_error(req_id, error_code, error_string, contract=None):
            ib_errors.append((error_code, error_string))

        ib.errorEvent += record_ib_error
        try:
            ib.connect(host, port, clientId=attempt_id, timeout=connect_timeout)
            ib.reqMarketDataType(3)
            print(f'Connected to IBKR with client id {attempt_id}.')
            return ib
        except Exception as exc:
            last_exception = exc
            message = ' '.join(
                [str(exc)]
                + [f'{code}: {text}' for code, text in ib_errors]
            ).lower()
            client_id_in_use = (
                any(code == 326 for code, _ in ib_errors)
                or 'client id is already in use' in message
                or 'already in use' in message
            )

            if client_id_in_use:
                print(f'Client id {attempt_id} already in use, trying next id...')
                continue
            raise RuntimeError(
                f'Unable to connect to IBKR on {host}:{port} with client id {attempt_id}.'
            ) from exc
        finally:
            ib.errorEvent -= record_ib_error
            if not ib.isConnected():
                ib.disconnect()

    raise RuntimeError(
        f'Unable to connect to IBKR on {host}:{port}: all client ids '
        f'{base_id}..{base_id+attempts-1} failed.'
    ) from last_exception


def fetch_option_positions(ib):
    return [
        position
        for position in ib.positions()
        if getattr(position.contract, 'secType', '').upper() == 'OPT'
        and position.position != 0
    ]


def market_data_contract(contract, option_exchange):
    market_contract = copy.copy(contract)
    if not getattr(market_contract, 'exchange', ''):
        market_contract.exchange = option_exchange
    return market_contract


def request_model_greeks(ib, contract, timeout=6.0, option_exchange='SMART'):
    market_contract = market_data_contract(contract, option_exchange)
    ticker = ib.reqMktData(market_contract, '', False, False)
    try:
        elapsed = 0.0
        poll_interval = 0.25
        while elapsed < timeout:
            if ticker.modelGreeks is not None:
                return ticker.modelGreeks
            ib.sleep(poll_interval)
            elapsed += poll_interval
    finally:
        ib.cancelMktData(market_contract)
    return None


def request_share_price(ib, symbol, currency='USD', timeout=6.0, stock_exchange='SMART'):
    stock = Stock(symbol, stock_exchange, currency)
    qualified = ib.qualifyContracts(stock)
    market_contract = qualified[0] if qualified else stock
    ticker = ib.reqMktData(market_contract, '', False, False)
    try:
        elapsed = 0.0
        poll_interval = 0.25
        while elapsed < timeout:
            candidates = [
                ticker.marketPrice(),
                getattr(ticker, 'last', None),
                getattr(ticker, 'close', None),
                getattr(ticker, 'bid', None),
                getattr(ticker, 'ask', None),
            ]
            for price in candidates:
                if valid_number(price) and price > 0:
                    return price
            ib.sleep(poll_interval)
            elapsed += poll_interval
    finally:
        ib.cancelMktData(market_contract)
    return None


def contract_key(contract):
    return (
        contract.symbol,
        getattr(contract, 'lastTradeDateOrContractMonth', ''),
        getattr(contract, 'strike', ''),
        getattr(contract, 'right', ''),
        getattr(contract, 'exchange', ''),
        getattr(contract, 'multiplier', '')
    )


def summarize_positions(positions, ib, wait, option_exchange, stock_exchange):
    memo = {}
    share_prices = {}
    totals = defaultdict(lambda: {
        'total_delta': 0.0,
        'total_theta': 0.0,
        'delta_dollars': None,
        'share_price': None,
        'currency': '',
        'positions': 0,
        'contracts': []
    })

    for position in positions:
        contract = position.contract
        underlying = contract.symbol
        quantity = position.position
        multiplier = safe_int(getattr(contract, 'multiplier', None), default=100)
        currency = getattr(contract, 'currency', '') or 'USD'
        key = contract_key(contract)
        totals[underlying]['currency'] = currency

        if key not in memo:
            greeks = request_model_greeks(
                ib,
                contract,
                timeout=wait,
                option_exchange=option_exchange
            )
            memo[key] = greeks

        if underlying not in share_prices:
            share_prices[underlying] = request_share_price(
                ib,
                underlying,
                currency=currency,
                timeout=wait,
                stock_exchange=stock_exchange
            )
        totals[underlying]['share_price'] = share_prices[underlying]

        greeks = memo[key]
        if greeks is None:
            totals[underlying]['contracts'].append(
                {
                    'contract': contract.localSymbol or repr(contract),
                    'quantity': quantity,
                    'multiplier': multiplier,
                    'delta': None,
                    'theta': None,
                }
            )
            continue

        delta = getattr(greeks, 'delta', None)
        theta = getattr(greeks, 'theta', None)
        position_delta = delta * quantity * multiplier if delta is not None else None
        position_theta = theta * quantity * multiplier if theta is not None else None

        totals[underlying]['total_delta'] += position_delta or 0.0
        totals[underlying]['total_theta'] += position_theta or 0.0
        totals[underlying]['positions'] += 1
        totals[underlying]['contracts'].append(
            {
                'contract': contract.localSymbol or repr(contract),
                'quantity': quantity,
                'multiplier': multiplier,
                'delta': delta,
                'theta': theta,
                'position_delta': position_delta,
                'position_theta': position_theta,
            }
        )

    for data in totals.values():
        share_price = data['share_price']
        if share_price is not None:
            data['delta_dollars'] = data['total_delta'] * share_price

    return totals


def print_summary(totals):
    if not totals:
        print('No option positions were found in the connected IBKR account.')
        return

    print('Ticker | Total Delta |        Delta $ | Total Theta | Option Contracts')
    print('------ | ----------- | -------------- | ----------- | ----------------')
    for ticker, data in sorted(totals.items()):
        delta = data['total_delta']
        delta_dollars = data['delta_dollars']
        delta_dollars_text = f'{delta_dollars:,.2f}' if delta_dollars is not None else 'n/a'
        theta = data['total_theta']
        count = data['positions']
        print(
            f'{ticker:6} | {delta:11.2f} | {delta_dollars_text:>14} | '
            f'{theta:11.2f} | {count:16d}'
        )

    print('\nDetailed position breakdown:')
    for ticker, data in sorted(totals.items()):
        print(f'\n{ticker} - {len(data["contracts"])} option position(s)')
        for item in data['contracts']:
            print(
                f"  {item['contract']:20} qty={item['quantity']:>5} "
                f"mult={item['multiplier']:>3} "
                f"delta={item['delta']} "
                f"theta={item['theta']} "
                f"posDelta={item.get('position_delta')} "
                f"posTheta={item.get('position_theta')}"
            )


def main():
    args = parse_args()
    ib = connect_ib(
        args.host,
        args.port,
        args.client_id,
        args.client_id_attempts,
        args.connect_timeout
    )
    try:
        option_positions = fetch_option_positions(ib)
        totals = summarize_positions(
            option_positions,
            ib,
            args.wait,
            args.option_exchange,
            args.stock_exchange
        )
        print_summary(totals)
    finally:
        ib.disconnect()


if __name__ == '__main__':
    main()
