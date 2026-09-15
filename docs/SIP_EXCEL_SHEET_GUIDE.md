# SIP Workbook Sheet Guide — `SIP_ FY26_ NA_CS_Q2.xlsb`

Plain-language guide to **every sheet** in the workbook: what it is, why it
exists, what columns it has, and — for the sheets that matter to the
calculation — the **actual Excel formulas** (pulled live via Excel COM, not
guessed) showing exactly which other sheet each column depends on.

---

## Group 1 — Core data feeds (map directly to the app's 5 input files)

### `HR`
**What it is:** The employee master list — one row per person. This is the
source for the app's `employee` canonical table.

| Column | Type | Notes |
|---|---|---|
| Employee ID | typed | Primary key for everything |
| Preferred Name | typed | Display name |
| Sales office Description | **formula** | `=VLOOKUP([Employee ID], BP, MATCH(...))` — pulled from **`BP File`**, not stored natively in HR |
| Sales Group Description | **formula** | Same pattern, from **`BP File`** |
| Job Profile | typed | Raw HRIS job title |
| Job Profile for SIP | **formula** | `=VLOOKUP([Employee ID], BP[...Role Type], 3, 0)` — pulled from **`BP File`'s "Role Type"** column, not from HR's own Job Profile. **This is the actual field the app reads to bucket someone into a role.** |
| Country, Region, BU | typed | Org hierarchy |
| Active (Yes/No) | typed | |
| Annual Salary (Payroll currency) | typed | |
| Annual Salary (USD) | **formula** | `=[Salary PC] / VLOOKUP([Payroll Currency], FX!C:D, 2, 0)` — converts using **`FX`** sheet |
| SIP Target % | typed | The % of salary this person's incentive target is based on |
| Local/Global Cost Center | typed | |
| Payroll Currency | typed | Drives the FX lookup above |
| Hire Date / Movement date / Termination date | typed | |
| SIP Eligible date | **formula** | `=IF(Active="Yes", Termination date OR Movement date OR Hire Date, " ")` — feeds the app's `months_eligible` calculation |
| SIP Team Comments, Regional FP&A Comments | typed | Free text |
| check with BP | **formula** | `=VLOOKUP([Employee ID], BP[Employee number], 1, 0)` — validation: does this person exist in BP File? |
| Status | typed | |
| Seller ID Check | **formula** | Cross-checks against `Seller vs Emp` sheet |

**Depends on:** `BP File` (office/group/role type), `FX` (currency conversion), `Seller vs Emp` (validation).

---

### `BP File`
**What it is:** The raw **target-setting file** — the source of truth for
revenue/GP targets, before anything gets rolled up by role. Maps to the app's
`bp` canonical table. 323 rows, all typed/pasted values (this is itself an
export from a planning tool, not a formula-driven sheet).

| Column | Meaning |
|---|---|
| Reporting line | Business line code (e.g. `NA_CS`) |
| Sales District ID / Desc | District identifiers |
| Sales Office ID | Office code |
| DM Name | District Manager's name |
| Sales Area/Group ID | Group/area code |
| AM Name | Area Manager's name |
| Seller # | The employee ID who owns this target row |
| Emp # (only for shared) | If this row is a **shared account**, whose employee ID gets partial credit |
| Currency code | Currency the FY26 Rev/GP figures are in |
| Seller Desc | Seller's display name |
| FY26 Rev, FY26 GP | **The target numbers themselves** — this is `fy26_rev`/`fy26_gp` in the app |
| Sales Office Description, Sales Group Description | Human-readable office/group names (these get borrowed by `HR`) |
| Comments, If any | Free text |

Rows 254-306+ of this sheet are a **separate block used specifically for CAM/BDM targets** — several formulas elsewhere (`FY26 BP & Actuals`, `CAM Summary`) reference `'BP File'!G254:G306` explicitly, meaning CAM/BDM targets live in a different row range of the same sheet than the DM/AM/SP targets.

**Depended on by:** `HR`, `FY26 BP & Actuals`, `CAM Summary`, `DM`.

---

### `Tableau YTD 26 Actual`
**What it is:** The **giant raw actuals feed** — 437,928 rows, one row per
sales transaction/line-item, exported from Tableau. This is where the app's
`sales` canonical table comes from. Nothing here is a formula — it's a raw
data dump.

Key columns (by letter, since formulas elsewhere reference them by letter):

