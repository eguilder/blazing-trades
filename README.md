# Blazing Trades

A collection of options trading tools covering OPEX analysis and live Greeks overlays for DeGiro.

---

# Project Structure

```text
├── opex_spot.py                     # OPEX data pipeline
├── opex_spot.html                   # OPEX dashboard
├── greeks_service.py                # Greeks API server (Flask + IBKR)
├── ibkr_option_greeks.py            # IBKR option position Greeks summary
├── DeGiro-Greeks-Overlay-1.0.user.js     # Tampermonkey script — live Greeks
├── DeGiro-Options-Month-Buttons.user.js  # Tampermonkey script — expiry filter
├── pl_report.py                     # Realized P&L report from broker CSV
└── README.md
```

---

# Section 1 — OPEX Range Dashboard

Analyses historical spot ranges during monthly expiration weeks and models the forward implied move for the next OPEX.

## Usage

**Step 1** — Run the pipeline:

```bash
pip install pandas yfinance
python opex_spot.py
```

This generates `opex_study_results.csv`.

**Step 2** — Open `opex_spot.html` in your browser and upload the CSV.

## What It Shows

| Column | Description |
|---|---|
| `week_high` / `week_low` | Realized weekly spot range |
| `range_percent` | Weekly range normalized |
| `expiration_close` | Friday expiration close |
| `close_position_in_range` | Where price closed within the range |
| `expected_move` | ATM call + put premium |
| `implied_upper` / `implied_lower` | Implied move bounds |
| `high_oi_put_strike` | Highest near-the-money put OI (support) |
| `high_oi_call_strike` | Highest near-the-money call OI (resistance) |

OI strikes are filtered to `spot ± (2 × expected move)` to keep analysis near-the-money.

## Supported Underlyings

TSLA, NVDA, QCOM, MU, INTC, AAPL, META, AMZN, MSFT, AMD, RKLB — configurable in `opex_spot.py`.

---

# Section 2 — DeGiro Options Tools

Two Tampermonkey userscripts that enhance the DeGiro portfolio page with options-specific features.

## Requirements

