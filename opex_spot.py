# ============================================================
# OPEX RANGE + IMPLIED MOVE STUDY
# ============================================================

import pandas as pd
import yfinance as yf
import calendar
from datetime import datetime, timedelta

# ============================================================
# CONFIGURATION
# ============================================================

TICKERS = [
    "TSLA",
    "NVDA",
    "QCOM",
    "MU",
    "INTC",
    "AAPL",
    "META",
    "AMZN",
    "MSFT",
    "AMD",
    "RKLB",
    "SOXX",
    "QQQ",
    "SPY"
]

NUM_MONTHS = 12

OUTPUT_CSV = "opex_study_results.csv"

# ============================================================
# THIRD FRIDAY FUNCTION
# ============================================================

def third_friday(year, month):

    cal = calendar.monthcalendar(year, month)

    friday_column = calendar.FRIDAY

    if cal[0][friday_column] != 0:
        day = cal[2][friday_column]
    else:
        day = cal[3][friday_column]

    return datetime(year, month, day)

# ============================================================
# SAFE OPTION PRICING
# ============================================================

def safe_option_price(option_row):

    bid = float(option_row["bid"])
    ask = float(option_row["ask"])
    last = float(option_row["lastPrice"])

    # Preferred midpoint pricing
    if bid > 0 and ask > 0:
        return (bid + ask) / 2

    # Fallback to last trade
    if last > 0:
        return last

    return 0.0

# ============================================================
# GET NEXT MONTHLY EXPIRATION
# ============================================================

def get_next_monthly_expiration(ticker):

    tk = yf.Ticker(ticker)

    expirations = tk.options

    monthly_expirations = []

    for exp in expirations:

        exp_date = pd.Timestamp(exp)

        # Monthly expirations generally
        # occur between 15th and 21st

        if 15 <= exp_date.day <= 21:

            # Thursday or Friday
            if exp_date.weekday() in [3, 4]:

                monthly_expirations.append(exp)

    monthly_expirations = sorted(
        monthly_expirations
    )

    if len(monthly_expirations) == 0:

        raise Exception(
            f"No monthly expirations found for {ticker}"
        )

    return monthly_expirations[0]

# ============================================================
# GENERATE HISTORICAL OPEX DATES
# ============================================================

today = pd.Timestamp.today().normalize()

print("\nTODAY:", today)

historical_opex_dates = []

for i in range(NUM_MONTHS):

    month_date = today - pd.DateOffset(
        months=i
    )

    year = month_date.year
    month = month_date.month

    opex = third_friday(year, month)

    if opex <= today:
        historical_opex_dates.append(opex)

historical_opex_dates = sorted(
    historical_opex_dates
)

print("\nHistorical OPEX Dates:\n")

for d in historical_opex_dates:
    print(d.strftime("%Y-%m-%d"))

# ============================================================
# GET NEXT FUTURE MONTHLY EXPIRATIONS
# ============================================================

future_opex_per_ticker = {}

print("\nNext Monthly OPEX Per Ticker:\n")

for ticker in TICKERS:

    try:

        future_exp = get_next_monthly_expiration(
            ticker
        )

        future_opex_per_ticker[ticker] = (
            future_exp
        )

        print(
            f"{ticker}: {future_exp}"
        )

    except Exception as e:

        print(
            f"Error finding future "
            f"expiration for {ticker}: {e}"
        )

# ============================================================
# DOWNLOAD HISTORICAL DATA
# ============================================================

start_date = min(
    historical_opex_dates
) - timedelta(days=14)

end_date = today

all_data = {}

for ticker in TICKERS:

    print(f"\nDownloading {ticker}...")

    df = yf.download(
        ticker,
        start=start_date.strftime(
            "%Y-%m-%d"
        ),
        end=end_date.strftime(
            "%Y-%m-%d"
        ),
        auto_adjust=True,
        progress=False,
        group_by="column"
    )

    # Flatten MultiIndex columns
    if isinstance(df.columns, pd.MultiIndex):

        df.columns = (
            df.columns.get_level_values(0)
        )

    df.index = pd.to_datetime(df.index)

    all_data[ticker] = df

# ============================================================
# BUILD HISTORICAL DATASET
# ============================================================

results = []

