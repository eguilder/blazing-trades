import asyncio
import os
import time

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

        # ---------------------------------------------------------------------
        # CACHE
        # ---------------------------------------------------------------------

        if key in cache:

            age = time.time() - cache[key]["timestamp"]

            if age < CACHE_SECONDS:

                c = cache[key]

                results.append({
                    "rowId": row_id,
                    "key": key,
                    "multiplier": c["multiplier"],
                    "delta": c["delta"],
                    "theta": c["theta"],
                    "gamma": c["gamma"],
                    "vega": c["vega"],
                    "positionDelta":
                        c["delta"] * qty * c["multiplier"]
                        if c["delta"] is not None else None,
                    "positionTheta":
                        c["theta"] * qty * c["multiplier"]
                        if c["theta"] is not None else None
                })

                continue

        # ---------------------------------------------------------------------
        # CONTRACT
        # ---------------------------------------------------------------------

        print(
            f"{underlying} -> "
            f"{symbol} "
            f"{right}{strike} "
            f"{expiry}"
        )

        contract = build_contract(
            symbol,
            trading_class,
            exchange,
            expiry,
            strike,
            right
        )

        qualified = ib.qualifyContracts(contract)

        if not qualified:

            results.append({
                "rowId": row_id,
                "key": key,
                "error": "Contract not found"
            })

            continue

        contract = qualified[0]

        # ---------------------------------------------------------------------
        # MARKET DATA
        # ---------------------------------------------------------------------

        ticker = ib.reqMktData(
            contract,
            "",
            False,
            False
        )

        ib.sleep(3)

        g = ticker.modelGreeks

        if g:

            delta = g.delta
            theta = g.theta
            gamma = g.gamma
            vega = g.vega

        else:

            delta = None
            theta = None
            gamma = None
            vega = None

        ib.cancelMktData(contract)

        # ---------------------------------------------------------------------
        # CACHE
        # ---------------------------------------------------------------------

        cache[key] = {
            "timestamp": time.time(),
            "multiplier": multiplier,
            "delta": delta,
            "theta": theta,
            "gamma": gamma,
            "vega": vega
        }

        # ---------------------------------------------------------------------
        # RESPONSE
        # ---------------------------------------------------------------------

        results.append({
            "rowId": row_id,
            "key": key,
            "multiplier": multiplier,
            "delta": delta,
            "theta": theta,
            "gamma": gamma,
            "vega": vega,
            "positionDelta":
                delta * qty * multiplier
                if delta is not None else None,
            "positionTheta":
                theta * qty * multiplier
                if theta is not None else None
        })

    return jsonify(results)


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
