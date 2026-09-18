--
-- PostgreSQL database dump
--

\restrict 32kDAK41JBhLc6bGECd7eXcuzSGwu2xFhVU8P3binVCn0HXiszTlLo5tLa1qbzd

-- Dumped from database version 18.4
-- Dumped by pg_dump version 18.4

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: canonical; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA canonical;


--
-- Name: core; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA core;


--
-- Name: raw; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA raw;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: bdm; Type: TABLE; Schema: canonical; Owner: -
--

CREATE TABLE canonical.bdm (
    pipeline_run_id uuid NOT NULL,
    bdm_id character varying(30),
    bdm_name character varying(200),
    profitcentersbudesc character varying(500),
    ship_to character varying(50),
    ship_to_description character varying(500),
    ship_to_city character varying(100),
    material character varying(100),
    sharing_pct numeric(7,4),
    material_name character varying(500),
    revenue numeric(20,8),
    gp numeric(20,8),
    record_source character varying(50),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: bp; Type: TABLE; Schema: canonical; Owner: -
--

CREATE TABLE canonical.bp (
    bp_sk integer,
    reporting_line character varying(10),
    sales_district_id character varying(10),
    sales_district_description character varying(100),
    sales_office_id character varying(10),
    dm_name character varying(100),
    sales_area_group_id character varying(10),
    am_name character varying(100),
    seller_id character varying(10),
    employee_id_only_for_shared character varying(10),
    currency_code character(3),
    fy26_rev numeric(20,8),
    fy26_gp numeric(20,8),
    sales_office_description character varying(500),
    sales_group_description character varying(500),
    record_source character varying(50),
    created_at timestamp without time zone,
    pipeline_run_id uuid,
    am_id character varying(100),
    dm_id character varying(100),
    cam_id character varying(100),
    bdm_id character varying(100),
    division_node character varying(50)
);


--
-- Name: employee; Type: TABLE; Schema: canonical; Owner: -
--

CREATE TABLE canonical.employee (
    employee_sk integer,
    employee_id character varying(10) NOT NULL,
    preferred_name character varying(100),
    sales_office_description character varying(200),
    sales_group_description character varying(200),
    job_profile character varying(100),
    job_profile_for_sip character varying(100),
    country character varying(50),
    region character varying(50),
    bu character varying(10),
    active_flag character varying(10),
    annual_salary_payroll_currency numeric(20,8),
    annual_salary_usd numeric(20,8),
    sip_target_pct numeric(7,4),
    local_cost_center_id character varying(100),
    local_cost_center_name character varying(100),
    global_cost_center character varying(100),
    payroll_currency character(3) NOT NULL,
    hire_date date,
    movement_date date,
    termination_date date,
    sip_eligible_date date,
    check_with_bp character varying(10),
    seller_id_check character varying(10),
    status character varying(100),
    effective_start_date date,
    effective_end_date date,
    is_current boolean,
    record_source character varying(50),
    created_at timestamp without time zone,
    pipeline_run_id uuid
);


--
-- Name: nacs_guarantee; Type: TABLE; Schema: canonical; Owner: -
--

CREATE TABLE canonical.nacs_guarantee (
    pipeline_run_id uuid NOT NULL,
    employee_id character varying(20) NOT NULL,
    preferred_name character varying(200),
    job_profile character varying(100),
    region character varying(50),
    bu character varying(50),
    country character varying(50),
    employee_type character varying(50),
    time_type character varying(50),
    cost_center_id character varying(50),
    cost_center_name character varying(200),
    active_flag character varying(10),
    payroll_currency character(3) NOT NULL,
    total_base_payroll_currency numeric(20,8),
    sip_target_pct numeric(7,4),
    hire_date date,
    fy25_q1 numeric(20,8),
    fy25_q2 numeric(20,8),
    fy25_q3 numeric(20,8),
    fy25_q4 numeric(20,8),
    comments character varying(500),
    sip_target numeric(20,8),
    guarantee_eligibility_fy25_months integer,
    payment_in_fy25 numeric(20,8),
    carry_forward_payable_fy26 numeric(20,8),
    guarantee_eligibility_fy26_months integer,
    guarantee_eligibility_fy26_q1_months integer,
    guarantee_eligibility_fy26_q2_months integer,
    guarantee_eligibility_fy26_q3_months integer,
    guarantee_eligibility_fy26_q4_months integer,
    fy26_q1 numeric(20,8),
    fy26_q2 numeric(20,8),
    fy26_q3 numeric(20,8),
    fy26_q4 numeric(20,8),
    fy26_total numeric(20,8),
    carry_forward_payable_fy27 numeric(20,8),
    guarantee_eligibility_status character varying(50),
    calculated_sip_payroll_currency numeric(20,8),
    calculated_sip_usd numeric(20,8),
    guarantee_sip_ending_date date,
    final_guarantee_eligibility_fy26_months integer,
    total_calculated_sip_payroll_currency numeric(20,8),
    total_calculated_sip_usd numeric(20,8),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: sales; Type: TABLE; Schema: canonical; Owner: -
--

CREATE TABLE canonical.sales (
    sales_target_sk integer,
    reporting_line character varying(10),
    region character varying(10),
    bu character varying(100),
    sales_district_description character varying(500),
    sales_office_description character varying(500),
    sales_group_description character varying(500),
    profitcentersbudesc character varying(500),
    fiscal_period character varying(7),
    ship_to character varying(50),
    ship_to_description character varying(500),
    ship_to_city character varying(100),
    employee_id character varying(10),
    material character varying(100),
    material_description character varying(500),
    supply_point_name character varying(100),
    customergroupdesc character varying(200),
    customergroup1desc character varying(200),
    division_node character varying(50),
    division_node_desc character varying(100),
    division character varying(50),
    company_code character varying(10),
    currency_code character(3) NOT NULL,
    shared_acc_flag character varying(50),
    split_share character varying(50),
    bp_direct_rev numeric(20,8),
    bp_direct_gp numeric(20,8),
    bp_shared_rev numeric(20,8),
    bp_shared_gp numeric(20,8),
    cc_direct_rev numeric(20,10),
    cc_direct_gp numeric(20,10),
    cc_shared_rev numeric(20,10),
    cc_shared_gp numeric(20,10),
    ytd_rev numeric(20,8),
    ytd_gp numeric(20,8),
    exceptions character varying(500),
    low_margin_exceptions character varying(500),
    sa_materials character varying(50),
    gp_flag_cam character varying(10),
    operational_sbu character varying(50),
    sbu_based_on_emp_id character varying(50),
    preferred_name character varying(100),
    record_source character varying(50),
    created_at timestamp without time zone,
    pipeline_run_id uuid,
    profitcenter_shipto_revenue numeric(20,8),
    profitcenter_shipto_gp numeric(20,8),
    low_margin_flag character varying(20),
    gp_flag character varying(20),
    cam_profitcenter_shipto_division_revenue numeric(20,8),
    cam_profitcenter_shipto_division_gp numeric(20,8),
    cam_low_margin_flag character varying(50)
);


--
-- Name: ytd_payments; Type: TABLE; Schema: canonical; Owner: -
--

CREATE TABLE canonical.ytd_payments (
    pipeline_run_id uuid NOT NULL,
    employee_id character varying(10),
    preferred_name character varying(200),
    job_profile character varying(200),
    country character varying(100),
    bu character varying(50),
    currency_code character(3),
    crossed_gtee character varying(200),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    sip_in_usd numeric(20,8),
    sip_payroll_currency numeric(20,8),
    record_source character varying(50)
);


--
-- Name: bridge_employee_seller; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.bridge_employee_seller (
    employee_seller_sk integer NOT NULL,
    bu character varying(50),
    employee_id character varying(30),
    seller_name character varying(100),
    role_type character varying(50),
    seller_id character varying(30),
    seller_description character varying(500),
    name_check_with_hr boolean,
    status character varying(10),
    name_check_with_tableau boolean,
    check_with_tableau boolean,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: bridge_employee_seller_employee_seller_sk_seq; Type: SEQUENCE; Schema: core; Owner: -
--

ALTER TABLE core.bridge_employee_seller ALTER COLUMN employee_seller_sk ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME core.bridge_employee_seller_employee_seller_sk_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: fact_fx_rate; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.fact_fx_rate (
    fx_rate_sk integer NOT NULL,
    region character varying(50),
    country character varying(50),
    currency_code character varying(10),
    rate_basis character varying(10),
    rate_type character varying(30),
    rate_period_date date,
    fiscal_year smallint,
    rate_value numeric(20,8),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: fact_fx_rate_fx_rate_sk_seq; Type: SEQUENCE; Schema: core; Owner: -
--

ALTER TABLE core.fact_fx_rate ALTER COLUMN fx_rate_sk ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME core.fact_fx_rate_fx_rate_sk_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: bdm; Type: TABLE; Schema: raw; Owner: -
--

CREATE TABLE raw.bdm (
    pipeline_run_id uuid NOT NULL,
    bdm_id character varying(30),
    bdm_name character varying(200),
    profitcentersbudesc character varying(500),
    ship_to character varying(50),
    ship_to_description character varying(500),
    ship_to_city character varying(100),
    material character varying(100),
    sharing_pct numeric(7,4),
    material_name character varying(500),
    record_source character varying(50),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: bp; Type: TABLE; Schema: raw; Owner: -
--

CREATE TABLE raw.bp (
    bp_sk integer NOT NULL,
    reporting_line character varying(30),
    sales_district_id character varying(30),
    sales_district_description character varying(100),
    sales_office_id character varying(30),
    dm_name character varying(100),
    sales_area_group_id character varying(30),
    am_name character varying(100),
    seller_id character varying(30),
    employee_id_only_for_shared character varying(10),
    currency_code character(3),
    seller_desc character varying(100),
    fy26_rev numeric(20,8),
    fy26_gp numeric(20,8),
    sales_office_description character varying(500),
    sales_group_description character varying(500),
    comments character varying(500),
    record_source character varying(50),
    created_at timestamp without time zone,
    pipeline_run_id uuid,
    am_id character varying(100),
    dm_id character varying(100),
    cam_id character varying(100),
    bdm_id character varying(100),
    division_node character varying(50)
);


--
-- Name: bp_bp_sk_seq; Type: SEQUENCE; Schema: raw; Owner: -
--

ALTER TABLE raw.bp ALTER COLUMN bp_sk ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME raw.bp_bp_sk_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: employee; Type: TABLE; Schema: raw; Owner: -
--

CREATE TABLE raw.employee (
    employee_sk integer NOT NULL,
    employee_id character varying(10),
    preferred_name character varying(100),
    job_profile character varying(100),
    country character varying(50),
    region character varying(50),
    bu character varying(10),
    active_flag character varying(10),
    annual_salary_payroll_currency numeric(20,8),
    sip_target_pct numeric(7,4),
    local_cost_center_id character varying(100),
    local_cost_center_name character varying(100),
    global_cost_center character varying(100),
    payroll_currency character(3),
    hire_date date,
    movement_date date,
    termination_date date,
    sip_team_comments character varying(500),
    regional_fpa_comments character varying(500),
    status character varying(100),
    color_code character varying(50),
    record_source character varying(50),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    pipeline_run_id uuid,
    sales_office_description character varying(200),
    sales_group_description character varying(200),
    job_profile_for_sip character varying(100)
);


--
-- Name: employee_employee_sk_seq; Type: SEQUENCE; Schema: raw; Owner: -
--

ALTER TABLE raw.employee ALTER COLUMN employee_sk ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME raw.employee_employee_sk_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: nacs_guarantee; Type: TABLE; Schema: raw; Owner: -
--

CREATE TABLE raw.nacs_guarantee (
    pipeline_run_id uuid NOT NULL,
    country character varying(50),
    bu character varying(50),
    region character varying(50),
    employee_type character varying(50),
    time_type character varying(50),
    cost_center_id character varying(50),
    cost_center_name character varying(200),
    employee_id character varying(20),
    preferred_name character varying(200),
    active_flag character varying(10),
    job_profile character varying(100),
    payroll_currency character(3),
    total_base_payroll_currency numeric(20,8),
    sip_target_pct numeric(7,4),
    hire_date date,
    fy25_q1 numeric(20,8),
    fy25_q2 numeric(20,8),
    fy25_q3 numeric(20,8),
    fy25_q4 numeric(20,8),
    comments character varying(500),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: sales; Type: TABLE; Schema: raw; Owner: -
--

CREATE TABLE raw.sales (
    sales_target_sk integer NOT NULL,
    reporting_line character varying(30),
    region character varying(50),
    bu character varying(100),
    sales_district_description character varying(500),
    sales_office_description character varying(500),
    sales_group_description character varying(500),
    profitcentersbudesc character varying(500),
    fiscal_period character varying(7),
    ship_to character varying(50),
    ship_to_description character varying(500),
    ship_to_city character varying(100),
    employee_id character varying(10),
    material character varying(100),
    material_description character varying(500),
    supply_point_name character varying(100),
    customergroupdesc character varying(200),
    customergroup1desc character varying(200),
    division_node character varying(50),
    division_node_desc character varying(100),
    division character varying(50),
    company_code character varying(10),
    currency_code character(3),
    shared_acc_flag character varying(50),
    split_share character varying(50),
    bp_direct_rev numeric(20,8),
    bp_direct_gp numeric(20,8),
    bp_shared_rev numeric(20,8),
    bp_shared_gp numeric(20,8),
    cc_direct_rev numeric(20,8),
    cc_direct_gp numeric(20,8),
    cc_shared_rev numeric(20,8),
    cc_shared_gp numeric(20,8),
    exceptions character varying(500),
    low_margin_exceptions character varying(500),
    comments character varying(500),
    preferred_name character varying(100),
    record_source character varying(50),
    created_at timestamp without time zone,
    pipeline_run_id uuid
);


--
-- Name: sales_sales_target_sk_seq; Type: SEQUENCE; Schema: raw; Owner: -
--

ALTER TABLE raw.sales ALTER COLUMN sales_target_sk ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME raw.sales_sales_target_sk_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: ytd_payments; Type: TABLE; Schema: raw; Owner: -
--

CREATE TABLE raw.ytd_payments (
    pipeline_run_id uuid NOT NULL,
    employee_id character varying(10),
    preferred_name character varying(200),
    job_profile character varying(200),
    country character varying(100),
    bu character varying(50),
    currency_code character(3),
    crossed_gtee character varying(200),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    sip_payroll_currency numeric(20,8),
    record_source character varying(50)
);


--
-- Name: bridge_employee_seller bridge_employee_seller_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.bridge_employee_seller
    ADD CONSTRAINT bridge_employee_seller_pkey PRIMARY KEY (employee_seller_sk);


--
-- Name: fact_fx_rate fact_fx_rate_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.fact_fx_rate
    ADD CONSTRAINT fact_fx_rate_pkey PRIMARY KEY (fx_rate_sk);


--
-- Name: bp bp_pkey; Type: CONSTRAINT; Schema: raw; Owner: -
--

ALTER TABLE ONLY raw.bp
    ADD CONSTRAINT bp_pkey PRIMARY KEY (bp_sk);


--
-- Name: employee employee_pkey; Type: CONSTRAINT; Schema: raw; Owner: -
--

ALTER TABLE ONLY raw.employee
    ADD CONSTRAINT employee_pkey PRIMARY KEY (employee_sk);


--
-- Name: sales sales_pkey; Type: CONSTRAINT; Schema: raw; Owner: -
--

ALTER TABLE ONLY raw.sales
    ADD CONSTRAINT sales_pkey PRIMARY KEY (sales_target_sk);


--
-- Name: raw/canonical pipeline_run_id indexes; Type: INDEX
--
-- Every raw/canonical read, and CanonicalRepository.delete_by_run() before
-- a canonical rebuild, filters by "WHERE pipeline_run_id = :run_id". None
-- of these 12 tables had an index on that column - only on unrelated
-- surrogate keys (e.g. sales_target_sk) - so those filters were full
-- table scans. In this dev database raw.sales/canonical.sales alone had
-- grown to ~5-6 million rows across accumulated test runs, making a single
-- "Apply All Changes" (Data Corrections) or Recalculate take 30+ seconds
-- for a run that only touches ~150k of those rows. These indexes make
-- every such read/delete effectively O(rows for this run) instead of
-- O(rows for every run ever executed).
--

CREATE INDEX IF NOT EXISTS ix_raw_bdm_pipeline_run_id ON raw.bdm (pipeline_run_id);
CREATE INDEX IF NOT EXISTS ix_raw_bp_pipeline_run_id ON raw.bp (pipeline_run_id);
CREATE INDEX IF NOT EXISTS ix_raw_employee_pipeline_run_id ON raw.employee (pipeline_run_id);
CREATE INDEX IF NOT EXISTS ix_raw_nacs_guarantee_pipeline_run_id ON raw.nacs_guarantee (pipeline_run_id);
CREATE INDEX IF NOT EXISTS ix_raw_sales_pipeline_run_id ON raw.sales (pipeline_run_id);
CREATE INDEX IF NOT EXISTS ix_raw_ytd_payments_pipeline_run_id ON raw.ytd_payments (pipeline_run_id);

CREATE INDEX IF NOT EXISTS ix_canonical_bdm_pipeline_run_id ON canonical.bdm (pipeline_run_id);
CREATE INDEX IF NOT EXISTS ix_canonical_bp_pipeline_run_id ON canonical.bp (pipeline_run_id);
CREATE INDEX IF NOT EXISTS ix_canonical_employee_pipeline_run_id ON canonical.employee (pipeline_run_id);
CREATE INDEX IF NOT EXISTS ix_canonical_nacs_guarantee_pipeline_run_id ON canonical.nacs_guarantee (pipeline_run_id);
CREATE INDEX IF NOT EXISTS ix_canonical_sales_pipeline_run_id ON canonical.sales (pipeline_run_id);
CREATE INDEX IF NOT EXISTS ix_canonical_ytd_payments_pipeline_run_id ON canonical.ytd_payments (pipeline_run_id);


--
-- PostgreSQL database dump complete
--

\unrestrict 32kDAK41JBhLc6bGECd7eXcuzSGwu2xFhVU8P3binVCn0HXiszTlLo5tLa1qbzd