for ticker in TICKERS:

    print(
        f"\nProcessing Historical Data: "
        f"{ticker}"
    )

    df = all_data[ticker]

    for opex in historical_opex_dates:

        week_start = opex - timedelta(days=4)

        week_df = df.loc[week_start:opex]

        # ====================================================
        # HANDLE PARTIAL WEEKS
        # ====================================================

        if len(week_df) == 0:

            print(
                f"No data available for "
                f"{ticker} {opex}"
            )

            continue

        if len(week_df) < 5:

            print(
                f"Using partial week for "
                f"{ticker} {opex} "
                f"({len(week_df)} trading days)"
            )

        try:

            week_open = float(
                week_df.iloc[0]["Open"]
            )

            week_high = float(
                week_df["High"].max()
            )

            week_low = float(
                week_df["Low"].min()
            )

            expiration_close = float(
                week_df.iloc[-1]["Close"]
            )

            total_volume = int(
                week_df["Volume"].sum()
            )

            avg_volume = int(
                week_df["Volume"].mean()
            )

            range_dollars = (
                week_high - week_low
            )

            range_percent = (
                (range_dollars / week_open) * 100
            )

            weekly_return = (
                (expiration_close - week_open)
                / week_open
            ) * 100

            close_position = (
                (expiration_close - week_low)
                / (week_high - week_low)
            )

            result = {

                "ticker": ticker,

                "opex_date": opex.strftime(
                    "%Y-%m-%d"
                ),

                "data_type": "historical",

                "week_open": round(
                    week_open, 2
                ),

                "week_high": round(
                    week_high, 2
                ),

                "week_low": round(
                    week_low, 2
                ),

                "expiration_close": round(
                    expiration_close, 2
                ),

                "range_dollars": round(
                    range_dollars, 2
                ),

                "range_percent": round(
                    range_percent, 2
                ),

                "weekly_return_percent": round(
                    weekly_return, 2
                ),

                "close_position_in_range": round(
                    close_position, 3
                ),

                "total_volume": total_volume,

                "average_volume": avg_volume,

                # Future metrics
                "spot_price": None,
                "atm_strike": None,
                "atm_call_mid": None,
                "atm_put_mid": None,
                "expected_move": None,
                "expected_move_percent": None,
                "implied_upper": None,
                "implied_lower": None,
                "iv_percent": None,

                # OI metrics
                "high_oi_put_strike": None,
                "high_oi_put_oi": None,
                "high_oi_call_strike": None,
                "high_oi_call_oi": None
            }

            results.append(result)

        except Exception as e:

            print(
                f"Error processing "
                f"{ticker} {opex}: {e}"
            )

# ============================================================
# ADD FUTURE IMPLIED MOVE ROW
# ============================================================

