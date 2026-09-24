import asyncio
import math
import os
import time
from collections import defaultdict

# IMPORTANT: create event loop before importing ib_insync
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

from flask import Flask, request, jsonify
from ib_insync import *

# -----------------------------------------------------------------------------
# CONFIG
# -----------------------------------------------------------------------------

IB_HOST = os.getenv("IB_HOST", "127.0.0.1")
IB_PORT = int(os.getenv("IB_PORT", "7496"))
IB_CLIENT_ID = int(os.getenv("IB_CLIENT_ID", "777"))

CACHE_SECONDS = 300

UNDERLYINGS = {

    "ADY": {
        "symbol": "ADYEN",
        "tradingClass": "ADY",
        "exchange": "FTA",
        "multiplier": 10
    },

    "ASL": {
        "symbol": "ASML",
        "tradingClass": "ASL",
        "exchange": "FTA",
        "multiplier": 100
    },

    "BES": {
        "symbol": "BESI",
        "tradingClass": "BESI",
        "exchange": "FTA",
        "multiplier": 100
    },

    "ING": {
        "symbol": "ING",
        "tradingClass": "ING",
        "exchange": "FTA",
        "multiplier": 100
    }
}

# -----------------------------------------------------------------------------
# APP
# -----------------------------------------------------------------------------

app = Flask(__name__)

ib = IB()

cache = {}

# -----------------------------------------------------------------------------
# IBKR
# -----------------------------------------------------------------------------

def connect_ib():

    if ib.isConnected():
        return

    print("Connecting to IBKR...")

    ib.connect(
        IB_HOST,
        IB_PORT,
        clientId=IB_CLIENT_ID
    )

    # delayed data
    ib.reqMarketDataType(3)

    print("Connected")


# -----------------------------------------------------------------------------
# HELPERS
# -----------------------------------------------------------------------------

def cache_key(
    underlying,
    expiry,
    strike,
    right
):
    return (
        f"{underlying}_"
        f"{expiry}_"
        f"{strike}_"
        f"{right}"
    )


def build_contract(
    symbol,
    trading_class,
    exchange,
    expiry,
    strike,
    right
):

    return Option(
        symbol=symbol,
        lastTradeDateOrContractMonth=expiry,
        strike=float(strike),
        right=right,
        exchange=exchange,
        tradingClass=trading_class
    )


def build_result(
    row_id,
    key,
    underlying,
    multiplier,
    delta,
    theta,
    gamma,
    vega,
    underlying_price,
    in_the_money,
    qty,
    premium_price
):

    return {
        "rowId": row_id,
        "key": key,
        "underlying": underlying,
        "multiplier": multiplier,
        "delta": delta,
        "theta": theta,
        "gamma": gamma,
        "vega": vega,
        "underlyingPrice": underlying_price,
        "inTheMoney": in_the_money,
        "positionDelta":
            delta * qty * multiplier
            if delta is not None else None,
        "positionTheta":
            theta * qty * multiplier
            if theta is not None else None,
        "premiumPrice": premium_price,
        "positionPremium":
            premium_price * qty * multiplier
            if premium_price is not None else None
    }


def current_premium_price(ticker, underlying_price, strike, right):

    try:
        market_price = ticker.marketPrice()
    except Exception:
        market_price = None

    if not (
        isinstance(market_price, (int, float))
        and math.isfinite(market_price)
    ):
        bid = getattr(ticker, "bid", None)
        ask = getattr(ticker, "ask", None)
        if (
            isinstance(bid, (int, float))
            and math.isfinite(bid)
            and isinstance(ask, (int, float))
            and math.isfinite(ask)
        ):
            market_price = (bid + ask) / 2
        else:
            for value in (
                getattr(ticker, "last", None),
                getattr(ticker, "close", None)
            ):
                if isinstance(value, (int, float)) and math.isfinite(value):
                    market_price = value
                    break

    if not (
        isinstance(market_price, (int, float))
        and math.isfinite(market_price)
    ):
        return None

    if (
        isinstance(underlying_price, (int, float))
        and math.isfinite(underlying_price)
    ):
        intrinsic_value = max(
            underlying_price - strike
            if right == "C"
            else strike - underlying_price,
            0
        )
        return max(market_price - intrinsic_value, 0)

    return market_price


def add_theta_summary(results):

    theta_by_ticker = defaultdict(float)
    portfolio_theta = 0.0

    for result in results:

        underlying = result.get("underlying")
        position_theta = result.get("positionTheta")

        if underlying is None or position_theta is None:
            continue

        theta_by_ticker[underlying] += position_theta
        portfolio_theta += position_theta

    theta_by_ticker = dict(sorted(theta_by_ticker.items()))

    for result in results:

        result["portfolioTheta"] = portfolio_theta
        result["thetaByTicker"] = theta_by_ticker

    return results