- [Tampermonkey](https://www.tampermonkey.net/) browser extension
- Both scripts are scoped to `https://trader.degiro.nl/trader/#/portfolio/assets`

## Installation

1. Open the raw userscript URL in your browser:
   - [DeGiro Options Month Buttons](https://raw.githubusercontent.com/eguilder/blazing-trades/main/DeGiro-Options-Month-Buttons.user.js)
   - [DeGiro Greeks Overlay](https://raw.githubusercontent.com/eguilder/blazing-trades/main/DeGiro-Greeks-Overlay-1.0.user.js)
2. Tampermonkey should open its install screen automatically.
3. Install or update the script from that screen.

If an existing manually pasted script does not detect updates, remove that Tampermonkey copy and reinstall it from the raw URL above. Future updates use the script's `@updateURL` and `@downloadURL` metadata.

---

## Script 1 — DeGiro Options Month Buttons

**File:** `DeGiro-Options-Month-Buttons.user.js`

Adds a row of filter buttons above the portfolio table, one per expiry month present in the portfolio. Clicking a month hides all option rows for other expiries, making it easy to focus on a single expiration.

**Buttons:**
- `ALL` — show all rows
- `JAN`, `FEB`, ... — show only that expiry month

The active filter is highlighted in green. The button bar updates automatically when positions change.

---

## Script 2 — DeGiro Greeks Overlay

**File:** `DeGiro-Greeks-Overlay-1.0.user.js`

Fetches live option Greeks from a local IBKR-connected API server (`greeks_service.py`) and overlays them directly onto the DeGiro portfolio table.

### What It Adds

**Table columns** (inserted after Total P/L):

| Column | Description |
|---|---|
| `Δ` | Per-share delta from IBKR model Greeks |
| `Θ` | Per-share theta from IBKR model Greeks |

**Summary panel** (fixed top-right overlay):

| Field | Description |
|---|---|
| Portfolio Θ | Total theta across all positions (`theta × qty × multiplier`) |
| Synthetic Shares | Per-ticker delta exposure (`delta × qty × multiplier`), showing the equivalent share position each underlying's options represent |

### Greeks Service Setup

The script requires `greeks_service.py` to be running locally:

```bash
pip install -r requirements.txt
python greeks_service.py
```

IBKR TWS or Gateway must be running with API access enabled on port `7496`.

On Windows, Python 3.14+ also works when the dependencies are installed into
that interpreter:

```powershell
py -3.14 -m pip install -r requirements.txt
py -3.14 .\greeks_service.py
```

If IBKR reports that the client id is already in use, start the service with a
different id:

```powershell
$env:IB_CLIENT_ID = "778"
py -3.14 .\greeks_service.py
```

Configure the API host in the script:

```js
const API_URL = 'http://127.0.0.1:5000/greeks';
```

### Supported Underlyings

Configured in `greeks_service.py`:

| Key | Symbol | Exchange | Multiplier |
|---|---|---|---|
| `ADY` | ADYEN | FTA | 10 |
| `ASL` | ASML | FTA | 100 |
| `BES` | BESI | FTA | 100 |
| `ING` | ING | FTA | 100 |

Add further underlyings by extending the `UNDERLYINGS` dict in `greeks_service.py`.

---

# Section 3 - IBKR Option Greeks Summary

**File:** `ibkr_option_greeks.py`

Connects directly to IBKR, reads current option positions, requests IBKR model
Greeks for each option contract, and prints total delta/theta by underlying plus
a delta dollar exposure column and a detailed per-contract breakdown. `Delta $`
is calculated as total delta exposure multiplied by the underlying share price.

## Usage

```powershell
pip install -r requirements.txt
py -3 .\ibkr_option_greeks.py
```

IBKR TWS or Gateway must be running with API access enabled. By default the
script connects to `127.0.0.1:7496`, uses delayed market data, and starts with
client id `778` so it does not collide with `greeks_service.py`, which defaults
to `777`.

## Options

| Flag | Default | Description |
|---|---:|---|
| `--host` | `127.0.0.1` | IBKR TWS/Gateway host |
| `--port` | `7496` | IBKR TWS/Gateway API port |
| `--client-id` | `778` | First IBKR API client id to try |
| `--client-id-attempts` | `10` | Number of sequential client ids to try |
| `--connect-timeout` | `4.0` | Seconds to wait for each connection attempt |
| `--option-exchange` | `SMART` | Exchange used when a position contract has no exchange |
| `--stock-exchange` | `SMART` | Exchange used when requesting underlying stock prices |
| `--wait` | `6.0` | Seconds to wait for model Greeks per contract |

Environment variables are also supported:

```powershell
$env:IB_HOST = "127.0.0.1"
$env:IB_PORT = "7496"
$env:IB_OPTION_GREEKS_CLIENT_ID = "778"
$env:IB_CLIENT_ID_ATTEMPTS = "10"
$env:IB_CONNECT_TIMEOUT = "4"
$env:IB_OPTION_EXCHANGE = "SMART"
$env:IB_STOCK_EXCHANGE = "SMART"
```

If IBKR reports `client id is already in use`, the script automatically tries
the next id. If IBKR reports `Please enter exchange` for an option market-data
request, the script fills blank option exchanges with `SMART`; override this
with `--option-exchange` if a specific venue is required.

---

# Section 4 — Realized P&L Report

Generates a realized P&L report from a broker CSV export (e.g. DeGiro transaction history). Produces a per-product, per-month breakdown using FIFO lot matching.

## Usage

```bash
pip install pandas openpyxl
python pl_report.py trades.csv [--details] [--write] [--output report.xlsx]
```

| Flag | Description |
|---|---|
| `--details` | Print per-product breakdown in console output |
| `--write` | Save Excel report to `<input_stem>_PL_Report.xlsx` |
| `--output PATH` | Save Excel report to a custom path (implies `--write`) |

## How It Works

**Input:** Auto-detects CSV encoding (`utf-8`, `latin1`, `cp1252`) and delimiter (`,`, `;`, `tab`, `|`), so broker exports work without manual cleanup.

**FIFO matching:** Opens and closes are matched chronologically per product. Realized P&L is assigned to the month the position was **closed**, not opened. Partial closes, position flips, and leftover open lots are all handled. Falls back to naive monthly cash summation if no quantity column is present.

**Output:**

| View | Description |
|---|---|
| Summary | Total realized P&L, number of product/month groups, open/unmatched trade count |
| Monthly P&L | Total realized P&L per calendar month |
| Product + Month P&L | Per-product breakdown — closed qty, first open, last close, realized P&L |

Always printed to the console. Use `--write` or `--output` to also export an Excel file with all three views as separate sheets.

---

# Disclaimer

For research and analytical purposes only. Not financial advice. Options trading involves significant risk.
