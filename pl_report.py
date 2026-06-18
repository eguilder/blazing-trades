from pathlib import Path
import pandas as pd
import numpy as np
import sys
from collections import deque

# =========================================================
# ARGUMENTS
# =========================================================

if len(sys.argv) < 2:

    print("\nUsage:")
    print("python3 pl_report.py <csv_file> [--details] [--write] [--output <xlsx_path>]")
    print("  --write          Export Excel to default path (<input_stem>_PL_Report.xlsx) or --output path")
    print("  --output PATH    Export Excel to custom PATH (implies --write)")
    sys.exit(1)

INPUT_CSV = sys.argv[1]

# Optional flags
SHOW_DETAILS = "--details" in sys.argv
WRITE_TO_FILE = ("--write" in sys.argv) or ("--output" in sys.argv)

# Output filename resolution
output_path_arg = None
if "--output" in sys.argv:
    try:
        idx = sys.argv.index("--output")
        output_path_arg = sys.argv[idx + 1]
        # Basic validation: next token should not be another flag
        if output_path_arg.startswith("--"):
            raise ValueError
    except Exception:
        print("Error: --output requires a file path argument")
        sys.exit(1)

input_path = Path(INPUT_CSV)
if output_path_arg:
    OUTPUT_XLSX = output_path_arg
else:
    OUTPUT_XLSX = input_path.stem + "_PL_Report.xlsx"

# =========================================================
# COLUMN CONFIG
# =========================================================

DATE_COLUMN = "Date"
PRODUCT_COLUMN = "Product"
VALUE_COLUMN = "Total EUR"  # Net cash flow per trade (including fees) if available

# Try to auto-detect common alternative column names
QTY_CANDIDATES = [
    "Qty", "Quantity", "Contracts", "Units", "Size"
]
AMOUNT_CANDIDATES = [
    VALUE_COLUMN,
    "Net Amount EUR", "Amount EUR", "Net EUR", "Cash EUR", "Cash",
    "Net Amount", "Amount", "Total"
]
FEE_CANDIDATES = [
    "Commission", "Fee", "Fees", "Commission EUR", "Fees EUR",
    "Charges", "Total Fees", "Cost"
]

# =========================================================
# LOAD CSV
# =========================================================

encodings = [
    "utf-8",
    "utf-8-sig",
    "latin1",
    "cp1252"
]

separators = [
    ",",
    ";",
    "\t",
    "|"
]

df = None

for encoding in encodings:

    for sep in separators:

        try:

            temp = pd.read_csv(
                INPUT_CSV,
                sep=sep,
                encoding=encoding,
                engine="python"
            )

            if temp.shape[1] > 1:

                df = temp

                print(
                    f"Loaded CSV using "
                    f"encoding={encoding}, sep='{sep}'"
                )

                break

        except Exception:
            pass

    if df is not None:
        break

if df is None:

    raise Exception(
        "Could not parse CSV. "
        "Check delimiter or encoding."
    )

# =========================================================
# CLEAN COLUMN NAMES
# =========================================================

df.columns = [c.strip() for c in df.columns]

# =========================================================
# VALIDATE REQUIRED COLUMNS
# =========================================================

required = [
    DATE_COLUMN,
    PRODUCT_COLUMN
]

missing = [
    c for c in required
    if c not in df.columns
]

if missing:

    raise Exception(
        f"Missing columns: {missing}"
    )

# Resolve optional columns

def first_existing(cols, candidates):
    for name in candidates:
        if name in cols:
            return name
    return None

QTY_COLUMN = first_existing(df.columns, QTY_CANDIDATES)
AMOUNT_COLUMN = first_existing(df.columns, AMOUNT_CANDIDATES) or VALUE_COLUMN
FEE_COLUMN = first_existing(df.columns, FEE_CANDIDATES)

if AMOUNT_COLUMN not in df.columns:
    raise Exception(
        f"Missing cash amount column. Looked for any of: {AMOUNT_CANDIDATES}"
    )

# =========================================================
# PREPARE DATA
# =========================================================

use_cols = [DATE_COLUMN, PRODUCT_COLUMN, AMOUNT_COLUMN]
if QTY_COLUMN:
    use_cols.append(QTY_COLUMN)
if FEE_COLUMN:
    use_cols.append(FEE_COLUMN)

work = df[use_cols].copy()

# Parse dates (supports time if present)
work["DateParsed"] = pd.to_datetime(
    work[DATE_COLUMN],
    dayfirst=True,
    errors="coerce"
)

