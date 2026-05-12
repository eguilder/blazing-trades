# OPEX Range + Implied Move Dashboard

A quantitative options expiration (OPEX) analysis framework for studying:

- Historical spot ranges during monthly expiration weeks
- Expiration closing behavior
- Forward implied volatility ranges
- ATM expected moves
- Near-the-money open interest positioning
- Dealer support/resistance structures

This project combines:

- Python data engineering
- Options chain analysis
- Interactive Plotly visualization
- Historical + forward-looking volatility analysis

---

# Features

## Historical OPEX Analysis

For each underlying and each monthly expiration:

- Weekly high-low spot range
- Expiration close
- Weekly return
- Range %
- Close location within weekly range
- Volume analysis

### Metrics Included

| Metric | Description |
|---|---|
| `week_high` | Highest price during OPEX week |
| `week_low` | Lowest price during OPEX week |
| `expiration_close` | Friday expiration close |
| `range_percent` | Weekly range normalized |
| `weekly_return_percent` | Weekly directional move |
| `close_position_in_range` | Where expiration closed inside weekly range |

---

# Forward Implied Move Modeling

The framework also calculates the next monthly OPEX implied move using:

- ATM call premium
- ATM put premium
- Expected move pricing
- Implied volatility

### Formula

```python
Expected Move =
ATM Call Premium + ATM Put Premium
```

### Outputs

| Metric | Description |
|---|---|
| `expected_move` | Dollar expected move |
| `expected_move_percent` | Normalized expected move |
| `implied_upper` | Expected upper bound |
| `implied_lower` | Expected lower bound |
| `iv_percent` | ATM implied volatility |

---

# Open Interest Positioning

The framework identifies:

- Highest near-the-money put open interest below spot
- Highest near-the-money call open interest above spot

These act as:

- Dealer support zones
- Dealer resistance zones
- Potential gamma walls
- Possible pinning levels

### OI Filtering

To avoid distorted far-OTM strikes:

- strike selection is constrained to:
  
```text
spot ± (2 × expected move)
```

This keeps positioning analysis near-the-money and relevant.

---

# Dashboard Features

The HTML dashboard provides:

## Interactive Visualization

### Historical Data

- Blue vertical bars
  - realized weekly spot ranges

- Green/red dots
  - expiration close locations

### Future OPEX Structure

- Orange dashed vertical bar
  - implied move range

- Yellow marker
  - current spot price

- Green horizontal bar
  - highest put OI support

- Red horizontal bar
  - highest call OI resistance

---

# Example Visualization Structure

```text
CALL WALL ───────

        │
        │ implied move
        │

        ● current spot

        │
        │

PUT WALL ───────
```

---

# Technologies Used

## Backend

- Python
- pandas
- yfinance

## Frontend

- HTML
- JavaScript
- Plotly.js

---

# Project Structure

```text
project/
│
├── opex_spot.py
├── opex_spot.html
├── opex_study_results.csv
└── README.md
```

---

# Installation

## Python Dependencies

```bash
pip install pandas yfinance
```

---

# Usage

# Step 1 — Run Python Pipeline

```bash
python opex_spot.py
```

This generates:

```text
opex_study_results.csv
```

---

# Step 2 — Open Dashboard

Open:

```text
opex_spot.html
```

in your browser.

---

# Step 3 — Upload CSV

Upload:

```text
opex_study_results.csv
```

using the dashboard upload interface.

---

# Supported Underlyings

Default configuration:

- SPY
- QQQ
- AAPL
- NVDA
- TSLA

You can add additional highly liquid names easily.

---

# Research Applications

This framework can be used to study:

- OPEX pinning behavior
- Dealer hedging dynamics
- Gamma walls
- Volatility compression
- Volatility expansion
- Realized vs implied move pricing
- Event volatility
- Dealer positioning structure
- Options market sentiment

---

# Potential Future Enhancements

## Volatility Analytics

- Realized volatility
- ATR
- IV rank
- Historical IV percentile

## Options Analytics

- Gamma exposure (GEX)
- Delta exposure
- Max pain
- Skew analysis
- Term structure

## Dashboard Enhancements

- Heatmaps
- Multi-ticker comparison
- Realized vs implied ratio charts
- Auto-refresh
- Live data mode
- Multi-expiration support

## Backend Improvements

- Polygon API
- Tradier API
- Interactive Brokers API
- CBOE data integration

---

# Notes

## Monthly Expiration Logic

The framework dynamically discovers:

- actual listed monthly expirations

instead of relying solely on calendar math.

This handles:

- exchange holidays
- Thursday-settled monthlies
- special expiration schedules

---

# Data Quality Notes

`yfinance` is suitable for:

- prototyping
- research
- visualization

For institutional-grade options analysis consider:

- Polygon
- ORATS
- Tradier
- dxFeed
- CBOE DataShop

---

# Disclaimer

This project is for:

- research
- educational
- analytical purposes only

Not financial advice.

Options trading involves significant risk.