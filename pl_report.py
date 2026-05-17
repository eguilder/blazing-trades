from pathlib import Path
import pandas as pd
import numpy as np
import sys

# =========================================================
# ARGUMENTS
# =========================================================

if len(sys.argv) < 2:

    print("\nUsage:")
    print("python3 pl_report.py <csv_file> [--details]")
    sys.exit(1)

INPUT_CSV = sys.argv[1]

# Optional flag
SHOW_DETAILS = "--details" in sys.argv

# Output filename
input_path = Path(INPUT_CSV)

OUTPUT_XLSX = (
    input_path.stem + "_PL_Report.xlsx"
)

# =========================================================
# COLUMN CONFIG
# =========================================================

DATE_COLUMN = "Date"
PRODUCT_COLUMN = "Product"
VALUE_COLUMN = "Total EUR"

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
    PRODUCT_COLUMN,
    VALUE_COLUMN
]

missing = [
    c for c in required
    if c not in df.columns
]

if missing:

    raise Exception(
        f"Missing columns: {missing}"
    )

# =========================================================
# PREPARE DATA
# =========================================================

work = df[
    [
        DATE_COLUMN,
        PRODUCT_COLUMN,
        VALUE_COLUMN
    ]
].copy()

# Parse dates
work["DateParsed"] = pd.to_datetime(
    work[DATE_COLUMN],
    dayfirst=True,
    errors="coerce"
)

# Parse EUR values
def parse_number(x):

    s = str(x).strip()

    # Remove commas if present
    s = s.replace(",", "")

    try:
        return float(s)

    except:
        return np.nan

work["TotalEUR"] = (
    work[VALUE_COLUMN]
    .apply(parse_number)
)

# Remove invalid rows
work = work.dropna(
    subset=[
        "DateParsed",
        PRODUCT_COLUMN,
        "TotalEUR"
    ]
)

# =========================================================
# CREATE MONTH KEY
# =========================================================

work["Month"] = (
    work["DateParsed"]
    .dt.strftime("%Y-%m")
)

# =========================================================
# GROUP BY PRODUCT + MONTH
# =========================================================

grouped = (
    work.groupby(
        [
            PRODUCT_COLUMN,
            "Month"
        ],
        as_index=False
    )
    .agg({
        "TotalEUR": "sum",
        "DateParsed": [
            "min",
            "max",
            "count"
        ]
    })
)

# Flatten columns
grouped.columns = [
    "Product",
    "Month",
    "Net EUR",
    "First Trade",
    "Last Trade",
    "Trade Count"
]

# Realized P/L
grouped["Realized P/L EUR"] = (
    grouped["Net EUR"]
)

# =========================================================
# MONTHLY P/L
# =========================================================

monthly_pl = (
    grouped.groupby("Month")[
        "Realized P/L EUR"
    ]
    .sum()
    .reset_index()
    .sort_values("Month")
)

# =========================================================
# SUMMARY
# =========================================================

total_pl = round(
    grouped["Realized P/L EUR"].sum(),
    2
)

summary = pd.DataFrame([{
    "Total Realized P/L EUR": total_pl,
    "Total Product+Month Groups": len(grouped),
    "Open/Unmatched Trades": 0
}])

# =========================================================
# SORT OUTPUT
# =========================================================

grouped = grouped.sort_values(
    ["Month", "Product"]
)

# =========================================================
# EXPORT TO EXCEL
# =========================================================

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
            print(f"    Trades: {trades}")
            print(f"    First Trade: {first_trade}")
            print(f"    Last Trade : {last_trade}")
            print()

# =========================================================
# TOTAL
# =========================================================

print("\n==============================")
print("TOTAL P/L")
print("==============================")

print(f"{total_pl:.2f} EUR")

print("\nExcel report saved to:")
print(OUTPUT_XLSX)