# Generic number parser (supports '1,234.56' and '1.234,56')
def parse_number(x):
    if pd.isna(x):
        return np.nan
    s = str(x).strip()
    if s == "":
        return np.nan
    # Heuristic: if both "." and "," present and "," is to the right of ".", assume comma is decimal
    if "," in s and "." in s and s.rfind(",") > s.rfind("."):
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except Exception:
        return np.nan

work["CashEUR"] = work[AMOUNT_COLUMN].apply(parse_number)
if QTY_COLUMN:
    work["Qty"] = work[QTY_COLUMN].apply(parse_number)
else:
    work["Qty"] = np.nan

# Optional fees (if present) – included for completeness; if your cash column already includes fees, this will be 0
if FEE_COLUMN:
    work["FeeEUR"] = work[FEE_COLUMN].apply(parse_number).fillna(0.0)
else:
    work["FeeEUR"] = 0.0

# Remove invalid rows
req = ["DateParsed", PRODUCT_COLUMN, "CashEUR"]
work = work.dropna(subset=req)

# Ensure stable ordering
work = work.sort_values([PRODUCT_COLUMN, "DateParsed"]).reset_index(drop=True)

# =========================================================
# REALIZATION LOGIC (assign realized P/L to the close month)
# =========================================================

has_qty = work["Qty"].notna().any()

realized_rows = []  # List of dicts with realized events
open_lots_count = 0

if has_qty:

    for product, g in work.groupby(PRODUCT_COLUMN, sort=False):
        # FIFO queue of open lots: each lot is dict with remaining units and per-unit cash
        # Positive qty lot => opened long (cash usually negative). Negative qty lot => opened short (cash usually positive).
        lots = deque()

        for _, r in g.iterrows():
            dt = r["DateParsed"]
            qty = int(round(r["Qty"])) if not pd.isna(r["Qty"]) else 0
            if qty == 0:
                continue
            per_unit_cash = r["CashEUR"] / abs(qty)

            # If no position or adding in same direction => open lot
            def position_sign():
                total = sum(lot["remain"] * lot["side"] for lot in lots)
                if total > 0:
                    return 1
                if total < 0:
                    return -1
                return 0

            sign_now = 1 if qty > 0 else -1
            pos_sign = position_sign()

            # Determine if this trade closes existing lots
            if pos_sign != 0 and sign_now != pos_sign:
                # We are closing against existing position
                qty_to_close = abs(qty)
                while qty_to_close > 0 and lots:
                    lot = lots[0]
                    closable = min(qty_to_close, lot["remain"])
                    # Realized per-unit = open per-unit cash + close per-unit cash
                    realized = closable * (lot["per_unit_cash"] + per_unit_cash)
                    realized_rows.append({
                        "Product": product,
                        "Open Date": lot["open_date"],
                        "Close Date": dt,
                        "Close Month": dt.strftime("%Y-%m"),
                        "Closed Qty": closable,
                        "Realized P/L EUR": realized
                    })

                    lot["remain"] -= closable
                    qty_to_close -= closable

                    if lot["remain"] == 0:
                        lots.popleft()

                # If we over-closed and flipped the position, the remainder becomes a new lot in the new direction
                if qty_to_close > 0:
                    lots.append({
                        "remain": qty_to_close,
                        "per_unit_cash": per_unit_cash,
                        "open_date": dt,
                        "side": sign_now
                    })
            else:
                # Opening or adding to same direction
                lots.append({
                    "remain": abs(qty),
                    "per_unit_cash": per_unit_cash,
                    "open_date": dt,
                    "side": sign_now
                })

        # Count any open (unmatched) lots leftover
        open_lots_count += sum(lot["remain"] for lot in lots)

    if realized_rows:
        realized_df = pd.DataFrame(realized_rows)
    else:
        realized_df = pd.DataFrame(columns=[
            "Product", "Open Date", "Close Date", "Close Month",
            "Closed Qty", "Realized P/L EUR"
        ])

    # Build per-product per-close-month aggregation
    if not realized_df.empty:
        grouped = (
            realized_df
            .groupby(["Product", "Close Month"], as_index=False)
            .agg({
                "Realized P/L EUR": "sum",
                "Open Date": "min",
                "Close Date": "max",
                "Closed Qty": "sum"
            })
            .rename(columns={
                "Close Month": "Month",
                "Open Date": "First Trade",
                "Close Date": "Last Trade",
                "Closed Qty": "Trade Count"
            })
        )
        grouped["Net EUR"] = grouped["Realized P/L EUR"]
    else:
        # No realized events; fall back to empty report
        grouped = pd.DataFrame(columns=[
            "Product", "Month", "Net EUR", "First Trade", "Last Trade",
            "Trade Count", "Realized P/L EUR"
        ])

