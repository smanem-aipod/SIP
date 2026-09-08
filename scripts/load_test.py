"""
Load test: generates synthetic Excel files at multiple sizes and times
each pipeline stage (upload/raw-load, canonical, calculations).

Usage:
    python scripts/load_test.py [--rows N]
    e.g. python scripts/load_test.py --rows 5000
"""

import argparse
import io
import time
import random
import string
import openpyxl
import requests
import pandas as pd

API_BASE = "http://127.0.0.1:8000/api/v1/runs"
SIZES = [500, 2000, 5000]  # employee row counts to test


# ------------------------------------------------------------------ #
# Data generators
# ------------------------------------------------------------------ #

def rand_id(prefix="E", n=6):
    return prefix + "".join(random.choices(string.digits, k=n))

def rand_name():
    first = random.choice(["Alice", "Bob", "Carol", "David", "Emma", "Frank", "Grace", "Henry"])
    last  = random.choice(["Smith", "Jones", "Brown", "Davis", "Wilson", "Taylor", "Moore"])
    return f"{first} {last}"

def rand_division():
    return random.choice(["DIV-NA", "DIV-EU", "DIV-APAC", "DIV-LATAM", "DIV-MEA"])

def rand_currency():
    return random.choice(["USD", "EUR", "GBP", "SGD"])

def rand_office():
    return random.choice(["Chicago", "London", "Singapore", "Frankfurt", "Houston", "Toronto"])

def rand_group():
    return random.choice(["Group-A", "Group-B", "Group-C", "Group-D"])

ROLES = ["Sales Professional", "Area Manager", "District Manager", "CAM", "BDM"]


def make_employee_df(n_employees):
    rows = []
    for i in range(n_employees):
        eid = rand_id("E", 6)
        role = random.choice(ROLES)
        rows.append({
            "Employee ID": eid,
            "Preferred Name": rand_name(),
            "Job Profile for SIP": role,
            "Payroll Currency": rand_currency(),
            "Region": random.choice(["NA", "EU", "APAC"]),
            "BU": random.choice(["BU1", "BU2", "BU3"]),
            "Sales Office Description": rand_office(),
            "Sales Group Description": rand_group(),
            "SIP Target %": round(random.uniform(10, 25), 2),
            "Annual Salary (Payroll currency)": round(random.uniform(50000, 150000), 2),
            "Active (Yes/No)": "Yes",
        })
    return pd.DataFrame(rows)


def make_bp_df(n_rows):
    rows = []
    for i in range(n_rows):
        cam_id = rand_id("C", 5)
        rows.append({
            "Employee number only for Shared": rand_id("E", 6),
            "AM ID": rand_id("A", 5),
            "DM ID": rand_id("D", 5),
            "CAM_ID": cam_id,
            "BDM_ID": rand_id("B", 5),
            "FY26 Rev": round(random.uniform(100_000, 2_000_000), 2),
            "FY26 GP": round(random.uniform(20_000, 500_000), 2),
            "Sales Office Description": rand_office(),
            "Sales Group Description": rand_group(),
            "Division Node": rand_division(),
            "Currency Code": rand_currency(),
            "Sales District Description": f"District-{random.randint(1,20)}",
        })
    return pd.DataFrame(rows)


def make_sales_df(n_rows):
    rows = []
    quarters = ["2024-001", "2024-002", "2024-003", "2024-004",
                "2025-001", "2025-002", "2025-003", "2025-004"]
    for i in range(n_rows):
        rows.append({
            "Reporting_Line": f"RL-{random.randint(1,50)}",
            "REGION": random.choice(["NA", "EU", "APAC"]),
            "BU": random.choice(["BU1", "BU2", "BU3"]),
            "FISCAL PERIOD": random.choice(quarters),
            "CurrencyCode": rand_currency(),
            "Division Node": rand_division(),
            "Sales Office Description": rand_office(),
            "Sales Group Description": rand_group(),
            "EMP ID": rand_id("E", 6),
            "CC Direct Rev": round(random.uniform(-10_000, 500_000), 2),
            "CC Direct GP": round(random.uniform(-5_000, 200_000), 2),
            "CC Shared Rev": round(random.uniform(0, 100_000), 2),
            "CC Shared GP": round(random.uniform(0, 50_000), 2),
        })
    return pd.DataFrame(rows)