# -----------------------------------------------------------------------------
# ROUTES
# -----------------------------------------------------------------------------

@app.route("/health")
def health():

    return jsonify({
        "connected": ib.isConnected()
    })


@app.route("/greeks", methods=["POST"])
def greeks():

    connect_ib()

    positions = request.get_json(force=True)

    results = []
    pending_by_key = {}

    for pos in positions:

        row_id = pos.get("rowId")

        underlying = pos["underlying"]

        if underlying not in UNDERLYINGS:

            results.append({
                "rowId": row_id,
                "error": f"Unknown underlying {underlying}"
            })

            continue

        info = UNDERLYINGS[underlying]

        symbol = info["symbol"]
        trading_class = info["tradingClass"]
        exchange = info["exchange"]
        multiplier = info["multiplier"]

        expiry = pos["expiry"]
        strike = float(pos["strike"])
        right = pos["right"]
        qty = int(pos.get("qty", 1))

        key = cache_key(
            underlying,
            expiry,
            strike,
            right
        )

        if key in cache:

            age = time.time() - cache[key]["timestamp"]

            if age < CACHE_SECONDS:

                c = cache[key]

                results.append(
                    build_result(
                        row_id,
                        key,
                        underlying,
                        c["multiplier"],
                        c["delta"],
                        c["theta"],
                        c["gamma"],
                        c["vega"],
                        c.get("underlyingPrice"),
                        c.get("inTheMoney"),
                        qty,
                        c.get("premiumPrice")
                    )
                )

                continue

        pending_by_key.setdefault(key, {
            "key": key,
            "underlying": underlying,
            "symbol": symbol,
            "tradingClass": trading_class,
            "exchange": exchange,
            "multiplier": multiplier,
            "expiry": expiry,
            "strike": strike,
            "right": right,
            "contract": build_contract(
                symbol,
                trading_class,
                exchange,
                expiry,
                strike,
                right
            )
        })

    if pending_by_key:
        print(f"Batch qualifying {len(pending_by_key)} uncached option contracts...")
        pending_items = list(pending_by_key.values())
        qualified = ib.qualifyContracts(
            *(item["contract"] for item in pending_items)
        )

        valid_items = []
        for index, item in enumerate(pending_items):
            contract = qualified[index] if index < len(qualified) else None
            if not getattr(contract, "conId", 0):
                item["error"] = "Contract not found"
                continue
            item["contract"] = contract
            valid_items.append(item)

        print(f"Requesting Greeks for {len(valid_items)} contracts concurrently...")
        tickers = {
            item["key"]: ib.reqMktData(item["contract"], "", False, False)
            for item in valid_items
        }

        if tickers:
            # All subscriptions are active before waiting, so this is one
            # shared wait instead of three seconds per position.
            ib.sleep(3)

        for item in valid_items:
            ticker = tickers[item["key"]]
            g = ticker.modelGreeks
            if g:
                delta = g.delta
                theta = g.theta
                gamma = g.gamma
                vega = g.vega
                underlying_price = getattr(g, "undPrice", None)
            else:
                delta = theta = gamma = vega = underlying_price = None

            premium_price = current_premium_price(
                ticker,
                underlying_price,
                item["strike"],
                item["right"]
            )

            in_the_money = None
            if underlying_price is not None:
                in_the_money = (
                    underlying_price > item["strike"]
                    if item["right"] == "C"
                    else underlying_price < item["strike"]
                )

            cache[item["key"]] = {
                "timestamp": time.time(),
                "multiplier": item["multiplier"],
                "delta": delta,
                "theta": theta,
                "gamma": gamma,
                "vega": vega,
                "underlyingPrice": underlying_price,
                "inTheMoney": in_the_money,
                "premiumPrice": premium_price
            }
            ib.cancelMktData(item["contract"])

    # Build responses in the same order as the submitted portfolio positions.
    for pos in positions:
        row_id = pos.get("rowId")
        underlying = pos.get("underlying")
        if underlying not in UNDERLYINGS:
            continue
        info = UNDERLYINGS[underlying]
        expiry = pos["expiry"]
        strike = float(pos["strike"])
        right = pos["right"]
        qty = int(pos.get("qty", 1))
        key = cache_key(underlying, expiry, strike, right)

        if key in cache:
            c = cache[key]
            results.append(build_result(
                row_id, key, underlying, c["multiplier"], c["delta"],
                c["theta"], c["gamma"], c["vega"],
                c.get("underlyingPrice"), c.get("inTheMoney"), qty,
                c.get("premiumPrice")
            ))
        elif key in pending_by_key and pending_by_key[key].get("error"):
            results.append({"rowId": row_id, "key": key, "error": pending_by_key[key]["error"]})

    return jsonify(add_theta_summary(results))


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------

if __name__ == "__main__":

    connect_ib()

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
        threaded=False
    )