| Column | Letter | Meaning |
|---|---|---|
| Reporting_Line, REGION, BU | A-C | Org hierarchy |
| SalesDistrictDesc | D | |
| salesofficedesc | **E** | Office name — DM's actuals SUMIFS key |
| salesgroupdesc | **F** | Group name — Area Manager's actuals SUMIFS key |
| ProfitCenterSBUDesc | **G** | Product/SBU line — BDM's actuals SUMIFS key |
| FISCAL PERIOD | H | e.g. `2026003` = FY2026 period 3 |
| ShipTo | **I** | Customer account ID — BDM's actuals SUMIFS key |
| shiptodesc, shiptocity | J-K | Customer name/city |
| EMP ID | **O** | Employee ID — Sales Professional's actuals SUMIFS key |
| Material, MaterialDesc | P-Q | Product sold |
| DivisionNode, DivisionNodeDesc, Division | U-W | Product division — **CAM's weighting key** |
| SHARED_ACC_FLAG, Split/Share | Z-AA | Marks shared accounts and the split % |
| BP_Direct_Rev, BP_Direct_GP, BP_Shared_Rev, BP_Shared_GP | AB-AE | Line-level target figures (rarely used — role rollups mostly use `BP File`/`DM` instead) |
| $CC_Direct_Rev | **AH** | **Direct revenue, constant currency** — this is `cc_direct_rev` in the app |
| $CC_Direct_GP | **AI** | `cc_direct_gp` |
| $CC_Shared_Rev | **AJ** | Shared-account revenue — `cc_shared_rev`, **Sales-Professional-only** |
| $CC_Shared_GP | **AK** | `cc_shared_gp` |
| YTD REV | **AL** | Total YTD revenue (direct+shared combined) — used by Area Manager/DM/BDM, who don't split direct vs shared |
| YTD GP | **AM** | Total YTD GP |
| exception, Low Margin Exceptions, SA Materials, Operational SBU's | AR-AS | Data-quality/exclusion tags (low-margin material filtering — see `Low margin Table`) |
| GP Flag | **AU** | `"ok"` / other — **this is the `gp_flag` column the app filters revenue on** |

**This one sheet is the ultimate source for almost every role's "actuals" number** — traced through `SUMIFS` formulas in `FY26 BP & Actuals`, `DM`, `BDM`, and directly for Sales Professional/Area Manager.

---

### `BDM ` (note trailing space in the sheet name)
**What it is:** Line-item-level actuals for BDM employees, one row per
customer/material combination. This is the pre-calculated `bdm` canonical
table the app reads directly (no further math needed downstream).

| Column | Meaning |
|---|---|
| EMP ID, EMP Name | The BDM |
| Profit Center SBU | Product line filter |
| Shipto, Shipto Desc, ShipTo City | Customer |
| Material Number, Material Name | Product |
| Rev | **formula:** `=SUMIFS('Tableau'!AL:AL, I:I=Shipto, G:G=SBU, AU:AU="ok")` — pulled straight from the raw Tableau feed, filtered to this customer + SBU + valid rows |
| GP | **formula:** same pattern using `AM:AM`, **no `"ok"` filter** |
| (blank cols 11) | | |
| SBU Included in formula | typed note | Confirms which SBU rows are counted |

**Depends on:** `Tableau YTD 26 Actual` directly.

---

### `NACS-Guarantee SIP`
**What it is:** Tracks employees who have a **contractual guaranteed minimum
SIP** (NACS = New Account/Contract Sales guarantee), independent of
performance. Maps to the app's `nacs_guarantee` file.

| Column | Meaning |
|---|---|
| Rank for sorting | Manual sort order |
| Employee ID, Full Name, Job Profile, Region, Department, Country | Identity |
| Employee Type, Time Type | Full-time/Regular etc. |
| Cost Center ID/name | |
| Active (Yes/No) | |
| Total Base Pay (Payroll Currency) | Salary basis for the guarantee |
| Payroll Currency | |
| SIP Target Percent | |
| SIP Target | **formula:** `=[Base Pay] × [SIP Target %]` |
| Hire Date | |
| Guarantee SIP Eligibility (Months) | **formula:** a long `IFS` ladder comparing hire date against fixed cutoff dates, tiering how many months of guarantee apply based on how recently they were hired |
| FY25 Q1/Q2/... | **formula:** guarantee $ amount = `SIP Target × (months applicable ÷ 12)`-style proration per quarter |

**Why it exists:** protects new hires (or specific negotiated roles) from earning $0 if their territory/ramp-up period means they can't hit normal targets yet.

---

### `YTD Payments`
**What it is:** A record of **what's already been paid out**, quarter by
quarter (the sheet literally starts with a "Q1" label — implying Q2/Q3
versions exist elsewhere or get added as the year progresses). Maps to the
app's `ytd_payments` file — this is the input to the "overpayment/true-up"
calculation (SIP 54).

| Column | Meaning |
|---|---|
| Country, Bus. Unit | |
| Solenis | (mostly blank in sample — internal grouping) |
| Name, Position | Who was paid |
| Currency | |
| Payroll Currency | The $ amount actually paid, in local currency |
| SIP in USD | Same amount converted to USD |
| Crossed Gtee | Flag/amount — whether this payment already crossed into guarantee territory |