def make_nacs_df(n_rows):
    rows = []
    for _ in range(n_rows):
        rows.append({
            "Employee ID": rand_id("E", 6),
            "Guarantee Amount": round(random.uniform(1000, 10000), 2),
            "Payroll Currency": rand_currency(),
            "Quarter": random.choice(["Q1", "Q2", "Q3", "Q4"]),
        })
    return pd.DataFrame(rows)


def make_ytd_df(n_rows):
    rows = []
    for _ in range(n_rows):
        rows.append({
            "Employee ID": rand_id("E", 6),
            "Q1 Payment": round(random.uniform(0, 5000), 2),
            "Q2 Payment": round(random.uniform(0, 5000), 2),
            "Q3 Payment": round(random.uniform(0, 5000), 2),
            "Currency": rand_currency(),
        })
    return pd.DataFrame(rows)


def make_bdm_df(n_rows):
    rows = []
    for _ in range(n_rows):
        rows.append({
            "Employee ID": rand_id("B", 5),
            "ShipTo": f"ST-{random.randint(1000, 9999)}",
            "BDM Target Rev": round(random.uniform(50_000, 500_000), 2),
            "BDM Target GP": round(random.uniform(10_000, 150_000), 2),
            "Currency Code": rand_currency(),
            "Division Node": rand_division(),
        })
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def df_to_excel_bytes(df):
    """header=0 format: column names on row 0."""
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    buf.seek(0)
    return buf.read()


