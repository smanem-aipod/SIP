from pathlib import Path

import pandas as pd

file_path = Path(
    "data/source_files/SIP_ FY26_ NA_CS_Q2.xlsb"
)

df = pd.read_excel(
    file_path,
    sheet_name="BP File",
    header=1,
    engine="pyxlsb",
)

print("Columns:")
print(df.columns.tolist())

print("\nRows where Reporting line contains the header text:")

mask = (
    df["Reporting line"]
    .astype("string")
    .str.strip()
    .str.casefold()
    .eq("reporting line")
)

print(df.loc[mask])
print("Excel/DataFrame row indexes:", df.index[mask].tolist())

print("\nRows completely empty across all real BP columns:")

real_columns = [
    column
    for column in df.columns
    if not str(column).startswith("Unnamed:")
]

empty_mask = df[real_columns].isna().all(axis=1)

print("Empty row count:", int(empty_mask.sum()))
print("Empty row indexes:", df.index[empty_mask].tolist())