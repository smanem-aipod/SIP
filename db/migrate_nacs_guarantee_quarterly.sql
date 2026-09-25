-- Run this against the testing team's Postgres database
-- (the same one their local sip-automation app connects to)
-- to bring canonical.nacs_guarantee up to date with the new quarter-aware columns.

ALTER TABLE canonical.nacs_guarantee
    ADD COLUMN IF NOT EXISTS calculated_sip_usd_q1 numeric(20,8),
    ADD COLUMN IF NOT EXISTS calculated_sip_usd_q2 numeric(20,8),
    ADD COLUMN IF NOT EXISTS calculated_sip_usd_q3 numeric(20,8),
    ADD COLUMN IF NOT EXISTS calculated_sip_usd_q4 numeric(20,8),
    DROP COLUMN IF EXISTS calculated_sip_payroll_currency,
    DROP COLUMN IF EXISTS calculated_sip_usd;