def df_to_excel_bytes_header1(df):
    """header=1 format: blank title row at position 0, column names at position 1.
    Required for ytd_payments and nacs_guarantee (see config/sources/excel.yaml)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([""] * len(df.columns))  # dummy title row (position 0, discarded)
    ws.append(list(df.columns))        # actual header (position 1)
    for row in df.itertuples(index=False):
        ws.append(list(row))
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


def fmt(seconds):
    return f"{seconds:.2f}s"


# ------------------------------------------------------------------ #
# Load test runner
# ------------------------------------------------------------------ #

def run_test(n_employees):
    n_bp     = int(n_employees * 1.5)   # BP typically has more rows than employees
    n_sales  = n_employees * 8          # Sales = many transactions per employee
    n_nacs   = max(20, n_employees // 10)
    n_ytd    = n_employees
    n_bdm    = max(20, n_employees // 5)

    print(f"\n{'='*60}")
    print(f"  LOAD TEST: {n_employees} employees | {n_bp} BP rows | {n_sales} sales rows")
    print(f"{'='*60}")

    t0 = time.perf_counter()
    print(f"  Generating data...", end=" ", flush=True)
    emp_bytes   = df_to_excel_bytes(make_employee_df(n_employees))
    bp_bytes    = df_to_excel_bytes(make_bp_df(n_bp))
    sales_bytes = df_to_excel_bytes(make_sales_df(n_sales))
    nacs_bytes  = df_to_excel_bytes_header1(make_nacs_df(n_nacs))
    ytd_bytes   = df_to_excel_bytes_header1(make_ytd_df(n_ytd))
    bdm_bytes   = df_to_excel_bytes(make_bdm_df(n_bdm))
    gen_time = time.perf_counter() - t0

    sizes = {
        "employee": len(emp_bytes),
        "bp":       len(bp_bytes),
        "sales":    len(sales_bytes),
        "nacs":     len(nacs_bytes),
        "ytd":      len(ytd_bytes),
        "bdm":      len(bdm_bytes),
    }
    total_mb = sum(sizes.values()) / 1_048_576
    print(f"done ({fmt(gen_time)}) — total payload {total_mb:.1f} MB")
    for name, sz in sizes.items():
        print(f"    {name}: {sz/1024:.0f} KB")

    # Stage 1: Upload + raw load
    print(f"\n  Stage 1 — Upload & raw load...", end=" ", flush=True)
    t1 = time.perf_counter()
    resp = requests.post(API_BASE, files={
        "employee_file":       ("employee.xlsx",       emp_bytes,   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        "bp_file":             ("bp.xlsx",             bp_bytes,    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        "sales_file":          ("sales.xlsx",          sales_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        "nacs_guarantee_file": ("nacs.xlsx",           nacs_bytes,  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        "ytd_payments_file":   ("ytd.xlsx",            ytd_bytes,   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        "bdm_file":            ("bdm.xlsx",            bdm_bytes,   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    }, timeout=600)
    t_stage1 = time.perf_counter() - t1

    if resp.status_code not in (200, 201):
        print(f"FAILED ({resp.status_code}): {resp.text[:300]}")
        return

    run_id = resp.json().get("run_id")
    print(f"done in {fmt(t_stage1)}  (run_id={run_id})")

    # Stage 2: Canonical
    print(f"  Stage 2 — Canonical processing...", end=" ", flush=True)
    t2 = time.perf_counter()
    resp2 = requests.post(f"{API_BASE}/{run_id}/canonical", timeout=600)
    t_stage2 = time.perf_counter() - t2
    if resp2.status_code not in (200, 201):
        print(f"FAILED ({resp2.status_code}): {resp2.text[:300]}")
        return
    print(f"done in {fmt(t_stage2)}")

    # Stage 3: Calculations
    print(f"  Stage 3 — SIP calculations...", end=" ", flush=True)
    t3 = time.perf_counter()
    resp3 = requests.post(f"{API_BASE}/{run_id}/calculations",
                          json={}, timeout=600)
    t_stage3 = time.perf_counter() - t3
    if resp3.status_code not in (200, 201):
        print(f"FAILED ({resp3.status_code}): {resp3.text[:300]}")
        return
    calc_result = resp3.json()
    print(f"done in {fmt(t_stage3)}")

    total = t_stage1 + t_stage2 + t_stage3
    print(f"\n  RESULTS:")
    print(f"    Stage 1 (upload+raw):   {fmt(t_stage1)}")
    print(f"    Stage 2 (canonical):    {fmt(t_stage2)}")
    print(f"    Stage 3 (calculations): {fmt(t_stage3)}")
    print(f"    TOTAL:                  {fmt(total)}")
    print(f"    Enabled roles:          {calc_result.get('enabled_roles', [])}")
    print(f"    Row counts:             {calc_result.get('role_row_counts', {})}")

    return {
        "n_employees": n_employees,
        "payload_mb": round(total_mb, 1),
        "stage1": round(t_stage1, 2),
        "stage2": round(t_stage2, 2),
        "stage3": round(t_stage3, 2),
        "total": round(total, 2),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=0,
                        help="Single employee count to test (0 = run all sizes)")
    args = parser.parse_args()

    sizes = [args.rows] if args.rows else SIZES

    print("\nSIP Automation — Load Test")
    print(f"Target: {API_BASE}")

    results = []
    for n in sizes:
        r = run_test(n)
        if r:
            results.append(r)

    if len(results) > 1:
        print(f"\n{'='*60}")
        print("  SUMMARY TABLE")
        print(f"{'='*60}")
        print(f"  {'Employees':>10} {'Payload MB':>12} {'Stage1':>8} {'Stage2':>8} {'Stage3':>8} {'Total':>8}")
        for r in results:
            print(f"  {r['n_employees']:>10} {r['payload_mb']:>12.1f} {r['stage1']:>8.2f} {r['stage2']:>8.2f} {r['stage3']:>8.2f} {r['total']:>8.2f}")


if __name__ == "__main__":
    main()
