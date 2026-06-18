# Blazing Trades

A collection of options trading tools covering OPEX analysis and live Greeks overlays for DeGiro.

---

# Project Structure

```text
├── opex_spot.py                     # OPEX data pipeline
├── opex_spot.html                   # OPEX dashboard
├── greeks_service.py                # Greeks API server (Flask + IBKR)
├── DeGiro Greeks Overlay-1.0.js     # Tampermonkey script — live Greeks
├── DeGiro Options Month Buttons.js  # Tampermonkey script — expiry filter
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

1. Open Tampermonkey → **Create new script**
2. Paste the contents of the script file
3. Save — the script activates automatically on the DeGiro portfolio page

---

## Script 1 — DeGiro Options Month Buttons

**File:** `DeGiro Options Month Buttons.js`

Adds a row of filter buttons above the portfolio table, one per expiry month present in the portfolio. Clicking a month hides all option rows for other expiries, making it easy to focus on a single expiration.

**Buttons:**
- `ALL` — show all rows
- `JAN`, `FEB`, ... — show only that expiry month

The active filter is highlighted in green. The button bar updates automatically when positions change.

---

## Script 2 — DeGiro Greeks Overlay

**File:** `DeGiro Greeks Overlay-1.0.js`

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
pip install flask ib_insync
python greeks_service.py
```

IBKR TWS or Gateway must be running with API access enabled on port `7496`.

Configure the API host in the script:

```js
const API_URL = 'http://172.23.224.1:5000/greeks';
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

# Disclaimer

For research and analytical purposes only. Not financial advice. Options trading involves significant risk.