All typed values here (this is a payroll extract, not calculated).

---

### `FX`
**What it is:** Currency conversion rate table. Every payroll-currency ↔ USD
conversion anywhere in the workbook (and in the app's `payroll_fx_rate`
lookup) traces back here.

| Column | Meaning |
|---|---|
| Region, Country | |
| vs USD | |
| $ CC / € CC | Constant-currency USD/EUR rates |
| AVG EUR YTD Q1/Q2/Q3, AVG EUR FY2020 | Rolling average EUR rates by quarter |
| AVG USD YTD Q1/Q2/Q3, AVG USD FY2020 | Rolling average USD rates by quarter |
| (dated columns further right) | Monthly exchange-rate history by currency |

All typed/pasted rates — this is a reference table, not derived from other sheets.

---

## Group 2 — Role rollup sheets (the "did they hit target" math per role)

These are where finance manually computes what the app's engine computes
automatically. Each is a per-role slice of the same target-vs-actual logic.

### `DM` (District Manager)
| Column | Meaning / Formula |
|---|---|
| EMP ID, District manager Name, Sales Office | Identity |
| BP Rev | `=SUMIFS('BP File'!M:M, 'BP File'!O:O=[Sales Office])` — target revenue for this office, from **BP File** |
| BP GP | Same, column N |
| BP SG&A | typed (manual overhead allocation) |
| BP DOP | `=[BP GP] - [BP SG&A]` |
| YTD 2026 Rev | `=SUMIFS('Tableau'!AL:AL, E:E=[Sales Office], AU:AU="ok")` — actual revenue from **Tableau**, filtered to `"ok"` rows |
| YTD 2026 GP | Same, column AM, **no "ok" filter** |
| YTD 2026 SGA | typed |
| YTD 2026 DOP | `=[YTD GP] - [YTD SGA]` |
| Rev % | `=[YTD Rev] / [BP Rev]` — this is the DM's attainment % |
| GP% | `=[YTD DOP] / [BP DOP]` |
| Comments2 | free text |

### `BDM Summary`
| Column | Meaning / Formula |
|---|---|
| EMP ID, BDM, Reporting to | Identity |
| Rev BP | `=VLOOKUP([BDM], 'BP File'!C290:H301, 5, 0)` — target pulled from the **CAM/BDM-specific row block** of BP File |
| GP BP | Same, column 6 |
| YTD Q2 Rev | `=SUMIFS('BDM '!I:I, 'BDM '!A:A=[EMP ID])` — sums the line-item actuals from the **`BDM `** sheet |
| YTD Q2 GP | Same, column J |
| Rev% | `=[YTD Q2 Rev] / [Rev BP]` |
| GP% | `=[YTD Q2 GP] / [GP BP]` |
| Comments, if any | free text |

### `CAM Summary`
This one's the most involved — CAM math needs a **weighted allocation**
because one CAM only owns a *slice* of a division's business.

| Column | Meaning / Formula |
|---|---|
| EMP ID, CAM | Identity |
| Comments | `=VLOOKUP([EMP ID], HR[...], 22, 0)` — pulled from HR |
| BP Rev | `=SUMIFS('BP File'!G254:G287, C254:C287=[CAM])` — target from BP File's CAM row-block |
| BP GP | Same, column H |
| YTD Q2 2026 Rev | `=SUMIFS($P25:$P55, $D25:$D55=CAM) + SUMIFS($Q25:$Q55, $F25:$F55=CAM) + SUMIFS($R25:$R55, $H25:$H55=CAM)` — sums **this same sheet's own internal working table** (rows 25-55, described below) across up to 3 different "CAM slot" columns |
| YTD Q2 2026 GP | Same pattern, columns S/T/U |
| Rev % | `=[YTD Rev] / [BP Rev]` |
| GP% | `=[YTD GP] / [BP GP]` |

**The hidden working table** (rows 23-55 of this same sheet) is the actual
weighted-allocation engine:
- `Div Node`, `Div Node Desc` — each product division
- `CAM 1`, `CAM 1%`, `CAM 2`, `CAM 2%`, `CAM 3`, `CAM 3%` — up to 3 CAMs can share a division, each with their ownership %
- `REVENUE`, `GP` — total actual revenue/GP for that division
- `CAM 1`/`CAM 2`/`CAM 3` (under Rev and GP) — `= REVENUE × CAM_n%` — **this is the literal weighted-allocation math**, one column per possible CAM per division

This matches the app's `weighted_allocation_sum` operation for the CAM role exactly — division-level actuals × ownership share, summed across every division a CAM touches.

---

## Group 3 — Manual adjustment / exception tracking

### `Exceptions`
**What it is:** Where RSDs/DMs request manual corrections to target or
actuals — the human version of the app's `precompute_exceptions` file.