else:
    # =====================================================
    # FALLBACK: no quantity column available -> use original
    # logic (sum cash by transaction month)
    # =====================================================

    print(
        "Warning: Quantity column not found. "
        f"Looked for any of: {QTY_CANDIDATES}.\n"
        "Falling back to naive monthly sum by transaction date."
    )

    # Parse EUR values already in work["CashEUR"], create Month key
    work["Month"] = work["DateParsed"].dt.strftime("%Y-%m")

    grouped = (
        work.groupby([PRODUCT_COLUMN, "Month"], as_index=False)
        .agg({
            "CashEUR": "sum",
            "DateParsed": ["min", "max", "count"]
        })
    )

    grouped.columns = [
        "Product", "Month", "Net EUR", "First Trade", "Last Trade", "Trade Count"
    ]
    grouped["Realized P/L EUR"] = grouped["Net EUR"]

# =========================================================
# MONTHLY P/L
# =========================================================

if grouped.empty:
    monthly_pl = pd.DataFrame(columns=["Month", "Realized P/L EUR"])  # empty
else:
    monthly_pl = (
        grouped.groupby("Month")["Realized P/L EUR"]
        .sum()
        .reset_index()
        .sort_values("Month")
    )

# =========================================================
# SUMMARY
# =========================================================

total_pl = round(float(grouped["Realized P/L EUR"].sum()) if not grouped.empty else 0.0, 2)

summary = pd.DataFrame([{
    "Total Realized P/L EUR": total_pl,
    "Total Product+Month Groups": int(len(grouped)),
    "Open/Unmatched Trades": int(open_lots_count)
}])

# =========================================================
# SORT OUTPUT
# =========================================================

if not grouped.empty:
    grouped = grouped.sort_values(["Month", "Product"]).reset_index(drop=True)

# =========================================================
# EXPORT TO EXCEL (optional)
# =========================================================

if 'WRITE_TO_FILE' in globals() and WRITE_TO_FILE:
    with pd.ExcelWriter(
        OUTPUT_XLSX,
        engine="openpyxl"
    ) as writer:

        summary.to_excel(
            writer,
            sheet_name="Summary",
            index=False
        )

        monthly_pl.to_excel(
            writer,
            sheet_name="Monthly P&L",
            index=False
        )

        grouped.to_excel(
            writer,
            sheet_name="Product+Month P&L",
            index=False
        )

# =========================================================
# CONSOLE OUTPUT
# =========================================================

print("\n==============================")
print("SUMMARY")
print("==============================")

print(summary.to_string(index=False))

print("\n==============================")
print("MONTHLY P/L")
print("==============================")

for _, month_row in monthly_pl.iterrows():

    month = month_row["Month"]
    month_pl = month_row["Realized P/L EUR"]

    print(f"{month}: {month_pl:.2f} EUR")

# =========================================================
# OPTIONAL DETAILS
# =========================================================

if SHOW_DETAILS:

    print("\n==============================")
    print("PRODUCT DETAILS")
    print("==============================")

    for _, month_row in monthly_pl.iterrows():

        month = month_row["Month"]
        month_pl = month_row["Realized P/L EUR"]

        print(f"\n{month}")
        print("-" * 40)
        print(f"Monthly P/L: {month_pl:.2f} EUR")
        print()

        month_products = grouped[
            grouped["Month"] == month
        ]

        for _, row in month_products.iterrows():

            product = row["Product"]
            pnl = row["Realized P/L EUR"]
            trades = row["Trade Count"]
            first_trade = row["First Trade"]
            last_trade = row["Last Trade"]

            print(f"  Product: {product}")
            print(f"    P/L: {pnl:.2f} EUR")
            print(f"    Closed Qty: {int(trades) if not pd.isna(trades) else 0}")
            print(f"    First Open: {first_trade}")
            print(f"    Last Close: {last_trade}")
            print()

# =========================================================
# TOTAL
# =========================================================

print("\n==============================")
print("TOTAL P/L")
print("==============================")

print(f"{total_pl:.2f} EUR")

if 'WRITE_TO_FILE' in globals() and WRITE_TO_FILE:
    print("\nExcel report saved to:")
    print(OUTPUT_XLSX)
else:
    print("\nNote: no file written. Use --write to export Excel to the default path or --output <path>.")