for ticker in TICKERS:

    print(
        f"\nProcessing Future OPEX: "
        f"{ticker}"
    )

    try:

        tk = yf.Ticker(ticker)

        current_price = float(
            tk.history(period="1d")[
                "Close"
            ].iloc[-1]
        )

        expiration_str = (
            future_opex_per_ticker[ticker]
        )

        option_chain = tk.option_chain(
            expiration_str
        )

        calls = option_chain.calls.copy()
        puts = option_chain.puts.copy()

        # ====================================================
        # FIND ATM STRIKE
        # ====================================================

        calls["distance"] = abs(
            calls["strike"] - current_price
        )

        atm_row = calls.sort_values(
            "distance"
        ).iloc[0]

        atm_strike = float(
            atm_row["strike"]
        )

        # Match same strike
        call_option = calls[
            calls["strike"] == atm_strike
        ].iloc[0]

        put_option = puts[
            puts["strike"] == atm_strike
        ].iloc[0]

        # ====================================================
        # SAFE OPTION PRICING
        # ====================================================

        call_mid = safe_option_price(
            call_option
        )

        put_mid = safe_option_price(
            put_option
        )

        print(
            f"{ticker} ATM Strike: "
            f"{atm_strike} | "
            f"Call: {call_mid:.2f} | "
            f"Put: {put_mid:.2f}"
        )

        # ====================================================
        # IMPLIED MOVE
        # ====================================================

        expected_move = (
            call_mid + put_mid
        )

        expected_move_percent = (
            expected_move / current_price
        ) * 100

        implied_upper = (
            current_price + expected_move
        )

        implied_lower = (
            current_price - expected_move
        )

        iv_percent = (
            float(
                call_option[
                    "impliedVolatility"
                ]
            ) * 100
        )

        # ====================================================
        # LIMIT OI SEARCH RANGE
        # ====================================================

        oi_range = expected_move * 2

        lower_bound = (
            current_price - oi_range
        )

        upper_bound = (
            current_price + oi_range
        )

        # ====================================================
        # HIGHEST OI PUT BELOW SPOT
        # ====================================================

        puts_below = puts[
            (puts["strike"] < current_price)
            & (puts["strike"] >= lower_bound)
        ].copy()

        puts_below = puts_below.sort_values(
            "openInterest",
            ascending=False
        )

        if len(puts_below) > 0:

            top_put = puts_below.iloc[0]

            high_oi_put_strike = float(
                top_put["strike"]
            )

            high_oi_put_oi = int(
                top_put["openInterest"]
            )

        else:

            high_oi_put_strike = None
            high_oi_put_oi = None

        # ====================================================
        # HIGHEST OI CALL ABOVE SPOT
        # ====================================================

        calls_above = calls[
            (calls["strike"] > current_price)
            & (calls["strike"] <= upper_bound)
        ].copy()

        calls_above = calls_above.sort_values(
            "openInterest",
            ascending=False
        )

        if len(calls_above) > 0:

            top_call = calls_above.iloc[0]

            high_oi_call_strike = float(
                top_call["strike"]
            )

            high_oi_call_oi = int(
                top_call["openInterest"]
            )

        else:

            high_oi_call_strike = None
            high_oi_call_oi = None

        print(
            f"{ticker} High OI Put: "
            f"{high_oi_put_strike} "
            f"({high_oi_put_oi})"
        )

        print(
            f"{ticker} High OI Call: "
            f"{high_oi_call_strike} "
            f"({high_oi_call_oi})"
        )

        # ====================================================
        # FINAL FUTURE RESULT ROW
        # ====================================================

        result = {

            "ticker": ticker,

            "opex_date": expiration_str,

            "data_type": "future",

            # Historical fields
            "week_open": None,
            "week_high": None,
            "week_low": None,
            "expiration_close": None,
            "range_dollars": None,
            "range_percent": None,
            "weekly_return_percent": None,
            "close_position_in_range": None,
            "total_volume": None,
            "average_volume": None,

            # Future implied metrics
            "spot_price": round(
                current_price, 2
            ),

            "atm_strike": round(
                atm_strike, 2
            ),

            "atm_call_mid": round(
                call_mid, 2
            ),

            "atm_put_mid": round(
                put_mid, 2
            ),

            "expected_move": round(
                expected_move, 2
            ),

            "expected_move_percent": round(
                expected_move_percent, 2
            ),

            "implied_upper": round(
                implied_upper, 2
            ),

            "implied_lower": round(
                implied_lower, 2
            ),

            "iv_percent": round(
                iv_percent, 2
            ),

            # OI metrics
            "high_oi_put_strike": (
                round(high_oi_put_strike, 2)
                if high_oi_put_strike
                else None
            ),

            "high_oi_put_oi": (
                high_oi_put_oi
            ),

            "high_oi_call_strike": (
                round(high_oi_call_strike, 2)
                if high_oi_call_strike
                else None
            ),

            "high_oi_call_oi": (
                high_oi_call_oi
            )
        }

        results.append(result)

        print(
            f"{ticker} Expected Move: "
            f"+/- {expected_move:.2f} "
            f"({expected_move_percent:.2f}%)"
        )

    except Exception as e:

        print(
            f"Error processing future "
            f"options for {ticker}: {e}"
        )

# ============================================================
# FINAL DATAFRAME
# ============================================================

results_df = pd.DataFrame(results)

results_df = results_df.sort_values(
    ["ticker", "opex_date"]
)

# ============================================================
# EXPORT CSV
# ============================================================

results_df.to_csv(
    OUTPUT_CSV,
    index=False
)

print(
    f"\nCSV exported: {OUTPUT_CSV}"
)

# ============================================================
# SUMMARY STATISTICS
# ============================================================

historical_df = results_df[
    results_df["data_type"] == "historical"
]

summary = historical_df.groupby("ticker")[
    [
        "range_percent",
        "weekly_return_percent",
        "close_position_in_range"
    ]
].mean()

print("\n===============================")
print("AVERAGE HISTORICAL STATISTICS")
print("===============================\n")

print(summary)