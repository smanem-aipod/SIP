# SIP Calculation Reference

This is a plain-language map of **every column used**, **why it's used**, and
**every constant/parameter**, walked in calculation order from raw source
files to the final SIP payout number.

Source of truth for this doc:
- `config/calculations/sip_metrics.yaml` — all formulas (SIP 1–59), finance parameters
- `config/calculations/role_mappings.yaml` — which columns/keys each role plugs into those formulas

---

## 1. Source files and the columns pulled from each

| Source file (canonical table) | Column | Used for | Why |
|---|---|---|---|
| `employee` | `employee_id` | Population key, join key everywhere | Uniquely identifies the person the whole row is being calculated for |
| `employee` | `job_profile_for_sip` | Role population filter | Decides which role bucket (Sales Professional / Area Manager / District Manager / CAM / BDM) an employee falls into — each role has totally different grouping rules downstream |
| `employee` | `sip_eligible_date` | `months_eligible_computed` (SIP 1) | How many months this year the person was actually SIP-eligible (new hires / leavers get prorated, not a full year) |
| `employee` | `annual_salary_payroll_currency` | `annual_sip_target_pc`, `ytd_salary_pc` (SIP 2, 4) | Base for computing both the SIP $ target and YTD salary, in the employee's own payroll currency |
| `employee` | `annual_salary_usd` | `ytd_salary_usd` (SIP 5) | Same as above, but in USD — used for cross-currency reporting/caps |
| `employee` | `sip_target_pct` | `annual_sip_target_pc` (SIP 2 intermediate), `max_sip_pc` Q4 rule | The person's target incentive as a % of salary (e.g. 15%, 20%) — set by HR/Comp per role/level |
| `employee` | `payroll_currency` | `payroll_fx_rate` lookup | Which currency this person is paid in — needed to convert PC ↔ USD |
| `bp` (Business Plan / targets file) | `fy26_rev` | `bp_sales_2026_direct` (SIP 9 base) | This year's revenue **target**, before any adjustments |
| `bp` | `fy26_gp` | `bp_gp_dop_2026_direct` (SIP 9 base for GP) | This year's GP/DOP **target** |
| `bp` | `employee_id` / `employee_id_only_for_shared` / `sales_group_description` / `sales_office_description` / `cam_id` / `bdm_id` | Grouping & join keys (role-specific — see Section 2) | Determines *whose* target a given BP row rolls up into |
| `sales` (actuals file) | `cc_direct_rev`, `ytd_rev` | `ytd_actual_revenue_computed` (SIP 11) | Actual revenue booked so far this year — the numerator of "did they hit target" |
| `sales` | `cc_direct_gp`, `ytd_gp` | `ytd_actual_gp_dop_computed` (SIP 12) | Actual GP/margin booked so far this year |
| `sales` | `cc_shared_rev` / `cc_shared_gp` | `shared_accounts_revenue` / `shared_accounts_gp` (SIP 13, 14) | For Sales Professionals only — their cut of accounts they co-sell with a teammate. AM/DM/CAM/BDM don't use this (hardcoded to 0) |
| `sales` | `gp_flag` | Revenue filter (`gp_flag = OK`) | Excludes bad/error sales rows from revenue counting. Notably **not** applied to GP — GP counts every row |
| `sales` | `division_node` | CAM's `group_by`/weighting key | CAM actuals are computed per product division, then weighted by the CAM's ownership share of that division, then summed |
| `bdm` (canonical, pre-calculated) | `revenue`, `gp` | BDM actuals (no SIP # — reads pre-built numbers) | BDM's revenue/GP already has allocation/sharing logic applied upstream, so the engine just sums it as-is |
| `bdm` | `bdm_id` | Join key | Matches `employee.employee_id` → `bdm.bdm_id` |
| `fx_rates` | `currency_code`, `rate_value` | `payroll_fx_rate` lookup | Converts every payroll-currency ($ target/salary) figure into USD and vice versa |
| `nacs_guarantee` | `calculated_sip_usd` | `guarantee_sip_q2` (SIP 56/57) | Some employees have a **guaranteed minimum SIP** (NACS = new-account/contract guarantee) regardless of performance |
| `nacs_guarantee` | `guarantee_eligibility_fy26_months` | `nacs_region_currency` (SIP 56) | How many months of that guarantee apply this year |
| `ytd_payments` | `sip_payroll_currency` | `q1_payment_payroll_currency` (SIP 51) | What's already been paid out in Q1 — needed to compute overpayment/true-up later |
| `precompute_exceptions` (admin override file) | `months_eligible_override` | Overrides SIP 1 if HR manually corrects eligible months | Manual finance correction always wins over the computed value |
| `precompute_exceptions` | `bp_rev_adjustments`, `bp_gp_adjustments` | Added to BP target (SIP 9 final) | Manual target corrections (e.g. mid-year territory change) |
| `precompute_exceptions` | `bp_sga` | Subtracted from GP target before adjustments | SG&A (overhead cost) allocation against the target |
| `precompute_exceptions` | `rev_adjustments`, `gp_adjustments` | Added to final actuals (SIP 15/16/18/19) | Manual actuals corrections (e.g. a booking error fix) |
| `precompute_exceptions` | `ytd_sga` | Subtracted from actual GP | SG&A allocation against actuals |
| `precompute_exceptions` | `ytd_actual_revenue_override`, `ytd_actual_gp_dop_override` | Full override of computed actuals | Used when finance needs to hand-enter a number instead of trusting the raw sales feed |

---

## 2. Role-specific wiring (what changes per role)

The math is identical for every role. Only the **grouping key** and **which
dataset the "actuals" come from** change. This lives in `role_mappings.yaml`.

| Role | Population filter (`job_profile_for_sip`) | BP target grouped by | Actuals dataset & grouped by | Shared-account cut? |
|---|---|---|---|---|
| Sales Professional | `= "Sales Professional"` | `employee_id_only_for_shared` | `sales`, by `employee_id` | Yes (`cc_shared_rev`/`cc_shared_gp`) |
| Area Manager | `= "Area Manager"` | `sales_group_description` | `sales`, by `sales_group_description` | No (constant 0) |
| District Manager | `= "District Manager"` | `sales_office_description` | `sales`, by `sales_office_description` | No (constant 0) |
| CAM | `= "CAM"` | `cam_id` | `sales`, weighted-allocation by `division_node`, filtered `gp_flag_cam = OK` | No (constant 0) |
| BDM | `= "BDM"` | `bdm_id` | `bdm` (pre-calculated), by `bdm_id` | No (constant 0) |

---

## 3. Constants / finance-controlled parameters

All of these live in `parameters:` at the top of `sip_metrics.yaml`. They are
the knobs Finance can turn without touching any formula.

| Parameter | Value | Used in | Meaning |
|---|---|---|---|
| `fiscal_year` | 2026 | Which year's BP/sales columns are read | Selects `fy26_rev`/`fy26_gp` etc. |
| `quarter` | `"Q2"` | Every quarter-phased formula (target phasing, max SIP, payment lookups) | Which quarter's rules currently apply — this single switch changes target %, max SIP multiplier, and which quarter's payment placeholder is active |
| `annual_month_count` | 12 | Proration (SIP 2, 4, 5) | Denominator for "months eligible ÷ this" proration math |
| `target_q2_multiplier` | 0.50 | Target phasing (SIP 9/10) | Only 50% of the annual target counts as the Q2 target |
| `target_q3_multiplier` | 0.75 | Target phasing | 75% of annual target counts by Q3 |
| `target_q4_multiplier` | 1.00 | Target phasing | Full annual target counts by Q4 |
| `q2_max_sip_multiplier` | 0.50 | Max SIP cap (SIP 6) | In Q2, you can earn at most 50% of your annual target incentive |
| `q3_max_sip_multiplier` | 0.75 | Max SIP cap | In Q3, cap rises to 75% |
| `q4_high_target_multiplier` | 3.00 | Max SIP cap (Q4, high-target employees) | Employees with a normal-sized target get a generous 3x cap in Q4 (uncapped upside) |
| `q4_high_target_threshold` | 0.33 | Decides which Q4 cap rule applies | If `sip_target_pct` > 33%, use the 3x cap; otherwise cap at YTD salary instead (protects against tiny-target employees gaming an uncapped multiplier) |
| `revenue_incentive_weight` | 0.65 | Commission rate numerators | 65% of the incentive $ pool is tied to revenue performance |
| `gp_incentive_weight` | 0.35 | Commission rate numerators | 35% of the incentive $ pool is tied to GP/margin performance |
| `base_band_weight` | 0.25 | Base commission rate | 25% of each incentive pool is paid out across the 0–90% "base" band |
| `surge_band_weight` | 0.75 | Surge commission rate | 75% of each incentive pool is paid out across the 90–100% "surge" band — surge is intentionally richer per-point than base |
| `base_achievement_band` | 0.90 | Base rate denominator | Base commission rate is calculated as if the band spans 0–90% of target |
| `surge_achievement_band` | 0.10 | Surge rate denominator | Surge band spans exactly 10 percentage points (90%→100%) |
| `special_surge_revenue_cap` | 0.05 | Caps the special-surge revenue rate | Prevents the >100% "special surge" revenue rate from exceeding 5% |
| `special_surge_gp_floor` | 0.0035 | Floors the special-surge GP rate | Special-surge GP rate can't go below 0.35% |
| `special_surge_gp_cap` | 0.09 | Caps the special-surge GP rate | Special-surge GP rate can't exceed 9% |
| `base_commission_threshold` | 0.90 | Splits base vs. surge/special-surge logic everywhere | The 90% line — below it you're purely in "base", above it different candidate formulas kick in |
| `surge_commission_cap` | 0.10 | Clamps surge % (SIP 31/32) | Surge-eligible percentage can never exceed 10 points, no matter how far over 90% someone is |
| `special_surge_threshold` | 1.00 | Splits surge vs. special-surge | The 100% line — full target attainment |

### Static reference values (`static_reference_data`)
| Key | Value | Used for |
|---|---|---|
| `flags.ok` | `"OK"` | `sip_cap_flag` result when under cap |
| `flags.crossed_cap` | `"Crossed CAP"` | `sip_cap_flag` result when earned SIP hit the ceiling |
| `placeholders.unallocated_cost_weight` | 0 | Multiplier for unallocated cost (currently inactive — placeholder for future finance rule) |
| `placeholders.bp_sales_2026_shared`, `bp_gp_2026_shared` | 0 | Reserved for a future "shared BP target" feature — not used in current formulas |
| `placeholders.q2_payment_payroll_currency`, `q3_payment_payroll_currency`, `q2_payment_region_currency`, `q3_payment_region_currency`, `crossed_gtee_payment_region_currency` | 0 | Payment-tracking placeholders — real values will come from a future payroll integration; currently always 0 |

---

## 4. Full calculation chain (in order, to final SIP)

Each step shows: **what it computes → from what → why**.

### Stage A — Eligibility & Target ($ base)
1. **`months_eligible`** (SIP 1) = months between `sip_eligible_date` and quarter-end (or admin override). *Why:* mid-year joiners/leavers shouldn't get a full year's target or salary.
2. **`annual_sip_target_pc`** = `annual_salary_payroll_currency` × `sip_target_pct`. *Why:* converts the person's target % into an actual $ number.
3. **`sip_target_pc`** (SIP 2) = `annual_sip_target_pc` prorated by `months_eligible ÷ 12`. *Why:* partial-year target.
4. **`sip_target_usd`** (SIP 3) = `sip_target_pc ÷ payroll_fx_rate`. *Why:* USD version for cross-region reporting/caps.
5. **`ytd_salary_pc`** (SIP 4) / **`ytd_salary_usd`** (SIP 5) = salary prorated the same way. *Why:* used later as the Q4 fallback cap for low-target employees.

### Stage B — BP Target (revenue & GP)
6. **`bp_sales_2026_direct`** / **`bp_gp_dop_2026_direct`** (SIP 9/10 base) = `SUM(fy26_rev)` / `SUM(fy26_gp)` from `bp`, grouped per role's key. *Why:* raw target before any corrections.
7. **`bp_gp_dop_2026_direct_after_sga`** = target GP − `bp_sga` (admin exception). *Why:* charges overhead against the target before finance adjustments are added.
8. **`bp_sales_2026`** / **`bp_gp_dop_2026`** = above + `bp_rev_adjustments` / `bp_gp_adjustments`. *Why:* final, finance-corrected target.
9. **`q2/q3/q4_target_revenue`** and **`..._gp_dop`** = target × the quarter multiplier (0.50/0.75/1.00).
10. **`target_region_currency_revenue`** (SIP 9) / **`target_region_currency_gp_dop`** (SIP 10) = whichever quarter's phased value matches `parameters.quarter`. *Why:* single "the target that counts right now" number.

### Stage C — Actuals (revenue & GP)
11. **`ytd_actual_revenue_computed`** (SIP 11) = `SUM(cc_direct_rev)` from `sales` where `gp_flag = OK` (CAM: weighted by division share). *Why:* actual revenue booked, direct accounts only, excluding bad rows.
12. **`ytd_actual_gp_dop_computed`** (SIP 12) = `SUM(cc_direct_gp)`, no `gp_flag` filter. *Why:* GP counts every row, even ones flagged out of revenue.
13. **`ytd_actual_revenue`** / **`ytd_actual_gp_dop`** = computed value, unless `precompute_exceptions` has an override — then the override wins.
14. **`ytd_actual_gp_dop_after_sga`** = actual GP − `ytd_sga`. *Why:* overhead charge against actuals too, for symmetry with the target side.
15. **`shared_accounts_revenue`** (SIP 13) / **`shared_accounts_gp`** (SIP 14) = SP-only shared-account cut, 0 for other roles.
16. **`final_ytd_actual_revenue`** (SIP 18) = `ytd_actual_revenue + shared_accounts_revenue + rev_adjustments`. *Why:* the true "what actually counts" revenue figure — direct + shared + manual fix.
17. **`ytd_gp_before_unallocated_cost`** = `ytd_actual_gp_dop_after_sga + shared_accounts_gp + gp_adjustments`.
18. **`unallocated_cost`** (SIP 17) = `(final revenue − GP before unallocated cost) × unallocated_cost_weight` (currently weight = 0, so this is always 0 today — reserved for future use).
19. **`final_ytd_actual_gp_dop`** (SIP 19) = `ytd_gp_before_unallocated_cost − unallocated_cost`. *Why:* the true "what actually counts" GP figure.

### Stage D — Attainment %
20. **`bp_met_revenue_pct`** (SIP 20) = `final_ytd_actual_revenue ÷ target_region_currency_revenue`. *Why:* the single number that drives every commission band decision — "how much of target did they hit."
21. **`bp_met_gp_pct`** (SIP 21) = same, for GP.

### Stage E — Commission rates (the $-per-% band prices)
22. **`phased_sip_target_usd`** = whichever quarter's phased SIP-target-USD applies.
23. **Base rate** (revenue & GP) = `(phased_sip_target_usd × incentive_weight × base_band_weight) ÷ (target × base_achievement_band)`. *Why:* spreads 25% of the incentive pool evenly across the 0–90% band, expressed as $ per 1% of target.
24. **Surge rate** (revenue & GP) = `(phased_sip_target_usd × incentive_weight × surge_band_weight) ÷ (target × surge_achievement_band)`. *Why:* spreads 75% of the incentive pool across just the 10-point 90–100% band — much richer per point than base, rewarding closing the gap to 100%.
25. **Special surge rate** = same as surge rate, but clamped to `[special_surge_gp_floor, special_surge_gp_cap]` for GP or capped at `special_surge_revenue_cap` for revenue. *Why:* the >100% band uses a bounded rate so extreme overachievement doesn't produce runaway payouts.

### Stage F — Commission $ earned, per band
26. **`base_commission_revenue`** (SIP 28) / **`base_commission_gp`** (SIP 29) = if attainment ≤ 90%: `actual × base_rate`; else capped at `target × 90% × base_rate`. *Why:* base commission is either "pay on what they actually did" (if under 90%) or "pay the full base band" (if they're past it, since the base tier is already maxed).
27. **`surge_bp_met_revenue_pct`** (SIP 31) / **`...gp_pct`** (SIP 32) = attainment % − 90%, clamped to `[0, 10%]` (`surge_commission_cap`). *Why:* isolates just the portion of attainment that falls in the surge band.
28. **`surge_commission_revenue`** (SIP 33) / **`...gp`** (SIP 34) = `target × surge_rate × eligible_surge_pct`.
29. **`special_surge_bp_met_revenue_pct`** (SIP 36) / **`...gp_pct`** (SIP 37) = attainment % − 100%, floored at 0. *Why:* isolates only the overachievement beyond full target.
30. **`special_surge_commission_revenue`** (SIP 38) / **`...gp`** (SIP 39) = `target × eligible_special_surge_pct × special_surge_rate`.

### Stage G — Total SIP earned & cap
31. **`sip_earned_revenue`** (SIP 41) = base + surge + special-surge (revenue side). **`sip_earned_gp`** (SIP 42) = same for GP.
32. **`candidate_ytd_sip_earned`** = `sip_earned_revenue + sip_earned_gp`. *Why:* combines the 65%-weighted revenue outcome and 35%-weighted GP outcome into one number.
33. **`max_sip_pc`** (SIP 6) — quarter-dependent ceiling:
    - Q2 → `sip_target_pc × 0.50`
    - Q3 → `sip_target_pc × 0.75`
    - Q4, target% > 33% → `sip_target_pc × 3.00` (generous, effectively uncapped for normal targets)
    - Q4, target% ≤ 33% → `ytd_salary_pc` (protects tiny-target employees from an abusive 3x multiplier)
34. **`max_sip_usd`** (SIP 7) = `max_sip_pc ÷ payroll_fx_rate`.
35. **`ytd_sip_earned`** (SIP 43) = `MIN(candidate_ytd_sip_earned, max_sip_usd)`. **This is the final SIP number.** *Why:* no matter how well someone overachieves, payout can never exceed the cap set for the current quarter/target size.
36. **`sip_cap_flag`** (SIP 45) = `"OK"` if `months_eligible = 0` or `ytd_sip_earned < max_sip_usd`; otherwise `"Crossed CAP"`. *Why:* tells finance/the employee whether they hit the ceiling.

### Stage H — Payroll-currency conversion, guarantees, and true-up
37. **`ytd_sip_earned_payroll_currency`** (SIP 44) = `ytd_sip_earned × payroll_fx_rate`.
38. **`guarantee_sip_q2`** = looked up from `nacs_guarantee.calculated_sip_usd` — a contractual minimum some employees have regardless of performance.
39. **`overpayment`** (SIP 54) = compares `ytd_sip_earned` against what's already been paid (`q1/q2/q3_payment_region_currency`) plus any guarantee already paid out. *Why:* if prior quarterly payments already exceeded what's now earned YTD, this is the clawback/true-up amount.
40. **`overpayment_payroll_currency`** (SIP 55) = `overpayment × payroll_fx_rate`.
41. **`nacs_region_currency`** (SIP 56) → **`nacs_payroll_currency`** (SIP 58) → **`nacs_usd_cc`** (SIP 59) = guarantee-vs-earned reconciliation, converted across currencies for reporting.

---

## 5. One-sentence summary of the whole pipeline

```
Target ($ from BP)  →  Actual ($ from sales, + shared accounts, + admin fixes)
        ↓                              ↓
        └────────── % Attainment ──────┘
                       ↓
      Base (0–90%) + Surge (90–100%) + Special Surge (100%+)
         each band priced from target × incentive weights
                       ↓
         Revenue-side SIP + GP-side SIP (65/35 weighted)
                       ↓
              MIN(that, Max SIP cap for this quarter)
                       ↓
                 = YTD SIP Earned  (final number)
                       ↓
      minus what's already been paid  =  Overpayment / true-up
```