| Column | Meaning |
|---|---|
| Role, Sales District, Sales Office, Sales Group | Which employee/group this exception applies to |
| BP FY26 Rev, BP FY26 GP | Target-side adjustment amount |
| YTD FY26 Rev, YTD FY26 GP | Actuals-side adjustment amount — **`FY26 BP & Actuals`'s "Rev/GP Adjustments" columns pull directly from these two columns** |
| Comments from RSDs/DMs | Why the exception is being requested |
| Manual Adj/Exception | The adjustment value/description |
| Approval | Sign-off status |
| Comments for Manual Adj | Additional notes |

**Data-quality flag:** rows 2-3 of this sheet currently contain `=#REF!+#REF!` broken formulas (the referenced cells/sheet got deleted at some point) — those two exception rows are silently returning garbage numbers (`-2146826265`) instead of real adjustment values. Worth flagging to finance since `FY26 BP & Actuals` will pull that broken number for any employee matching those rows.

### `Rate Factors`
**What it is:** The commission-rate lookup table — the manual version of the
`base_band_weight`/`surge_band_weight`/etc. parameters in `sip_metrics.yaml`.

| Section | Columns |
|---|---|
| % of Target Payment | Base %, Flex % — mirrors `base_band_weight`(0.25)/`surge_band_weight`(0.75) |
| Up to % of Sales Target | Base %, Flex % |
| Up to % of GP Target | Base %, Flex % |
| Sales Surge Min/Max % | Mix, Max — mirrors `surge_achievement_band`/`surge_commission_cap` |
| GP/DOP Surge Min/Max % | Mix, Max |
| Surge | Factor, "to Flex target" |

This sheet has 18 numbered columns across the top (1-18) — likely a lookup-by-band-number table rather than a flat list, matching the tiered base/surge/special-surge structure in the app.

---

## Group 4 — Scratch / ad-hoc working tabs (not part of the standard pipeline)

These are analyst working areas — useful for finance's own investigation, but
**not** inputs the app ingests:

| Sheet | Rows | What it's for |
|---|---|---|
| `SIP Calculations` | 14 | Top-level scratch totals block, no clean header |
| `Observations` | 49 | Open questions log (e.g. "Do we need to consider Unallocated Cost?") |
| `Special Cases` | 426 | List of districts/offices/groups flagged for manual review |
| `Cascades Claim` | 42 | A specific customer ("Cascades") dispute/claim investigation |
| `CS-IS District` | 48 | Sharing % / target breakdown for a specific district cross-section (columns: Position, salesofficedesc, salesgroupdesc, ShipTo, % Sharing, Target Rev, Target GP) |
| `Joe, Hany, Jim, Rory, Travis` | 225 | Named-employee investigation — Sharing %, Revenue, GP, Tag, per shipto/material |
| `Seller vs Emp` | 288 | Cross-check between `BP File` sellers and `HR` employees — data-quality reconciliation |
| `Low margin Table` / `CAM Low margin Table` | 10,830 / 10,968 | Rules for excluding low-margin materials (<10% GP) from counting toward targets — referenced by the `Low Margin Exceptions`/`GP Flag` logic in `Tableau YTD 26 Actual` |
| `Amy Calc's`, `Amy's Pivot`, `Amy's Data` | 18 / 66 / 1,382 | One analyst's (Amy) personal BDM calculation workspace and pivot |
| `FY25 - Top Screen MF Exclusion` | 34 | Prior-year material-exclusion reference list |
| `Exclusions from Low Margin` | 19 | Master exclusion lists: PAM materials, non-operational SBUs, distributor list |

---

## Overall dependency map

```
FX ──────────────────────► HR (salary USD conversion)
BP File ─────────────────► HR (office/group/role), FY26 BP & Actuals, DM, CAM Summary
Tableau YTD 26 Actual ───► FY26 BP & Actuals, DM, BDM, CAM Summary (via Low Margin filters)
DM, BDM Summary, CAM Summary, BDM ──► FY26 BP & Actuals (role-specific actuals)
Exceptions ──────────────► FY26 BP & Actuals (manual adjustments)
NACS-Guarantee SIP ──────► guarantee floor (used downstream, not in this workbook's final calc)
YTD Payments ────────────► overpayment/true-up calc (used downstream)
HR ──────────────────────► CAM Summary (comments lookup)
```

**In one sentence:** `HR`, `BP File`, and `Tableau YTD 26 Actual` are the three
foundational sheets everything else either reads from or rolls up from role by
role — `DM`/`BDM Summary`/`CAM Summary`/`BDM ` are per-role summaries of the
same actuals feed, `FY26 BP & Actuals` stitches all 5 roles into one table,
`Exceptions`/`Rate Factors`/`FX`/`NACS-Guarantee SIP`/`YTD Payments` are
supporting reference/override tables, and everything else is analyst scratch
work.
